"""Orchestrator — Iterative harness controller for deep research.

LangGraph StateGraph that evolves research output through
Context → Tool → Execution → Verification → Observability layers
until quality threshold is met or max iterations reached.
"""

import json
import logging
import os
import sys
import time
import uuid

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt, Command, StreamWriter
from typing import Callable, Literal

from dotenv import load_dotenv

load_dotenv(override=True)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from agents.orchestrator.state import ResearchState
from agents.orchestrator.layers.context import gather_context, load_past_failure_memory
from agents.orchestrator.layers.tools import (
    semantic_search,
    web_search,
    synthesize_context,
    generate_plan,
    generate_sectioned_plan,
    draft_report,
    draft_section,
    assemble_report,
    run_verification,
    verify_sections,
    classify_intent,
    direct_response,
)
from agents.orchestrator.layers.observability import HarnessObserver
from harness.failure import FailureCategory
logger = logging.getLogger(__name__)

# Module-level observer registry (per session)
_observers: dict[str, HarnessObserver] = {}


def _get_observer(session_id: str) -> HarnessObserver:
    if session_id not in _observers:
        _observers[session_id] = HarnessObserver(session_id)
    return _observers[session_id]


# --- Graph Nodes ---


def normalize_node(state: ResearchState) -> dict:
    """Normalize the input and initialize session state."""
    session_id = state.get("session_id") or str(uuid.uuid4())[:12]
    observer = _get_observer(session_id)
    observer.start_iteration(1)
    observer.trace_context(0, "normalize", f"Query: {state['query'][:200]}")

    past_memory = load_past_failure_memory()

    update = {
        "session_id": session_id,
        "iteration": 1,
        "status": "planning",
        "failure_hints": past_memory,
    }
    return update


def classify_intent_node(state: ResearchState) -> dict:
    """Classify query intent and route accordingly."""
    observer = _get_observer(state["session_id"])
    result = classify_intent(state["query"])
    observer.trace_tool_call(
        iteration=state["iteration"],
        operation="classify_intent",
        input_summary=state["query"][:200],
        output_summary=f"intent={result.get('intent')}, reason={result.get('reason', '')}",
        tokens_used=result.get("tokens_used", 0),
    )
    intent = result.get("intent", "research")
    update = {
        "status": "responding" if intent == "casual" else "planning",
        "intent": intent,
        "total_tokens": state.get("total_tokens", 0) + result.get("tokens_used", 0),
    }
    return update


def route_by_intent(state: ResearchState) -> Literal["plan", "direct_response"]:
    """Route based on classified intent."""
    if state.get("intent") in ("casual", "needs_clarification"):
        return "direct_response"
    return "plan"


def direct_response_node(state: ResearchState) -> dict:
    """Generate a direct conversational response for non-research queries."""
    observer = _get_observer(state["session_id"])
    intent = state.get("intent", "casual")
    result = direct_response(state["query"], state.get("language_instruction", ""), intent=intent)
    observer.trace_tool_call(
        iteration=state["iteration"],
        operation="direct_response",
        input_summary=state["query"][:200],
        output_summary=result.get("response", "")[:200],
        tokens_used=result.get("tokens_used", 0),
    )
    response_text = result.get("response", "")
    update = {
        "current_draft": response_text,
        "quality_score": 10.0,
        "status": "complete",
        "total_tokens": state.get("total_tokens", 0) + result.get("tokens_used", 0),
    }
    return update


