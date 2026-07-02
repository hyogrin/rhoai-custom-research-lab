"""Chainlit frontend for the RHOAI Custom Deep Research Lab.

Connects to the backend API and renders the harness engineering
plan-execute-verify-reflect loop as interactive Chainlit steps.
"""

import json
import logging
import os
import asyncio

import aiohttp
import chainlit as cl
from dotenv import load_dotenv

from app_utils import (
    ChatSettings,
    StepNameManager,
    safe_stream_token,
    safe_send_step,
    safe_update_message,
    retry_async,
)
from i18n import SUPPORTED_LANGUAGES, STARTERS, SYSTEM_PROMPT_LANGUAGE

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

API_URL = os.getenv("API_URL", "http://localhost:8000")



# ---------------------------------------------------------------------------
# Chat lifecycle
# ---------------------------------------------------------------------------


@cl.on_chat_start
async def on_chat_start():
    """Initialize session state and present the settings panel."""
    settings = ChatSettings()

    profile = cl.user_session.get("chat_profile", "English")
    settings.language = "ko-KR" if profile == "Korean" else "en-US"

    cl.user_session.set("settings", settings)
    cl.user_session.set("step_mgr", StepNameManager())

    ui_settings = await cl.ChatSettings(
        [
            cl.input_widget.Slider(
                id="quality_threshold",
                label="Quality Threshold",
                initial=settings.quality_threshold,
                min=1.0,
                max=10.0,
                step=0.5,
                description="Minimum quality score (1-10) before the harness stops iterating.",
            ),
            cl.input_widget.Slider(
                id="max_iterations",
                label="Max Iterations",
                initial=settings.max_iterations,
                min=1,
                max=10,
                step=1,
                description="Maximum harness iterations before returning the best result.",
            ),
            cl.input_widget.Switch(
                id="verbose",
                label="Verbose Output",
                initial=settings.verbose,
                description="Show detailed step information during research.",
            ),
            cl.input_widget.Switch(
                id="log_sse",
                label="Step History",
                initial=settings.log_sse,
                description="ON: show all processing steps. OFF: show only the current step (compact).",
            ),
            cl.input_widget.Switch(
                id="enable_web_search",
                label="Web Search",
                initial=settings.enable_web_search,
                description="Allow the agent to search the web for up-to-date information.",
            ),
            cl.input_widget.Switch(
                id="enable_planning",
                label="Research Planning",
                initial=settings.enable_planning,
                description="Generate a structured research plan before executing. OFF: search directly.",
            ),
            cl.input_widget.Switch(
                id="enable_fact_check",
                label="Fact Check",
                initial=settings.enable_fact_check,
                description="Cross-reference claims against source documents during verification.",
            ),
            cl.input_widget.Switch(
                id="enable_parallel",
                label="Parallel Processing",
                initial=settings.enable_parallel,
                description="Run multiple searches and verifications concurrently for faster results.",
            ),
            cl.input_widget.Switch(
                id="enable_sectioned",
                label="Sectioned Report",
                initial=settings.enable_sectioned,
                description="Decompose the query into sub-topics and write each section independently.",
            ),
        ]
    ).send()

    if ui_settings:
        _apply_settings(settings, ui_settings)


@cl.on_settings_update
async def on_settings_update(raw_settings: dict):
    """Persist updated settings into the session."""
    settings = cl.user_session.get("settings") or ChatSettings()
    _apply_settings(settings, raw_settings)
    cl.user_session.set("settings", settings)


def _apply_settings(settings: ChatSettings, raw: dict):
    if "language" in raw:
        settings.language = raw["language"]
    if "quality_threshold" in raw:
        settings.quality_threshold = float(raw["quality_threshold"])
    if "max_iterations" in raw:
        settings.max_iterations = int(raw["max_iterations"])
    if "verbose" in raw:
        settings.verbose = bool(raw["verbose"])
    if "log_sse" in raw:
        settings.log_sse = bool(raw["log_sse"])
    if "enable_web_search" in raw:
        settings.enable_web_search = bool(raw["enable_web_search"])
    if "enable_planning" in raw:
        settings.enable_planning = bool(raw["enable_planning"])
    if "enable_fact_check" in raw:
        settings.enable_fact_check = bool(raw["enable_fact_check"])
    if "enable_parallel" in raw:
        settings.enable_parallel = bool(raw["enable_parallel"])
    if "enable_sectioned" in raw:
        settings.enable_sectioned = bool(raw["enable_sectioned"])


