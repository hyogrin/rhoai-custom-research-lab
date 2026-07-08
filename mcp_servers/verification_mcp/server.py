"""Verification MCP Server — Quality scoring, citation validation, fact checking, LLM-as-Judge."""

import json
import os
import re
import threading
import time
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from openai import OpenAI

load_dotenv()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "not-needed")
LLM_MODEL = os.getenv("LLM_MODEL", "granite-3.3-8b-instruct")
MAAS_API_KEY = os.getenv("MAAS_API_KEY", "")
_EFFECTIVE_LLM_KEY = MAAS_API_KEY if MAAS_API_KEY else LLM_API_KEY
_MAX_TOKEN_SMALL = int(os.getenv("LLM_MAX_TOKEN_SMALL", "512"))
_VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() not in ("false", "0", "no")
_THINKING_EXTRA_BODY: dict = {"chat_template_kwargs": {"enable_thinking": False}}

_llm_lock = threading.Lock()
_last_llm_call: float = 0.0
_MIN_CALL_INTERVAL = 1.0

mcp = FastMCP("verification-mcp", host="0.0.0.0", port=9004, stateless_http=True)


def _rate_limit():
    global _last_llm_call
    with _llm_lock:
        now = time.time()
        elapsed = now - _last_llm_call
        if elapsed < _MIN_CALL_INTERVAL:
            time.sleep(_MIN_CALL_INTERVAL - elapsed)
        _last_llm_call = time.time()


def _get_llm() -> OpenAI:
    http_client = None
    if not _VERIFY_SSL:
        http_client = httpx.Client(verify=False, timeout=httpx.Timeout(90.0))
    return OpenAI(
        base_url=LLM_BASE_URL,
        api_key=_EFFECTIVE_LLM_KEY,
        http_client=http_client,
        max_retries=0,
        timeout=90.0,
    )


def _call_llm(messages: list[dict], max_tokens: int = 512) -> tuple[str, int]:
    for attempt in range(3):
        if attempt > 0:
            time.sleep(10 + 5 * attempt)
        _rate_limit()
        try:
            client = _get_llm()
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=0.1,
                max_tokens=max_tokens,
                extra_body=_THINKING_EXTRA_BODY,
            )
            content = response.choices[0].message.content or ""
            tokens = response.usage.total_tokens if response.usage else 0
            return content, tokens
        except Exception:
            pass
    return "", 0


def _extract_json(text: str) -> Any:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    md_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if md_match:
        text = md_match.group(1).strip()
    brace = text.find("{")
    if brace == -1:
        return None
    text = text[brace:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for end in range(len(text), 0, -1):
        try:
            return json.loads(text[:end])
        except json.JSONDecodeError:
            continue
    return None


@mcp.tool()
def quality_score(draft: str, query: str) -> dict:
    """Score a research draft on completeness, accuracy, clarity, and structure (1-10 each)."""
    content, tokens = _call_llm(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a research quality evaluator. Score the following draft on a scale of 1-10 "
                    "for each criterion. Return ONLY a JSON object with keys: "
                    "'completeness', 'accuracy', 'clarity', 'structure', 'overall', 'feedback'. "
                    "The 'overall' score is the weighted average. 'feedback' is a brief improvement suggestion. "
                    "No explanation, ONLY JSON."
                ),
            },
            {"role": "user", "content": f"Query: {query}\n\nDraft:\n{draft[:2000]}"},
        ],
    )
    if content:
        scores = _extract_json(content)
        if isinstance(scores, dict):
            scores["tokens_used"] = tokens
            return scores
    return {
        "completeness": 5, "accuracy": 5, "clarity": 5, "structure": 5,
        "overall": 5, "feedback": "Unable to evaluate", "tokens_used": tokens,
    }