def plan_node(state: ResearchState) -> dict:
    """Plan the research strategy using the context and tool layers."""
    observer = _get_observer(state["session_id"])
    iteration = state["iteration"]

    # Context layer
    ctx = gather_context(state)
    observer.trace_context(iteration, "gather_context", ctx.get("context_summary", "")[:200])

    planning_enabled = state.get("enable_planning", True)
    if not planning_enabled:
        fallback_plan = [{"action": "search", "query": state["query"], "purpose": "Direct search (planning disabled)"}]
        update = {
            "research_plan": fallback_plan,
            "status": "researching",
        }
        return update

    # Generate plan via tool layer
    existing_context = "\n".join(
        c.get("content", "")[:200] for c in (state.get("accumulated_context") or [])[-5:]
    )

    failure_hints = state.get("failure_hints", "")
    human_direction = state.get("human_direction", "")
    if human_direction:
        failure_hints += f"\n\n[User direction]: {human_direction}"

    use_sections = state.get("enable_sectioned", False)

    ws_flag = state.get("enable_web_search", True)

    if use_sections:
        result = generate_sectioned_plan(
            state["query"],
            iteration,
            failure_hints,
            existing_context,
            language_instruction=state.get("language_instruction", ""),
            enable_web_search=ws_flag,
        )
        plan_data = result.get("sub_topics", [])
        section_order = [t.get("title", "") for t in plan_data]
        observer.trace_tool_call(
            iteration=iteration,
            operation="generate_sectioned_plan",
            input_summary=state["query"][:200],
            output_summary=json.dumps(plan_data)[:200],
            tokens_used=result.get("tokens_used", 0),
        )
        update = {
            "research_plan": plan_data,
            "section_order": section_order,
            "status": "researching",
            "total_tokens": state.get("total_tokens", 0) + result.get("tokens_used", 0),
        }
    else:
        result = generate_plan(
            state["query"],
            iteration,
            failure_hints,
            existing_context,
            enable_web_search=ws_flag,
        )
        observer.trace_tool_call(
            iteration=iteration,
            operation="generate_plan",
            input_summary=state["query"][:200],
            output_summary=json.dumps(result.get("plan", []))[:200],
            tokens_used=result.get("tokens_used", 0),
        )
        update = {
            "research_plan": result.get("plan", []),
            "status": "researching",
            "total_tokens": state.get("total_tokens", 0) + result.get("tokens_used", 0),
        }
    return update


_PARALLEL_WORKERS = int(os.getenv("PARALLEL_WORKERS", "4"))