# ---------------------------------------------------------------------------
# Chat profiles (language switching with per-language starters)
# ---------------------------------------------------------------------------


def _starters_for_language(lang: str) -> list[cl.Starter]:
    """Build Starter objects from the i18n STARTERS dict."""
    return [
        cl.Starter(label=s["label"], message=s["message"], icon=s["icon"])
        for s in STARTERS.get(lang, STARTERS["en-US"])
    ]


@cl.set_chat_profiles
async def chat_profiles():
    return [
        cl.ChatProfile(
            name="English",
            markdown_description="Research in English",
            starters=_starters_for_language("en-US"),
        ),
        cl.ChatProfile(
            name="Korean",
            markdown_description="한국어로 리서치",
            starters=_starters_for_language("ko-KR"),
        ),
    ]


# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------


async def handle_file_upload(files: list, settings: ChatSettings):
    """Upload files to the backend /upload endpoint and poll for processing status."""
    file_names = [f.name for f in files if hasattr(f, "name")]
    file_list_str = "\n".join([f"• {n}" for n in file_names])

    status_msg = cl.Message(
        content=f"📤 **Uploading documents...**\n\n{file_list_str}"
    )
    await status_msg.send()

    try:
        async with aiohttp.ClientSession() as session:
            data = aiohttp.FormData()
            for f in files:
                file_bytes = await _read_file_bytes(f)
                if file_bytes:
                    data.add_field(
                        "files",
                        file_bytes,
                        filename=f.name,
                        content_type="application/octet-stream",
                    )

            async with session.post(f"{API_URL}/upload", data=data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    upload_id = result.get("upload_id") if isinstance(result, dict) else None

                    if upload_id:
                        await _poll_upload_status(session, upload_id, status_msg)
                    else:
                        status_msg.content = "✅ **Upload complete!**"
                else:
                    error_text = await resp.text()
                    status_msg.content = f"❌ **Upload failed** (HTTP {resp.status}): {error_text}"
                    logger.error("Upload failed: %s %s", resp.status, error_text)

    except aiohttp.ClientError as e:
        status_msg.content = f"❌ **Upload error**: could not reach backend. ({e})"
        logger.error("Upload connection error: %s", e)
    except Exception as e:
        status_msg.content = f"❌ **Unexpected upload error**: {e}"
        logger.exception("Unexpected upload error")

    await safe_update_message(status_msg)


async def _poll_upload_status(
    session: aiohttp.ClientSession, upload_id: str, status_msg: cl.Message
):
    """Poll the upload status endpoint with progress bar."""
    for _ in range(600):
        await asyncio.sleep(2)
        try:
            async with session.get(f"{API_URL}/upload_status/{upload_id}") as resp:
                if resp.status != 200:
                    continue
                info = await resp.json()
                status = info.get("status", "processing")
                message = info.get("message", "Processing...")
                progress = int(info.get("progress", 0))

                green_blocks = progress // 10
                progress_bar = "🟩" * green_blocks + "⬜" * (10 - green_blocks)

                if status == "processing":
                    status_msg.content = (
                        f"📤 **Processing documents...**\n\n"
                        f"{message}\n\n"
                        f"Progress: {progress}%\n{progress_bar}"
                    )
                elif status == "completed":
                    status_msg.content = (
                        f"✅ **{message}**\n\n"
                        f"💡 You can now ask research questions about your document!"
                    )
                    await safe_update_message(status_msg)
                    return
                elif status == "error":
                    status_msg.content = f"❌ **{message}**"
                    await safe_update_message(status_msg)
                    return

                await safe_update_message(status_msg)
        except Exception as e:
            logger.warning("Upload status poll error: %s", e)
            continue

    status_msg.content = "⏳ Document processing is taking longer than expected (>20 min). It will continue in the background."
    await safe_update_message(status_msg)


async def _read_file_bytes(f) -> bytes | None:
    """Read bytes from a Chainlit file element."""
    try:
        if hasattr(f, "path") and f.path:
            with open(f.path, "rb") as fh:
                return fh.read()
        if hasattr(f, "content") and f.content:
            return f.content if isinstance(f.content, bytes) else f.content.encode()
    except Exception as e:
        logger.warning("Could not read file %s: %s", getattr(f, "name", "?"), e)
    return None


# ---------------------------------------------------------------------------
# SSE research stream
# ---------------------------------------------------------------------------


async def stream_research(query: str, settings: ChatSettings, file_path: str = ""):
    """POST to /research and render SSE events as Chainlit steps."""
    msg = cl.Message(content="")
    await msg.send()

    # Compact mode: a single status message that gets overwritten per step
    status_msg: cl.Message | None = None
    if not settings.log_sse:
        status_msg = cl.Message(content="⏳ Preparing...")
        await status_msg.send()

    step_mgr: StepNameManager = cl.user_session.get("step_mgr") or StepNameManager()
    step_mgr.reset()

    timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=600)
    current_phase_step: cl.Step | None = None
    stop_event = asyncio.Event()
    last_activity = asyncio.get_event_loop().time()

    async def keepalive_monitor():
        """Warn if the SSE stream goes silent for too long."""
        nonlocal last_activity
        while not stop_event.is_set():
            await asyncio.sleep(30)
            if last_activity:
                idle = asyncio.get_event_loop().time() - last_activity
                if idle > 120:
                    logger.warning(
                        "No SSE data for %.0fs (harness may be processing)", idle
                    )

    keepalive_task = asyncio.create_task(keepalive_monitor())

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            lang_instruction = SYSTEM_PROMPT_LANGUAGE.get(
                settings.language, SYSTEM_PROMPT_LANGUAGE["en-US"]
            )
            payload = {
                "query": query,
                "file_path": file_path,
                "quality_threshold": settings.quality_threshold,
                "max_iterations": settings.max_iterations,
                "language_instruction": lang_instruction,
                "enable_web_search": settings.enable_web_search,
                "enable_planning": settings.enable_planning,
                "enable_fact_check": settings.enable_fact_check,
                "enable_parallel": settings.enable_parallel,
                "enable_sectioned": settings.enable_sectioned,
            }

            async with session.post(f"{API_URL}/research", json=payload) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    msg.content = f"Backend error (HTTP {resp.status}): {error_text}"
                    await safe_update_message(msg)
                    return

                buffer = ""
                async for chunk in resp.content.iter_any():
                    last_activity = asyncio.get_event_loop().time()
                    buffer += chunk.decode("utf-8")

                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()

                        if not line or line.startswith(":"):
                            continue

                        if line.startswith("data:"):
                            data_str = line[5:].strip()

                            if data_str == "[DONE]":
                                current_phase_step = await _close_phase(
                                    current_phase_step
                                )
                                break

                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                logger.warning("Malformed SSE data: %s", data_str[:120])
                                continue

                            current_phase_step = await _handle_event(
                                data,
                                msg,
                                current_phase_step,
                                step_mgr,
                                settings,
                                status_msg,
                            )

    except aiohttp.ClientError as e:
        msg.content += f"\n\nConnection error: {e}"
        logger.error("SSE connection error: %s", e)
    except asyncio.CancelledError:
        logger.info("Research stream cancelled")
    except Exception as e:
        msg.content += f"\n\nUnexpected error: {e}"
        logger.exception("Unexpected error during research stream")
    finally:
        stop_event.set()
        keepalive_task.cancel()
        try:
            await keepalive_task
        except asyncio.CancelledError:
            pass
        await _close_phase(current_phase_step)
        # In compact mode, remove the status message (final result is in msg)
        if status_msg:
            status_msg.content = ""
            await safe_update_message(status_msg)
        await safe_update_message(msg)


