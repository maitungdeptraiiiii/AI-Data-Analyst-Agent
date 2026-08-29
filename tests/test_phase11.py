from fastapi.testclient import TestClient

from analyst_agent.api.app import app
from analyst_agent.api.routes import analysis
from analyst_agent.pii import redact_sample_rows, redact_text

client = TestClient(app)


def test_redact_email() -> None:
    text = "Contact user at john.doe@example.com for details."
    redacted = redact_text(text)
    assert "john.doe@example.com" not in redacted
    assert "[EMAIL_REDACTED]" in redacted


def test_redact_phone() -> None:
    text = "Call 0912345678 or +84987654321 now."
    redacted = redact_text(text)
    assert "0912345678" not in redacted
    assert "[PHONE_REDACTED]" in redacted


def test_redact_credit_card() -> None:
    text = "Payment card 4111-2222-3333-4444 charged."
    redacted = redact_text(text)
    assert "4111-2222-3333-4444" not in redacted
    assert "[CARD_REDACTED]" in redacted


def test_redact_ip_and_ssn() -> None:
    text = "Host 192.168.1.100 SSN 123-45-6789"
    redacted = redact_text(text)
    assert "192.168.1.100" not in redacted
    assert "123-45-6789" not in redacted
    assert "[IP_REDACTED]" in redacted
    assert "[SSN_REDACTED]" in redacted


def test_redact_sample_rows_preserves_numeric_metrics() -> None:
    raw = [
        {
            "customer": "Alice (alice@test.com)",
            "phone": "0988888888",
            "revenue": 50000.0,
            "units": 10,
        },
        {"customer": "Bob", "phone": "0911111111", "revenue": 25000.0, "units": 5},
    ]
    redacted = redact_sample_rows(raw)
    assert len(redacted) == 2
    assert "alice@test.com" not in redacted[0]["customer"]
    assert "[EMAIL_REDACTED]" in redacted[0]["customer"]
    assert "[PHONE_REDACTED]" in redacted[0]["phone"]
    assert redacted[0]["revenue"] == 50000.0
    assert redacted[0]["units"] == 10


def test_api_health_endpoint() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ai-data-analyst-agent"}


def test_api_get_samples() -> None:
    response = client.get("/api/datasets/samples")
    assert response.status_code == 200
    samples = response.json()
    assert len(samples) >= 3
    assert any(s["id"] == "superstore" for s in samples)


def test_api_start_analysis_validation_failures() -> None:
    # Empty question
    res_empty = client.post("/api/analysis/start", data={"question": ""})
    assert res_empty.status_code in (400, 422)

    # No dataset or file
    res_no_data = client.post("/api/analysis/start", data={"question": "Analyze"})
    assert res_no_data.status_code in (400, 422)

    # Invalid non-csv file
    files = {"file": ("test.txt", b"not a csv", "text/plain")}
    res_bad_file = client.post("/api/analysis/start", data={"question": "Analyze"}, files=files)
    assert res_bad_file.status_code in (400, 422)


def test_api_start_and_get_result(monkeypatch) -> None:
    # Mock background runner to avoid waiting on real LLM in fast unit test
    async def _mock_run(job_id: str, thread_id: str, question: str, dataset_path: str) -> None:
        analysis._jobs[job_id]["status"] = "completed"
        analysis._jobs[job_id]["final_answer"] = "Test analysis completed"

    monkeypatch.setattr(analysis, "_run_agent_pipeline", _mock_run)

    response = client.post(
        "/api/analysis/start",
        data={"question": "Analyze superstore sales", "dataset_name": "superstore"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    job_id = data["job_id"]

    # Check result endpoint
    res_result = client.get(f"/api/analysis/{job_id}/result")
    assert res_result.status_code == 200
    result_data = res_result.json()
    assert result_data["job_id"] == job_id


def test_api_cancel_endpoint() -> None:
    job_id = "test_job_cancel"
    analysis._jobs[job_id] = {
        "job_id": job_id,
        "thread_id": "thread_cancel",
        "question": "test",
        "dataset_path": "data/sample_sales.csv",
        "status": "running",
    }
    response = client.post(f"/api/analysis/{job_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert analysis._jobs[job_id]["status"] == "failed"
