"""Claim-Evidence Graph planner — generates structured graph specs from research reports.

Produces a validated JSON specification that a trusted renderer converts into SVG.
The LLM generates ONLY structured data; it never produces executable code.
"""

import html
import json
import logging
import re
from typing import Any

from agents.orchestrator.layers.tools import _call_llm

logger = logging.getLogger(__name__)

MAX_CLAIMS = 5
MAX_EVIDENCE = 10
MAX_TOTAL_NODES = 15
MAX_EDGES = 20
MAX_LABEL_LENGTH = 300

VALID_NODE_TYPES = {"claim", "evidence"}
VALID_EDGE_RELATIONS = {"supports", "contradicts", "partially_supports"}

PLANNER_SYSTEM_PROMPT = """\
You are a research analysis assistant. Given a completed research report and its \
source metadata, produce a Claim-Evidence Graph specification as JSON.

Rules:
- Extract the key claims from the report (max {max_claims} claims).
- Link each claim to supporting or contradicting evidence from the cited sources.
- Each evidence node MUST reference a real source_id from the provided sources.
- Do NOT invent sources. Only use source IDs from the provided list.
- Keep labels concise (max {max_label_length} characters).
- Use confidence values between 0.0 and 1.0 for claims.
- Edge relations must be one of: supports, contradicts, partially_supports.

Output ONLY valid JSON matching this schema:
{{
  "title": "Claim-Evidence Graph",
  "summary": "Brief description of the graph",
  "nodes": [
    {{
      "id": "claim-N",
      "type": "claim",
      "label": "A concise claim",
      "confidence": 0.85,
      "citation_ids": ["1", "3"]
    }},
    {{
      "id": "evidence-N",
      "type": "evidence",
      "label": "Evidence description",
      "source_id": "1",
      "source_title": "Source title",
      "source_url": "https://example.com"
    }}
  ],
  "edges": [
    {{
      "source": "evidence-N",
      "target": "claim-N",
      "relation": "supports"
    }}
  ]
}}
""".format(max_claims=MAX_CLAIMS, max_label_length=MAX_LABEL_LENGTH)


def _extract_source_ids(accumulated_context: list[dict]) -> list[dict]:
    """Extract unique source IDs and metadata from accumulated context.

    Uses the stable source_id field (SRC_XXXX) rather than positional indices.
    """
    sources: list[dict] = []
    seen_ids: set[str] = set()
    for ctx in accumulated_context:
        src_id = ctx.get("source_id", "")
        if not src_id or src_id in seen_ids:
            continue
        seen_ids.add(src_id)
        metadata = ctx.get("metadata", {})
        doc_name = ctx.get("document_name", ctx.get("source", ""))
        sources.append({
            "id": src_id,
            "source": ctx.get("source", ""),
            "title": doc_name or metadata.get("title", ""),
            "url": metadata.get("source_url", "") or metadata.get("url", ""),
        })
    return sources


def _sanitize_label(label: str) -> str:
    """Strip HTML and truncate labels."""
    cleaned = re.sub(r"<[^>]+>", "", label)
    cleaned = html.unescape(cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) > MAX_LABEL_LENGTH:
        cleaned = cleaned[: MAX_LABEL_LENGTH - 3] + "..."
    return cleaned


def _validate_spec(spec: dict, available_source_ids: set[str]) -> list[str]:
    """Validate the claim-evidence spec. Returns list of error messages."""
    errors: list[str] = []

    nodes = spec.get("nodes", [])
    edges = spec.get("edges", [])

    if not isinstance(nodes, list):
        errors.append("nodes must be a list")
        return errors
    if not isinstance(edges, list):
        errors.append("edges must be a list")
        return errors

    claims = [n for n in nodes if n.get("type") == "claim"]
    evidence = [n for n in nodes if n.get("type") == "evidence"]

    if len(claims) > MAX_CLAIMS:
        errors.append(f"Too many claims: {len(claims)} > {MAX_CLAIMS}")
    if len(evidence) > MAX_EVIDENCE:
        errors.append(f"Too many evidence nodes: {len(evidence)} > {MAX_EVIDENCE}")
    if len(nodes) > MAX_TOTAL_NODES:
        errors.append(f"Too many total nodes: {len(nodes)} > {MAX_TOTAL_NODES}")
    if len(edges) > MAX_EDGES:
        errors.append(f"Too many edges: {len(edges)} > {MAX_EDGES}")

    node_ids: set[str] = set()
    for node in nodes:
        nid = node.get("id", "")
        if not nid:
            errors.append("Node missing id")
            continue
        if nid in node_ids:
            errors.append(f"Duplicate node id: {nid}")
        node_ids.add(nid)

        ntype = node.get("type", "")
        if ntype not in VALID_NODE_TYPES:
            errors.append(f"Invalid node type '{ntype}' for {nid}")

        label = node.get("label", "")
        if not label:
            errors.append(f"Node {nid} missing label")
        if len(label) > MAX_LABEL_LENGTH:
            errors.append(f"Node {nid} label exceeds {MAX_LABEL_LENGTH} chars")

        if ntype == "evidence":
            src_id = node.get("source_id", "")
            if src_id and src_id not in available_source_ids:
                errors.append(
                    f"Evidence {nid} references unknown source_id '{src_id}'"
                )

        if ntype == "claim":
            confidence = node.get("confidence", 0)
            if not (0.0 <= confidence <= 1.0):
                errors.append(f"Claim {nid} confidence {confidence} not in [0,1]")

    for edge in edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        rel = edge.get("relation", "")

        if src not in node_ids:
            errors.append(f"Edge source '{src}' not in nodes")
        if tgt not in node_ids:
            errors.append(f"Edge target '{tgt}' not in nodes")
        if rel not in VALID_EDGE_RELATIONS:
            errors.append(f"Invalid edge relation '{rel}'")

    return errors


