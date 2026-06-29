"""FastAPI backend API with SSE streaming for the research harness."""

import json
import os
import uuid
import tempfile
import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, Header, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.session import SessionManager, ResearchSession
from agents.orchestrator.agent import orchestrator_graph

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="RHOAI Deep Research API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

session_mgr = SessionManager()


class ResearchRequest(BaseModel):
    query: str
    file_path: str = ""
    quality_threshold: float = 7.0
    max_iterations: int = 3
    language_instruction: str = "You MUST respond entirely in English."


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
            "title": "[Harness] Research session initialized",
            "detail": f"Query: \"{session.query[:120]}\"",
        })
        hints = state_update.get("failure_hints", "")
        if hints:
            events.append({
                "event": "step",
                "phase": "normalize",
                "icon": "💡",
                "title": "[Harness] Loaded past failure memory",
                "detail": hints[:200],
            })

    elif node_name == "plan":
        plan = state_update.get("research_plan", [])
        events.append({
            "event": "step",
            "phase": "plan",
            "icon": "📋",
            "title": f"[Plan] Research plan generated ({len(plan)} steps)",
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
                "title": f"[Plan] Step {i}: [{action}] {query[:80]}",
                "detail": step.get("purpose", ""),
            })

    elif node_name == "execute":
        ctx = state_update.get("accumulated_context", [])
        new_ctx = [c for c in ctx if c.get("iteration") == iteration]

        search_results = [c for c in new_ctx if c.get("source", "").startswith(("search", "semantic")) or "[" in c.get("source", "")]
        synth_results = [c for c in new_ctx if c.get("source") == "synthesis"]

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
                "title": f"[Tool-Search] {len(search_results)} chunks retrieved",
                "detail": f"Sources: {', '.join(list(sources)[:5])}",
            })

        if synth_results:
            events.append({
                "event": "step",
                "phase": "execute",
                "icon": "🧠",
                "title": "[Researching] Context synthesized",
                "detail": synth_results[-1].get("content", "")[:150],
            })

        draft = state_update.get("current_draft", "")
        if draft:
            draft_preview = draft[:200].replace("\n", " ")
            events.append({
                "event": "step",
                "phase": "execute",
                "icon": "📝",
                "title": f"[Writing] Report drafted ({len(draft):,} chars)",
                "detail": draft_preview,
            })
        else:
            events.append({
                "event": "step",
                "phase": "execute",
                "icon": "⚠️",
                "title": "[Writing] Report generation failed",
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
            "title": f"[Reviewing] Quality score: {score}/10 — {'PASSED' if passed else 'needs improvement'}",
            "detail": "",
        })

        if details:
            breakdown = " | ".join(f"{k}: {v}" for k, v in details.items() if isinstance(v, (int, float)))
            if breakdown:
                events.append({
                    "event": "step",
                    "phase": "verify",
                    "icon": "📊",
                    "title": "[Reviewing] Score breakdown",
                    "detail": breakdown,
                })

        if improvements:
            events.append({
                "event": "step",
                "phase": "verify",
                "icon": "💬",
                "title": "[Reviewing] Improvement suggestions",
                "detail": " / ".join(improvements[:3]),
            })

    elif node_name == "observe":
        events.append({
            "event": "step",
            "phase": "observe",
            "icon": "📊",
            "title": f"[Harness] Iteration {iteration}/{max_iter} analysis recorded",
            "detail": state_update.get("failure_hints", "")[:150],
        })

    elif node_name == "iterate":
        new_iter = state_update.get("iteration", iteration)
        events.append({
            "event": "step",
            "phase": "iterate",
            "icon": "🔁",
            "title": f"[Harness] Starting iteration {new_iter}/{max_iter}",
            "detail": "Applying improvements from previous verification feedback...",
        })

    elif node_name == "finalize":
        events.append({
            "event": "step",
            "phase": "finalize",
            "icon": "🎯",
            "title": f"[Harness] Research complete — Quality: {session.quality_score}/10, Iterations: {iteration}",
            "detail": f"Total tokens used: {session.total_tokens:,}",
        })

    return events


async def _stream_research(session: ResearchSession) -> AsyncGenerator[str, None]:
    """Run the orchestrator graph and yield rich SSE events for each phase."""
    initial_state = {
        "session_id": session.session_id,
        "query": session.query,
        "file_path": "",
        "has_document": False,
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
        "status": "normalizing",
        "final_output": "",
        "error": "",
    }

    yield _sse({"event": "status", "message": "[Harness] 🚀 Starting deep research...", "phase": "start"})

    state_update = {}
    try:
        async for chunk in orchestrator_graph.astream(
            initial_state, stream_mode="updates"
        ):
            node_name = next(iter(chunk))
            state_update = chunk[node_name]
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
            session.updated_at = __import__("datetime").datetime.utcnow().isoformat()

            session_mgr.save(session)

            # Emit rich sub-events for this node
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

    except Exception as exc:
        logger.exception("Error during research streaming")
        session.status = "failed"
        session_mgr.save(session)
        yield _sse({"event": "error", "message": f"Research error: {exc}", "phase": "error"})

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
    session_mgr.save(session)
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
    """Split a Docling document using the same logic as doc_processor."""
    from agents.doc_processor.tools import semantic_chunk_document
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
        from agents.doc_processor.tools import get_embeddings, get_db_connection
        import psycopg2.extras
        import hashlib

        converter = DocumentConverter()
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
            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute(
                """INSERT INTO documents (id, name, file_type, chunk_count, status, object_store_path)
                   VALUES (%s, %s, %s, %s, 'completed', %s)
                   ON CONFLICT (id) DO UPDATE SET
                       chunk_count = EXCLUDED.chunk_count,
                       status = EXCLUDED.status,
                       updated_at = NOW()""",
                (document_id, filename, os.path.splitext(path)[1], len(chunks), path),
            )
            cur.execute("DELETE FROM document_chunks WHERE document_id = %s", (document_id,))

            for idx, (chunk, embedding) in enumerate(zip(chunks, all_embeddings)):
                metadata = chunk.get("metadata", {})
                cur.execute(
                    """INSERT INTO document_chunks (document_id, document_name, chunk_index, content, metadata, embedding)
                       VALUES (%s, %s, %s, %s, %s::jsonb, %s::vector)""",
                    (document_id, filename, idx, chunk["text"],
                     psycopg2.extras.Json(metadata) if metadata else "{}", str(embedding)),
                )

            conn.commit()
            cur.close()
            conn.close()
            total_chunks_stored += len(chunks)
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


@app.get("/health")
async def health():
    """Simple liveness probe."""
    return {"status": "ok"}


