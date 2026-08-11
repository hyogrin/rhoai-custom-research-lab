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

    def check_connectivity(self) -> tuple[bool, str]: ...
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
        self._workspace_cache: dict[str, str] = {}

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

    def check_connectivity(self) -> tuple[bool, str]:
        """Verify the OpenShell gateway is reachable via TCP (gRPC port)."""
        import socket
        import urllib.parse
        gateway_url = os.environ.get("OPENSHELL_GATEWAY_URL", "http://127.0.0.1:8080")
        parsed = urllib.parse.urlparse(gateway_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8080
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((host, port))
            s.close()
            return True, ""
        except Exception as e:
            return False, f"Gateway {host}:{port} unreachable: {e}"

    def create_sandbox(self, config: SandboxConfig) -> str:
        client = self._get_client()

        spec = None
        if config.image:
            from openshell._proto import openshell_pb2
            spec = openshell_pb2.SandboxSpec(
                template=openshell_pb2.SandboxTemplate(image=config.image),
            )
            logger.info("Using custom image: %s", config.image)

        sandbox = client.create(
            workspace=config.workspace,
            name=config.name,
            labels=config.labels,
            spec=spec,
        )
        logger.info("Created sandbox: %s (id=%s)", config.name, sandbox.id)
        self._workspace_cache[config.name] = config.workspace

        if config.policy_path and os.path.exists(config.policy_path):
            import subprocess
            subprocess.run(
                ["openshell", "policy", "set", "--policy", config.policy_path, config.name],
                capture_output=True,
                timeout=30,
            )

        try:
            client.wait_ready(config.name, workspace=config.workspace, timeout_seconds=120.0)
            logger.info("Sandbox %s is ready", config.name)
        except Exception as e:
            logger.warning("Sandbox %s wait_ready failed: %s — proceeding anyway", config.name, e)

        return sandbox.id

    def upload_inputs(self, sandbox_id: str, files: dict[str, bytes]) -> None:
        client = self._get_client()
        for path, data in files.items():
            dirname = os.path.dirname(path)
            logger.info("Uploading %s (%d bytes) to sandbox %s", path, len(data), sandbox_id)

            mkdir_result = client.exec(
                sandbox_id,
                ["mkdir", "-p", dirname],
                timeout_seconds=10,
            )
            if mkdir_result.exit_code != 0:
                logger.error("mkdir -p %s failed (code %d): %s", dirname, mkdir_result.exit_code,
                             getattr(mkdir_result, "stderr", ""))

            import base64
            b64_data = base64.b64encode(data).decode("ascii")
            write_result = client.exec(
                sandbox_id,
                ["sh", "-c", f"echo '{b64_data}' | base64 -d > {path}"],
                timeout_seconds=30,
            )
            if write_result.exit_code != 0:
                logger.error("Write to %s failed (code %d): %s", path, write_result.exit_code,
                             getattr(write_result, "stderr", ""))
            else:
                verify = client.exec(sandbox_id, ["ls", "-la", path], timeout_seconds=5)
                logger.info("Verified upload %s: %s", path,
                            getattr(verify, "stdout", "").strip() if verify.exit_code == 0 else "MISSING")

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
            workspace = self._workspace_cache.pop(sandbox_id, os.environ.get("OPENSHELL_WORKSPACE", "default"))
            client.delete(sandbox_id, workspace=workspace)
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

    def check_connectivity(self) -> tuple[bool, str]:
        return True, ""

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
