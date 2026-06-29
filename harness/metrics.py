"""Metrics aggregation for token usage, cost, and latency tracking."""

from dataclasses import dataclass, field
from datetime import datetime


# Approximate costs per 1M tokens (adjust for your model)
MODEL_COSTS = {
    "granite-3.3-8b-instruct": {"input": 0.10, "output": 0.30},
    "granite-embedding-278m-multilingual": {"input": 0.02, "output": 0.0},
    "default": {"input": 0.50, "output": 1.50},
}


@dataclass
class IterationMetrics:
    """Metrics for a single iteration."""

    iteration: int
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    llm_calls: int = 0
    mcp_calls: int = 0
    total_latency_ms: int = 0
    cost_usd: float = 0.0
    quality_score: float = 0.0
    passed: bool = False


@dataclass
class MetricsAggregator:
    """Aggregates metrics across iterations for a research session."""

    session_id: str
    iterations: list[IterationMetrics] = field(default_factory=list)
    _current: IterationMetrics | None = field(default=None, repr=False)

    def start_iteration(self, iteration: int):
        """Begin tracking a new iteration."""
        self._current = IterationMetrics(iteration=iteration)

    def record_llm_call(self, input_tokens: int, output_tokens: int, model: str = "default"):
        """Record an LLM call with token usage."""
        if not self._current:
            return
        self._current.input_tokens += input_tokens
        self._current.output_tokens += output_tokens
        self._current.total_tokens += input_tokens + output_tokens
        self._current.llm_calls += 1

        costs = MODEL_COSTS.get(model, MODEL_COSTS["default"])
        self._current.cost_usd += (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1_000_000

    def record_mcp_call(self, latency_ms: int):
        """Record an MCP tool call."""
        if not self._current:
            return
        self._current.mcp_calls += 1
        self._current.total_latency_ms += latency_ms

    def record_latency(self, latency_ms: int):
        """Record arbitrary latency."""
        if self._current:
            self._current.total_latency_ms += latency_ms

    def end_iteration(self, quality_score: float, passed: bool):
        """Finalize the current iteration metrics."""
        if not self._current:
            return
        self._current.quality_score = quality_score
        self._current.passed = passed
        self.iterations.append(self._current)
        self._current = None

    @property
    def total_tokens(self) -> int:
        return sum(it.total_tokens for it in self.iterations)

    @property
    def total_cost(self) -> float:
        return sum(it.cost_usd for it in self.iterations)

    @property
    def total_llm_calls(self) -> int:
        return sum(it.llm_calls for it in self.iterations)

    @property
    def total_latency_ms(self) -> int:
        return sum(it.total_latency_ms for it in self.iterations)

    def summary(self) -> dict:
        """Generate a summary report of all metrics."""
        return {
            "session_id": self.session_id,
            "iterations": len(self.iterations),
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost, 4),
            "total_llm_calls": self.total_llm_calls,
            "total_latency_ms": self.total_latency_ms,
            "avg_quality_score": (
                round(sum(it.quality_score for it in self.iterations) / len(self.iterations), 2)
                if self.iterations else 0.0
            ),
            "final_score": self.iterations[-1].quality_score if self.iterations else 0.0,
            "passed": self.iterations[-1].passed if self.iterations else False,
            "per_iteration": [
                {
                    "iteration": it.iteration,
                    "tokens": it.total_tokens,
                    "cost_usd": round(it.cost_usd, 4),
                    "llm_calls": it.llm_calls,
                    "quality": it.quality_score,
                    "passed": it.passed,
                }
                for it in self.iterations
            ],
        }
