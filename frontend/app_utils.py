"""Utility classes for the Chainlit frontend."""

import logging
import asyncio
from typing import Any

import chainlit as cl

logger = logging.getLogger(__name__)


class ChatSettings:
    """User session settings for the research UI."""

    def __init__(self):
        self.quality_threshold: float = 7.0
        self.max_iterations: int = 2
        self.max_tokens: int = 4096
        self.temperature: float = 0.7
        self.verbose: bool = True
        self.log_sse: bool = False  # True: accumulate all steps, False: show only current step
        self.language: str = "en-US"  # en-US or ko-KR
        self.enable_web_search: bool = True
        self.enable_planning: bool = True
        self.enable_fact_check: bool = True
        self.enable_parallel: bool = True
        self.enable_sectioned: bool = True


class StepNameManager:
    """Generate unique step names to avoid collisions in Chainlit UI."""

    def __init__(self):
        self._counter: dict[str, int] = {}

    def get_unique_name(self, base_name: str) -> str:
        clean = base_name.strip()
        if clean not in self._counter:
            self._counter[clean] = 1
            return clean
        self._counter[clean] += 1
        return f"{clean} ({self._counter[clean]})"

    def reset(self):
        self._counter.clear()


async def safe_stream_token(msg: cl.Message, content: str) -> bool:
    """Stream a token to a Chainlit message, returning False on failure."""
    try:
        await msg.stream_token(content)
        return True
    except Exception as e:
        logger.warning(f"Failed to stream token: {e}")
        return False


async def safe_send_step(step: cl.Step) -> bool:
    """Send a Chainlit step, returning False on failure."""
    try:
        await step.send()
        return True
    except Exception as e:
        logger.warning(f"Failed to send step: {e}")
        return False


async def safe_update_message(msg: cl.Message) -> bool:
    """Update a Chainlit message, returning False on failure."""
    try:
        await msg.update()
        return True
    except Exception as e:
        logger.warning(f"Failed to update message: {e}")
        return False


async def retry_async(operation, *args, max_retries=3, delay=0.2, backoff=2.0, **kwargs):
    """Retry an async operation with exponential backoff."""
    current_delay = delay
    last_error = None
    for attempt in range(max_retries):
        try:
            return await operation(*args, **kwargs)
        except Exception as e:
            last_error = e
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(current_delay)
                current_delay *= backoff
    raise last_error