def _search_section(
    topic: dict, query: str, iteration: int, ws_flag: bool, parallel: bool,
) -> dict:
    """Run search queries for a single section and return context + counts."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    title = topic.get("title", "Untitled")
    queries = topic.get("queries", [query])

    section_context: list[dict] = []
    semantic_count = 0
    web_count = 0

    if parallel:
        futures_map: dict = {}
        with ThreadPoolExecutor(max_workers=_PARALLEL_WORKERS) as pool:
            for idx, q in enumerate(queries[:3]):
                futures_map[pool.submit(_run_semantic, q, iteration)] = ("semantic", q)
                if ws_flag and idx == 0:
                    futures_map[pool.submit(_run_web, q, iteration)] = ("web", q)

            for future in as_completed(futures_map):
                kind, q = futures_map[future]
                try:
                    results = future.result()
                    for r in results:
                        r.setdefault("metadata", {})["sub_topic"] = title
                    section_context.extend(results)
                    if kind == "semantic":
                        semantic_count += len(results)
                    else:
                        web_count += len(results)
                except Exception as e:
                    logger.error("Section '%s' search (%s) failed: %s", title, kind, e, exc_info=True)
    else:
        for idx, q in enumerate(queries[:3]):
            for r in _run_semantic(q, iteration):
                r.setdefault("metadata", {})["sub_topic"] = title
                section_context.append(r)
                semantic_count += 1
            if ws_flag and idx == 0:
                for r in _run_web(q, iteration):
                    r.setdefault("metadata", {})["sub_topic"] = title
                    section_context.append(r)
                    web_count += 1

    return {
        "context": section_context,
        "semantic_count": semantic_count,
        "web_count": web_count,
    }


def _draft_and_build_section(
    topic: dict, query: str, search_result: dict,
    previous_content: str, failure_hints: str, language_instruction: str,
    stream_callback: Callable[[str], None] | None = None,
) -> dict:
    """Draft a section from search results and return the section data."""
    title = topic.get("title", "Untitled")
    section_context = search_result["context"]

    result = draft_section(
        query, topic, section_context,
        previous_content=previous_content,
        improvement_hints=failure_hints,
        language_instruction=language_instruction,
        stream_callback=stream_callback,
    )

    section_data = {
        "sub_topic": title,
        "content": result.get("content", ""),
        "search_context": [{"source": c["source"], "content": c["content"][:200]} for c in section_context[:5]],
        "score": 0.0,
        "status": "drafted",
    }
    return {
        "section_data": section_data,
        "context": section_context,
        "tokens_used": result.get("tokens_used", 0),
        "title": title,
        "semantic_count": search_result["semantic_count"],
        "web_count": search_result["web_count"],
    }


def _execute_sections(state: ResearchState, writer: StreamWriter) -> dict:
    """Per-section execute path: process sections sequentially, parallelize MCP calls within each.

    Uses writer() for real-time SSE progress between search and draft phases.
    """
    try:
        import mlflow
        _mlflow = mlflow
    except Exception:
        _mlflow = None

    observer = _get_observer(state["session_id"])
    iteration = state["iteration"]
    plan = state.get("research_plan", [])
    section_order = state.get("section_order", [])
    sections = list(state.get("report_sections") or [])
    failing = set(state.get("failing_sections") or [])
    ws_flag = state.get("enable_web_search", True)
    parallel = state.get("enable_parallel", True)

    new_context = list(state.get("accumulated_context") or [])
    total_tokens = state.get("total_tokens", 0)

    topics_to_process = []
    previous_contents: dict[str, str] = {}
    for topic in plan:
        title = topic.get("title", "Untitled")
        existing = next((s for s in sections if s.get("sub_topic") == title), None)
        if existing and existing.get("status") == "passed" and title not in failing:
            logger.info("Skipping passed section: %s", title)
            continue
        previous_contents[title] = existing.get("content", "") if existing else ""
        topics_to_process.append(topic)

    total_sections = len(topics_to_process)

    def _collect_section(topic, out):
        nonlocal total_tokens
        title = topic.get("title", "Untitled")
        total_tokens += out["tokens_used"]
        new_context.extend(out["context"])
        existing = next((s for s in sections if s.get("sub_topic") == title), None)
        if existing:
            sections[sections.index(existing)] = out["section_data"]
        else:
            sections.append(out["section_data"])
        observer.trace_tool_call(
            iteration=iteration,
            operation=f"search+draft_section:{title}",
            input_summary=f"Section '{title}' iteration {iteration}",
            output_summary=out["section_data"]["content"][:200],
            tokens_used=out["tokens_used"],
        )
        logger.info("Drafted section '%s' (%d chars)", title, len(out["section_data"]["content"]))

    for idx, topic in enumerate(topics_to_process, 1):
        title = topic.get("title", "Untitled")
        evt_base = {"section_title": title, "section_index": idx, "total_sections": total_sections}

        # --- Phase 1: Search ---
        writer({"progress": "section_start", **evt_base})

        try:
            search_result = _search_section(topic, state["query"], iteration, ws_flag, parallel)
        except Exception as e:
            logger.error("Section '%s' search failed: %s", title, e, exc_info=True)
            sections.append({"sub_topic": title, "content": "", "search_context": [], "score": 0.0, "status": "failed"})
            writer({"progress": "section_failed", **evt_base})
            continue

        sem = search_result["semantic_count"]
        web = search_result["web_count"]

        if sem == 0 and web == 0:
            logger.warning("No search results for section '%s' — skipping (MCP servers may be unavailable)", title)
            sections.append({"sub_topic": title, "content": "", "search_context": [], "score": 0.0, "status": "no_results"})
            writer({"progress": "section_failed", **evt_base})
            continue

        doc_sources: set[str] = set()
        web_urls: list[str] = []
        for ctx in search_result["context"]:
            src = ctx.get("source", "")
            if src.startswith("web:"):
                url = ctx.get("metadata", {}).get("url", src[4:])
                if url and url not in web_urls:
                    web_urls.append(url)
            elif src:
                doc_name = src.split("[")[0] if "[" in src else src
                doc_sources.add(doc_name)

        writer({
            "progress": "search_done",
            "semantic_count": sem, "web_count": web,
            "doc_sources": list(doc_sources),
            "web_urls": web_urls[:5],
            **evt_base,
        })

        # --- Phase 2: Draft (with token streaming) ---
        writer({"progress": "drafting", **evt_base})

        def _on_draft_chunk(text: str) -> None:
            writer({"progress": "draft_chunk", "text": text, **evt_base})

        try:
            span_ctx = _mlflow.start_span(name=f"section:{title}") if _mlflow else None
            span = span_ctx.__enter__() if span_ctx else None
            try:
                if span:
                    span.set_inputs({"title": title, "queries": topic.get("queries", [])[:3], "iteration": iteration})

                out = _draft_and_build_section(
                    topic, state["query"], search_result,
                    previous_contents.get(title, ""),
                    state.get("failure_hints", ""),
                    state.get("language_instruction", ""),
                    stream_callback=_on_draft_chunk,
                )

                if span:
                    span.set_outputs({
                        "mcp_calls": [f"vector-search/semantic_search x{sem}", f"web-search/web_search x{web}"],
                        "semantic_chunks": sem, "web_results": web,
                        "content_length": len(out.get("section_data", {}).get("content", "")),
                        "tokens_used": out.get("tokens_used", 0),
                    })
            finally:
                if span_ctx:
                    span_ctx.__exit__(None, None, None)

            _collect_section(topic, out)
            section_content = out.get("section_data", {}).get("content", "")
            writer({"progress": "section_done", "content": section_content, **evt_base})

        except Exception as e:
            logger.error("Section '%s' draft failed: %s", title, e, exc_info=True)
            sections.append({"sub_topic": title, "content": "", "search_context": [], "score": 0.0, "status": "failed"})
            writer({"progress": "section_failed", **evt_base})

    writer({"progress": "assembling_report", "total_sections": total_sections})
    report_result = assemble_report(
        sections, section_order, state["query"],
        language_instruction=state.get("language_instruction", ""),
    )
    total_tokens += report_result.get("tokens_used", 0)

    update = {
        "accumulated_context": new_context,
        "report_sections": sections,
        "current_draft": report_result.get("draft", ""),
        "status": "verifying",
        "total_tokens": total_tokens,
    }
    return update


def _format_context_entry(ctx: dict) -> str:
    """Format a context entry for LLM prompt, including source URL when available."""
    metadata = ctx.get("metadata") or {}
    source = ctx.get("source", "unknown")
    url = metadata.get("source_url", "")
    content = ctx.get("content", "")[:500]
    if url and url.startswith("http"):
        return f"[{source}]({url})\n{content}"
    return f"[{source}]\n{content}"


def _run_semantic(query: str, iteration: int) -> list[dict]:
    """Run a single semantic_search and return context entries. Thread-safe."""
    seen: set = set()
    entries: list[dict] = []
    for r in semantic_search(query, top_k=3):
        key = (r.get("document_id", ""), r.get("chunk_index", 0))
        if key not in seen:
            seen.add(key)
            entries.append({
                "iteration": iteration,
                "source": f"{r.get('document_name', 'unknown')}[{r.get('chunk_index', 0)}]",
                "content": r.get("content", ""),
                "metadata": {
                    "similarity": r.get("similarity", 0),
                    "source_url": r.get("source_url", ""),
                    "document_name": r.get("document_name", ""),
                    "chunk_index": r.get("chunk_index", 0),
                },
            })
    return entries


def _run_web(query: str, iteration: int) -> list[dict]:
    """Run a single web_search and return context entries. Thread-safe."""
    entries: list[dict] = []
    for wr in web_search(query, num_results=2):
        entries.append({
            "iteration": iteration,
            "source": f"web:{wr.get('url', '')}",
            "content": f"{wr.get('title', '')}\n{wr.get('content', '')}",
            "metadata": {"type": "web_search", "url": wr.get("url", "")},
        })
    return entries


def execute_node(state: ResearchState, writer: StreamWriter) -> dict:
    """Execute research: fan-out all searches (semantic + web) in parallel."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    use_sections = (
        state.get("enable_sectioned", False)
        and bool(state.get("section_order"))
    )
    if use_sections:
        return _execute_sections(state, writer)

    observer = _get_observer(state["session_id"])
    iteration = state["iteration"]
    plan = state.get("research_plan", [])

    new_context = list(state.get("accumulated_context") or [])
    total_tokens = state.get("total_tokens", 0)

    ws_flag = state.get("enable_web_search", True)
    parallel = state.get("enable_parallel", True)

    search_steps = [s for s in plan[:4] if s.get("action", "search") in ("search", "web_search")]
    other_steps = [s for s in plan[:4] if s.get("action", "search") not in ("search", "web_search")]

    if parallel:
        futures_map: dict = {}
        with ThreadPoolExecutor(max_workers=_PARALLEL_WORKERS) as pool:
            for step in search_steps:
                q = step.get("query", state["query"])
                futures_map[pool.submit(_run_semantic, q, iteration)] = ("semantic", q)
                if ws_flag:
                    futures_map[pool.submit(_run_web, q, iteration)] = ("web", q)

            for future in as_completed(futures_map):
                kind, q = futures_map[future]
                try:
                    results = future.result()
                    new_context.extend(results)
                    observer.trace_tool_call(
                        iteration=iteration,
                        operation=f"{'web_search' if kind == 'web' else 'semantic_search'}",
                        input_summary=q[:200],
                        output_summary=f"{len(results)} results",
                        tokens_used=0,
                    )
                except Exception as e:
                    logger.error("Search (%s) failed for '%s': %s", kind, q[:80], e, exc_info=True)
    else:
        for step in search_steps:
            q = step.get("query", state["query"])
            new_context.extend(_run_semantic(q, iteration))
            observer.trace_tool_call(iteration=iteration, operation="semantic_search", input_summary=q[:200], output_summary="done", tokens_used=0)
            if ws_flag:
                new_context.extend(_run_web(q, iteration))
                observer.trace_tool_call(iteration=iteration, operation="web_search", input_summary=q[:200], output_summary="done", tokens_used=0)

    for step in other_steps:
        action = step.get("action", "search")
        step_query = step.get("query", state["query"])
        if action in ("analyze", "compare"):
            synthesis = synthesize_context(step_query, [
                {"content": c.get("content", ""), "document_name": c.get("source", ""), "chunk_index": 0, "similarity": 0.8}
                for c in new_context[-5:]
            ])
            total_tokens += synthesis.get("tokens_used", 0)
            new_context.append({
                "iteration": iteration,
                "source": "synthesis",
                "content": synthesis.get("synthesis", ""),
                "metadata": {"type": action},
            })
            observer.trace_tool_call(
                iteration=iteration, operation=f"synthesize_{action}",
                input_summary=step_query[:200],
                output_summary=synthesis.get("synthesis", "")[:200],
                tokens_used=synthesis.get("tokens_used", 0),
            )

    # Draft or improve the report (include source URLs for citation linking)
    context_text = "\n\n".join(_format_context_entry(c) for c in new_context[-10:])
    plan_text = json.dumps(plan)

    logger.info(
        "draft_report input: query=%d chars, context=%d chars, plan=%d chars",
        len(state["query"]), len(context_text), len(plan_text),
    )

    result = draft_report(
        state["query"],
        context_text,
        plan_text,
        previous_draft=state.get("current_draft", ""),
        improvement_hints=state.get("failure_hints", ""),
        language_instruction=state.get("language_instruction", ""),
    )
    total_tokens += result.get("tokens_used", 0)

    observer.trace_tool_call(
        iteration=iteration,
        operation="draft_report",
        input_summary=f"Drafting iteration {iteration}",
        output_summary=result.get("draft", "")[:200],
        tokens_used=result.get("tokens_used", 0),
    )

    update = {
        "accumulated_context": new_context,
        "current_draft": result.get("draft", ""),
        "status": "verifying",
        "total_tokens": total_tokens,
    }
    return update