def _sanitize_spec(spec: dict) -> dict:
    """Sanitize all labels in the spec."""
    for node in spec.get("nodes", []):
        if "label" in node:
            node["label"] = _sanitize_label(node["label"])
        if "source_title" in node:
            node["source_title"] = _sanitize_label(node["source_title"])
    if "title" in spec:
        spec["title"] = _sanitize_label(spec["title"])
    if "summary" in spec:
        spec["summary"] = _sanitize_label(spec["summary"])
    return spec


def _extract_cited_passages(draft: str, max_chars: int = 2500) -> str:
    """Extract only paragraphs that contain citations, with their section headings.

    At this stage the draft still uses [[cite:SRC_XXX]] format (pre-finalize).
    Falls back to head-truncation when no citations are found.
    """
    cite_re = re.compile(r"\[\[cite:SRC_[A-Za-z0-9]+\]\]", re.IGNORECASE)

    paragraphs = draft.split("\n\n")
    cited_parts: list[str] = []
    last_heading = ""
    heading_emitted = False
    total = 0

    for para in paragraphs:
        stripped = para.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            last_heading = stripped
            heading_emitted = False
            continue
        if cite_re.search(stripped):
            if last_heading and not heading_emitted:
                cited_parts.append(last_heading)
                total += len(last_heading) + 2
                heading_emitted = True
            if total + len(stripped) > max_chars:
                break
            cited_parts.append(stripped)
            total += len(stripped) + 2

    if not cited_parts:
        return draft[:max_chars]
    return "\n\n".join(cited_parts)


def plan_claim_evidence_graph(state: dict[str, Any]) -> dict:
    """Generate a Claim-Evidence Graph spec from the research state.

    Returns a dict with keys:
      - spec: the validated ClaimEvidenceSpec dict
      - errors: list of validation errors (empty on success)
      - tokens_used: token count from the LLM call
    """
    current_draft = state.get("current_draft", "")
    accumulated_context = state.get("accumulated_context", [])
    verification_result = state.get("verification_result", {})

    available_sources = _extract_source_ids(accumulated_context)
    available_source_ids = {s["id"] for s in available_sources}

    # Only send citation-bearing paragraphs to minimize prompt size
    cited_text = _extract_cited_passages(current_draft)

    sources_for_prompt = available_sources[:10]
    sources_text = json.dumps(sources_for_prompt, ensure_ascii=False)
    if len(sources_text) > 2000:
        sources_text = sources_text[:2000] + "..."

    user_prompt = f"""Report (cited passages only):
{cited_text}

Sources (use ONLY these IDs): {sources_text}

Generate a Claim-Evidence Graph as JSON."""

    logger.info(
        "Claim-evidence planner: draft=%d chars, cited=%d chars, sources=%d, prompt=%d chars",
        len(current_draft), len(cited_text), len(sources_for_prompt), len(user_prompt),
    )

    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        content, tokens_used = _call_llm(messages, max_tokens=1536, temperature=0.2)
        logger.info("Claim-evidence planner LLM response: %d chars, %d tokens", len(content), tokens_used)
    except Exception as e:
        logger.error("LLM call failed for claim-evidence planning: %s", e)
        return {"spec": {}, "errors": [f"LLM call failed: {e}"], "tokens_used": 0}

    json_match = re.search(r"\{[\s\S]*\}", content)
    if not json_match:
        return {
            "spec": {},
            "errors": ["LLM did not return valid JSON"],
            "tokens_used": tokens_used,
        }

    try:
        spec = json.loads(json_match.group())
    except json.JSONDecodeError as e:
        return {
            "spec": {},
            "errors": [f"Invalid JSON from LLM: {e}"],
            "tokens_used": tokens_used,
        }

    spec = _sanitize_spec(spec)
    errors = _validate_spec(spec, available_source_ids)

    if errors:
        logger.warning("Claim-evidence spec validation errors: %s", errors)

    return {"spec": spec, "errors": errors, "tokens_used": tokens_used}
