import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from langgraph.types import Command

from analyst_agent.api.models import (
    AnalysisResultResponse,
    DatasetSampleItem,
    ProgressEvent,
    ResumeAnalysisRequest,
    StartAnalysisResponse,
)
from analyst_agent.cli import initial_state, normalize_graph_result
from analyst_agent.config import get_settings
from analyst_agent.graph import get_runtime_graph
from analyst_agent.pii import redact_text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["analysis"])

# In-memory registry for jobs and SSE subscribers
_jobs: dict[str, dict[str, Any]] = {}
_subscribers: dict[str, list[asyncio.Queue[ProgressEvent]]] = {}
_UPLOAD_DIR = Path("data/uploads")


def _get_samples() -> list[DatasetSampleItem]:
    samples = [
        DatasetSampleItem(
            id="superstore",
            name="Superstore Sales 2026",
            path="eval/datasets/superstore_sales.csv",
            description="Multi-category retail sales & profit data across regions",
            rows=21,
            columns=[
                "date",
                "region",
                "category",
                "sub_category",
                "product_name",
                "sales",
                "profit",
                "quantity",
                "discount",
            ],
        ),
        DatasetSampleItem(
            id="sample_sales",
            name="Sample Regional Sales",
            path="data/sample_sales.csv",
            description="Quarterly revenue by product and region (North, South)",
            rows=9,
            columns=["date", "region", "product", "units", "unit_price", "revenue"],
        ),
        DatasetSampleItem(
            id="edge_case",
            name="Customer Orders with Nulls",
            path="eval/datasets/edge_case_nulls.csv",
            description="Dataset testing missing country, null amounts, and discount codes",
            rows=5,
            columns=["id", "customer_name", "country", "order_date", "amount", "discount_code"],
        ),
    ]
    return samples


async def _emit_event(job_id: str, event: ProgressEvent) -> None:
    if job_id in _subscribers:
        for q in _subscribers[job_id]:
            await q.put(event)


async def _run_agent_pipeline(
    job_id: str, thread_id: str, question: str, dataset_path: str
) -> None:
    job = _jobs[job_id]
    job["status"] = "running"

    await _emit_event(
        job_id,
        ProgressEvent(
            event="job_started",
            status="running",
            message=f"Starting analysis for: {question}",
            timestamp=time.time(),
        ),
    )

    loop = asyncio.get_running_loop()

    def _execute() -> dict[str, Any]:
        config = {"configurable": {"thread_id": thread_id}}
        runtime = get_runtime_graph()
        state = initial_state(question, dataset_path)
        # Use graph stream to capture intermediate events
        res = runtime.graph.invoke(state, config=config)
        return dict(res)

    try:
        raw_result = await loop.run_in_executor(None, _execute)
        normalized = normalize_graph_result(raw_result, thread_id)

        job["raw_result"] = raw_result
        if normalized["status"] == "interrupted":
            job["status"] = "interrupted"
            payload = normalized.get("interrupt_payload")
            clarification = payload.get("question") if isinstance(payload, dict) else str(payload)
            job["clarification_question"] = clarification
            await _emit_event(
                job_id,
                ProgressEvent(
                    event="clarification_needed",
                    status="interrupted",
                    message=f"Clarification required: {clarification}",
                    data={"clarification_question": clarification, "thread_id": thread_id},
                    timestamp=time.time(),
                ),
            )
        else:
            job["status"] = "completed"
            job["final_report"] = raw_result.get("final_report")
            job["final_answer"] = raw_result.get("final_answer")
            job["charts"] = raw_result.get("charts", [])
            job["analysis_log"] = raw_result.get("analysis_log", [])
            job["node_metrics"] = raw_result.get("node_metrics", [])

            await _emit_event(
                job_id,
                ProgressEvent(
                    event="completed",
                    status="completed",
                    message="Analysis pipeline completed successfully",
                    data={
                        "final_answer": raw_result.get("final_answer"),
                        "final_report": raw_result.get("final_report"),
                        "charts": raw_result.get("charts", []),
                    },
                    timestamp=time.time(),
                ),
            )
    except Exception as exc:
        logger.exception("Job %s execution failed: %s", job_id, exc)
        job["status"] = "failed"
        job["error"] = redact_text(str(exc))
        await _emit_event(
            job_id,
            ProgressEvent(
                event="error",
                status="failed",
                message=f"Analysis failed: {job['error']}",
                timestamp=time.time(),
            ),
        )