def verify_node(state: ResearchState, writer: StreamWriter) -> dict:
    """Run verification checks on the current draft."""
    time.sleep(1)
    writer({"progress": "verifying"})
    observer = _get_observer(state["session_id"])
    iteration = state["iteration"]
    draft = state.get("current_draft", "")
    context = state.get("accumulated_context") or []

    fc_flag = state.get("enable_fact_check", True)
    parallel = state.get("enable_parallel", True)
    verification = run_verification(draft, state["query"], context, iteration, enable_fact_check=fc_flag, enable_parallel=parallel)

    observer.trace_verification(
        iteration=iteration,
        operation="full_verification",
        input_summary=f"Draft length: {len(draft)} chars",
        output_summary=f"Score: {verification.get('quality_score', 0)}, Passed: {verification.get('passed', False)}",
        tokens_used=verification.get("tokens_used", 0),
    )

    # Record failures if verification didn't pass
    if not verification.get("passed", False):
        details = verification.get("quality_details", {})
        if details.get("completeness", 10) < 6:
            observer.record_failure(iteration, FailureCategory.INSUFFICIENT_DEPTH, "Report lacks depth")
        if not verification.get("citation_check", {}).get("passed", True):
            observer.record_failure(iteration, FailureCategory.MISSING_CITATIONS, "Missing or invalid citations")
        if not verification.get("fact_check", {}).get("passed", True):
            observer.record_failure(iteration, FailureCategory.HALLUCINATION, "Unsupported claims detected")

    # Per-section verification (only when sectioned report is active)
    sections = state.get("report_sections") or []
    failing = []
    section_tokens = 0
    if sections:
        failing = verify_sections(
            sections, state["query"],
            quality_threshold=state.get("quality_threshold", 7.0),
            enable_parallel=parallel,
        )
        section_tokens = sum(s.get("score", 0) for s in sections if isinstance(s.get("score"), (int, float)))

    history = list(state.get("verification_history") or [])
    history.append({
        "iteration": iteration,
        "score": verification.get("quality_score", 0),
        "passed": verification.get("passed", False),
        "improvements": verification.get("improvements", []),
        "failing_sections": failing,
    })

    update = {
        "verification_result": verification,
        "verification_history": history,
        "quality_score": verification.get("quality_score", 0),
        "report_sections": sections if sections else state.get("report_sections", []),
        "failing_sections": failing,
        "status": "observing",
        "total_tokens": state.get("total_tokens", 0) + verification.get("tokens_used", 0),
    }
    return update


