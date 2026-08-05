"""FastAPI backend API with SSE streaming for the research harness."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import uuid
import tempfile
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, Header, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from prometheus_fastapi_instrumentator import Instrumentator

load_dotenv(override=True)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.session import SessionManager, ResearchSession
import agents.orchestrator.graph as _graph_module
from backend.metrics import (
    active_research_sessions,
    research_sessions_total,
    research_quality_score,
    documents_processed_total,
)
from backend.observability import init_mlflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MCP_SERVERS = [
    ("vector-search-mcp", "mcp_servers.vector_search_mcp.server", 9002),
    ("web-search-mcp", "mcp_servers.web_search_mcp.server", 9003),
    ("verification-mcp", "mcp_servers.verification_mcp.server", 9004),
    ("observability-mcp", "mcp_servers.observability_mcp.server", 9005),
]

_mcp_processes: list[subprocess.Popen] = []


def _port_in_use(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0




def _start_mcp_servers():
    """Start MCP servers as subprocesses."""
    for name, module, port in MCP_SERVERS:
        if _port_in_use(port):
            logger.info("MCP server %s already running on port %d — skipping", name, port)
            continue
        proc = subprocess.Popen(
            [sys.executable, "-m", module],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        _mcp_processes.append(proc)
        logger.info("Started %s (pid=%d) on port %d", name, proc.pid, port)

    max_wait, interval = 15, 1
    waited = 0
    while waited < max_wait:
        time.sleep(interval)
        waited += interval
        pending = [f"{n}:{p}" for n, _, p in MCP_SERVERS if not _port_in_use(p)]
        if not pending:
            break
    if pending:
        logger.warning("MCP servers not ready after %ds: %s", max_wait, ", ".join(pending))
    else:
        logger.info("All %d MCP servers ready (%ds)", len(MCP_SERVERS), waited)


def _stop_mcp_servers():
    """Gracefully stop tracked MCP subprocesses (ones this process started)."""
    for proc in _mcp_processes:
        if proc.poll() is None:
            proc.terminate()
    for proc in _mcp_processes:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    if _mcp_processes:
        logger.info("Stopped %d tracked MCP subprocesses", len(_mcp_processes))
    _mcp_processes.clear()


def _stop_mcp_servers_full():
    """Stop tracked subprocesses + port-based cleanup for orphans.

    Only called during lifespan shutdown (the real backend exit),
    not from atexit or signal handlers, to avoid killing MCP servers
    owned by another process during casual imports.
    """
    _stop_mcp_servers()

    for name, _, port in MCP_SERVERS:
        if _port_in_use(port):
            try:
                import signal as _sig
                result = subprocess.run(
                    ["lsof", "-ti", f":{port}"],
                    capture_output=True, text=True, timeout=5,
                )
                for pid_str in result.stdout.strip().splitlines():
                    pid = int(pid_str)
                    os.kill(pid, _sig.SIGTERM)
                    logger.info("Killed orphan process pid=%d on port %d (%s)", pid, port, name)
            except Exception as e:
                logger.warning("Port-based cleanup failed for %s (port %d): %s", name, port, e)


import atexit

atexit.register(_stop_mcp_servers)

def _signal_handler(signum, frame):
    _stop_mcp_servers()
    sys.exit(0)

signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _start_mcp_servers()

    # Initialize PostgreSQL checkpointer if configured
    pg_url = os.getenv("POSTGRES_URL", "")
    if pg_url:
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            checkpointer_ctx = AsyncPostgresSaver.from_conn_string(pg_url)
            checkpointer = await checkpointer_ctx.__aenter__()
            await checkpointer.setup()

            compiled = _graph_module.build_graph(checkpointer=checkpointer)
            _graph_module.orchestrator_graph = compiled

            app.state.pg_checkpointer = checkpointer
            app.state.pg_checkpointer_ctx = checkpointer_ctx
            logger.info("PostgreSQL checkpointer initialized: %s", pg_url[:40] + "...")
        except Exception as e:
            logger.warning("PostgreSQL checkpointer setup failed (falling back to in-memory): %s", e)
            app.state.pg_checkpointer = None
    else:
        app.state.pg_checkpointer = None
        logger.info("POSTGRES_URL not set — using in-memory checkpointer")

    yield

    if getattr(app.state, "pg_checkpointer_ctx", None):
        await app.state.pg_checkpointer_ctx.__aexit__(None, None, None)
    _stop_mcp_servers_full()


app = FastAPI(title="RHOAI Deep Research API", version="0.1.0", lifespan=lifespan)

Instrumentator().instrument(app).expose(app)
init_mlflow()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

session_mgr = SessionManager()


# --- AG-UI Protocol Endpoint ---


class AgUiRunInput(BaseModel):
    """Matches the RunAgentInput schema sent by @ag-ui/client HttpAgent."""
    model_config = {"populate_by_name": True}

    run_id: str = Field(default="", alias="runId")
    thread_id: str = Field(default="", alias="threadId")
    messages: list = []
    state: dict | None = None
    tools: list = []
    context: list = []
    forwarded_props: dict = Field(default_factory=dict, alias="forwardedProps")


def _agui_event(payload: dict) -> str:
    """Format a dict as an AG-UI SSE data line."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream_agui(run_id: str, thread_id: str, query: str, settings: dict, resume_direction: str = "") -> AsyncGenerator[str, None]:
    """Run the orchestrator graph and yield AG-UI protocol SSE events."""
    has_document = _check_documents_exist()
    msg_id = str(uuid.uuid4())

    yield _agui_event({"type": "RUN_STARTED", "runId": run_id, "threadId": thread_id})

    if not has_document and not query and not resume_direction:
        yield _agui_event({"type": "TEXT_MESSAGE_START", "messageId": msg_id})
        yield _agui_event({
            "type": "TEXT_MESSAGE_CONTENT",
            "messageId": msg_id,
            "delta": "Please upload a document first, then ask your research question.",
        })
        yield _agui_event({"type": "TEXT_MESSAGE_END", "messageId": msg_id})
        yield _agui_event({
            "type": "MESSAGES_SNAPSHOT",
            "messages": [{"id": msg_id, "role": "assistant", "content": "Please upload a document first, then ask your research question."}],
        })
        yield _agui_event({"type": "RUN_FINISHED", "runId": run_id, "threadId": thread_id})
        return

    language = settings.get("language", "en-US")
    lang_instruction = (
        "You MUST respond entirely in Korean (한국어로 답변하세요)."
        if language == "ko-KR"
        else "You MUST respond entirely in English."
    )

    config = {"configurable": {"thread_id": thread_id}}

    if resume_direction:
        from langgraph.types import Command
        graph_input = Command(resume={"action": "continue", "direction": resume_direction})
    else:
        graph_input = {
            "session_id": thread_id[:12] if thread_id else str(uuid.uuid4())[:12],
            "query": query,
            "file_path": "",
            "has_document": has_document,
            "iteration": 0,
            "max_iterations": settings.get("maxIterations", 2),
            "quality_threshold": settings.get("qualityThreshold", 7.0),
            "language_instruction": lang_instruction,
            "research_plan": [],
            "accumulated_context": [],
            "current_draft": "",
            "verification_result": {},
            "verification_history": [],
            "quality_score": 0.0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "failure_hints": "",
            "human_direction": "",
            "enable_web_search": settings.get("enableWebSearch", True),
            "enable_planning": settings.get("enablePlanning", True),
            "enable_fact_check": settings.get("enableFactCheck", True),
            "enable_parallel": settings.get("enableParallel", True),
            "enable_sectioned": settings.get("enableSectioned", True),
            "report_sections": [],
            "section_order": [],
            "failing_sections": [],
            "intent": "",
            "status": "normalizing",
            "final_output": "",
            "error": "",
        }

    session_id = thread_id[:12] if thread_id else str(uuid.uuid4())[:12]
    session = ResearchSession(
        session_id=session_id,
        query=query,
        max_iterations=settings.get("maxIterations", 2),
        quality_threshold=settings.get("qualityThreshold", 7.0),
    )

    event_queue: asyncio.Queue = asyncio.Queue()
    text_started = False
    accumulated_steps: list[dict] = []
    accumulated_verbose: list[dict] = []
    state_update: dict = {}

    async def _run_graph():
        try:
            async for mode, chunk in _graph_module.orchestrator_graph.astream(
                graph_input,
                config=config,
                stream_mode=["updates", "custom"],
            ):
                await event_queue.put((mode, chunk))
        except Exception as exc:
            logger.error("Graph error: %s", exc, exc_info=True)
            await event_queue.put(("error", {"__error__": str(exc)}))
        finally:
            await event_queue.put(None)

    graph_task = asyncio.create_task(_run_graph())

    try:
        while True:
            try:
                item = await asyncio.wait_for(event_queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue

            if item is None:
                logger.info("[agui] Graph stream completed normally")
                break

            mode, chunk = item
            logger.debug("[agui] mode=%s chunk_keys=%s", mode, list(chunk.keys()) if isinstance(chunk, dict) else type(chunk))

            if mode == "error" or (isinstance(chunk, dict) and "__error__" in chunk):
                error_msg = chunk.get("__error__", "Unknown error") if isinstance(chunk, dict) else str(chunk)
                logger.error("[agui] Emitting RUN_ERROR: %s", error_msg)
                yield _agui_event({"type": "RUN_ERROR", "message": error_msg})
                return

            if mode == "custom":
                progress = chunk.get("progress", "")
                if progress == "draft_chunk":
                    text = chunk.get("text", "")
                    if text:
                        if not text_started:
                            text_started = True
                            yield _agui_event({"type": "TEXT_MESSAGE_START", "messageId": msg_id})
                        yield _agui_event({"type": "TEXT_MESSAGE_CONTENT", "messageId": msg_id, "delta": text})

                step_evt = _custom_progress_to_step(chunk, session)
                if step_evt:
                    accumulated_steps.append(step_evt)
                    yield _agui_event({"type": "CUSTOM", "name": "step", "value": step_evt})

                verbose_evt = {
                    "id": str(uuid.uuid4())[:8],
                    "type": progress or "custom",
                    "timestamp": int(__import__("time").time() * 1000),
                    "data": {k: v for k, v in chunk.items() if k != "progress"},
                }
                accumulated_verbose.append(verbose_evt)
                yield _agui_event({"type": "CUSTOM", "name": "verbose", "value": verbose_evt})
                yield _agui_event({"type": "STATE_SNAPSHOT", "snapshot": {"steps": accumulated_steps, "verbose": accumulated_verbose}})
                continue

            if not isinstance(chunk, dict) or not chunk:
                logger.debug("[agui] Skipping non-dict chunk: %s", type(chunk))
                continue
            node_name = next(iter(chunk))
            state_update = chunk[node_name]
            if not isinstance(state_update, dict):
                logger.debug("[agui] Skipping non-dict state from node %s: %s", node_name, type(state_update))
                continue
            iteration = state_update.get("iteration", session.iteration)
            quality_score = state_update.get("quality_score", session.quality_score)
            status = state_update.get("status", session.status)

            session.iteration = iteration
            session.quality_score = quality_score
            session.status = status
            if "current_draft" in state_update:
                session.current_draft = state_update["current_draft"]
            if "accumulated_context" in state_update:
                session.accumulated_context = state_update["accumulated_context"]
            if "total_tokens" in state_update:
                session.total_tokens = state_update["total_tokens"]
            if "report_sections" in state_update:
                session.report_sections = state_update["report_sections"]
            if "section_order" in state_update:
                session.section_order = state_update["section_order"]
            if "failing_sections" in state_update:
                session.failing_sections = state_update["failing_sections"]

            sub_events = _emit_sub_events(node_name, state_update, session)
            for evt in sub_events:
                evt["iteration"] = session.iteration
                evt["max_iterations"] = session.max_iterations
                evt["quality_score"] = session.quality_score

                step_entry = {
                    "id": str(uuid.uuid4())[:8],
                    "phase": evt.get("phase", node_name),
                    "icon": evt.get("icon", ""),
                    "title": evt.get("title", ""),
                    "detail": evt.get("detail", ""),
                    "timestamp": int(__import__("time").time() * 1000),
                }
                accumulated_steps.append(step_entry)
                yield _agui_event({"type": "CUSTOM", "name": "step", "value": step_entry})

                verbose_entry = {
                    "id": str(uuid.uuid4())[:8],
                    "type": f"node:{node_name}",
                    "timestamp": int(__import__("time").time() * 1000),
                    "data": evt,
                }
                accumulated_verbose.append(verbose_entry)
                yield _agui_event({"type": "CUSTOM", "name": "verbose", "value": verbose_entry})

            yield _agui_event({"type": "STATE_SNAPSHOT", "snapshot": {"steps": accumulated_steps, "verbose": accumulated_verbose}})

        # Check if graph was interrupted (human-in-the-loop review)
        graph_state = await _graph_module.orchestrator_graph.aget_state(config)
        pending_interrupts = getattr(graph_state, "tasks", [])
        logger.info("[agui] Checking interrupts: %d tasks, next=%s", len(pending_interrupts), getattr(graph_state, "next", None))
        interrupt_data = None
        for task in pending_interrupts:
            logger.info("[agui] Task: %s, has interrupts: %s", getattr(task, "name", "?"), bool(hasattr(task, "interrupts") and task.interrupts))
            if hasattr(task, "interrupts") and task.interrupts:
                interrupt_data = task.interrupts[0].value
                break

        if interrupt_data:
            logger.info("[agui] Graph interrupted for review: %s", interrupt_data)
            if text_started:
                yield _agui_event({"type": "TEXT_MESSAGE_END", "messageId": msg_id})

            yield _agui_event({"type": "CUSTOM", "name": "iteration_review", "value": interrupt_data})
            yield _agui_event({"type": "STATE_SNAPSHOT", "snapshot": {
                "steps": accumulated_steps,
                "verbose": accumulated_verbose,
                "iteration_review": interrupt_data,
            }})

            review_msg = _format_review_message(interrupt_data, language)
            yield _agui_event({
                "type": "MESSAGES_SNAPSHOT",
                "messages": [{"id": msg_id, "role": "assistant", "content": review_msg}],
            })

            yield _agui_event({"type": "RUN_FINISHED", "runId": run_id, "threadId": thread_id})
        else:
            final_output = state_update.get("final_output", session.current_draft) if state_update else ""
            logger.info("[agui] Stream done. text_started=%s, final_output_len=%d", text_started, len(final_output))

            if text_started:
                yield _agui_event({"type": "TEXT_MESSAGE_END", "messageId": msg_id})

            if final_output and not text_started:
                yield _agui_event({"type": "TEXT_MESSAGE_START", "messageId": msg_id})
                yield _agui_event({"type": "TEXT_MESSAGE_CONTENT", "messageId": msg_id, "delta": final_output})
                yield _agui_event({"type": "TEXT_MESSAGE_END", "messageId": msg_id})

            sources_list = state_update.get("sources", []) if state_update else []
            if not sources_list and session.accumulated_context:
                from agents.orchestrator.graph import _dedup_sources
                sources_list = _dedup_sources(session.accumulated_context)
            if sources_list:
                yield _agui_event({"type": "CUSTOM", "name": "sources", "value": {"sources": sources_list}})
                yield _agui_event({"type": "STATE_SNAPSHOT", "snapshot": {
                    "steps": accumulated_steps,
                    "verbose": accumulated_verbose,
                    "sources": {"sources": sources_list},
                }})

            yield _agui_event({
                "type": "MESSAGES_SNAPSHOT",
                "messages": [{"id": msg_id, "role": "assistant", "content": final_output}],
            })

            yield _agui_event({"type": "RUN_FINISHED", "runId": run_id, "threadId": thread_id})

    except Exception as exc:
        logger.exception("Error in AG-UI stream")
        yield _agui_event({"type": "RUN_ERROR", "message": str(exc)})
        return
    finally:
        if not graph_task.done():
            graph_task.cancel()
            try:
                await graph_task
            except (asyncio.CancelledError, Exception):
                pass


def _format_review_message(review_data: dict, language: str = "en-US") -> str:
    """Format the iteration review data as a readable message for the user."""
    score = review_data.get("quality_score", 0)
    threshold = review_data.get("quality_threshold", 7.0)
    iteration = review_data.get("iteration", 0)
    max_iter = review_data.get("max_iterations", 5)
    improvements = review_data.get("improvements", [])
    can_iterate = review_data.get("can_iterate", True)

    if language == "ko-KR":
        lines = [
            f"## Iteration Review",
            f"",
            f"**Quality Score**: {score:.1f} / {threshold:.1f} (Iteration {iteration}/{max_iter})",
            f"",
        ]
        if improvements:
            lines.append("**Improvement Suggestions**:")
            for imp in improvements:
                lines.append(f"- {imp}")
            lines.append("")
        if can_iterate:
            lines.append("추가 개선 방향을 입력하시면 다음 iteration을 진행합니다. 현재 결과를 그대로 사용하시려면 **'accept'** 를 입력하세요.")
        else:
            lines.append(f"최대 iteration ({max_iter})에 도달했습니다. 추가 방향을 입력하시면 한 번 더 시도합니다. **'accept'** 를 입력하면 현재 결과를 확정합니다.")
    else:
        lines = [
            f"## Iteration Review",
            f"",
            f"**Quality Score**: {score:.1f} / {threshold:.1f} (Iteration {iteration}/{max_iter})",
            f"",
        ]
        if improvements:
            lines.append("**Improvement Suggestions**:")
            for imp in improvements:
                lines.append(f"- {imp}")
            lines.append("")
        if can_iterate:
            lines.append("Enter additional direction to proceed with the next iteration, or type **'accept'** to use the current result as-is.")
        else:
            lines.append(f"Maximum iterations ({max_iter}) reached. Enter direction for one more attempt, or type **'accept'** to finalize.")

    return "\n".join(lines)


def _custom_progress_to_step(chunk: dict, session: ResearchSession) -> dict | None:
    """Convert a custom progress event to a step entry for the frontend."""
    progress = chunk.get("progress", "")
    title = chunk.get("section_title", "")
    idx = chunk.get("section_index", 0)
    total = chunk.get("total_sections", 0)

    step = None
    if progress == "section_start":
        step = {
            "phase": "execute",
            "icon": "🔎",
            "title": f"[Execute][Researcher] ({idx}/{total}) Searching: {title}",
        }
    elif progress == "section_done":
        step = {
            "phase": "execute",
            "icon": "✅",
            "title": f"[Execute][Writer] ({idx}/{total}) Done: {title}",
        }
    elif progress == "section_failed":
        step = {
            "phase": "execute",
            "icon": "❌",
            "title": f"[Execute][Researcher] ({idx}/{total}) Failed: {title}",
        }
    elif progress == "assembling_report":
        step = {
            "phase": "execute",
            "icon": "📋",
            "title": f"[Execute][Writer] Assembling final report ({total} sections)",
        }
    elif progress == "search_done":
        sem = chunk.get("semantic_count", 0)
        web = chunk.get("web_count", 0)
        parts = []
        if sem:
            parts.append(f"{sem} chunks")
        if web:
            parts.append(f"{web} web results")
        step = {
            "phase": "execute",
            "icon": "🔍",
            "title": f"[Tool-Search][Researcher] {', '.join(parts)}",
        }
    elif progress == "drafting":
        step = {
            "phase": "execute",
            "icon": "✍️",
            "title": f"[Execute][Writer] ({idx}/{total}) Drafting: {title}",
        }
    elif progress == "verifying":
        step = {
            "phase": "verify",
            "icon": "📊",
            "title": "[Reviewing][Reviewer] Quality scoring...",
        }

    if step:
        step["id"] = str(uuid.uuid4())[:8]
        step["detail"] = ""
        step["timestamp"] = int(__import__("time").time() * 1000)
    return step


@app.post("/agent")
async def agui_endpoint(req: AgUiRunInput):
    """AG-UI protocol endpoint — streams research as AG-UI SSE events."""
    messages = req.messages or []
    query = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                query = " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            elif isinstance(content, str):
                query = content
            break

    run_id = req.run_id or str(uuid.uuid4())
    thread_id = req.thread_id or str(uuid.uuid4())
    settings = req.forwarded_props.get("settings", {})

    # Detect resume: check if the graph has a pending interrupt for this thread
    resume_direction = ""
    try:
        config = {"configurable": {"thread_id": thread_id}}
        graph_state = await _graph_module.orchestrator_graph.aget_state(config)
        pending_tasks = getattr(graph_state, "tasks", [])
        has_interrupt = any(
            hasattr(t, "interrupts") and t.interrupts for t in pending_tasks
        )
        if has_interrupt and query.strip():
            if query.strip().lower() == "accept":
                resume_direction = "__accept__"
            else:
                resume_direction = query.strip()
            query = ""
    except Exception:
        pass

    return StreamingResponse(
        _stream_agui(run_id, thread_id, query.strip(), settings, resume_direction=resume_direction),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class ResearchRequest(BaseModel):
    query: str
    file_path: str = ""
    quality_threshold: float = 7.0
    max_iterations: int = 2
    language_instruction: str = "You MUST respond entirely in English."
    enable_web_search: bool = True
    enable_planning: bool = True
    enable_fact_check: bool = True
    enable_parallel: bool = True
    enable_sectioned: bool = True


UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "rhoai_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _sse(event_data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"


def _emit_sub_events(node_name: str, state_update: dict, session: ResearchSession) -> list[dict]:
    """Generate rich sub-events that describe what happened inside a graph node."""
    events: list[dict] = []
    iteration = session.iteration
    max_iter = session.max_iterations

    if node_name == "normalize":
        events.append({
            "event": "step",
            "phase": "normalize",
            "icon": "🔄",
            "title": "[Harness][Orchestrator] Research session initialized",
            "agent": "Orchestrator",
            "detail": f"Query: \"{session.query[:120]}\"",
        })
        hints = state_update.get("failure_hints", "")
        if hints:
            events.append({
                "event": "step",
                "phase": "normalize",
                "icon": "💡",
                "title": "[Harness][Orchestrator] Loaded past failure memory",
                "agent": "Orchestrator",
                "detail": hints[:200],
            })

    elif node_name == "classify_intent":
        intent = state_update.get("intent", "research")
        icon = "💬" if intent == "casual" else "🔬"
        label = "casual conversation" if intent == "casual" else "research query"
        events.append({
            "event": "step",
            "phase": "classify_intent",
            "icon": icon,
            "title": f"[Harness][Orchestrator] Query classified as {label}",
            "agent": "Orchestrator",
            "detail": f"Intent: {intent}",
        })

    elif node_name == "direct_response":
        response = state_update.get("current_draft", "")
        events.append({
            "event": "step",
            "phase": "direct_response",
            "icon": "💬",
            "title": "[Harness][Orchestrator] Direct response generated",
            "agent": "Orchestrator",
            "detail": response[:150].replace("\n", " "),
        })

    elif node_name == "plan":
        plan = state_update.get("research_plan", [])
        section_order = state_update.get("section_order", [])
        is_sectioned = bool(section_order)

        if is_sectioned:
            events.append({
                "event": "step",
                "phase": "plan",
                "icon": "📋",
                "title": f"[Plan][Planner] Sectioned research plan — {len(plan)} sub-topics",
                "agent": "Planner",
                "detail": "",
            })
            for i, topic in enumerate(plan, 1):
                title = topic.get("title", "Untitled")
                events.append({
                    "event": "step",
                    "phase": "plan",
                    "icon": "📑",
                    "title": f"[Plan][Planner] Section {i}: {title}",
                    "agent": "Planner",
                    "detail": topic.get("purpose", ""),
                })
        else:
            events.append({
                "event": "step",
                "phase": "plan",
                "icon": "📋",
                "title": f"[Plan][Planner] Research plan generated ({len(plan)} steps)",
                "agent": "Planner",
                "detail": "",
            })
            for i, step in enumerate(plan, 1):
                action = step.get("action", "search")
                query = step.get("query", "")
                icon = {"search": "🔍", "analyze": "🧪", "compare": "⚖️"}.get(action, "📌")
                events.append({
                    "event": "step",
                    "phase": "plan",
                    "icon": icon,
                    "title": f"[Plan][Planner] Step {i}: [{action}] {query[:80]}",
                    "agent": "Planner",
                    "detail": step.get("purpose", ""),
                })

    elif node_name == "execute":
        error_msg = state_update.get("error", "")
        if error_msg:
            events.append({
                "event": "error",
                "phase": "execute",
                "icon": "🚫",
                "title": "[Execute][Error] Search failed",
                "agent": "Researcher",
                "detail": error_msg,
            })
            return events

        report_sections = state_update.get("report_sections", [])
        is_sectioned = bool(report_sections)

        if is_sectioned:
            ctx = state_update.get("accumulated_context", [])
            new_ctx = [c for c in ctx if c.get("iteration") == iteration]

            web_results = [c for c in new_ctx if c.get("source", "").startswith("web:")]
            search_results = [c for c in new_ctx if not c.get("source", "").startswith("web:") and c.get("source") != "synthesis" and "[" in c.get("source", "")]

            if search_results:
                sources = set()
                for r in search_results:
                    src = r.get("source", "")
                    doc_name = src.split("[")[0] if "[" in src else src
                    sources.add(doc_name)
                events.append({
                    "event": "step",
                    "phase": "execute",
                    "icon": "🔍",
                    "title": f"[Vector-Search][Researcher] {len(search_results)} chunks retrieved",
                    "agent": "Researcher",
                    "detail": f"Sources: {', '.join(list(sources)[:5])}",
                })

            if web_results:
                urls = [c.get("metadata", {}).get("url", "") for c in web_results if c.get("metadata", {}).get("url")]
                events.append({
                    "event": "step",
                    "phase": "execute",
                    "icon": "🌐",
                    "title": f"[Web Search][Researcher] Web search: {len(web_results)} results",
                    "agent": "Researcher",
                    "detail": ", ".join(urls[:3]),
                })

            draft = state_update.get("current_draft", "")
            if draft:
                events.append({
                    "event": "step",
                    "phase": "execute",
                    "icon": "📋",
                    "title": f"[Writing][Writer] Report ready ({len(draft):,} chars, {len(report_sections)} sections)",
                    "agent": "Writer",
                    "detail": "",
                })
        else:
            ctx = state_update.get("accumulated_context", [])
            new_ctx = [c for c in ctx if c.get("iteration") == iteration]

            web_results = [c for c in new_ctx if c.get("source", "").startswith("web:")]
            search_results = [c for c in new_ctx if not c.get("source", "").startswith("web:") and (c.get("source", "").startswith(("search", "semantic")) or "[" in c.get("source", ""))]
            synth_results = [c for c in new_ctx if c.get("source") == "synthesis"]

            if web_results:
                urls = [c.get("metadata", {}).get("url", "") for c in web_results if c.get("metadata", {}).get("url")]
                events.append({
                    "event": "step",
                    "phase": "execute",
                    "icon": "🌐",
                    "title": f"[Web Search][Researcher] Web search: {len(web_results)} results",
                    "agent": "Researcher",
                    "detail": ", ".join(urls[:3]),
                })

            if search_results:
                sources = set()
                for r in search_results:
                    src = r.get("source", "")
                    doc_name = src.split("[")[0] if "[" in src else src
                    sources.add(doc_name)
                events.append({
                    "event": "step",
                    "phase": "execute",
                    "icon": "🔍",
                    "title": f"[Vector-Search][Researcher] {len(search_results)} chunks retrieved",
                    "agent": "Researcher",
                    "detail": f"Sources: {', '.join(list(sources)[:5])}",
                })

            if synth_results:
                events.append({
                    "event": "step",
                    "phase": "execute",
                    "icon": "🧠",
                    "title": "[Researching][Researcher] Context synthesized",
                    "agent": "Researcher",
                    "detail": synth_results[-1].get("content", "")[:150],
                })

            draft = state_update.get("current_draft", "")
            if draft:
                draft_preview = draft[:200].replace("\n", " ")
                events.append({
                    "event": "step",
                    "phase": "execute",
                    "icon": "📝",
                    "title": f"[Writing][Writer] Report drafted ({len(draft):,} chars)",
                    "agent": "Writer",
                    "detail": draft_preview,
                })
            else:
                events.append({
                    "event": "step",
                    "phase": "execute",
                    "icon": "⚠️",
                    "title": "[Writing][Writer] Report generation failed",
                    "agent": "Writer",
                    "detail": "Report could not be generated in this iteration.",
                })

    elif node_name == "verify":
        score = state_update.get("quality_score", 0)
        passed = state_update.get("verification_result", {}).get("passed", False)
        v_result = state_update.get("verification_result", {})
        details = v_result.get("quality_details", {})
        improvements = v_result.get("improvements", [])

        status_icon = "✅" if passed else "⚠️"
        events.append({
            "event": "step",
            "phase": "verify",
            "icon": status_icon,
            "title": f"[Reviewing][Reviewer] Quality score: {score}/10 — {'PASSED' if passed else 'needs improvement'}",
            "agent": "Reviewer",
            "detail": "",
        })

        failing_sections = state_update.get("failing_sections", [])
        if failing_sections:
            events.append({
                "event": "step",
                "phase": "verify",
                "icon": "🔄",
                "title": f"[Reviewing][Reviewer] {len(failing_sections)} section(s) need rewrite",
                "agent": "Reviewer",
                "detail": ", ".join(failing_sections),
            })
        sections = state_update.get("report_sections", [])
        if sections:
            passed_sections = [s["sub_topic"] for s in sections if s.get("status") == "passed"]
            if passed_sections:
                events.append({
                    "event": "step",
                    "phase": "verify",
                    "icon": "✅",
                    "title": f"[Reviewing][Reviewer] {len(passed_sections)} section(s) passed",
                    "agent": "Reviewer",
                    "detail": ", ".join(passed_sections),
                })

        if details:
            breakdown = " | ".join(f"{k}: {v}" for k, v in details.items() if isinstance(v, (int, float)))
            if breakdown:
                events.append({
                    "event": "step",
                    "phase": "verify",
                    "icon": "📊",
                    "title": "[Reviewing][Reviewer] Score breakdown",
                    "agent": "Reviewer",
                    "detail": breakdown,
                })

        if improvements:
            events.append({
                "event": "step",
                "phase": "verify",
                "icon": "💬",
                "title": "[Reviewing][Reviewer] Improvement suggestions",
                "agent": "Reviewer",
                "detail": " / ".join(improvements[:3]),
            })

    elif node_name == "observe":
        events.append({
            "event": "step",
            "phase": "observe",
            "icon": "📊",
            "title": f"[Harness][Orchestrator] Iteration {iteration}/{max_iter} analysis recorded",
            "agent": "Orchestrator",
            "detail": state_update.get("failure_hints", "")[:150],
        })

    elif node_name == "iterate":
        new_iter = state_update.get("iteration", iteration)
        events.append({
            "event": "step",
            "phase": "iterate",
            "icon": "🔁",
            "title": f"[Harness][Orchestrator] Starting iteration {new_iter}/{max_iter}",
            "agent": "Orchestrator",
            "detail": "Applying improvements from previous verification feedback...",
        })

    elif node_name == "finalize":
        events.append({
            "event": "step",
            "phase": "finalize",
            "icon": "🎯",
            "title": f"[Harness][Orchestrator] Research complete — Quality: {session.quality_score}/10, Iterations: {iteration}",
            "agent": "Orchestrator",
            "detail": f"Total tokens used: {session.total_tokens:,}",
        })

    return events


def _collect_sources(accumulated_context: list[dict]) -> list[dict]:
    """Deduplicate and format sources from accumulated_context for citation display."""
    seen: set[str] = set()
    sources: list[dict] = []
    for ctx in accumulated_context:
        src = ctx.get("source", "")
        if not src or src in ("synthesis",) or src in seen:
            continue
        seen.add(src)
        meta = ctx.get("metadata", {})
        entry: dict = {"source": src}
        if src.startswith("web:"):
            entry["type"] = "web"
            entry["url"] = meta.get("url", src[4:])
            entry["title"] = ctx.get("content", "").split("\n")[0][:120]
        else:
            entry["type"] = "document"
            doc_name = src.split("[")[0] if "[" in src else src
            entry["document"] = doc_name
            entry["chunk"] = src
        sources.append(entry)
    return sources


_SSE_HEARTBEAT_INTERVAL = 15  # seconds between keepalive comments


def _check_documents_exist() -> bool:
    """Check if any documents have been ingested into the database."""
    try:
        from lib.document_processing import get_db_connection
        conn = get_db_connection()
        row = conn.execute("SELECT COUNT(*) FROM documents").fetchone()
        conn.close()
        return row[0] > 0 if row else False
    except Exception:
        return False


async def _stream_research(session: ResearchSession) -> AsyncGenerator[str, None]:
    """Run the orchestrator graph and yield rich SSE events for each phase.

    Sends SSE comment heartbeats every 15s to prevent connection timeouts
    while graph nodes are processing.
    """
    has_document = _check_documents_exist()

    if not has_document:
        yield _sse({
            "event": "content",
            "text": (
                "📄 **No documents found.** Please upload a document first using the "
                "attachment button (📎) at the bottom of the chat, then ask your research question.\n\n"
                "Supported formats: **PDF, TXT, MD, DOCX**"
            ),
        })
        yield "data: [DONE]\n\n"
        return

    initial_state = {
        "session_id": session.session_id,
        "query": session.query,
        "file_path": "",
        "has_document": has_document,
        "iteration": 0,
        "max_iterations": session.max_iterations,
        "quality_threshold": session.quality_threshold,
        "language_instruction": getattr(session, "language_instruction", "You MUST respond entirely in English."),
        "research_plan": [],
        "accumulated_context": [],
        "current_draft": "",
        "verification_result": {},
        "verification_history": [],
        "quality_score": 0.0,
        "total_tokens": 0,
        "total_cost": 0.0,
        "failure_hints": "",
        "enable_web_search": getattr(session, "_enable_web_search", True),
        "enable_planning": getattr(session, "_enable_planning", True),
        "enable_fact_check": getattr(session, "_enable_fact_check", True),
        "enable_parallel": getattr(session, "_enable_parallel", True),
        "enable_sectioned": getattr(session, "_enable_sectioned", True),
        "report_sections": [],
        "section_order": [],
        "failing_sections": [],
        "intent": "",
        "status": "normalizing",
        "final_output": "",
        "error": "",
    }

    yield _sse({"event": "status", "message": "[Harness] 🚀 Starting deep research...", "phase": "start"})

    state_update = {}
    event_queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def _run_graph():
        """Run the graph and push completed node updates into the queue."""
        try:
            async for mode, chunk in _graph_module.orchestrator_graph.astream(
                initial_state, stream_mode=["updates", "custom"]
            ):
                await event_queue.put((mode, chunk))
        except Exception as exc:
            await event_queue.put(("error", {"__error__": str(exc)}))
        finally:
            await event_queue.put(None)

    graph_task = asyncio.create_task(_run_graph())

    try:
        while True:
            try:
                item = await asyncio.wait_for(
                    event_queue.get(), timeout=_SSE_HEARTBEAT_INTERVAL
                )
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue

            if item is None:
                break

            mode, chunk = item

            if mode == "error" or (isinstance(chunk, dict) and "__error__" in chunk):
                raise RuntimeError(chunk["__error__"])

            if mode == "custom":
                progress = chunk.get("progress", "")
                title = chunk.get("section_title", "")
                idx = chunk.get("section_index", 0)
                total = chunk.get("total_sections", 0)
                if progress == "section_start":
                    evt = {
                        "event": "step",
                        "phase": "execute",
                        "icon": "🔎",
                        "title": f"[Execute][Researcher] ({idx}/{total}) Searching: {title}",
                        "agent": "Researcher",
                        "detail": f"Running semantic search & web search for section {idx} of {total}...",
                        "iteration": session.iteration,
                        "max_iterations": session.max_iterations,
                        "quality_score": session.quality_score,
                    }
                    yield _sse(evt)
                elif progress == "draft_chunk":
                    yield _sse({"event": "stream", "text": chunk.get("text", "")})
                elif progress == "section_done":
                    evt = {
                        "event": "step",
                        "phase": "execute",
                        "icon": "✅",
                        "title": f"[Execute][Writer] ({idx}/{total}) Done: {title}",
                        "agent": "Writer",
                        "detail": "",
                        "iteration": session.iteration,
                        "max_iterations": session.max_iterations,
                        "quality_score": session.quality_score,
                    }
                    yield _sse(evt)
                    content = chunk.get("content", "")
                    if content:
                        yield _sse({
                            "event": "section",
                            "sub_topic": title,
                            "content": content,
                            "section_index": idx,
                            "total_sections": total,
                            "iteration": session.iteration,
                        })
                elif progress == "section_failed":
                    evt = {
                        "event": "step",
                        "phase": "execute",
                        "icon": "❌",
                        "title": f"[Execute][Researcher] ({idx}/{total}) Failed: {title}",
                        "agent": "Researcher",
                        "detail": "",
                        "iteration": session.iteration,
                        "max_iterations": session.max_iterations,
                        "quality_score": session.quality_score,
                    }
                    yield _sse(evt)
                elif progress == "assembling_report":
                    evt = {
                        "event": "step",
                        "phase": "execute",
                        "icon": "📋",
                        "title": f"[Execute][Writer] Assembling final report ({total} sections)",
                        "agent": "Writer",
                        "detail": "",
                        "iteration": session.iteration,
                        "max_iterations": session.max_iterations,
                        "quality_score": session.quality_score,
                    }
                    yield _sse(evt)
                elif progress == "search_done":
                    sem = chunk.get("semantic_count", 0)
                    web = chunk.get("web_count", 0)
                    doc_sources = chunk.get("doc_sources", [])
                    web_urls = chunk.get("web_urls", [])
                    _iter_meta = {
                        "iteration": session.iteration,
                        "max_iterations": session.max_iterations,
                        "quality_score": session.quality_score,
                    }
                    if sem:
                        yield _sse({
                            "event": "step",
                            "phase": "execute",
                            "icon": "🔍",
                            "title": f"[Vector-Search][Researcher] {sem} chunks retrieved",
                            "agent": "Researcher",
                            "detail": f"Sources: {', '.join(doc_sources[:5])}" if doc_sources else "",
                            **_iter_meta,
                        })
                    if web:
                        yield _sse({
                            "event": "step",
                            "phase": "execute",
                            "icon": "🌐",
                            "title": f"[Web Search][Researcher] Web search: {web} results",
                            "agent": "Researcher",
                            "detail": ", ".join(web_urls[:3]),
                            **_iter_meta,
                        })
                elif progress == "drafting":
                    evt = {
                        "event": "step",
                        "phase": "execute",
                        "icon": "✍️",
                        "title": f"[Execute][Writer] ({idx}/{total}) Drafting: {title}",
                        "agent": "Writer",
                        "detail": "",
                        "iteration": session.iteration,
                        "max_iterations": session.max_iterations,
                        "quality_score": session.quality_score,
                    }
                    yield _sse(evt)
                elif progress == "verifying":
                    yield _sse({
                        "event": "step",
                        "phase": "verify",
                        "icon": "📊",
                        "title": "[Reviewing][Reviewer] Quality scoring & token calculation...",
                        "agent": "Reviewer",
                        "detail": "",
                        "iteration": session.iteration,
                        "max_iterations": session.max_iterations,
                        "quality_score": session.quality_score,
                    })
                continue

            if not isinstance(chunk, dict) or not chunk:
                continue
            node_name = next(iter(chunk))
            state_update = chunk[node_name]
            if not isinstance(state_update, dict):
                continue
            iteration = state_update.get("iteration", session.iteration)
            quality_score = state_update.get("quality_score", session.quality_score)
            status = state_update.get("status", session.status)

            session.iteration = iteration
            session.quality_score = quality_score
            session.status = status
            if "current_draft" in state_update:
                session.current_draft = state_update["current_draft"]
            if "accumulated_context" in state_update:
                session.accumulated_context = state_update["accumulated_context"]
            if "verification_history" in state_update:
                session.verification_history = state_update["verification_history"]
            if "total_tokens" in state_update:
                session.total_tokens = state_update["total_tokens"]
            if "report_sections" in state_update:
                session.report_sections = state_update["report_sections"]
            if "section_order" in state_update:
                session.section_order = state_update["section_order"]
            if "failing_sections" in state_update:
                session.failing_sections = state_update["failing_sections"]
            session.updated_at = __import__("datetime").datetime.utcnow().isoformat()

            session_mgr.save(session)

            sub_events = _emit_sub_events(node_name, state_update, session)
            for evt in sub_events:
                evt["iteration"] = session.iteration
                evt["max_iterations"] = session.max_iterations
                evt["quality_score"] = session.quality_score
                yield _sse(evt)

        final_output = state_update.get("final_output", session.current_draft)
        session.status = "complete"
        session_mgr.save(session)

        yield _sse({"event": "content", "text": final_output})

        active_research_sessions.dec()
        research_sessions_total.labels(status="completed").inc()
        research_quality_score.observe(session.quality_score)

        yield _sse({
            "event": "metadata",
            "iterations": session.iteration,
            "quality_score": session.quality_score,
            "total_tokens": session.total_tokens,
        })

        sources = _collect_sources(session.accumulated_context)
        if sources:
            yield _sse({"event": "sources", "sources": sources})

    except Exception as exc:
        logger.exception("Error during research streaming")
        active_research_sessions.dec()
        research_sessions_total.labels(status="failed").inc()
        session.status = "failed"
        session_mgr.save(session)
        yield _sse({"event": "error", "message": f"Research error: {exc}", "phase": "error"})
    finally:
        if not graph_task.done():
            graph_task.cancel()
            try:
                await graph_task
            except (asyncio.CancelledError, Exception):
                pass

    yield "data: [DONE]\n\n"


@app.post("/research")
async def start_research(req: ResearchRequest):
    """Start an SSE-streamed research session."""
    session = ResearchSession(
        query=req.query,
        max_iterations=req.max_iterations,
        quality_threshold=req.quality_threshold,
    )
    session.language_instruction = req.language_instruction
    session._enable_web_search = req.enable_web_search
    session._enable_planning = req.enable_planning
    session._enable_fact_check = req.enable_fact_check
    session._enable_parallel = req.enable_parallel
    session._enable_sectioned = req.enable_sectioned
    session_mgr.save(session)
    active_research_sessions.inc()
    research_sessions_total.labels(status="started").inc()
    logger.info("Starting research session %s for query: %s", session.session_id, req.query[:120])
    return StreamingResponse(
        _stream_research(session),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/sessions/{session_id}/status")
async def session_status(session_id: str):
    """Return the current progress of a research session."""
    progress = session_mgr.get_progress(session_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return progress


@app.get("/sessions/{session_id}/draft")
async def session_draft(session_id: str):
    """Return the current draft for a research session."""
    session = session_mgr.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"draft": session.current_draft, "status": session.status}


@app.post("/upload")
async def upload_files(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
):
    """Accept file uploads, save, and trigger Docling document processing."""
    upload_id = str(uuid.uuid4())[:12]
    upload_dir = os.path.join(UPLOAD_DIR, upload_id)
    os.makedirs(upload_dir, exist_ok=True)

    saved: list[dict] = []
    file_paths: list[str] = []
    for f in files:
        dest = os.path.join(upload_dir, f.filename or "unnamed")
        contents = await f.read()
        with open(dest, "wb") as fh:
            fh.write(contents)
        file_paths.append(dest)
        saved.append({"filename": f.filename or "unnamed", "size": len(contents)})
        logger.info("Saved uploaded file %s to %s", f.filename, dest)

    background_tasks.add_task(_process_documents_background, upload_id, file_paths)

    return {
        "upload_id": upload_id,
        "status": "processing",
        "files": [s["filename"] for s in saved],
        "message": f"Processing {len(saved)} file(s) in background.",
    }


_upload_status: dict[str, dict] = {}


def _semantic_chunk_document(doc) -> list[dict]:
    """Split a Docling document using semantic chunking."""
    from lib.document_processing import semantic_chunk_document
    return semantic_chunk_document(doc)


def _process_documents_background(upload_id: str, file_paths: list[str]):
    """Background task: parse, chunk, embed, and store documents with granular progress."""
    total = len(file_paths)
    filenames = [os.path.basename(p) for p in file_paths]

    def _update(message: str, progress: int):
        _upload_status[upload_id] = {
            "upload_id": upload_id,
            "status": "processing",
            "message": message,
            "progress": progress,
            "total_files": total,
            "files": filenames,
        }

    _update(f"🖨️ [Docling] Parsing {total} document(s) with Docling...", 5)

    try:
        from docling.document_converter import DocumentConverter
        from docling.datamodel.base_models import InputFormat
        from lib.document_processing import get_embeddings, get_db_connection
        from sqlite_vec import serialize_float32
        import hashlib
        import json as _json

        converter = DocumentConverter(
            allowed_formats=[
                InputFormat.PDF,
                InputFormat.DOCX,
                InputFormat.PPTX,
                InputFormat.MD,
                InputFormat.HTML,
            ]
        )
        total_chunks_stored = 0

        for file_idx, path in enumerate(file_paths):
            filename = os.path.basename(path)
            file_base_pct = int(5 + 90 * file_idx / total)

            _update(f"📄 [Docling] Parsing ({file_idx+1}/{total}): {filename}", file_base_pct + 5)
            logger.info("Parsing document: %s", path)
            result = converter.convert(path)
            doc = result.document

            _update(f"✂️ [Docling] Smart chunking (heading hierarchy): {filename}", file_base_pct + 15)
            chunks = _semantic_chunk_document(doc)
            _update(f"✂️ [Docling] {len(chunks)} semantic chunks created: {filename}", file_base_pct + 18)

            if not chunks:
                logger.warning("No chunks from %s", filename)
                continue

            chunk_texts = [c["text"] for c in chunks]
            embed_batch_size = 10
            num_batches = (len(chunk_texts) + embed_batch_size - 1) // embed_batch_size
            all_embeddings = []

            for batch_idx in range(0, len(chunk_texts), embed_batch_size):
                batch = chunk_texts[batch_idx : batch_idx + embed_batch_size]
                current_batch = batch_idx // embed_batch_size + 1
                embed_pct = file_base_pct + 20 + int(60 * current_batch / num_batches / total)
                _update(
                    f"🧠 [Docling] Embedding: {filename} (batch {current_batch}/{num_batches})",
                    min(embed_pct, 95),
                )
                embeddings = get_embeddings(batch)
                all_embeddings.extend(embeddings)

            _update(f"💾 [Docling] Storing {len(chunks)} chunks: {filename}", file_base_pct + 85 // total)

            document_id = hashlib.sha256(path.encode()).hexdigest()[:16]

            object_store_path = path

            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute(
                """INSERT INTO documents (id, name, file_type, chunk_count, status, object_store_path)
                   VALUES (?, ?, ?, ?, 'completed', ?)
                   ON CONFLICT (id) DO UPDATE SET
                       chunk_count = excluded.chunk_count,
                       status = excluded.status,
                       object_store_path = excluded.object_store_path,
                       updated_at = datetime('now')""",
                (document_id, filename, os.path.splitext(path)[1], len(chunks), object_store_path),
            )
            cur.execute("DELETE FROM vec_chunks WHERE chunk_id IN (SELECT id FROM document_chunks WHERE document_id = ?)", (document_id,))
            cur.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))

            for idx, (chunk, embedding) in enumerate(zip(chunks, all_embeddings)):
                metadata = chunk.get("metadata", {})
                cur.execute(
                    """INSERT INTO document_chunks (document_id, document_name, chunk_index, content, metadata)
                       VALUES (?, ?, ?, ?, ?)""",
                    (document_id, filename, idx, chunk["text"],
                     _json.dumps(metadata) if metadata else "{}"),
                )
                chunk_id = cur.lastrowid
                cur.execute(
                    "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
                    (chunk_id, serialize_float32(embedding)),
                )

            conn.commit()
            cur.close()
            conn.close()
            total_chunks_stored += len(chunks)
            documents_processed_total.labels(status="success").inc()
            logger.info("Document stored: %s → %d chunks", filename, len(chunks))

        _upload_status[upload_id] = {
            "upload_id": upload_id,
            "status": "completed",
            "message": f"✅ [Docling] Complete! {total_chunks_stored} chunks from {total} file(s) stored.",
            "progress": 100,
            "total_files": total,
            "files": filenames,
        }
    except Exception as e:
        documents_processed_total.labels(status="error").inc()
        logger.exception("Background document processing failed for upload %s", upload_id)
        _upload_status[upload_id] = {
            "upload_id": upload_id,
            "status": "error",
            "message": f"❌ Processing failed: {e}",
            "progress": 100,
            "total_files": total,
            "files": filenames,
            "error": str(e),
        }


@app.get("/upload_status/{upload_id}")
async def get_upload_status(upload_id: str):
    """Get document processing status for an upload."""
    if upload_id in _upload_status:
        return _upload_status[upload_id]
    return {"upload_id": upload_id, "status": "processing", "message": "Still processing..."}


@app.get("/documents")
async def list_documents():
    """List all completed documents from the database."""
    try:
        from lib.document_processing import get_db_connection

        conn = get_db_connection()
        rows = conn.execute(
            "SELECT id, name, file_type, chunk_count, status, created_at "
            "FROM documents WHERE status = 'completed' ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
        return {
            "documents": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "file_type": r["file_type"],
                    "chunk_count": r["chunk_count"],
                    "status": r["status"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        }
    except Exception as e:
        logger.warning("Failed to list documents: %s", e)
        return {"documents": []}


@app.get("/documents/{document_id}/download_url")
async def get_document_download_url(document_id: str):
    """Return the stored path for a document."""
    from lib.document_processing import get_db_connection

    conn = get_db_connection()
    row = conn.execute(
        "SELECT object_store_path, name FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    return {"document_id": document_id, "name": row["name"], "path": row["object_store_path"] or ""}


@app.get("/health")
async def health():
    """Simple liveness probe."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Thread management endpoints (for Next.js frontend ThreadList adapter)
# ---------------------------------------------------------------------------

POSTGRES_URL = os.getenv("POSTGRES_URL", "")


@app.get("/threads")
async def list_threads():
    """List all research threads from PostgreSQL checkpointer."""
    if not POSTGRES_URL:
        return {"threads": []}

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(POSTGRES_URL) as checkpointer:
            try:
                seen: dict[str, dict] = {}
                async for checkpoint in checkpointer.alist({}):
                    thread_id = checkpoint.config.get("configurable", {}).get("thread_id", "")
                    if not thread_id or thread_id in seen:
                        continue
                    state = checkpoint.checkpoint.get("channel_values", {})
                    seen[thread_id] = {
                        "id": thread_id,
                        "title": (state.get("query", "")[:60] or "New conversation"),
                        "created_at": checkpoint.checkpoint.get("ts", ""),
                        "status": state.get("status", "unknown"),
                    }
                return {"threads": list(seen.values())}
            except Exception as table_err:
                if "does not exist" in str(table_err):
                    await checkpointer.setup()
                    logger.info("Auto-created checkpointer tables on first access")
                    return {"threads": []}
                raise
    except Exception as e:
        logger.warning("Failed to list threads: %s", e)
        return {"threads": []}


@app.get("/threads/{thread_id}/messages")
async def get_thread_messages(thread_id: str):
    """Return the conversation messages for a thread from its checkpoint state."""
    if not POSTGRES_URL:
        return {"messages": []}

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(POSTGRES_URL) as checkpointer:
            config = {"configurable": {"thread_id": thread_id}}
            checkpoint = await checkpointer.aget(config)
            if not checkpoint:
                return {"messages": []}

            state = checkpoint.get("channel_values", {})
            query = state.get("query", "")
            final_output = state.get("final_output", "") or state.get("current_draft", "")

            messages = []
            if query:
                messages.append({
                    "id": f"{thread_id}-user",
                    "role": "user",
                    "content": [{"type": "text", "text": query}],
                })
            if final_output:
                messages.append({
                    "id": f"{thread_id}-assistant",
                    "role": "assistant",
                    "content": [{"type": "text", "text": final_output}],
                })
            return {"messages": messages}
    except Exception as e:
        logger.warning("Failed to get thread messages %s: %s", thread_id, e)
        return {"messages": []}


@app.post("/threads")
async def create_thread():
    """Create a new thread (returns a new thread_id)."""
    thread_id = str(uuid.uuid4())
    return {"thread_id": thread_id}


@app.delete("/threads/{thread_id}")
async def delete_thread(thread_id: str):
    """Delete a thread and its checkpoints."""
    if not POSTGRES_URL:
        raise HTTPException(status_code=501, detail="PostgreSQL not configured")

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(POSTGRES_URL) as checkpointer:
            config = {"configurable": {"thread_id": thread_id}}
            # Clear the thread's checkpoints
            await checkpointer.adelete(config)
        return {"deleted": True, "thread_id": thread_id}
    except Exception as e:
        logger.warning("Failed to delete thread %s: %s", thread_id, e)
        raise HTTPException(status_code=500, detail=str(e))