@router.get("/datasets/samples", response_model=list[DatasetSampleItem])
def get_sample_datasets() -> list[DatasetSampleItem]:
    """Retrieve available sample datasets for quick one-click analysis."""
    return _get_samples()


@router.post("/analysis/start", response_model=StartAnalysisResponse)
async def start_analysis_endpoint(
    question: str = Form(...),
    dataset_name: str | None = Form(None),
    file: UploadFile | None = File(None),  # noqa: B008
) -> StartAnalysisResponse:
    """Start an end-to-end data analysis workflow."""
    if not question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    target_path: Path | None = None

    if file and file.filename:
        # Validate filename and extension
        filename = os.path.basename(file.filename)
        if not filename.lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail="Only .csv files are supported.")

        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        unique_name = f"{uuid4().hex}_{filename}"
        target_path = (_UPLOAD_DIR / unique_name).resolve()

        # Enforce boundary check
        if _UPLOAD_DIR.resolve() not in target_path.parents:
            raise HTTPException(status_code=400, detail="Invalid target filepath.")

        with open(target_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    elif dataset_name:
        # Match sample
        matched = next(
            (s for s in _get_samples() if s.id == dataset_name or s.path == dataset_name), None
        )
        if matched and Path(matched.path).exists():
            target_path = Path(matched.path).resolve()
        elif Path(dataset_name).exists():
            target_path = Path(dataset_name).resolve()

    if not target_path or not target_path.exists():
        raise HTTPException(
            status_code=400,
            detail="Valid CSV file upload or valid dataset_name is required.",
        )

    job_id = uuid4().hex
    thread_id = str(uuid4())

    _jobs[job_id] = {
        "job_id": job_id,
        "thread_id": thread_id,
        "question": question,
        "dataset_path": str(target_path),
        "status": "queued",
        "created_at": time.time(),
        "final_report": None,
        "final_answer": None,
        "charts": [],
        "analysis_log": [],
        "node_metrics": [],
        "clarification_question": None,
        "error": None,
    }

    _subscribers[job_id] = []
    asyncio.create_task(_run_agent_pipeline(job_id, thread_id, question, str(target_path)))

    return StartAnalysisResponse(
        job_id=job_id,
        thread_id=thread_id,
        status="queued",
        message="Analysis job queued successfully",
    )


@router.get("/analysis/{job_id}/stream")
async def stream_analysis_progress(job_id: str) -> StreamingResponse:
    """Stream live Server-Sent Events (SSE) for pipeline execution progress."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Analysis job not found")

    queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()
    if job_id not in _subscribers:
        _subscribers[job_id] = []
    _subscribers[job_id].append(queue)

    async def _sse_generator() -> Any:
        try:
            # Yield initial state
            job = _jobs[job_id]
            status_data = json.dumps({"status": job["status"], "job_id": job_id})
            yield f"event: status\ndata: {status_data}\n\n"

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"event: {event.event}\ndata: {event.model_dump_json()}\n\n"
                    if event.event in ("completed", "error"):
                        break
                except TimeoutError:
                    yield ": ping\n\n"
        finally:
            if job_id in _subscribers and queue in _subscribers[job_id]:
                _subscribers[job_id].remove(queue)

    return StreamingResponse(_sse_generator(), media_type="text/event-stream")


@router.post("/analysis/{job_id}/resume", response_model=StartAnalysisResponse)
async def resume_analysis_endpoint(
    job_id: str,
    payload: ResumeAnalysisRequest,
) -> StartAnalysisResponse:
    """Resume an interrupted analysis after human-in-the-loop clarification."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = _jobs[job_id]
    if job["status"] != "interrupted":
        raise HTTPException(status_code=400, detail="Job is not in interrupted status")

    thread_id = job["thread_id"]
    answer = payload.answer.strip()
    if not answer:
        raise HTTPException(status_code=400, detail="Answer cannot be empty")

    job["status"] = "running"
    loop = asyncio.get_running_loop()

    async def _resume_worker() -> None:
        def _exec_resume() -> dict[str, Any]:
            config = {"configurable": {"thread_id": thread_id}}
            runtime = get_runtime_graph()
            res = runtime.graph.invoke(Command(resume=answer), config=config)
            return dict(res)

        try:
            raw = await loop.run_in_executor(None, _exec_resume)
            normalized = normalize_graph_result(raw, thread_id)
            if normalized["status"] == "interrupted":
                job["status"] = "interrupted"
                p = normalized.get("interrupt_payload")
                clarification = p.get("question") if isinstance(p, dict) else str(p)
                job["clarification_question"] = clarification
                await _emit_event(
                    job_id,
                    ProgressEvent(
                        event="clarification_needed",
                        status="interrupted",
                        message=f"Clarification required: {clarification}",
                        data={"clarification_question": clarification, "thread_id": thread_id},
                        timestamp=time.time(),
                    ),
                )
            else:
                job["status"] = "completed"
                job["final_report"] = raw.get("final_report")
                job["final_answer"] = raw.get("final_answer")
                job["charts"] = raw.get("charts", [])
                job["analysis_log"] = raw.get("analysis_log", [])
                job["node_metrics"] = raw.get("node_metrics", [])
                await _emit_event(
                    job_id,
                    ProgressEvent(
                        event="completed",
                        status="completed",
                        message="Analysis completed after clarification",
                        data={"final_answer": raw.get("final_answer")},
                        timestamp=time.time(),
                    ),
                )
        except Exception as exc:
            job["status"] = "failed"
            job["error"] = str(exc)
            await _emit_event(
                job_id,
                ProgressEvent(
                    event="error", status="failed", message=str(exc), timestamp=time.time()
                ),
            )

    asyncio.create_task(_resume_worker())

    return StartAnalysisResponse(
        job_id=job_id,
        thread_id=thread_id,
        status="running",
        message="Analysis resumed successfully",
    )


@router.get("/analysis/{job_id}/result", response_model=AnalysisResultResponse)
def get_analysis_result(job_id: str) -> AnalysisResultResponse:
    """Retrieve the full status and final result of an analysis job."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = _jobs[job_id]
    return AnalysisResultResponse(
        job_id=job["job_id"],
        thread_id=job["thread_id"],
        status=job["status"],
        question=job["question"],
        final_report=job.get("final_report"),
        final_answer=job.get("final_answer"),
        charts=job.get("charts", []),
        analysis_log=job.get("analysis_log", []),
        node_metrics=job.get("node_metrics", []),
        clarification_question=job.get("clarification_question"),
        error=job.get("error"),
    )


@router.get("/analysis/{job_id}/charts/{chart_filename}")
def serve_chart_image(job_id: str, chart_filename: str) -> FileResponse:
    """Safely serve generated chart PNG images."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    settings = get_settings()
    artifacts_dir = settings.artifacts_dir.resolve()
    chart_path = (artifacts_dir / os.path.basename(chart_filename)).resolve()

    if artifacts_dir not in chart_path.parents or not chart_path.is_file():
        raise HTTPException(status_code=404, detail="Chart image not found")

    return FileResponse(
        path=str(chart_path),
        media_type="image/png",
        headers={"Content-Disposition": f"inline; filename={chart_filename}"},
    )


@router.post("/analysis/{job_id}/cancel")
def cancel_analysis(job_id: str) -> dict[str, str]:
    """Cancel a running analysis."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = _jobs[job_id]
    if job["status"] in ("completed", "failed"):
        return {"status": job["status"], "message": "Job already terminated"}

    job["status"] = "failed"
    job["error"] = "Analysis was cancelled by user"
    return {"status": "cancelled", "message": "Analysis cancelled"}