def observe_node(state: ResearchState) -> dict:
    """Record observability data and determine next action."""
    observer = _get_observer(state["session_id"])
    iteration = state["iteration"]
    passed = state.get("verification_result", {}).get("passed", False)

    observer.end_iteration(state.get("quality_score", 0), passed)

    # Prepare failure hints for next iteration
    failure_hints = observer.get_improvement_hints()
    improvements = state.get("verification_result", {}).get("improvements", [])
    if improvements:
        failure_hints += "\n" + "\n".join(f"- {imp}" for imp in improvements)

    update = {
        "failure_hints": failure_hints,
    }
    return update


def should_iterate(state: ResearchState) -> Literal["iteration_review", "finalize"]:
    """Always route to iteration_review — the card handles both pass and fail states."""
    return "iteration_review"


def iteration_review_node(state: ResearchState) -> dict:
    """Pause for human-in-the-loop review before each iteration.

    Shows the LLM's quality assessment and improvement suggestions.
    The user can provide additional direction or accept the current result.
    Uses LangGraph's interrupt() to pause the graph.
    """
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 5)
    verification = state.get("verification_result", {})

    quality_score = state.get("quality_score", 0)
    quality_threshold = state.get("quality_threshold", 7.0)
    quality_met = quality_score >= quality_threshold

    review_data = {
        "quality_score": quality_score,
        "quality_threshold": quality_threshold,
        "iteration": iteration,
        "max_iterations": max_iterations,
        "improvements": verification.get("improvements", []),
        "can_iterate": not quality_met and iteration < max_iterations,
        "quality_met": quality_met,
    }

    user_response = interrupt(review_data)

    if quality_met:
        return {"status": "finalizing", "human_direction": ""}

    action = "accept"
    direction = ""
    if isinstance(user_response, dict):
        action = user_response.get("action", "accept")
        direction = user_response.get("direction", "")
    elif isinstance(user_response, str):
        raw = user_response.strip()
        if raw == "__accept__" or raw.lower() == "accept":
            action = "accept"
        elif raw:
            action = "continue"
            direction = raw

    if action == "accept" or iteration >= max_iterations:
        return {"status": "finalizing", "human_direction": direction}

    return {"status": "planning", "human_direction": direction}


