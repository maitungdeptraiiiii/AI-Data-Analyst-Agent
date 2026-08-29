<div align="center">

# 🧠 AI Data Analyst Agent

**Multi-Agent Data Analytics Platform — LangGraph × Redis Streams × Deterministic Grounding**

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-Orchestration-1C3C3C?logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Production_API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://postgresql.org)
[![Redis](https://img.shields.io/badge/Redis-Streams_Bus-DC382D?logo=redis&logoColor=white)](https://redis.io)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docker.com)

*Production-ready AI agent that analyzes datasets, generates verified reports with deterministic grounding, and visualizes insights — all through a beautiful web interface.*

</div>

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [Architecture](#-architecture)
- [Tech Stack](#-tech-stack)
- [Prerequisites](#-prerequisites)
- [Installation & Setup](#-installation--setup)
- [Configuration](#-configuration)
- [Usage](#-usage)
  - [Web UI (Recommended)](#1-web-ui-recommended)
  - [Command Line Interface](#2-command-line-interface)
  - [Evaluation Harness](#3-evaluation-harness)
- [Project Structure](#-project-structure)
- [Pipeline Deep Dive](#-pipeline-deep-dive)
- [Testing](#-testing)
- [Security & PII](#-security--pii)
- [Observability](#-observability)
- [Design Decisions](#-design-decisions)
- [Roadmap](#-roadmap)
- [License](#-license)

---

## 🎯 Overview

**AI Data Analyst Agent** is a production-grade multi-agent system that takes a natural-language question about a CSV dataset and produces a verified analytical report — complete with SQL evidence, auto-generated charts, root cause analysis, and actionable recommendations.

**Example prompt:**
> *"Phân tích file sales.csv, tìm nguyên nhân doanh thu tháng 7 giảm, tạo biểu đồ và đề xuất hướng cải thiện."*

The agent doesn't guess — it **plans**, **executes** structured queries, **verifies** every claim against the raw evidence, and only then produces a grounded report. If a claim can't be traced back to a real query result, the deterministic verifier removes it automatically.

---

## ✨ Key Features

### 🏗️ Multi-Agent Architecture (3-Tier)
- **Orchestrator**: LangGraph StateGraph controlling the full analysis pipeline
- **Executor Agent**: Per-step execution with local retry, error classification, and tool routing
- **Tool Agents**: Isolated SQL/Python workers communicating over Redis Streams

### 🔍 Deterministic Grounding Verification
- Every finding and root cause must cite a specific analysis step ID
- Numeric claims are compared against actual query metrics (1% tolerance)
- Invalid claims are automatically removed — **zero hallucination in the final report**

### 🧪 Evaluation Harness
- **30 golden test cases** across 9 categories (trend, root cause, outlier, edge case, etc.)
- Property-based checkers: citations, numeric matches, policy compliance
- Baseline regression detection with automated reports

### 🖥️ Production Web UI
- Dark mode glassmorphism design with real-time pipeline visualization
- Live SSE streaming showing each agent's progress as it happens
- Drag-and-drop CSV upload or one-click sample datasets
- Human-in-the-loop modal for clarification questions

### 🔒 Security First
- PII auto-redaction (email, phone, credit card, SSN, IP) before LLM context
- Read-only PostgreSQL role for all query execution
- AST-level policy guard for generated Python code
- Non-root Docker sandbox on internal-only network for Python execution

### 📊 Observability & Cost Tracking
- Per-node latency, token count, and cost estimation
- LangSmith integration ready (opt-in)
- Trace ID propagation across Redis Streams boundaries

### 🧠 Long-Term Memory
- SQLite-backed memory store persisting past analysis results
- Automatic context injection into Planner for repeat dataset analysis
- TTL-based cleanup for expired records

---

## 🏛️ Architecture

```
                    ┌─────────────┐
                    │    User     │
                    └──────┬──────┘
                           │  question + CSV
                           ▼
                  ┌──────────────────┐
                  │  Planner Node    │◄──── Memory Context (past analyses)
                  └────────┬─────────┘
                           │
              ┌────────────┼─────────────┐
              ▼            ▼             ▼
      [need_clarify]   [ready]      [off_topic]
              │            │             │
              ▼            │             ▼
    ┌──────────────┐       │     ┌──────────────┐
    │ HITL: Ask    │       │     │ Direct Answer │
    │ User         │       │     └──────────────┘
    └──────┬───────┘       │
           └───────────────┤
                           ▼
                  ┌──────────────────┐
                  │ Data Inspector   │ ← PII redaction on sample rows
                  │ (CSV → PostgreSQL│
                  │  via COPY)       │
                  └────────┬─────────┘
                           ▼
              ┌─────────────────────────────┐
              │ Executor Agent (subgraph)    │
              │                             │
              │  Tool Router → dispatch via │
              │  Redis Streams:             │
              │    tasks:sql ↔ SQL Worker   │
              │    tasks:python ↔ Py Worker │
              │                             │
              │  Local retry (max 2) with   │
              │  structured error repair    │
              └────────────┬────────────────┘
                           ▼
              ┌──────────────────────┐     ┌──────────────┐
              │ Critic Node          │────►│ Replanner    │──┐
              │ (evidence complete?) │ no  │ (max 3 extra │  │
              └────────┬─────────────┘     │  SQL goals)  │  │
                  yes  │                   └──────────────┘  │
                       ▼                          ▲          │
              ┌──────────────────────┐            │          │
              │ Chart Planner →      │            └──────────┘
              │ Chart Creator        │
              │ (Matplotlib, no LLM) │
              └────────┬─────────────┘
                       ▼
              ┌──────────────────────┐
              │ Reporter Node        │ ← Structured FinalReport with citations
              └────────┬─────────────┘
                       ▼
              ┌──────────────────────┐
              │ Grounding Verifier   │ ← Deterministic (pure code, no LLM)
              │ • Citation validity  │
              │ • Numeric accuracy   │
              └────────┬─────────────┘
              invalid  │  valid
          ┌────────────┴────────┐
          ▼                     ▼
  ┌──────────────┐     ┌──────────────────┐
  │ Retry /      │     │ Finalize Report  │ → Memory Store (save for future)
  │ Sanitize     │     │ → Final Answer   │
  └──────────────┘     └──────────────────┘
```

### Communication Boundaries

| Boundary | Transport | Reason |
|----------|-----------|--------|
| Orchestrator ↔ Executor Agent | In-process (subgraph-as-node) | Low latency, shared checkpoints |
| Executor Agent ↔ Tool Agent | **Redis Streams** | Independent scaling, crash isolation |
| Tool Agent ↔ PostgreSQL | `executor_ro` role | Read-only enforcement at DB level |
| Python Sandbox ↔ Network | Docker internal network only | No public internet access |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Orchestration** | LangGraph StateGraph with SQLite checkpoints |
| **LLM Providers** | OpenAI (GPT-4.1, GPT-4.1-mini, GPT-4o) / Anthropic (Claude Sonnet, Haiku) |
| **Message Bus** | Redis Streams with consumer groups & visibility timeout |
| **Database** | PostgreSQL 16 (CSV ingestion via COPY, role-based access control) |
| **Web API** | FastAPI with Server-Sent Events (SSE) streaming |
| **Frontend** | Vanilla HTML/CSS/JS — dark mode, glassmorphism, Inter + JetBrains Mono |
| **Charts** | Matplotlib (deterministic rendering from structured specs — no LLM code) |
| **Python Sandbox** | Docker container (non-root, read-only, internal network, AST policy guard) |
| **Memory** | SQLite with dataset-hash indexing and TTL cleanup |
| **Eval** | Property-based golden dataset harness (30 test cases, 9 categories) |
| **Testing** | pytest (114 unit tests), ruff, mypy |
| **Package Manager** | uv (with lockfile) |

---

## 📦 Prerequisites

- **Python 3.11+**
- **Docker** with Docker Compose
- **uv** (recommended) or pip
- **conda** (optional, for environment isolation)
- An **OpenAI** or **Anthropic** API key

---

## 🚀 Installation & Setup

### 1. Clone the repository

```bash
git clone https://github.com/maitungdeptraiiiii/AI-Data-Analyst-Agent.git
cd AI-Data-Analyst-Agent
```

### 2. Create a Python environment

**Option A — Using conda (recommended):**
```bash
conda create -n data_analyst_agent python=3.11 -y
conda activate data_analyst_agent
pip install uv
```

**Option B — Using venv:**
```bash
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
pip install uv
```

### 3. Install dependencies

```bash
uv sync --dev
```

### 4. Start infrastructure services

```bash
docker compose up -d
```

This starts:
- **PostgreSQL 16** on port `5433` (with read-only `executor_ro` and read-write `ingest_rw` roles auto-created)
- **Redis 7** on port `6379`

### 5. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set your API key (see [Configuration](#-configuration) below).

### 6. (Optional) Build Python sandbox

Only needed if you want to run Python-routed analysis:

```bash
docker compose --profile sandbox-build build python-sandbox
```

---

## ⚙️ Configuration

### `.env` — Required Settings

```dotenv
# ===== LLM Provider (choose one) =====

# Option 1: OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-proj-your-key-here
PLANNER_MODEL=gpt-4.1-mini
EXECUTOR_MODEL=gpt-4.1-mini
CRITIC_MODEL=gpt-4.1-mini
REPORTER_MODEL=gpt-4.1-mini

# Option 2: Anthropic
# LLM_PROVIDER=anthropic
# ANTHROPIC_API_KEY=sk-ant-your-key-here
# PLANNER_MODEL=claude-sonnet-5
# EXECUTOR_MODEL=claude-sonnet-5
# CRITIC_MODEL=claude-sonnet-5
# REPORTER_MODEL=claude-sonnet-5
```

### `.env` — Infrastructure (defaults match `docker-compose.yml`)

```dotenv
POSTGRES_INGEST_DSN=postgresql://ingest_rw:ingest_dev_password@localhost:5433/analyst
POSTGRES_EXECUTOR_DSN=postgresql://executor_ro:executor_dev_password@localhost:5433/analyst
REDIS_URL=redis://localhost:6379/0
```

### `.env` — Optional Settings

```dotenv
# Observability
OBSERVABILITY_BACKEND=local          # "local" | "langsmith" | "none"
LANGSMITH_API_KEY=lsv2_pt_xxx        # Only needed if backend=langsmith
LANGSMITH_PROJECT=ai-data-analyst-agent

# Timeouts & Limits
LLM_TIMEOUT_SECONDS=60
TOOL_AGENT_WAIT_TIMEOUT_SECONDS=30
TOOL_AGENT_VISIBILITY_TIMEOUT_MS=30000

# Sandbox
PYTHON_SANDBOX_IMAGE=analyst-python-sandbox:phase6
PYTHON_SANDBOX_TIMEOUT_SECONDS=15
PYTHON_SANDBOX_MEMORY=512m
PYTHON_MAX_DATASET_ROWS=100000
```

> ⚠️ **Note**: Only the selected provider's API key is required. Do not commit `.env` to Git.

> 💡 **Model recommendation**: Fast, non-reasoning models (e.g. `gpt-4.1-mini`, `claude-sonnet-5`) are ideal for this workload. Reasoning-heavy models like `gpt-5` may cause timeouts due to long processing times on structured output prompts.

---

## 🎮 Usage

### 1. Web UI (Recommended)

Start the Tool Worker and Web Server in separate terminals:

```bash
# Terminal 1 — Start the SQL Tool Worker
python -m analyst_agent.workers.tool_worker sql

# Terminal 2 — Start the Web API & UI
python -m analyst_agent.api.cli --port 8002
```

Open your browser at: **http://127.0.0.1:8002/**

**Web UI Features:**
- 📁 Drag-and-drop CSV upload or select from sample datasets
- 💬 Type your analysis question in natural language
- ⚡ Watch the pipeline execute in real-time with animated node progress
- 📊 View auto-generated charts and verified reports
- 🔄 Respond to clarification questions via interactive modal
- ⏱️ Live timer, token counter, and cost estimator

### 2. Command Line Interface

```bash
# Start analysis
python -m analyst_agent.cli start data/sample_sales.csv \
  "Phân tích nguyên nhân doanh thu tháng 7 giảm"

# If the agent pauses for clarification, resume with:
python -m analyst_agent.cli resume THREAD_ID "Năm 2026"
```

> **Important**: The SQL Tool Worker must be running in a separate terminal for CLI usage as well.

### 3. Evaluation Harness

Run the 30-case golden dataset evaluation:

```bash
# Mock mode (fast validation, no LLM calls)
python -m eval.eval_runner --mock

# Full evaluation (requires LLM API key)
python -m eval.eval_runner
```

**Evaluation output:**
```
Evaluation Complete! Total: 30, Passed: 28, Pass Rate: 93.33%
```

Results are saved to `eval/results/` with detailed per-case breakdown and baseline regression comparison.

---

## 📁 Project Structure

```
AI-Data-Analyst-Agent/
│
├── src/analyst_agent/                 # Main application package
│   ├── config.py                      # Pydantic Settings (.env loading)
│   ├── graph.py                       # LangGraph StateGraph orchestration
│   ├── state.py                       # State schemas (AgentState, ToolTaskData, etc.)
│   ├── schemas.py                     # Pydantic models (PlannerOutput, FinalReport, etc.)
│   ├── llm.py                         # LLM factory (OpenAI/Anthropic, model tiering)
│   ├── database.py                    # CSV → PostgreSQL ingestion via COPY
│   ├── grounding.py                   # Deterministic grounding verification
│   ├── observability.py               # Token tracking, cost estimation, tracing
│   ├── pii.py                         # PII detection & redaction engine
│   ├── charts.py                      # Matplotlib chart rendering
│   ├── checkpointing.py              # SQLite checkpoint configuration
│   ├── cli.py                         # CLI entry point (start/resume)
│   ├── context.py                     # Clarification history formatting
│   ├── errors.py                      # Error classification & retry logic
│   ├── python_guard.py                # AST policy guard for generated Python
│   ├── sandbox.py                     # Docker sandbox execution
│   ├── serialization.py               # JSON-safe serialization utilities
│   ├── streams.py                     # Redis Streams producer/consumer
│   │
│   ├── nodes/                         # Pipeline nodes
│   │   ├── planner.py                 # Plan generation (structured output)
│   │   ├── data_inspector.py          # Schema discovery + sample rows
│   │   ├── executor_agent.py          # Per-step execution subgraph
│   │   ├── tool_router.py             # SQL vs Python routing logic
│   │   ├── critic.py                  # Evidence completeness checker
│   │   ├── replan.py                  # Additional SQL goals on evidence gaps
│   │   ├── chart_planner.py           # Chart specification generator
│   │   ├── chart_creator.py           # Matplotlib rendering (no LLM code)
│   │   ├── reporter.py               # Structured report with citations
│   │   ├── grounding_verifier.py      # Citation + numeric claim verification
│   │   ├── ask_user.py                # Human-in-the-loop interrupt
│   │   └── tool_agents/               # SQL & Python tool agent implementations
│   │
│   ├── tools/                         # Tool implementations (SQL executor, etc.)
│   ├── workers/                       # Redis Streams consumer workers
│   │
│   ├── api/                           # FastAPI web backend
│   │   ├── app.py                     # Application factory (CORS, lifespan)
│   │   ├── cli.py                     # Web server CLI entry point
│   │   ├── models.py                  # Pydantic request/response models
│   │   └── routes/
│   │       └── analysis.py            # Analysis CRUD + SSE streaming endpoints
│   │
│   ├── static/                        # Web UI frontend (SPA)
│   │   ├── index.html                 # HTML structure
│   │   ├── style.css                  # Dark mode, glassmorphism design system
│   │   └── app.js                     # JavaScript logic + EventSource SSE
│   │
│   └── memory/                        # Long-term memory store
│       ├── schemas.py                 # AnalysisRecord model
│       ├── store.py                   # SQLite CRUD + TTL cleanup
│       └── retriever.py              # Memory retrieval + prompt augmentation
│
├── eval/                              # Evaluation harness
│   ├── golden_dataset.json            # 30 test cases across 9 categories
│   ├── eval_checks.py                 # Property-based checkers
│   ├── eval_runner.py                 # Evaluation CLI & runner
│   ├── eval_report.py                 # Summary generation & baseline comparison
│   ├── baselines/                     # Baseline metrics for regression detection
│   └── datasets/                      # Sample datasets
│       ├── superstore_sales.csv       # Multi-category retail dataset (21 rows)
│       └── edge_case_nulls.csv        # Null/mixed-format edge cases
│
├── tests/                             # Unit test suites (114 tests)
│   ├── test_phase1.py                 # Config, state, LLM factory
│   ├── test_phase2.py                 # Database ingestion
│   ├── test_phase3.py                 # Planner structured output
│   ├── test_phase4.py                 # Executor, error classification, retry
│   ├── test_phase5.py                 # Critic & replanning
│   ├── test_phase6.py                 # Python sandbox & AST guard
│   ├── test_phase7.py                 # Reporter & chart pipeline
│   ├── test_phase8.py                 # Grounding verifier & HITL
│   ├── test_phase8b.py                # Redis Streams & tool workers
│   ├── test_phase9.py                 # Observability & cost tracking
│   ├── test_phase10.py                # Evaluation harness
│   ├── test_phase11.py                # PII redaction & FastAPI endpoints
│   └── test_phase12.py                # Long-term memory store
│
├── init/                              # Database initialization SQL
│   └── 01-roles.sql                   # PostgreSQL role creation
│
├── sandbox/                           # Docker sandbox build context
├── data/                              # Runtime data (checkpoints, memory DB)
│
├── docker-compose.yml                 # PostgreSQL + Redis + Python sandbox
├── pyproject.toml                     # Project metadata & dependencies
├── uv.lock                            # Deterministic dependency lockfile
├── .env.example                       # Environment template
└── PROJECT_DESIGN.md                  # Detailed architecture design document
```

---

## 🔬 Pipeline Deep Dive

### Phase 1 — Planner

The Planner classifies the user request as `ready`, `need_clarification`, or `off_topic`. When `ready`, it produces an ordered list of analytical goals in plain English (never referencing column names — it doesn't know the schema yet). The Planner also receives **memory context** from past analyses on the same dataset.

### Phase 2 — Data Inspector

Loads the CSV into PostgreSQL via `COPY`, discovers schema/dtypes/null distribution, and extracts PII-redacted sample rows. All sample data passes through the PII redaction engine before entering the LLM context.

### Phase 3 — Executor Agent

For each plan step, the Executor Agent:
1. **Routes** to SQL or Python based on keywords (default: SQL)
2. **Dispatches** the task over Redis Streams to an isolated Tool Worker
3. **Handles** errors with structured LLM repair (max 2 retries per step)
4. **Records** results as `AnalysisStep` with code, metrics, and success status

### Phase 4 — Critic & Replanner

The Critic checks whether collected evidence is sufficient to answer the original question. If gaps exist, a Replanner produces up to 3 additional SQL-only analysis goals. The Critic loop caps at 2 improvement rounds.

### Phase 5 — Chart Generation

A Chart Planner selects the most impactful analysis step and produces a structured chart specification. Deterministic Matplotlib code renders the chart — **no LLM-generated Python is executed** for visualization. Chart failure is non-fatal.

### Phase 6 — Reporter

Produces a structured `FinalReport` with:
- Summary narrative
- Key findings (each citing a step ID + metric)
- Root causes (each citing a step ID + metric)
- Recommendations
- Limitations & confidence level

### Phase 7 — Grounding Verifier

A **pure-code, deterministic** verifier (no LLM involved):
- Checks every cited `step_id` exists and was successful
- Compares every numeric claim against the actual metric value (1% tolerance)
- Invalid claims → correction round (max 2) or automatic removal
- Confidence is lowered if sanitization was required

### Phase 8 — Finalize & Memory

The verified report is formatted for output. The analysis record is saved to the Memory Store for future reference when the same dataset is analyzed again.

---

## 🧪 Testing

```bash
# Run all 114 unit tests (excludes integration tests)
pytest -m "not integration and not sandbox_integration"

# Run integration tests (requires PostgreSQL container)
pytest -m integration

# Run sandbox integration tests (requires built sandbox image + PostgreSQL)
pytest -m sandbox_integration

# Linter
ruff check src tests eval

# Type checker
mypy src
```

**Current test results:**
```
114 passed, 5 deselected in 3.45s
mypy: Success — no issues found in 48 source files
ruff: All checks passed
```

### Test Coverage by Phase

| Phase | Tests | Description |
|-------|-------|-------------|
| 1 | 17 | Config, state schemas, LLM factory |
| 2 | 5 | CSV ingestion, PostgreSQL COPY |
| 3 | 5 | Planner structured output |
| 4 | 12 | Executor, error classification, retry |
| 5 | 3 | Critic & replan logic |
| 6 | 9 | Python guard, sandbox, tool router |
| 7 | 10 | Reporter, charts, structured output |
| 8 | 12 | Grounding verifier, HITL |
| 8b | 11 | Redis Streams, consumer groups, workers |
| 9 | 8 | Observability, token tracking, cost |
| 10 | 7 | Eval harness, golden dataset, baselines |
| 11 | 10 | PII redaction, FastAPI endpoints |
| 12 | 5 | Memory store, retriever, integration |

---

## 🔐 Security & PII

### PII Redaction

The PII engine (`src/analyst_agent/pii.py`) automatically detects and masks:
- 📧 Email addresses → `[EMAIL_REDACTED]`
- 📱 Phone numbers (Vietnamese & international) → `[PHONE_REDACTED]`
- 💳 Credit card numbers → `[CARD_REDACTED]`
- 🆔 SSN / National ID → `[SSN_REDACTED]`
- 🌐 IP addresses → `[IP_REDACTED]`

Redaction happens **before** data enters the LLM context (during `inspect_dataset`).

### Database Security

- **`ingest_rw`**: Can only create and load temporary dataset tables
- **`executor_ro`**: Read-only transactions enforced by PostgreSQL. 10-second statement timeout.
- Roles are created during PostgreSQL initialization (`init/01-roles.sql`)

### Python Sandbox

- Non-root Docker container on an internal-only network
- AST policy guard blocks `import os`, `subprocess`, `eval`, `exec`, etc.
- Memory limit: 512MB, CPU limit: 1 core, timeout: 15 seconds
- Can access PostgreSQL via `executor_ro` but has no public internet route

---

## 📈 Observability

### Local Mode (Default)

Every node execution automatically tracks:
- **Duration** (milliseconds)
- **Token count** (input, output, total)
- **Estimated cost** (USD, based on model pricing matrix)

Metrics are stored in `node_metrics` within the agent state and displayed live in the Web UI.

### LangSmith Mode (Opt-in)

```dotenv
OBSERVABILITY_BACKEND=langsmith
LANGSMITH_API_KEY=lsv2_pt_xxx
LANGSMITH_PROJECT=ai-data-analyst-agent
```

Enables full trace visualization in the LangSmith dashboard with per-node latency breakdowns.

### Cost Estimation

Built-in pricing matrix (per 1M tokens):

| Model | Input | Output |
|-------|-------|--------|
| GPT-4.1 | $2.00 | $8.00 |
| GPT-4.1-mini | $0.40 | $1.60 |
| GPT-4o | $2.50 | $10.00 |
| Claude Sonnet 5 | $3.00 | $15.00 |
| Claude Haiku | $0.25 | $1.25 |

---

## 🎨 Design Decisions

1. **Deterministic Grounding over LLM Self-Eval**: The grounding verifier is pure Python code, not an LLM — it cannot be fooled or hallucinate. Claims that don't trace back to real query results are removed automatically.

2. **3-Tier Agent Hierarchy**: Orchestrator → Executor Agent → Tool Agent. Each tier has its own state schema and communicates via structured messages, not shared mutable state.

3. **Redis Streams for Tool Agents Only**: The Executor ↔ Tool Agent boundary is the only place where a hung/slow agent needs its own process. Everything else stays in-process for simplicity and checkpoint coherence.

4. **Structured Output Everywhere**: Planner, Critic, Reporter — all use Pydantic `with_structured_output()`. No regex parsing of LLM free text.

5. **Charts without LLM Code Execution**: The Chart Planner produces a structured spec; Matplotlib renders deterministically. No LLM-generated Python is executed for visualization.

6. **Memory is Opt-in Context, Not State**: Long-term memory enriches the Planner's prompt with past analysis summaries. It does not alter the current session's state — keeping runs reproducible.

---

## 🗺️ Roadmap

- [ ] Semantic similarity search for memory retrieval (vector embeddings)
- [ ] Multi-dataset JOIN analysis support
- [ ] Export reports as PDF / Markdown
- [ ] Role-based access control for multi-tenant deployment
- [ ] Kubernetes Helm chart for production scaling
- [ ] Real-time collaborative analysis sessions

---

## 📜 License

This project is built for educational and portfolio purposes. See the repository for license details.

---

<div align="center">

**Built with ❤️ using LangGraph, FastAPI, PostgreSQL, and Redis**

*[⬆ Back to Top](#-ai-data-analyst-agent)*

</div>
