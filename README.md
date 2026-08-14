# AI Data Analyst Agent — Phase 6

Phase 6 implements this synchronous LangGraph workflow:

```text
Planner ⇄ Ask User → Data Inspector → Tool Router → SQL/Python Executor ⇄ Fix → Critic ⇄ Replanner → Chart → Reporter
```

The data inspector loads a CSV into PostgreSQL with `COPY`. The executor connects through a
different PostgreSQL role that is forced to read-only mode and has a 10-second statement timeout.
Questions that are off-topic, need clarification, or produce an empty plan skip ingestion and go
straight to a safe explanatory response.

## Requirements

- Python 3.11+
- Docker with Compose
- An Anthropic or OpenAI API key
- `uv` (recommended) or another Python package manager

## Setup

```powershell
Copy-Item .env.example .env
# Edit .env and select one provider/key (examples below)

docker compose up -d
uv sync --dev
```

Choose Anthropic:

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key
PLANNER_MODEL=claude-sonnet-5
EXECUTOR_MODEL=claude-sonnet-5
CRITIC_MODEL=claude-sonnet-5
REPORTER_MODEL=claude-sonnet-5
```

Or choose OpenAI:

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=your-key
PLANNER_MODEL=gpt-4.1-mini
EXECUTOR_MODEL=gpt-4.1-mini
CRITIC_MODEL=gpt-4.1-mini
REPORTER_MODEL=gpt-4.1-mini
```

Note: reasoning-heavy models (e.g. `gpt-5`) can take several minutes per call for structured
output on non-trivial prompts, and `httpx`'s read timeout resets on each keep-alive byte the
server sends — so a configured timeout may not bound wall-clock time the way you'd expect. Fast,
non-reasoning models are a better fit for this workload (mechanical planning/SQL generation).

Only the selected provider's key is required. Do not commit `.env`; it is ignored by Git.
`LLM_TIMEOUT_SECONDS` defaults to 60 seconds and applies to every provider call.

PostgreSQL initialization creates two application roles:

- `ingest_rw`: creates and loads temporary dataset tables.
- `executor_ro`: can only query those tables; PostgreSQL enforces read-only transactions.

The initialization scripts only run on a fresh PostgreSQL data volume. If the volume already
exists from an older schema, create the roles manually or intentionally recreate the development
volume.

## Run

```powershell
uv run analyst-agent start data/sample_sales.csv "Phân tích nguyên nhân doanh thu tháng 7 giảm"
```

If the graph pauses, it prints a thread ID and clarification question. Resume with:

```powershell
uv run analyst-agent resume THREAD_ID "Năm 2026"
```

A resume may produce another clarification interrupt. Continue using the same thread ID until the
analysis completes. Set `CHECKPOINT_DB_PATH` to change the SQLite checkpoint location.

The agent currently supports CSV input only. It executes one generated SQL query for each planner
step and caps every result set at 200 rows. Retryable PostgreSQL errors are classified primarily by
SQLSTATE, repaired with structured LLM output, and retried at most twice per analysis step. Policy
violations and infrastructure failures are finalized without agent-level retry.

After all planned SQL steps finish, a structured Critic checks evidence completeness. If evidence
is missing, a Replanner creates at most three additional read-only SQL analysis goals without
re-ingesting the dataset or discarding earlier evidence. SQL repair and Critic improvement use
separate retry budgets; the Critic loop stops after two improvement rounds and exposes a warning.

After the Critic passes, a Chart Planner may select one successful analysis step and produce a
structured chart specification. Deterministic Matplotlib code validates and renders that spec; no
LLM-generated Python is executed. Chart failure is non-fatal. Reporter returns both a structured
`FinalReport` and CLI text, while application code overrides chart paths, limitations, and maximum
confidence from real state.

When Planner cannot resolve genuine ambiguity, the graph pauses with a JSON clarification payload.
SQLite checkpoints persist state across CLI processes; resume uses the same thread ID and
`Command(resume=...)`. Clarification history is preserved as structured user-provided context and
propagated to every downstream LLM node. The loop is capped at three clarification rounds.

Tool Router defaults to read-only PostgreSQL and selects Python only for bounded datasets and
explicit statistical/advanced-analysis hints. Generated Python passes an AST policy guard and runs
in a non-root, read-only Docker sandbox on an internal-only network. The sandbox can read PostgreSQL
through `executor_ro` but has no public Internet route. SQL and Python share one execution retry
lifecycle, and every analysis step records tool, code, JSON-safe rows, and deterministic metrics.

Build the sandbox image before running Python-routed analysis:

```powershell
docker compose --profile sandbox-build build python-sandbox
```

## Verify

```powershell
uv run ruff check .
uv run mypy src
uv run pytest -m "not integration"
uv run pytest -m integration
```

The integration test requires the PostgreSQL container and `POSTGRES_EXECUTOR_DSN` in the process
environment. PII redaction is deliberately marked as a Phase 11 TODO; use only non-sensitive data
with this implementation.

## Phase 6 boundaries

Not implemented yet: verified citation grounding, Redis Streams, multi-agent workers, API service,
or observability. Human-in-the-loop currently covers clarification only.
