"""Execution models for the OpenShell sandbox abstraction."""

from dataclasses import dataclass, field


@dataclass
class SandboxConfig:
    """Configuration for creating an OpenShell sandbox."""
    name: str
    image: str
    workspace: str = "default"
    cpu: str = "500m"
    memory: str = "512Mi"
    labels: dict[str, str] = field(default_factory=dict)
    policy_path: str = ""


@dataclass
class ExecutionResult:
    """Result of executing a command inside a sandbox."""
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
