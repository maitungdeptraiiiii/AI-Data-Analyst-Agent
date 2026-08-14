from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from analyst_agent.cli import initial_state
from analyst_agent.nodes.executor import finalize_step
from analyst_agent.nodes.tool_router import choose_tool
from analyst_agent.python_guard import PythonPolicyError, validate_python_code
from analyst_agent.sandbox import build_docker_command
from analyst_agent.serialization import extract_metrics, normalize_json_value


def test_guard_allows_analysis_contract() -> None:
    code = "import pandas as pd\ndf = load_dataset()\nmetrics = {'mean': 1.0}\nresult = df"
    assert validate_python_code(code) == code


@pytest.mark.parametrize(
    "code",
    [
        "import os\nmetrics = {}\nresult = []",
        "open('/etc/passwd').read()",
        "import pandas as pd\npd.read_csv('secret.csv')",
        "eval('1 + 1')",
    ],
)
def test_guard_rejects_dangerous_code(code: str) -> None:
    with pytest.raises(PythonPolicyError):
        validate_python_code(code)


def test_router_defaults_sql_and_selects_python_for_correlation() -> None:
    state = initial_state("Analyze", "data/sample_sales.csv")
    state["dataset_info"] = {
        "table_name": "analysis.dataset_test",
        "columns": {},
        "n_rows": 100,
        "null_summary": {},
        "sample_rows": [],
    }
    state["plan"] = ["Calculate revenue by month"]
    assert choose_tool(state)["current_tool"] == "sql"
    state["plan"] = ["Calculate correlation between price and units"]
    assert choose_tool(state)["current_tool"] == "python"


def test_router_forces_sql_for_large_dataset() -> None:
    state = initial_state("Analyze", "data/sample_sales.csv")
    state["dataset_info"] = {
        "table_name": "analysis.dataset_test",
        "columns": {},
        "n_rows": 100_001,
        "null_summary": {},
        "sample_rows": [],
    }
    state["plan"] = ["Calculate correlation"]
    assert choose_tool(state)["current_tool"] == "sql"


def test_finalize_preserves_python_metrics_and_resets_current_metrics() -> None:
    state = initial_state("Analyze", "data/sample_sales.csv")
    state.update(
        plan=["Detect outliers"],
        current_tool="python",
        current_code="metrics = {'n': 2}",
        current_purpose="Outlier analysis",
        current_rows=[{"value": 10}],
        current_metrics={"outlier_count": 2.0},
    )
    update = finalize_step(state)
    assert update["analysis_log"][0]["metrics"] == {"outlier_count": 2.0}
    assert update["analysis_log"][0]["tool"] == "python"
    assert update["current_metrics"] == {}


def test_sql_metric_flatten_and_json_normalization() -> None:
    assert extract_metrics([{"revenue": Decimal("12.5"), "label": "July"}]) == {"revenue": 12.5}
    normalized = normalize_json_value({"at": datetime(2026, 7, 1), "amount": Decimal("2.5")})
    assert normalized == {"at": "2026-07-01T00:00:00", "amount": 2.5}


def test_docker_command_is_hardened_and_does_not_contain_dsn(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from analyst_agent import sandbox

    class Settings:
        python_sandbox_network = "internal"
        python_sandbox_memory = "512m"
        python_sandbox_cpus = 1.0
        python_sandbox_image = "sandbox:test"

    monkeypatch.setattr(sandbox, "get_settings", lambda: Settings())
    input_dir, output_dir = tmp_path / "input", tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    command = build_docker_command(input_dir, output_dir)
    joined = " ".join(command)
    assert "--read-only" in command
    assert "--cap-drop ALL" in joined
    assert "no-new-privileges" in joined
    assert "postgresql://" not in joined


def test_sanitize_error_message_strips_dsn_credentials() -> None:
    from analyst_agent.errors import sanitize_error_message

    message = (
        'connection failed: connection to server at "postgres" (172.19.0.2), port 5432 '
        "failed: FATAL: password authentication failed for user "
        '"executor_ro" dsn="postgresql://executor_ro:executor_dev_password@postgres:5432/analyst"'
    )
    sanitized = sanitize_error_message(message)
    assert "executor_dev_password" not in sanitized
    assert "postgresql://***@postgres:5432/analyst" in sanitized


def test_sql_and_sandbox_errors_are_sanitized_before_returning() -> None:
    from psycopg import errors

    from analyst_agent.errors import classify_sql_error

    exc = errors.OperationalError(
        'connection failed dsn="postgresql://executor_ro:secret@postgres:5432/analyst"'
    )
    result = classify_sql_error(exc)
    assert "secret" not in result["message"]


def _run_raw_sandbox(monkeypatch, python_source: str, timeout: float = 8.0):  # type: ignore[no-untyped-def]
    """Run `python_source` directly inside the hardened container, bypassing the app-level
    AST guard entirely — this isolates what the Docker boundary itself enforces.
    """
    import subprocess

    from analyst_agent import sandbox
    from analyst_agent.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(sandbox, "get_settings", lambda: settings)
    command = [
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
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "10001:10001",
        "--entrypoint",
        "python",
        settings.python_sandbox_image,
        "-c",
        python_source,
    ]
    return subprocess.run(command, shell=False, capture_output=True, text=True, timeout=timeout)


@pytest.mark.sandbox_integration
def test_sandbox_cannot_reach_public_internet(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    completed = _run_raw_sandbox(
        monkeypatch,
        "import socket; socket.create_connection(('8.8.8.8', 53), timeout=3)",
    )
    assert completed.returncode != 0
    assert "unreachable" in completed.stderr.lower() or "timed out" in completed.stderr.lower()


@pytest.mark.sandbox_integration
def test_sandbox_root_filesystem_is_read_only(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    completed = _run_raw_sandbox(monkeypatch, "open('/sandbox/escape.txt', 'w').write('x')")
    assert completed.returncode != 0
    assert "read-only" in completed.stderr.lower()


@pytest.mark.sandbox_integration
def test_sandbox_can_reach_postgres_internally(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from analyst_agent.config import get_settings

    dsn = get_settings().python_sandbox_database_dsn
    completed = _run_raw_sandbox(
        monkeypatch,
        f"import psycopg; psycopg.connect({dsn!r}).close(); print('ok')",
    )
    assert completed.returncode == 0
    assert "ok" in completed.stdout


@pytest.mark.sandbox_integration
def test_infinite_loop_is_killed_by_timeout() -> None:
    import time

    from analyst_agent.config import get_settings
    from analyst_agent.sandbox import execute_python_sandbox

    started = time.monotonic()
    result = execute_python_sandbox(
        "while True:\n    pass\n", "analysis.does_not_matter_for_this_test"
    )
    elapsed = time.monotonic() - started
    assert result["success"] is False
    assert result["error"] is not None
    assert result["error"]["category"] == "sandbox_timeout"
    assert elapsed < get_settings().python_sandbox_timeout_seconds + 5
