"""Writer tools: report generation and citation formatting."""

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
_MAX_TOKEN_LARGE = int(os.getenv("LLM_MAX_TOKEN_LARGE", "4096"))
_VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() not in ("false", "0", "no")
_HTTP_CLIENT = None if _VERIFY_SSL else httpx.Client(verify=False, timeout=httpx.Timeout(300.0))


def get_llm_client() -> OpenAI:
    return OpenAI(base_url=LLM_BASE_URL, api_key=_EFFECTIVE_LLM_KEY, http_client=_HTTP_CLIENT)


def plan_report_structure(query: str, context: str) -> str:
    """Plan the structure of the research report."""
    client = get_llm_client()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a research report planner. Given a research question and context, "
                    "create a brief outline (3-5 sections) for a comprehensive report. "
                    "Return only the outline as a numbered list."
                ),
            },
            {"role": "user", "content": f"Question: {query}\n\nAvailable context:\n{context[:2000]}"},
        ],
        temperature=0.3,
        max_tokens=_MAX_TOKEN_MEDIUM,
    )
    return response.choices[0].message.content


def generate_report(query: str, context: str, instructions: str) -> str:
    """Generate a comprehensive research report in markdown."""
    client = get_llm_client()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a professional research writer. Write a comprehensive, well-structured "
                    "research report in markdown format. Include:\n"
                    "- Clear headings and subheadings\n"
                    "- Key findings with supporting evidence\n"
                    "- Analysis and insights\n"
                    "- Conclusion with actionable takeaways\n\n"
                    "Reference source materials using [Source N] notation."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Research question: {query}\n\n"
                    f"Report structure:\n{instructions}\n\n"
                    f"Source materials:\n{context}"
                ),
            },
        ],
        temperature=0.4,
        max_tokens=_MAX_TOKEN_LARGE,
    )
    return response.choices[0].message.content


def format_citations(context: str) -> str:
    """Extract and format citations from the context."""
    client = get_llm_client()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Extract source references from the provided text and format them as a "
                    "numbered bibliography. Each entry should include the document name and "
                    "relevant section. Return only the formatted references list."
                ),
            },
            {"role": "user", "content": context[:3000]},
        ],
        temperature=0.1,
        max_tokens=_MAX_TOKEN_MEDIUM,
    )
    return response.choices[0].message.content
