"""Harness execution package — OpenShell sandbox abstraction."""

from harness.execution.models import SandboxConfig, ExecutionResult
from harness.execution.openshell_executor import (
    OpenShellExecutor,
    FakeOpenShellExecutor,
    get_executor,
    set_executor,
    ExecutorProtocol,
)

__all__ = [
    "SandboxConfig",
    "ExecutionResult",
    "OpenShellExecutor",
    "FakeOpenShellExecutor",
    "get_executor",
    "set_executor",
    "ExecutorProtocol",
]
