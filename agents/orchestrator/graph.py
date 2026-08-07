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
    search_by_document,
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


def _resolve_target_document(query: str) -> tuple[str, str]:
    """Match document references in the query against the document database.

    Returns (document_id, document_name) or ("", "") if no match.
    """
    try:
        from db import get_connection
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, name FROM documents WHERE status = 'completed'"
        ).fetchall()
        conn.close()

        if not rows:
            return "", ""

        q_lower = query.lower()
        for row in rows:
            doc_name = row["name"]
            if doc_name.lower() in q_lower:
                return row["id"], doc_name
            name_no_ext = os.path.splitext(doc_name)[0]
            if name_no_ext.lower() in q_lower:
                return row["id"], doc_name
            words = [w for w in doc_name.replace("_", " ").replace("-", " ").split() if len(w) > 3]
            if words and sum(1 for w in words if w.lower() in q_lower) >= len(words) * 0.6:
                return row["id"], doc_name
    except Exception as e:
        logger.debug("Document resolution failed: %s", e)
    return "", ""


def normalize_node(state: ResearchState) -> dict:
    """Normalize the input and initialize session state."""
    session_id = state.get("session_id") or str(uuid.uuid4())[:12]
    observer = _get_observer(session_id)
    observer.start_iteration(1)
    observer.trace_context(0, "normalize", f"Query: {state['query'][:200]}")

    past_memory = load_past_failure_memory()

    doc_id, doc_name = _resolve_target_document(state["query"])
    if doc_id:
        logger.info("Target document resolved: %s (%s)", doc_name, doc_id)

    update = {
        "session_id": session_id,
        "iteration": 1,
        "status": "planning",
        "failure_hints": past_memory,
        "target_document_id": doc_id,
        "target_document_name": doc_name,
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
    document_id: str = "", ws_limit: int = 2,
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
                futures_map[pool.submit(_run_semantic, q, iteration, document_id)] = ("semantic", q)
                if ws_flag and idx == 0:
                    futures_map[pool.submit(_run_web, q, iteration, ws_limit)] = ("web", q)

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
            for r in _run_semantic(q, iteration, document_id):
                r.setdefault("metadata", {})["sub_topic"] = title
                section_context.append(r)
                semantic_count += 1
            if ws_flag and idx == 0:
                for r in _run_web(q, iteration, ws_limit):
                    r.setdefault("metadata", {})["sub_topic"] = title
                    section_context.append(r)
                    web_count += 1

    logger.info("Section '%s' search: %d semantic, %d web results", title, semantic_count, web_count)
    return {
        "context": section_context,
        "semantic_count": semantic_count,
        "web_count": web_count,
    }


def _draft_and_build_section(
    topic: dict, query: str, search_result: dict,
    previous_content: str, failure_hints: str, language_instruction: str,
    stream_callback: Callable[[str], None] | None = None,
    source_offset: int = 0,
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
        source_offset=source_offset,
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

        target_doc_id = state.get("target_document_id", "")
        try:
            search_result = _search_section(
                topic, state["query"], iteration, ws_flag, parallel,
                document_id=target_doc_id,
                ws_limit=state.get("web_search_limit", 2),
            )
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

        if idx > 1:
            writer({"progress": "draft_chunk", "text": "\n\n---\n\n", **evt_base})

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
                    source_offset=len(new_context),
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


def _format_context_entry(ctx: dict, idx: int | None = None) -> str:
    """Format a context entry for LLM prompt using stable source_id for citations."""
    metadata = ctx.get("metadata") or {}
    source = ctx.get("source", "unknown")
    src_id = ctx.get("source_id", "SRC_UNKNOWN")
    doc_name = ctx.get("document_name", source)
    url = metadata.get("source_url", "") or metadata.get("url", "")
    content = ctx.get("content", "")[:500]
    header = f"[{src_id}: {doc_name}]"
    if url and url.startswith("http"):
        header = f"[{src_id}: {doc_name}]({url})"
    return f"{header}\n{content}"


def _run_semantic(query: str, iteration: int, document_id: str = "") -> list[dict]:
    """Run a single semantic_search and return context entries. Thread-safe.

    If document_id is provided, search is scoped to that document only.
    Each entry gets a stable source_id based on the document name (not position).
    """
    import hashlib
    seen: set = set()
    entries: list[dict] = []
    results = (
        search_by_document(query, document_id, top_k=5)
        if document_id
        else semantic_search(query, top_k=3)
    )
    for r in results:
        key = (r.get("document_id", ""), r.get("chunk_index", 0))
        if key not in seen:
            seen.add(key)
            doc_name = r.get("document_name", "unknown")
            source_url = r.get("source_url", "")
            # Stable source_id: hash of document name (deduplicates chunks from same doc)
            id_basis = source_url if (source_url and source_url.startswith("http")) else doc_name
            src_id = "SRC_" + hashlib.sha256(id_basis.encode()).hexdigest()[:6].upper()
            entries.append({
                "iteration": iteration,
                "source": f"{doc_name}[{r.get('chunk_index', 0)}]",
                "source_id": src_id,
                "document_name": doc_name,
                "content": r.get("content", ""),
                "metadata": {
                    "similarity": r.get("similarity", 0),
                    "source_url": source_url,
                    "document_name": doc_name,
                    "chunk_index": r.get("chunk_index", 0),
                },
            })
    return entries


def _run_web(query: str, iteration: int, num_results: int = 2) -> list[dict]:
    """Run a single web_search and return context entries. Thread-safe."""
    import hashlib
    entries: list[dict] = []
    results = web_search(query, num_results=num_results)
    logger.info("web_search('%s', num_results=%d) → %d results", query[:80], num_results, len(results))
    for wr in results:
        url = wr.get("url", "")
        src_id = "SRC_" + hashlib.sha256(url.encode()).hexdigest()[:6].upper()
        entries.append({
            "iteration": iteration,
            "source": f"web:{url}",
            "source_id": src_id,
            "document_name": wr.get("title", url),
            "content": f"{wr.get('title', '')}\n{wr.get('content', '')}",
            "metadata": {"type": "web_search", "url": url},
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
    target_doc_id = state.get("target_document_id", "")
    ws_limit = state.get("web_search_limit", 2)

    search_steps = [s for s in plan[:4] if s.get("action", "search") in ("search", "web_search")]
    other_steps = [s for s in plan[:4] if s.get("action", "search") not in ("search", "web_search")]

    if parallel:
        futures_map: dict = {}
        with ThreadPoolExecutor(max_workers=_PARALLEL_WORKERS) as pool:
            for step in search_steps:
                q = step.get("query", state["query"])
                futures_map[pool.submit(_run_semantic, q, iteration, target_doc_id)] = ("semantic", q)
                if ws_flag:
                    futures_map[pool.submit(_run_web, q, iteration, ws_limit)] = ("web", q)

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
            new_context.extend(_run_semantic(q, iteration, target_doc_id))
            observer.trace_tool_call(iteration=iteration, operation="semantic_search", input_summary=q[:200], output_summary="done", tokens_used=0)
            if ws_flag:
                new_context.extend(_run_web(q, iteration, ws_limit))
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
    # Use source_id-based context formatting for the LLM
    context_text = "\n\n".join(
        _format_context_entry(c) for c in new_context[-10:]
    )
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

    update: dict = {
        "failure_hints": failure_hints,
    }

    # Dynamically increase web_search_limit when sources appear insufficient
    if not passed:
        current_limit = state.get("web_search_limit", 2)
        max_limit = state.get("web_search_max_limit", 5)
        if current_limit < max_limit:
            details = state.get("verification_result", {}).get("quality_details", {})
            needs_more_sources = (
                details.get("completeness", 10) < 6
                or details.get("source_quality", 10) < 6
                or any(
                    kw in imp.lower()
                    for imp in improvements
                    for kw in ("source", "evidence", "citation", "reference", "web", "depth")
                )
            )
            if needs_more_sources:
                update["web_search_limit"] = min(current_limit + 2, max_limit)

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
        return {"status": "finalizing", "human_direction": direction, "quality_score": quality_score}

    return {"status": "planning", "human_direction": direction}


def route_after_review(state: ResearchState) -> Literal["iterate", "artifact_router"]:
    """Route after human review: iterate if user wants to continue, else artifact branch."""
    if state.get("status") == "finalizing":
        return "artifact_router"
    return "iterate"


def route_artifact(state: ResearchState) -> Literal["artifact_plan", "finalize"]:
    """Route after artifact_router: plan if enabled, else finalize."""
    if state.get("enable_claim_evidence_graph"):
        return "artifact_plan"
    return "finalize"


def route_after_plan(state: ResearchState) -> Literal["permission_gate", "finalize"]:
    """Route after artifact_plan: skip to finalize if planning failed."""
    if state.get("artifact_status") == "failed":
        return "finalize"
    return "permission_gate"


def route_after_permission(state: ResearchState) -> Literal["sandbox_execute", "finalize"]:
    """Route after permission gate: execute if approved, else finalize."""
    if state.get("execution_permission_decision") == "approved":
        return "sandbox_execute"
    return "finalize"


def route_after_artifact_verification(state: ResearchState) -> Literal["finalize"]:
    """Always routes to finalize after verification."""
    return "finalize"


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


# --- Artifact Branch Nodes ---


def artifact_router_node(state: ResearchState, writer: StreamWriter) -> dict:
    """Route: check if claim-evidence graph is enabled."""
    if state.get("enable_claim_evidence_graph"):
        return {"artifact_status": "planning"}
    return {"artifact_status": "disabled"}


def artifact_plan_node(state: ResearchState, writer: StreamWriter) -> dict:
    """Plan the claim-evidence graph using LLM to generate structured spec."""
    import concurrent.futures
    from agents.orchestrator.artifact_planner import plan_claim_evidence_graph

    execution_id = f"exec-{uuid.uuid4().hex[:8]}"

    writer({"progress": "artifact_planning", "artifact_type": "claim_evidence_graph"})
    logger.info("Starting claim-evidence graph planning (execution_id=%s)", execution_id)

    # Timeout guard: fail gracefully if LLM is unresponsive
    timeout_sec = int(os.environ.get("ARTIFACT_PLAN_TIMEOUT", "30"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(plan_claim_evidence_graph, state)
        try:
            result = future.result(timeout=timeout_sec)
        except concurrent.futures.TimeoutError:
            logger.error("Claim-evidence planning timed out after %ds", timeout_sec)
            writer({"progress": "execution_failed", "execution_id": execution_id, "stage": "artifact_plan", "error": f"Timed out ({timeout_sec}s)"})
            return {
                "artifact_status": "failed",
                "artifact_execution_id": execution_id,
                "claim_evidence_spec": {},
                "sandbox_error": f"Planning timed out after {timeout_sec}s — model may not support this prompt size",
                "total_tokens": state.get("total_tokens", 0),
            }

    spec = result.get("spec", {})
    errors = result.get("errors", [])
    tokens_used = result.get("tokens_used", 0)

    total_tokens = state.get("total_tokens", 0) + tokens_used

    if errors:
        logger.warning("Claim-evidence spec errors: %s", errors)
        writer({"progress": "execution_failed", "execution_id": execution_id, "stage": "artifact_plan", "error": errors[0][:200]})
        return {
            "artifact_status": "failed",
            "artifact_execution_id": execution_id,
            "claim_evidence_spec": {},
            "sandbox_error": f"Planning failed: {'; '.join(errors[:3])}",
            "total_tokens": total_tokens,
        }

    logger.info("Claim-evidence spec generated: %d nodes, %d edges", len(spec.get("nodes", [])), len(spec.get("edges", [])))

    exec_permissions = {
        "network": "deny",
        "read_only": ["/sandbox/app", "/sandbox/input"],
        "read_write": ["/sandbox/output", "/tmp"],
        "cpu": os.environ.get("OPENSHELL_CPU", "500m"),
        "memory": os.environ.get("OPENSHELL_MEMORY", "512Mi"),
        "timeout_seconds": int(os.environ.get("OPENSHELL_TIMEOUT_SECONDS", "60")),
    }

    permission_request = {
        "type": "execution_permission",
        "execution_id": execution_id,
        "artifact_type": "claim_evidence_graph",
        "purpose": "Render a Claim-Evidence Graph from the accepted report",
        "command": [
            "python3",
            "/sandbox/app/claim_evidence_renderer.py",
            "/sandbox/input/claim_evidence.json",
            "/sandbox/output/claim-evidence.svg",
        ],
        "permissions": exec_permissions,
    }

    writer({
        "progress": "execution_proposed",
        "execution_id": execution_id,
        "artifact_type": "claim_evidence_graph",
        "permission_summary": exec_permissions,
    })

    return {
        "artifact_status": "permission_required",
        "artifact_execution_id": execution_id,
        "claim_evidence_spec": spec,
        "execution_permission_request": permission_request,
        "total_tokens": total_tokens,
    }


def permission_gate_node(state: ResearchState, writer: StreamWriter) -> dict:
    """Gate: interrupt for user permission or auto-approve."""
    permission_request = state.get("execution_permission_request", {})
    execution_id = state.get("artifact_execution_id", "")
    require_approval = os.environ.get("OPENSHELL_REQUIRE_APPROVAL", "true").lower() == "true"

    if not require_approval:
        writer({
            "progress": "permission_approved",
            "execution_id": execution_id,
        })
        return {"execution_permission_decision": "approved", "artifact_status": "approved"}

    writer({
        "progress": "permission_required",
        "execution_id": execution_id,
        "permissions": permission_request.get("permissions", {}),
    })

    user_response = interrupt(permission_request)

    decision = "denied"
    if isinstance(user_response, str):
        raw = user_response.strip()
        if raw == "__execution_approve__":
            decision = "approved"
    elif isinstance(user_response, dict):
        action = user_response.get("action", "")
        if action == "__execution_approve__":
            decision = "approved"

    if decision == "approved":
        writer({"progress": "permission_approved", "execution_id": execution_id})
        return {"execution_permission_decision": "approved", "artifact_status": "approved"}
    else:
        writer({
            "progress": "execution_denied",
            "execution_id": execution_id,
            "reason": "User denied execution",
        })
        return {"execution_permission_decision": "denied", "artifact_status": "denied"}


def sandbox_execute_node(state: ResearchState, writer: StreamWriter) -> dict:
    """Execute the trusted renderer inside an OpenShell sandbox."""
    from harness.execution.openshell_executor import get_executor

    execution_id = state.get("artifact_execution_id", "")
    spec = state.get("claim_evidence_spec", {})
    session_id = state.get("session_id", "")

    executor = get_executor()
    sandbox_name = f"research-artifact-{session_id}-{execution_id}"

    writer({
        "progress": "sandbox_scheduled",
        "execution_id": execution_id,
        "sandbox_id": sandbox_name,
    })

    try:
        from harness.execution.models import SandboxConfig
        config = SandboxConfig(
            name=sandbox_name,
            image=os.environ.get("OPENSHELL_RENDERER_IMAGE", ""),
            workspace=os.environ.get("OPENSHELL_WORKSPACE", "default"),
            cpu=os.environ.get("OPENSHELL_CPU", "500m"),
            memory=os.environ.get("OPENSHELL_MEMORY", "512Mi"),
            labels={
                "app": "rhoai-custom-research",
                "artifact": "claim-evidence",
                "session": session_id,
                "execution": execution_id,
            },
            policy_path=os.environ.get(
                "OPENSHELL_POLICY_PATH",
                "config/openshell/claim-evidence-policy.yaml",
            ),
        )

        sandbox_id = executor.create_sandbox(config)

        writer({
            "progress": "sandbox_running",
            "execution_id": execution_id,
            "sandbox_id": sandbox_id,
        })

        import json as _json
        input_data = _json.dumps(spec, ensure_ascii=False).encode("utf-8")
        executor.upload_inputs(sandbox_id, {"/sandbox/input/claim_evidence.json": input_data})

        timeout = int(os.environ.get("OPENSHELL_TIMEOUT_SECONDS", "60"))
        result = executor.execute(
            sandbox_id,
            command=[
                "python3",
                "/sandbox/app/claim_evidence_renderer.py",
                "/sandbox/input/claim_evidence.json",
                "/sandbox/output/claim-evidence.svg",
            ],
            timeout=timeout,
        )

        if result.exit_code != 0:
            logger.error("Renderer exited with code %d: %s", result.exit_code, result.stderr[:500])
            writer({
                "progress": "execution_failed",
                "execution_id": execution_id,
                "stage": "sandbox_execute",
                "error": f"Renderer exited with code {result.exit_code}",
            })
            return {
                "sandbox_id": sandbox_id,
                "sandbox_status": "failed",
                "sandbox_error": f"Renderer exit code {result.exit_code}: {result.stderr[:200]}",
                "artifact_status": "failed",
            }

        outputs = executor.download_outputs(
            sandbox_id,
            ["/sandbox/output/claim-evidence.svg", "/sandbox/output/artifact-metadata.json"],
        )

        svg_data = outputs.get("/sandbox/output/claim-evidence.svg", b"")
        metadata_raw = outputs.get("/sandbox/output/artifact-metadata.json", b"")

        artifact_metadata = {}
        if metadata_raw:
            try:
                artifact_metadata = _json.loads(metadata_raw)
            except _json.JSONDecodeError:
                pass

        artifact_id = f"artifact-{uuid.uuid4().hex[:8]}"

        writer({
            "progress": "artifact_created",
            "execution_id": execution_id,
            "artifact_id": artifact_id,
            "format": "svg",
        })

        return {
            "sandbox_id": sandbox_id,
            "sandbox_status": "completed",
            "artifact_status": "created",
            "claim_evidence_artifact": {
                "artifact_id": artifact_id,
                "type": "claim_evidence_graph",
                "format": "svg",
                "svg_data": svg_data.decode("utf-8", errors="replace") if svg_data else "",
                "metadata": artifact_metadata,
                "execution_id": execution_id,
                "title": spec.get("title", "Claim-Evidence Graph"),
            },
        }

    except Exception as e:
        logger.error("Sandbox execution failed: %s", e)
        writer({
            "progress": "execution_failed",
            "execution_id": execution_id,
            "stage": "sandbox_execute",
            "error": str(e)[:200],
        })
        return {
            "sandbox_id": sandbox_name,
            "sandbox_status": "failed",
            "sandbox_error": str(e)[:500],
            "artifact_status": "failed",
        }
    finally:
        try:
            executor.delete_sandbox(sandbox_name)
        except Exception as cleanup_err:
            logger.warning("Sandbox cleanup failed: %s", cleanup_err)


def artifact_verify_node(state: ResearchState, writer: StreamWriter) -> dict:
    """Verify the generated SVG artifact for safety and completeness."""
    import xml.etree.ElementTree as ET

    execution_id = state.get("artifact_execution_id", "")
    artifact = state.get("claim_evidence_artifact", {})
    spec = state.get("claim_evidence_spec", {})

    writer({"progress": "artifact_verifying", "execution_id": execution_id})

    checks: dict[str, bool] = {}
    svg_data = artifact.get("svg_data", "")

    # Check 1: SVG exists
    checks["file_exists"] = bool(svg_data)

    # Check 2: Not empty and reasonable size
    checks["size_valid"] = 0 < len(svg_data) < 2_000_000

    # Check 3: Valid XML
    valid_xml = False
    if svg_data:
        try:
            ET.fromstring(svg_data)
            valid_xml = True
        except ET.ParseError:
            pass
    checks["valid_svg"] = valid_xml

    # Check 4: No script tags
    checks["no_scripts"] = "<script" not in svg_data.lower()

    # Check 5: No external resources
    has_external = False
    for pattern in ["xlink:href=\"http", "href=\"http", "url(http"]:
        if pattern in svg_data.lower():
            has_external = True
            break
    checks["no_external_resources"] = not has_external

    # Check 6: Source links valid — every evidence node references known source
    spec_nodes = spec.get("nodes", [])
    evidence_nodes = [n for n in spec_nodes if n.get("type") == "evidence"]
    accumulated = state.get("accumulated_context", [])
    available_ids = {str(i) for i in range(1, len(accumulated) + 1)}
    source_valid = all(
        n.get("source_id", "") in available_ids or not n.get("source_id")
        for n in evidence_nodes
    )
    checks["source_links_valid"] = source_valid

    # Check 7: Renderer exit code (already checked in sandbox_execute, infer from status)
    checks["renderer_success"] = state.get("sandbox_status") == "completed"

    passed = all(checks.values())

    verification = {"passed": passed, "checks": checks}

    if passed:
        writer({"progress": "execution_completed", "execution_id": execution_id, "artifact": artifact})
    else:
        failed_checks = [k for k, v in checks.items() if not v]
        logger.warning("Artifact verification failed: %s", failed_checks)
        writer({
            "progress": "execution_failed",
            "execution_id": execution_id,
            "stage": "artifact_verify",
            "error": f"Verification failed: {', '.join(failed_checks)}",
        })

    return {
        "artifact_verification": verification,
        "artifact_status": "completed" if passed else "failed",
    }


def _build_source_registry(accumulated_context: list[dict]) -> dict[str, dict]:
    """Build a source registry keyed by source_id from accumulated context.

    Returns: {source_id: {name, url, snippet, domain}}
    """
    import re as _re
    from urllib.parse import urlparse

    registry: dict[str, dict] = {}
    for ctx in accumulated_context:
        src_id = ctx.get("source_id", "")
        if not src_id or src_id in registry:
            continue
        metadata = ctx.get("metadata") or {}
        url = metadata.get("source_url", "") or metadata.get("url", "")
        raw_name = ctx.get("document_name", ctx.get("source", "")) or ""
        doc_name = _re.sub(r"\[\d+\]$", "", raw_name).strip() or src_id
        snippet = (ctx.get("content", "") or "")[:150].strip()
        domain = ""
        if url and url.startswith("http"):
            try:
                domain = urlparse(url).netloc
            except Exception:
                domain = url[:40]
        registry[src_id] = {
            "name": doc_name,
            "url": url if (url and url.startswith("http")) else "",
            "snippet": snippet,
            "domain": domain,
        }
    return registry


def resolve_citations(text: str, accumulated_context: list[dict]) -> tuple[str, list[dict]]:
    """Citation resolver: extract [[cite:SRC_ID]], validate, assign numbers, replace.

    1. Extract all [[cite:SOURCE_ID]] tokens from text.
    2. Validate each against the source registry.
    3. Assign citation numbers by first-appearance order.
    4. Replace [[cite:SRC_ID]] with [N](#cite-N).
    5. Return (resolved_text, sources_list for frontend).

    Unknown/hallucinated source IDs are silently removed.
    """
    import re as _re

    registry = _build_source_registry(accumulated_context)

    # Find all cited source IDs in order of appearance
    cite_pattern = _re.compile(r"\[\[cite:(SRC_[A-Z0-9]+)\]\]")
    all_cited = cite_pattern.findall(text)

    # Assign sequential numbers by first appearance (only valid IDs)
    id_to_num: dict[str, int] = {}
    for src_id in all_cited:
        if src_id in registry and src_id not in id_to_num:
            id_to_num[src_id] = len(id_to_num) + 1

    # Remove any legacy numeric citations the LLM might have produced
    text = _re.sub(r"\[Source\s+\d+\](?!\()", "", text)
    text = _re.sub(r"\[\d+\]\(#cite-\d+\)", "", text)

    # Replace [[cite:SRC_ID]] with [N](#cite-N) or remove if invalid
    def _replace_cite(m: _re.Match) -> str:
        src_id = m.group(1)
        num = id_to_num.get(src_id)
        if num is None:
            return ""
        return f"[{num}](#cite-{num})"

    resolved = cite_pattern.sub(_replace_cite, text)

    # Build sources list for frontend (only actually cited sources)
    sources_list = []
    for src_id, num in sorted(id_to_num.items(), key=lambda x: x[1]):
        entry = registry[src_id]
        sources_list.append({
            "index": num,
            "name": entry["name"],
            "url": entry["url"],
            "snippet": entry["snippet"],
            "domain": entry["domain"],
        })

    return resolved, sources_list


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

    output = _fix_markdown_output(output)

    # Resolve [[cite:SRC_ID]] → [N](#cite-N) and build sources list
    accumulated_context = state.get("accumulated_context") or []
    output, sources_list = resolve_citations(output, accumulated_context)

    # Append references section (only actually cited sources, deterministic order)
    if sources_list:
        ref_lines = []
        for s in sources_list:
            badge = f"[{s['index']}](#cite-{s['index']})"
            if s["url"]:
                ref_lines.append(f"{badge} [{s['name']}]({s['url']})")
            else:
                ref_lines.append(f"{badge} {s['name']}")
        references = "\n\n".join(ref_lines)
        footer_marker = "\n\n---\n*Research completed"
        if footer_marker in output:
            output = output.replace(footer_marker, f"\n\n---\n\n## References\n\n{references}{footer_marker}")
        else:
            output += f"\n\n---\n\n## References\n\n{references}"

    update = {
        "final_output": output,
        "sources": sources_list,
        "total_cost": total_cost,
        "status": "complete",
        "quality_score": score,
    }

    # Preserve artifact metadata if present (never modify report text)
    artifact = state.get("claim_evidence_artifact")
    if artifact and state.get("artifact_status") == "completed":
        update["claim_evidence_artifact"] = artifact

    return update


def _fix_markdown_output(text: str) -> str:
    """Ensure blank lines before headings and fix table formatting."""
    import re
    text = re.sub(r"(\])\.(#{1,6}\s)", r"\1.\n\n\2", text)
    text = re.sub(r"(\|)\s*(#{1,6}\s)", r"\1\n\n\2", text)
    text = re.sub(r"([^\n])\n(#{1,6}\s)", r"\1\n\n\2", text)
    text = re.sub(r"([^\n#])(#{1,6}\s)", r"\1\n\n\2", text)
    text = re.sub(r" \| \| ", " |\n| ", text)
    text = re.sub(r"(\| :?-+:? (?:\| :?-+:? )*\|) (\|)", r"\1\n\2", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
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
    graph.add_node("artifact_router", artifact_router_node)
    graph.add_node("artifact_plan", artifact_plan_node)
    graph.add_node("permission_gate", permission_gate_node)
    graph.add_node("sandbox_execute", sandbox_execute_node)
    graph.add_node("artifact_verify", artifact_verify_node)
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
        {"iterate": "iterate", "artifact_router": "artifact_router"},
    )
    graph.add_edge("iterate", "plan")
    graph.add_conditional_edges(
        "artifact_router", route_artifact,
        {"artifact_plan": "artifact_plan", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "artifact_plan", route_after_plan,
        {"permission_gate": "permission_gate", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "permission_gate", route_after_permission,
        {"sandbox_execute": "sandbox_execute", "finalize": "finalize"},
    )
    graph.add_edge("sandbox_execute", "artifact_verify")
    graph.add_edge("artifact_verify", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer)


from langgraph.checkpoint.memory import MemorySaver

orchestrator_graph = build_graph(checkpointer=MemorySaver())
