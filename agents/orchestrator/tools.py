"""Orchestrator tools: A2A communication and research planning."""

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
_VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() not in ("false", "0", "no")
_HTTP_CLIENT = None if _VERIFY_SSL else httpx.Client(verify=False, timeout=httpx.Timeout(300.0))

A2A_TIMEOUT = int(os.getenv("A2A_TIMEOUT", "120"))


def get_llm_client() -> OpenAI:
    return OpenAI(base_url=LLM_BASE_URL, api_key=_EFFECTIVE_LLM_KEY, http_client=_HTTP_CLIENT)


def a2a_discover_agents(base_urls: list[str]) -> list[dict]:
    """Discover available agents via their A2A AgentCard endpoints."""
    discovered = []
    for url in base_urls:
        try:
            card_url = f"{url.rstrip('/')}/.well-known/agent-card.json"
            response = httpx.get(card_url, timeout=10)
            if response.status_code == 200:
                card = response.json()
                discovered.append({
                    "url": url,
                    "name": card.get("name", "unknown"),
                    "description": card.get("description", ""),
                    "skills": [s.get("name", "") for s in card.get("skills", [])],
                })
        except Exception:
            continue
    return discovered


def a2a_send_message(agent_url: str, message: str) -> str:
    """Send a message to an agent via A2A JSON-RPC protocol."""
    payload = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": "1",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": message}],
            }
        },
    }

    try:
        response = httpx.post(
            agent_url.rstrip("/"),
            json=payload,
            timeout=A2A_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        result = response.json()

        # Extract text from A2A response
        if "result" in result:
            task_result = result["result"]
            if "artifacts" in task_result:
                parts = []
                for artifact in task_result["artifacts"]:
                    for part in artifact.get("parts", []):
                        if part.get("kind") == "text":
                            parts.append(part["text"])
                return "\n".join(parts) if parts else str(task_result)
            # Handle message response format
            if "message" in task_result:
                msg = task_result["message"]
                parts = []
                for part in msg.get("parts", []):
                    if part.get("kind") == "text":
                        parts.append(part["text"])
                return "\n".join(parts) if parts else str(msg)
        return str(result)

    except httpx.TimeoutException:
        return f"Error: Agent at {agent_url} timed out after {A2A_TIMEOUT}s"
    except Exception as e:
        return f"Error communicating with agent at {agent_url}: {e}"


def plan_research_strategy(query: str, has_document: bool) -> list[str]:
    """Use LLM to plan research steps based on the user query."""
    client = get_llm_client()

    steps = []
    if has_document:
        steps.append("ingest_document")
    steps.extend(["research", "write", "review"])

    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a research planner. Given a research question, determine the best "
                        "execution plan. Available steps: ingest_document, research, write, review. "
                        "Return ONLY a JSON array of step names in execution order."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Query: {query}\nHas document: {has_document}",
                },
            ],
            temperature=0.1,
            max_tokens=_MAX_TOKEN_SMALL,
        )
        result = json.loads(response.choices[0].message.content)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, Exception):
        pass

    return steps