def _format_metadata(data: dict) -> str:
    """Render research metadata as a markdown footer."""
    iterations = data.get("iterations", 0)
    score = data.get("quality_score", 0)
    tokens = data.get("total_tokens", 0)
    return (
        f"\n\n---\n"
        f"*Research completed in {iterations} iteration(s) | "
        f"Quality score: {score}/10 | "
        f"Total tokens: {tokens:,}*\n"
    )


def _format_sources(sources: list[dict]) -> str:
    """Render a list of sources as a markdown citation block."""
    if not sources:
        return ""
    lines = ["\n\n---\n\n**Sources**\n"]
    doc_sources = [s for s in sources if s.get("type") == "document"]
    web_sources = [s for s in sources if s.get("type") == "web"]

    if doc_sources:
        seen_docs: set[str] = set()
        for s in doc_sources:
            doc = s.get("document", s.get("source", ""))
            if doc not in seen_docs:
                seen_docs.add(doc)
                lines.append(f"- 📄 {doc}")

    if web_sources:
        for s in web_sources:
            url = s.get("url", "")
            title = s.get("title", url)
            if url:
                lines.append(f"- 🌐 [{title}]({url})")
            else:
                lines.append(f"- 🌐 {title}")

    return "\n".join(lines) + "\n"


async def _close_phase(step: cl.Step | None) -> None:
    """Finalize and close an open phase step."""
    if step is not None:
        try:
            await step.update()
        except Exception:
            pass
    return None


