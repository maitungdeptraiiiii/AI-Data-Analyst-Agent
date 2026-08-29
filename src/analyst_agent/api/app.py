from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from analyst_agent.api.routes.analysis import router as analysis_router
from analyst_agent.observability import setup_observability


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup
    setup_observability()
    yield
    # Shutdown


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI Data Analyst Agent API",
        description=(
            "Production API for multi-agent data analytics with LangGraph and Redis Streams"
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS configuration for frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:8002",
            "http://127.0.0.1:8002",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(analysis_router)

    @app.get("/api/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok", "service": "ai-data-analyst-agent"}

    # Mount static frontend directory if it exists
    frontend_dist = Path("src/analyst_agent/static")
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")

    return app


app = create_app()
