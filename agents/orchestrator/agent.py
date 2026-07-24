"""Orchestrator — Iterative harness controller for deep research.

LangGraph StateGraph that evolves research output through
Context → Tool → Execution → Verification → Observability layers
until quality threshold is met or max iterations reached.
"""

import json
import logging
import os
import sys
import uuid

from langgraph.graph import StateGraph, END
from typing import Literal

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from agents.orchestrator.state import ResearchState
from agents.orchestrator.layers.context import gather_context, load_past_failure_memory
from agents.orchestrator.layers.mcp_client import (
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
)
from agents.orchestrator.layers.observability import HarnessObserver
from harness.failure import FailureCategory
from harness.session import SessionManager, ResearchSession

logger = logging.getLogger(__name__)

# Module-level observer registry (per session)
_observers: dict[str, HarnessObserver] = {}

# Session manager for periodic checkpointing
_session_mgr: SessionManager | None = None


def _get_session_mgr() -> SessionManager:
    global _session_mgr
    if _session_mgr is None:
        _session_mgr = SessionManager()
        try:
            _session_mgr.ensure_table()
        except Exception as e:
            logger.warning(f"Could not ensure sessions table: {e}")
    return _session_mgr


def checkpoint_session(state: ResearchState):
    """Persist the current graph state to PostgreSQL for frontend resume."""
    try:
        mgr = _get_session_mgr()
        session = ResearchSession(
            session_id=state.get("session_id", ""),
            query=state.get("query", ""),
            iteration=state.get("iteration", 0),
            max_iterations=state.get("max_iterations", 3),
            quality_threshold=state.get("quality_threshold", 7.0),
            research_plan=state.get("research_plan", []),
            accumulated_context=state.get("accumulated_context", []),
            current_draft=state.get("current_draft", ""),
            verification_history=state.get("verification_history", []),
            total_tokens=state.get("total_tokens", 0),
            total_cost=state.get("total_cost", 0.0),
            report_sections=state.get("report_sections", []),
            section_order=state.get("section_order", []),
            failing_sections=state.get("failing_sections", []),
            status=state.get("status", "unknown"),
            quality_score=state.get("quality_score", 0.0),
        )
        mgr.save(session)
    except Exception as e:
        logger.warning(f"Session checkpoint failed: {e}")


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
    checkpoint_session({**state, **update})
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
        checkpoint_session({**state, **update})
        return update

    # Generate plan via tool layer
    existing_context = "\n".join(
        c.get("content", "")[:200] for c in (state.get("accumulated_context") or [])[-5:]
    )

    use_sections = state.get("enable_sectioned", False)

    ws_flag = state.get("enable_web_search", False)

    if use_sections:
        result = generate_sectioned_plan(
            state["query"],
            iteration,
            state.get("failure_hints", ""),
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
            state.get("failure_hints", ""),
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
    checkpoint_session({**state, **update})
    return update


_PARALLEL_WORKERS = int(os.getenv("PARALLEL_WORKERS", "4"))


def _process_one_section(
    topic: dict, query: str, iteration: int, ws_flag: bool, parallel: bool,
    previous_content: str, failure_hints: str, language_instruction: str,
) -> dict:
    """Search and draft a single section. Thread-safe — called from ThreadPoolExecutor."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    title = topic.get("title", "Untitled")
    queries = topic.get("queries", [query])

    section_context: list[dict] = []

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
                except Exception as e:
                    logger.error("Section '%s' search (%s) failed: %s", title, kind, e)
    else:
        for idx, q in enumerate(queries[:3]):
            for r in _run_semantic(q, iteration):
                r.setdefault("metadata", {})["sub_topic"] = title
                section_context.append(r)
            if ws_flag and idx == 0:
                for r in _run_web(q, iteration):
                    r.setdefault("metadata", {})["sub_topic"] = title
                    section_context.append(r)

    result = draft_section(
        query, topic, section_context,
        previous_content=previous_content,
        improvement_hints=failure_hints,
        language_instruction=language_instruction,
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
    }


def _execute_sections(state: ResearchState) -> dict:
    """Per-section execute path: search and draft sub-topics in parallel."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

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

    def _run_section(topic):
        return _process_one_section(
            topic, state["query"], iteration, ws_flag, parallel,
            previous_contents.get(topic.get("title", ""), ""),
            state.get("failure_hints", ""),
            state.get("language_instruction", ""),
        )

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

    if parallel:
        with ThreadPoolExecutor(max_workers=min(_PARALLEL_WORKERS, len(topics_to_process) or 1)) as pool:
            futures = {pool.submit(_run_section, t): t for t in topics_to_process}
            for future in as_completed(futures):
                topic = futures[future]
                try:
                    _collect_section(topic, future.result())
                except Exception as e:
                    title = topic.get("title", "Untitled")
                    logger.error("Section '%s' failed: %s", title, e)
                    sections.append({
                        "sub_topic": title, "content": "",
                        "search_context": [], "score": 0.0, "status": "failed",
                    })
    else:
        for topic in topics_to_process:
            try:
                _collect_section(topic, _run_section(topic))
            except Exception as e:
                title = topic.get("title", "Untitled")
                logger.error("Section '%s' failed: %s", title, e)
                sections.append({
                    "sub_topic": title, "content": "",
                    "search_context": [], "score": 0.0, "status": "failed",
                })

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
    checkpoint_session({**state, **update})
    return update


def _run_semantic(query: str, iteration: int) -> list[dict]:
    """Run a single semantic_search and return context entries. Thread-safe."""
    seen: set = set()
    entries: list[dict] = []
    for r in semantic_search(query, top_k=5):
        key = (r.get("document_id", ""), r.get("chunk_index", 0))
        if key not in seen:
            seen.add(key)
            entries.append({
                "iteration": iteration,
                "source": f"{r.get('document_name', 'unknown')}[{r.get('chunk_index', 0)}]",
                "content": r.get("content", ""),
                "metadata": {"similarity": r.get("similarity", 0)},
            })
    return entries


def _run_web(query: str, iteration: int) -> list[dict]:
    """Run a single web_search and return context entries. Thread-safe."""
    entries: list[dict] = []
    for wr in web_search(query, num_results=3):
        entries.append({
            "iteration": iteration,
            "source": f"web:{wr.get('url', '')}",
            "content": f"{wr.get('title', '')}\n{wr.get('content', '')}",
            "metadata": {"type": "web_search", "url": wr.get("url", "")},
        })
    return entries


def execute_node(state: ResearchState) -> dict:
    """Execute research: fan-out all searches (semantic + web) in parallel."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    use_sections = (
        state.get("enable_sectioned", False)
        and bool(state.get("section_order"))
    )
    if use_sections:
        return _execute_sections(state)

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
                    logger.error("Search (%s) failed for '%s': %s", kind, q[:80], e)
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

    # Draft or improve the report
    context_text = "\n\n".join(c.get("content", "")[:500] for c in new_context[-10:])
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
    checkpoint_session({**state, **update})
    return update


def verify_node(state: ResearchState) -> dict:
    """Run verification checks on the current draft."""
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
    checkpoint_session({**state, **update})
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
    checkpoint_session({**state, **update})
    return update


def should_iterate(state: ResearchState) -> Literal["plan", "finalize"]:
    """Decide whether to iterate or finalize."""
    quality_score = state.get("quality_score", 0)
    threshold = state.get("quality_threshold", 7.0)
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 5)

    if quality_score >= threshold:
        return "finalize"
    if iteration >= max_iterations:
        return "finalize"
    return "plan"


def iterate_node(state: ResearchState) -> dict:
    """Advance to next iteration."""
    new_iteration = state.get("iteration", 0) + 1
    observer = _get_observer(state["session_id"])
    observer.start_iteration(new_iteration)

    update = {
        "iteration": new_iteration,
        "status": "planning",
    }
    checkpoint_session({**state, **update})
    return update


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

    output += (
        f"\n\n---\n"
        f"*Research completed in {iterations} iteration(s) | "
        f"Quality score: {score}/10 | "
        f"Total tokens: {state.get('total_tokens', 0):,}*"
    )

    _observers.pop(state.get("session_id", ""), None)

    update = {
        "final_output": output,
        "total_cost": total_cost,
        "status": "complete",
    }
    checkpoint_session({**state, **update})
    return update


# --- Build the Graph ---


def build_graph():
    graph = StateGraph(ResearchState)

    graph.add_node("normalize", normalize_node)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("verify", verify_node)
    graph.add_node("observe", observe_node)
    graph.add_node("iterate", iterate_node)
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("normalize")
    graph.add_edge("normalize", "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "verify")
    graph.add_edge("verify", "observe")
    graph.add_conditional_edges("observe", should_iterate, {"plan": "iterate", "finalize": "finalize"})
    graph.add_edge("iterate", "plan")
    graph.add_edge("finalize", END)

    return graph.compile()


orchestrator_graph = build_graph()
