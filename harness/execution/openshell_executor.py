"""OpenShell executor abstraction.

Wraps the NVIDIA OpenShell Python SDK to provide a testable interface
for sandbox lifecycle management. Tests can replace this with FakeOpenShellExecutor.
"""

import logging
import os
from typing import Protocol

from harness.execution.models import SandboxConfig, ExecutionResult

logger = logging.getLogger(__name__)


class ExecutorProtocol(Protocol):
    """Protocol that both real and fake executors implement."""

    def create_sandbox(self, config: SandboxConfig) -> str: ...
    def upload_inputs(self, sandbox_id: str, files: dict[str, bytes]) -> None: ...
    def execute(self, sandbox_id: str, command: list[str], timeout: int) -> ExecutionResult: ...
    def download_outputs(self, sandbox_id: str, paths: list[str]) -> dict[str, bytes]: ...
    def get_logs(self, sandbox_id: str) -> str: ...
    def delete_sandbox(self, sandbox_id: str) -> None: ...


class OpenShellExecutor:
    """Real OpenShell executor using the openshell Python SDK."""

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openshell import SandboxClient
            except ImportError:
                raise ImportError(
                    "The 'openshell' package is required for real sandbox execution. "
                    "Install it with: uv pip install 'rhoai-custom-research-lab[openshell]' "
                    "or: pip install openshell"
                )
            self._client = SandboxClient.from_active_cluster()
        return self._client

    def create_sandbox(self, config: SandboxConfig) -> str:
        client = self._get_client()
        kwargs: dict = {
            "workspace": config.workspace,
            "name": config.name,
            "labels": config.labels,
        }
        if config.cpu:
            kwargs["cpu"] = config.cpu
        if config.memory:
            kwargs["memory"] = config.memory

        sandbox = client.create(**kwargs)
        logger.info("Created sandbox: %s (id=%s)", config.name, sandbox.id)

        if config.policy_path and os.path.exists(config.policy_path):
            import subprocess
            subprocess.run(
                ["openshell", "policy", "set", "--policy", config.policy_path, config.name],
                capture_output=True,
                timeout=30,
            )

        return sandbox.id

    def upload_inputs(self, sandbox_id: str, files: dict[str, bytes]) -> None:
        client = self._get_client()
        for path, data in files.items():
            client.exec(
                sandbox_id,
                ["mkdir", "-p", os.path.dirname(path)],
                timeout_seconds=10,
            )
            client.exec(
                sandbox_id,
                ["tee", path],
                stdin=data,
                timeout_seconds=30,
            )

    def execute(self, sandbox_id: str, command: list[str], timeout: int) -> ExecutionResult:
        client = self._get_client()
        result = client.exec(
            sandbox_id,
            command,
            timeout_seconds=timeout,
        )
        return ExecutionResult(
            exit_code=result.exit_code,
            stdout=result.stdout if hasattr(result, "stdout") else "",
            stderr=result.stderr if hasattr(result, "stderr") else "",
        )

    def download_outputs(self, sandbox_id: str, paths: list[str]) -> dict[str, bytes]:
        client = self._get_client()
        outputs: dict[str, bytes] = {}
        for path in paths:
            try:
                result = client.exec(
                    sandbox_id,
                    ["cat", path],
                    timeout_seconds=30,
                )
                if result.exit_code == 0 and hasattr(result, "stdout"):
                    outputs[path] = result.stdout.encode("utf-8") if isinstance(result.stdout, str) else result.stdout
            except Exception as e:
                logger.warning("Failed to download %s: %s", path, e)
        return outputs

    def get_logs(self, sandbox_id: str) -> str:
        import subprocess
        try:
            result = subprocess.run(
                ["openshell", "logs", sandbox_id, "--since", "10m"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.stdout
        except Exception as e:
            return f"Failed to get logs: {e}"

    def delete_sandbox(self, sandbox_id: str) -> None:
        try:
            client = self._get_client()
            client.delete(sandbox_id)
            logger.info("Deleted sandbox: %s", sandbox_id)
        except Exception as e:
            logger.warning("Failed to delete sandbox %s: %s", sandbox_id, e)


class FakeOpenShellExecutor:
    """Test double that simulates OpenShell without a real gateway."""

    def __init__(self, fail_on_execute: bool = False, exit_code: int = 0):
        self._fail_on_execute = fail_on_execute
        self._exit_code = exit_code
        self._svg_output = b'<svg xmlns="http://www.w3.org/2000/svg"><text>Test</text></svg>'
        self._metadata_output = b'{"nodes_rendered": 5}'
        self.created_sandboxes: list[str] = []
        self.deleted_sandboxes: list[str] = []

    def create_sandbox(self, config: SandboxConfig) -> str:
        self.created_sandboxes.append(config.name)
        return config.name

    def upload_inputs(self, sandbox_id: str, files: dict[str, bytes]) -> None:
        pass

    def execute(self, sandbox_id: str, command: list[str], timeout: int) -> ExecutionResult:
        if self._fail_on_execute:
            return ExecutionResult(exit_code=1, stderr="Simulated failure")
        return ExecutionResult(exit_code=self._exit_code, stdout="OK")

    def download_outputs(self, sandbox_id: str, paths: list[str]) -> dict[str, bytes]:
        outputs: dict[str, bytes] = {}
        for path in paths:
            if path.endswith(".svg"):
                outputs[path] = self._svg_output
            elif path.endswith(".json"):
                outputs[path] = self._metadata_output
        return outputs

    def get_logs(self, sandbox_id: str) -> str:
        return "fake logs"

    def delete_sandbox(self, sandbox_id: str) -> None:
        self.deleted_sandboxes.append(sandbox_id)


_executor_instance: ExecutorProtocol | None = None


def get_executor() -> ExecutorProtocol:
    """Get the singleton executor instance. Allows test injection."""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = OpenShellExecutor()
    return _executor_instance


def set_executor(executor: ExecutorProtocol) -> None:
    """Inject a custom executor (used for testing)."""
    global _executor_instance
    _executor_instance = executor