def route_after_review(state: ResearchState) -> Literal["iterate", "finalize"]:
    """Route after human review: iterate if user wants to continue, else finalize."""
    if state.get("status") == "finalizing":
        return "finalize"
    return "iterate"


def iterate_node(state: ResearchState) -> dict:
    """Advance to next iteration."""
    new_iteration = state.get("iteration", 0) + 1
    observer = _get_observer(state["session_id"])
    observer.start_iteration(new_iteration)

    update = {
        "iteration": new_iteration,
        "status": "planning",
    }
    return update


def _dedup_sources(accumulated_context: list[dict]) -> list[dict]:
    """Deduplicate sources from accumulated context into a list of dicts.

    Returns a 1-indexed list: [{"index": 1, "name": ..., "snippet": ..., "url": ..., "domain": ...}, ...]
    The index matches the [Source N] numbering used in LLM prompts.
    """
    import re as _re
    from urllib.parse import urlparse

    seen: dict[str, dict] = {}
    for ctx in accumulated_context:
        metadata = ctx.get("metadata") or {}
        url = metadata.get("source_url", "")
        raw_name = ctx.get("document_name", ctx.get("source", "")) or ""
        doc_name = _re.sub(r"\[\d+\]$", "", raw_name).strip()
        if not doc_name:
            continue
        key = url if (url and url.startswith("http")) else doc_name
        if key not in seen:
            snippet = (ctx.get("content", "") or "")[:150].strip()
            domain = ""
            if url and url.startswith("http"):
                try:
                    domain = urlparse(url).netloc
                except Exception:
                    domain = url[:40]
            seen[key] = {"name": doc_name, "url": url if url.startswith("http") else "", "snippet": snippet, "domain": domain}

    result = []
    for idx, entry in enumerate(seen.values(), 1):
        result.append({"index": idx, **entry})
    return result