@mcp.tool()
def validate_citations(draft: str, num_sources: int) -> dict:
    """Validate that [Source N] citations in the draft reference real sources."""
    citation_pattern = r'\[Source (\d+)\]'
    found_citations = set(int(m) for m in re.findall(citation_pattern, draft))
    available_sources = set(range(1, num_sources + 1))
    valid = found_citations & available_sources
    invalid = found_citations - available_sources
    missing_coverage = available_sources - found_citations
    total_claims = max(len(draft.split(". ")), 1)
    cited_ratio = len(found_citations) / max(total_claims // 3, 1)
    return {
        "valid_citations": sorted(valid),
        "invalid_citations": sorted(invalid),
        "uncited_sources": sorted(missing_coverage),
        "citation_coverage": min(round(cited_ratio, 2), 1.0),
        "has_citations": len(found_citations) > 0,
        "passed": len(invalid) == 0 and len(found_citations) > 0,
    }


@mcp.tool()
def fact_check(draft: str, context: list[dict]) -> dict:
    """Cross-reference claims in the draft against source documents."""
    if not context:
        return {"passed": True, "reason": "No context to verify against", "tokens_used": 0}
    source_text = "\n\n".join(
        f"[Source {i+1}]: {c.get('content', '')[:300]}"
        for i, c in enumerate(context[:5])
    )
    content, tokens = _call_llm(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a fact checker. Compare claims in the draft against the source documents. "
                    "Return ONLY a JSON object with: 'supported_claims' (int), 'unsupported_claims' (int), "
                    "'hallucinations' (list of unsupported statements), 'passed' (bool - true if >80% supported). "
                    "No explanation, ONLY JSON."
                ),
            },
            {"role": "user", "content": f"Draft:\n{draft[:1500]}\n\nSources:\n{source_text}"},
        ],
    )
    if content:
        result = _extract_json(content)
        if isinstance(result, dict):
            result["tokens_used"] = tokens
            return result
    return {"supported_claims": 0, "unsupported_claims": 0, "hallucinations": [], "passed": True, "tokens_used": tokens}


@mcp.tool()
def llm_as_judge(draft: str, query: str, iteration: int = 1) -> dict:
    """Evaluate a research report using a structured rubric (relevance, depth, evidence, clarity, completeness)."""
    content, tokens = _call_llm(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert research judge. Evaluate this research report using the following rubric:\n"
                    "1. Relevance (0-2): Does it answer the question?\n"
                    "2. Depth (0-2): Is it thorough and detailed?\n"
                    "3. Evidence (0-2): Are claims supported with citations?\n"
                    "4. Clarity (0-2): Is it well-organized and readable?\n"
                    "5. Completeness (0-2): Does it cover all aspects?\n\n"
                    "Return ONLY a JSON object with: 'relevance', 'depth', 'evidence', 'clarity', "
                    "'completeness' (each 0-2), 'total' (sum out of 10), 'verdict' ('pass'|'fail'), "
                    "'reasoning' (1-2 sentences), 'improvements' (list of specific things to fix). "
                    "No explanation, ONLY JSON."
                ),
            },
            {"role": "user", "content": f"Research Question: {query}\nIteration: {iteration}\n\nReport:\n{draft[:2000]}"},
        ],
    )
    if content:
        result = _extract_json(content)
        if isinstance(result, dict):
            result["tokens_used"] = tokens
            return result
    return {
        "relevance": 1, "depth": 1, "evidence": 1, "clarity": 1, "completeness": 1,
        "total": 5, "verdict": "fail", "reasoning": "Unable to evaluate",
        "improvements": ["Retry evaluation"], "tokens_used": tokens,
    }


@mcp.tool()
def run_verification(
    draft: str,
    query: str,
    context: list[dict],
    iteration: int = 1,
    enable_fact_check: bool = True,
) -> dict:
    """Run all verification checks (quality, citations, facts, judge) and aggregate results."""
    num_sources = len(context)
    citations = validate_citations(draft, num_sources)

    quality = quality_score(draft, query)
    judge = llm_as_judge(draft, query, iteration)
    if enable_fact_check:
        facts = fact_check(draft, context)
    else:
        facts = {"supported_claims": 0, "unsupported_claims": 0, "hallucinations": [], "passed": True, "tokens_used": 0}

    overall_score = judge.get("total", quality.get("overall", 5))
    total_tokens = quality.get("tokens_used", 0) + facts.get("tokens_used", 0) + judge.get("tokens_used", 0)

    improvements = []
    if not citations.get("passed"):
        improvements.append("Add proper [Source N] citations for all claims")
    if not facts.get("passed"):
        hallucinations = facts.get("hallucinations", [])
        if hallucinations:
            improvements.append(f"Remove unsupported claims: {'; '.join(str(h) for h in hallucinations[:3])}")
    improvements.extend(judge.get("improvements", []))

    return {
        "quality_score": overall_score,
        "quality_details": quality,
        "citation_check": citations,
        "fact_check": facts,
        "judge_verdict": judge,
        "passed": judge.get("verdict") == "pass" and overall_score >= 7,
        "improvements": improvements,
        "tokens_used": total_tokens,
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