async def _handle_event(
    data: dict,
    msg: cl.Message,
    current_phase_step: cl.Step | None,
    step_mgr: StepNameManager,
    settings: ChatSettings,
    status_msg: cl.Message | None = None,
) -> cl.Step | None:
    """Dispatch a parsed SSE event to the appropriate Chainlit handler."""
    event_type = data.get("event")

    # Compact mode: overwrite single status_msg instead of accumulating steps
    if not settings.log_sse and status_msg is not None:
        if event_type in ("status", "step"):
            icon = data.get("icon", "⚙️")
            title = data.get("title", "") or data.get("message", "")
            detail = data.get("detail", "")
            status_msg.content = f"{icon} {title}" + (f"\n_{detail}_" if detail else "")
            await safe_update_message(status_msg)
        elif event_type == "section":
            section_content = data.get("content", "")
            if section_content:
                sub_topic = data.get("sub_topic", "")
                status_msg.content = f"📝 Writing section: {sub_topic}"
                await safe_update_message(status_msg)
                await safe_stream_token(msg, section_content + "\n\n")
        elif event_type == "content":
            text = data.get("text", "")
            if text:
                status_msg.content = ""
                await safe_update_message(status_msg)
                if len(text) >= len(msg.content):
                    msg.content = text
                    await safe_update_message(msg)
        elif event_type == "metadata":
            meta_md = _format_metadata(data)
            if meta_md:
                await safe_stream_token(msg, meta_md)
        elif event_type == "sources":
            sources_md = _format_sources(data.get("sources", []))
            if sources_md:
                await safe_stream_token(msg, sources_md)
        elif event_type == "error":
            error_msg = data.get("message", "Unknown error")
            status_msg.content = ""
            await safe_update_message(status_msg)
            await safe_stream_token(msg, f"\n\n❌ {error_msg}")
        return current_phase_step

    # Log mode (default): accumulate all steps
    if event_type == "status":
        message = data.get("message", "")
        if message:
            step_name = step_mgr.get_unique_name(message)
            step = cl.Step(name=step_name, type="tool")
            step.output = ""
            await safe_send_step(step)
    elif event_type == "step":
        current_phase_step = await _handle_step_event(data, msg, current_phase_step, step_mgr, settings)
    elif event_type == "section":
        section_content = data.get("content", "")
        sub_topic = data.get("sub_topic", "")
        if section_content:
            step_name = step_mgr.get_unique_name(f"📝 Section: {sub_topic}")
            step = cl.Step(name=step_name, type="tool")
            step.output = section_content[:300] + ("..." if len(section_content) > 300 else "")
            await safe_send_step(step)
            await safe_stream_token(msg, section_content + "\n\n")
    elif event_type == "content":
        text = data.get("text", "")
        if text:
            if len(text) >= len(msg.content):
                msg.content = text
                await safe_update_message(msg)
    elif event_type == "metadata":
        meta_md = _format_metadata(data)
        if meta_md:
            await safe_stream_token(msg, meta_md)
    elif event_type == "sources":
        sources_md = _format_sources(data.get("sources", []))
        if sources_md:
            await safe_stream_token(msg, sources_md)
    elif event_type == "error":
        error_msg = data.get("message", "Unknown error")
        await safe_stream_token(msg, f"\n\n❌ {error_msg}")
    else:
        logger.debug("Unknown SSE event type: %s", event_type)

    return current_phase_step