def _build_references(accumulated_context: list[dict]) -> str:
    """Build a markdown references section from context entries.

    Each entry shows the citation badge number linked to #cite-N
    followed by the document name (with URL if available).
    """
    sources = _dedup_sources(accumulated_context)
    if not sources:
        return ""

    lines = []
    for s in sources:
        badge = f"[{s['index']}](#cite-{s['index']})"
        if s["url"]:
            lines.append(f"{badge} [{s['name']}]({s['url']})")
        else:
            lines.append(f"{badge} {s['name']}")
    return "\n\n".join(lines)


def finalize_node(state: ResearchState) -> dict:
    """Finalize the research output.

    For sectioned reports: concatenate original section texts in order and
    prepend the executive summary. This preserves the full section content
    that was streamed to the UI — the LLM-assembled draft is only used for
    verification scoring.
    """
    observer = _get_observer(state["session_id"])
    summary = observer.get_summary()
    observer.persist()
    total_cost = summary.get("total_cost", 0.0)
    logger.info(
        "Session %s summary: %s",
        state.get("session_id", ""),
        json.dumps(summary.get("metrics", {}), default=str)[:500],
    )

    score = state.get("quality_score", 0)
    iterations = state.get("iteration", 0)

    sections = state.get("report_sections") or []
    section_order = state.get("section_order") or []

    if sections and section_order:
        ordered_parts: list[str] = []
        for title in section_order:
            sec = next((s for s in sections if s.get("sub_topic") == title), None)
            if sec and sec.get("content"):
                ordered_parts.append(sec["content"])
        body = "\n\n".join(ordered_parts)

        draft = state.get("current_draft", "")
        exec_summary = ""
        if draft and "# Executive Summary" in draft:
            summary_end = draft.find("\n\n", draft.find("# Executive Summary") + 20)
            if summary_end > 0:
                exec_summary = draft[: summary_end].strip()

        if exec_summary:
            output = f"{exec_summary}\n\n---\n\n{body}"
        else:
            output = body
    else:
        output = state.get("current_draft", "")

    # Build references section from accumulated context source URLs
    references = _build_references(state.get("accumulated_context") or [])
    if references:
        output += f"\n\n---\n\n## References\n\n{references}"

    output += (
        f"\n\n---\n"
        f"*Research completed in {iterations} iteration(s) | "
        f"Quality score: {score}/10 | "
        f"Total tokens: {state.get('total_tokens', 0):,}*"
    )

    _observers.pop(state.get("session_id", ""), None)

    output = _fix_markdown_output(output)

    sources_list = _dedup_sources(state.get("accumulated_context") or [])

    update = {
        "final_output": output,
        "sources": sources_list,
        "total_cost": total_cost,
        "status": "complete",
    }
    return update


