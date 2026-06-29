"""Smoke test: FastAPI native SSE endpoint + aiohttp consumer.

Run:  uv run python backend/test_sse.py
      make sse-test

Expected output:
  5 harness phase events printed, then "[DONE]", then "PASSED".
"""

import asyncio
import threading

import aiohttp
import uvicorn
from fastapi import FastAPI
from fastapi.sse import EventSourceResponse, ServerSentEvent
from collections.abc import AsyncIterable

TEST_PORT = 9999
app = FastAPI()


@app.post("/test-research", response_class=EventSourceResponse)
async def test_research() -> AsyncIterable[ServerSentEvent]:
    """Simulate the harness inner loop emitting SSE events."""
    phases = [
        ("planning", "Generating research plan..."),
        ("executing", "Searching documents and drafting..."),
        ("verifying", "Running quality checks..."),
        ("reflecting", "Analyzing improvements needed..."),
        ("complete", "Research complete, score 8.1/10"),
    ]
    for i, (phase, message) in enumerate(phases):
        await asyncio.sleep(0.3)
        yield ServerSentEvent(
            data={
                "event": "phase",
                "phase": phase,
                "iteration": 1,
                "max_iterations": 3,
                "quality_score": 8.1 if phase == "complete" else 0,
                "message": message,
            },
            event="phase",
            id=str(i),
        )
    yield ServerSentEvent(raw_data="[DONE]", event="done")


async def consume_sse():
    """Connect to the test server and consume SSE events via aiohttp."""
    await asyncio.sleep(1.5)
    events_received = 0
    done_received = False

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(f"http://127.0.0.1:{TEST_PORT}/test-research") as resp:
            assert resp.status == 200, f"Unexpected status: {resp.status}"
            content_type = resp.headers.get("content-type", "")
            assert "text/event-stream" in content_type, f"Wrong content-type: {content_type}"

            buffer = ""
            async for chunk in resp.content.iter_any():
                buffer += chunk.decode("utf-8")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data == "[DONE]":
                            done_received = True
                        else:
                            events_received += 1
                            print(f"  << event {events_received}: {data[:80]}")

    assert events_received == 5, f"Expected 5 events, got {events_received}"
    assert done_received, "Never received [DONE] sentinel"
    print(f"\nSSE smoke test PASSED ({events_received} events + [DONE])")


def main():
    server_thread = threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": "127.0.0.1", "port": TEST_PORT, "log_level": "warning"},
        daemon=True,
    )
    server_thread.start()
    asyncio.run(consume_sse())


if __name__ == "__main__":
    main()
