import json
import subprocess
import tempfile
from pathlib import Path
from typing import TypedDict, cast

from analyst_agent.config import get_settings
from analyst_agent.errors import ExecutionError, sanitize_error_message
from analyst_agent.python_guard import PythonPolicyError, validate_python_code


class SandboxResult(TypedDict):
    success: bool
    rows: list[dict[str, object]]
    metrics: dict[str, float]
    error: ExecutionError | None


def build_docker_command(input_dir: Path, output_dir: Path) -> list[str]:
    settings = get_settings()
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        settings.python_sandbox_network,
        "--memory",
        settings.python_sandbox_memory,
        "--cpus",
        str(settings.python_sandbox_cpus),
        "--pids-limit",
        "64",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "10001:10001",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--mount",
        f"type=bind,src={input_dir.resolve()},dst=/run/input,readonly",
        "--mount",
        f"type=bind,src={output_dir.resolve()},dst=/run/output",
        settings.python_sandbox_image,
    ]


def execute_python_sandbox(code: str, table_name: str) -> SandboxResult:
    try:
        validate_python_code(code)
    except PythonPolicyError as exc:
        return {
            "success": False,
            "rows": [],
            "metrics": {},
            "error": {
                "category": "blocked_python",
                "code": None,
                "message": str(exc),
                "retryable": False,
            },
        }
    settings = get_settings()
    with tempfile.TemporaryDirectory(dir=settings.sandbox_runs_dir) as directory:
        root = Path(directory)
        input_dir, output_dir = root / "input", root / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        (input_dir / "generated.py").write_text(code, encoding="utf-8")
        (input_dir / "input.json").write_text(
            json.dumps(
                {
                    "table_name": table_name,
                    "database_dsn": settings.python_sandbox_database_dsn,
                    "max_output_rows": 200,
                }
            ),
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                build_docker_command(input_dir, output_dir),
                shell=False,
                capture_output=True,
                text=True,
                timeout=settings.python_sandbox_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "rows": [],
                "metrics": {},
                "error": {
                    "category": "sandbox_timeout",
                    "code": None,
                    "message": "Python sandbox timed out",
                    "retryable": True,
                },
            }
        output_path = output_dir / "output.json"
        if completed.returncode != 0 or not output_path.exists():
            return {
                "success": False,
                "rows": [],
                "metrics": {},
                "error": {
                    "category": "infrastructure",
                    "code": None,
                    "message": "Python sandbox failed to produce output",
                    "retryable": False,
                },
            }
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        error = payload.get("error")
        if error is not None:
            error["message"] = sanitize_error_message(error["message"])
        return cast(SandboxResult, payload)