def _fix_markdown_output(text: str) -> str:
    """Ensure blank lines before headings, fix table formatting, convert citations to links."""
    import re
    text = re.sub(r"(\])\.(#{1,6}\s)", r"\1.\n\n\2", text)
    text = re.sub(r"(\|)\s*(#{1,6}\s)", r"\1\n\n\2", text)
    text = re.sub(r"([^\n])\n(#{1,6}\s)", r"\1\n\n\2", text)
    text = re.sub(r"([^\n#])(#{1,6}\s)", r"\1\n\n\2", text)
    text = re.sub(r" \| \| ", " |\n| ", text)
    text = re.sub(r"(\| :?-+:? (?:\| :?-+:? )*\|) (\|)", r"\1\n\2", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Convert [Source N] and [Source 1, Source 2] into citation badge links.
    # Negative lookahead avoids transforming [Source N](url) which is already a link.
    def _expand_cite(m: re.Match) -> str:
        nums = re.findall(r"\d+", m.group(1))
        return "".join(f"[{n}](#cite-{n})" for n in nums)

    text = re.sub(r"\[Source (\d+(?:,\s*(?:Source\s*)?\d+)*)\](?!\()", _expand_cite, text)
    return text


# --- Build the Graph ---


def build_graph(checkpointer=None):
    graph = StateGraph(ResearchState)

    graph.add_node("normalize", normalize_node)
    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("direct_response", direct_response_node)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("verify", verify_node)
    graph.add_node("observe", observe_node)
    graph.add_node("iteration_review", iteration_review_node)
    graph.add_node("iterate", iterate_node)
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("normalize")
    graph.add_edge("normalize", "classify_intent")
    graph.add_conditional_edges(
        "classify_intent", route_by_intent,
        {"plan": "plan", "direct_response": "direct_response"},
    )
    graph.add_edge("direct_response", "finalize")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "verify")
    graph.add_edge("verify", "observe")
    graph.add_conditional_edges(
        "observe", should_iterate,
        {"iteration_review": "iteration_review", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "iteration_review", route_after_review,
        {"iterate": "iterate", "finalize": "finalize"},
    )
    graph.add_edge("iterate", "plan")
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer)


from langgraph.checkpoint.memory import MemorySaver

orchestrator_graph = build_graph(checkpointer=MemorySaver())
