"""Reviewer tools: quality scoring, citation validation, feedback generation."""

import json
import os

import httpx
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "not-needed")
LLM_MODEL = os.getenv("LLM_MODEL", "granite-3.3-8b-instruct")
MAAS_API_KEY = os.getenv("MAAS_API_KEY", "")
_EFFECTIVE_LLM_KEY = MAAS_API_KEY if MAAS_API_KEY else LLM_API_KEY
_MAX_TOKEN_SMALL = int(os.getenv("LLM_MAX_TOKEN_SMALL", "512"))
_MAX_TOKEN_MEDIUM = int(os.getenv("LLM_MAX_TOKEN_MEDIUM", "1024"))
_VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() not in ("false", "0", "no")
_HTTP_CLIENT = None if _VERIFY_SSL else httpx.Client(verify=False, timeout=httpx.Timeout(300.0))


def get_llm_client() -> OpenAI:
    return OpenAI(base_url=LLM_BASE_URL, api_key=_EFFECTIVE_LLM_KEY, http_client=_HTTP_CLIENT)


def score_quality(report: str) -> float:
    """Score the quality of a research report on a 1-10 scale."""
    client = get_llm_client()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a research quality evaluator. Score the following report on a scale of 1-10 "
                    "based on: comprehensiveness, accuracy, clarity, structure, and evidence quality. "
                    "Return ONLY a JSON object: {\"score\": <number>, \"reasoning\": \"<brief explanation>\"}"
                ),
            },
            {"role": "user", "content": report[:4000]},
        ],
        temperature=0.1,
        max_tokens=_MAX_TOKEN_SMALL,
    )
    try:
        result = json.loads(response.choices[0].message.content)
        return float(result.get("score", 5.0))
    except (json.JSONDecodeError, ValueError):
        return 5.0


def validate_citations(report: str) -> bool:
    """Check if citations in the report are properly formatted and referenced."""
    client = get_llm_client()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a citation validator. Check if the report has proper source references. "
                    "Return ONLY a JSON object: {\"valid\": true/false, \"issues\": [\"issue1\", ...]}"
                ),
            },
            {"role": "user", "content": report[:4000]},
        ],
        temperature=0.1,
        max_tokens=_MAX_TOKEN_SMALL,
    )
    try:
        result = json.loads(response.choices[0].message.content)
        return result.get("valid", False)
    except (json.JSONDecodeError, ValueError):
        return True


def generate_feedback(report: str, quality_score: float, citation_valid: bool) -> str:
    """Generate specific improvement feedback for the report."""
    client = get_llm_client()
    issues = []
    if quality_score < 7.0:
        issues.append(f"Quality score is {quality_score}/10 (minimum 7.0 required)")
    if not citation_valid:
        issues.append("Citations are not properly formatted or referenced")

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a research editor. Provide specific, actionable feedback "
                    "to improve the report. Be concise (3-5 bullet points)."
                ),
            },
            {
                "role": "user",
                "content": f"Issues found: {'; '.join(issues)}\n\nReport:\n{report[:3000]}",
            },
        ],
        temperature=0.3,
        max_tokens=_MAX_TOKEN_MEDIUM,
    )
    return response.choices[0].message.content