async def _handle_step_event(
    data: dict,
    msg: cl.Message,
    current_phase_step: cl.Step | None,
    step_mgr: StepNameManager,
    settings: ChatSettings,
) -> cl.Step | None:
    """Render a rich step event as a Chainlit Step with detail info."""
    phase = data.get("phase", "")
    icon = data.get("icon", "⚙️")
    title = data.get("title", "")
    detail = data.get("detail", "")

    display_name = f"{icon} {title}" if title else f"{icon} {phase}"
    step_name = step_mgr.get_unique_name(display_name)

    phase_type_map = {
        "normalize": "tool",
        "plan": "tool",
        "execute": "retrieval",
        "verify": "tool",
        "observe": "tool",
        "iterate": "tool",
        "finalize": "tool",
    }
    step_type = phase_type_map.get(phase, "tool")

    step = cl.Step(
        name=step_name,
        type=step_type,
        parent_id=current_phase_step.id if current_phase_step and phase == current_phase_step.name else None,
    )
    step.output = detail if detail else ""

    await safe_send_step(step)
    return current_phase_step


# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------


@cl.on_message
async def on_message(message: cl.Message):
    """Handle incoming user messages and file attachments."""
    settings: ChatSettings = cl.user_session.get("settings") or ChatSettings()

    upload_phrases = {
        "upload a document for research",
        "i want to upload a document for research.",
        "upload",
        "리서치를 위한 문서를 업로드합니다",
    }

    if message.elements:
        files = [e for e in message.elements if hasattr(e, "name")]
        if files:
            await handle_file_upload(files, settings)
            if not message.content or message.content.strip().lower() in upload_phrases:
                return

    query = message.content.strip()
    if not query:
        await cl.Message(content="Please enter a research query or upload a document.").send()
        return

    if query.lower() in upload_phrases:
        await cl.Message(
            content=(
                "Please use the **attachment button** (📎) at the bottom of the chat input "
                "to select and upload your document (PDF, TXT, MD, DOCX).\n\n"
                "After uploading, you can ask research questions about your document."
            )
        ).send()
        return

    await stream_research(query, settings)


# ---------------------------------------------------------------------------
# Session resume
# ---------------------------------------------------------------------------


@cl.on_chat_resume
async def on_chat_resume(thread: dict):
    """Restore session state when a user returns to a previous conversation."""
    settings = ChatSettings()
    cl.user_session.set("settings", settings)
    cl.user_session.set("step_mgr", StepNameManager())

    session_id = None
    for step in reversed(thread.get("steps", [])):
        if step.get("metadata", {}).get("session_id"):
            session_id = step["metadata"]["session_id"]
            break

    if session_id:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{API_URL}/sessions/{session_id}/status"
                ) as resp:
                    if resp.status == 200:
                        progress = await resp.json()
                        status = progress.get("status", "unknown")
                        score = progress.get("quality_score", 0)
                        iteration = progress.get("iteration", 0)
                        await cl.Message(
                            content=(
                                f"Resumed session `{session_id}`\n"
                                f"Status: **{status}** | "
                                f"Iteration: {iteration} | "
                                f"Score: {score}/10"
                            )
                        ).send()
                    else:
                        logger.info(
                            "Session %s not found on backend (HTTP %s)",
                            session_id,
                            resp.status,
                        )
        except Exception as e:
            logger.warning("Failed to restore session %s: %s", session_id, e)
