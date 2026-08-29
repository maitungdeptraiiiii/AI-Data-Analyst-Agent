<div align="center">

# 🧠 AI Data Analyst Agent

**Multi-Agent Data Analytics Platform powered by LangGraph, Redis Streams & Deterministic Grounding Verification**

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-Orchestration-1C3C3C?logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Production_API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL 16](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://postgresql.org)
[![Redis Streams](https://img.shields.io/badge/Redis-Streams_Bus-DC382D?logo=redis&logoColor=white)](https://redis.io)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docker.com)
[![Tests](https://img.shields.io/badge/Tests-116%20passed-brightgreen?logo=pytest&logoColor=white)](#-testing)

*An end-to-end AI agent that takes a natural-language question about a CSV dataset and produces a fully verified analytical report — with SQL/Python evidence, automated chart generation, root cause analysis, and actionable recommendations.*

</div>

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [System Architecture](#-system-architecture)
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
- [Multi-Agent Communication](#-multi-agent-communication)
- [Testing](#-testing)
- [Security & PII Protection](#-security--pii-protection)
- [Observability & Cost Tracking](#-observability--cost-tracking)
- [Long-Term Memory](#-long-term-memory)
- [Design Decisions](#-design-decisions)
- [Limitations & Future Work](#-limitations--future-work)
- [License](#-license)

---

## 🎯 Overview

**AI Data Analyst Agent** is a production-grade, multi-agent system built with LangGraph that transforms natural-language questions into fully verified analytical reports. The system implements a 3-tier agent architecture communicating over Redis Streams, with deterministic grounding verification ensuring zero hallucination in the final output.

### Example

> **Input:** *"Phân tích file sales.csv, tìm nguyên nhân doanh thu tháng 7 giảm, tạo biểu đồ và đề xuất hướng cải thiện."*
>
> **Output:** A structured report with:
> - Revenue trend analysis backed by SQL query evidence
> - Root cause identification with cited step IDs
> - Auto-generated Matplotlib charts
> - Actionable recommendations
> - Confidence level (high/medium/low)
> - Every numeric claim verified against raw query metrics (±1% tolerance)

The agent doesn't guess — it **plans**, **executes** structured queries, **critiques** evidence completeness, **verifies** every claim against raw data, and only then produces a grounded report.

---

## ✨ Key Features

### 🏗️ Multi-Agent Architecture (3-Tier)

| Tier | Agent | Responsibility |
|------|-------|---------------|
| **Tier 1** | Orchestrator (LangGraph StateGraph) | Pipeline control, routing, checkpointing |
| **Tier 2** | Executor Agent (subgraph-as-node) | Per-step execution with local retry & error classification |
| **Tier 3** | Tool Agents (SQL/Python workers) | Isolated code execution via Redis Streams |

### 🔍 Deterministic Grounding Verification
- Every finding and root cause must cite a specific analysis step ID
- Numeric claims verified against actual query metrics with 1% tolerance
- Invalid claims auto-removed — **zero hallucination guarantee in final report**
- Two retry rounds before fallback sanitization

### 🧪 Comprehensive Evaluation Harness
- **30 golden test cases** across 9 analytical categories
- Property-based checkers: citation validity, numeric accuracy, policy compliance
- Baseline regression detection with automated HTML reports
- Mock mode for CI/CD pipeline integration

### 🖥️ Production Web UI
- Dark mode glassmorphism design with real-time pipeline visualization
- Live SSE streaming showing each agent node's progress
- Drag-and-drop CSV upload or one-click sample datasets
- Human-in-the-loop modal for clarification questions
- Full audit log and node metrics display

### 🔒 Security First
- PII auto-redaction (email, phone, credit card, SSN, IP) before LLM context
- Read-only PostgreSQL role (`executor_ro`) for all query execution
- AST-level policy guard for generated Python (blocks `os`, `subprocess`, `eval`, etc.)
- Non-root Docker sandbox on internal-only network for Python execution

### 📊 Observability & Cost Tracking
- Per-node latency, token count, and estimated cost (USD)
- Model-specific pricing tables (OpenAI, Anthropic, Groq, Gemini)
- LangSmith integration ready (opt-in via environment variables)
- Trace ID propagation across Redis Streams boundaries

### 🧠 Long-Term Memory
- SQLite-backed memory store persisting past analysis summaries
- Automatic context injection into Planner for repeat dataset queries
- TTL-based cleanup for expired records

---

## 🏛️ System Architecture

```
                    ┌─────────────┐
                    │    User     │
                    │ (Web UI /   │
                    │  CLI)       │
                    └──────┬──────┘
                           │  question + CSV
                           ▼
                  ┌──────────────────┐
                  │  Planner Node    │◄──── Memory Context (past analyses)
                  │  (Structured     │
                  │   Output → Plan) │
                  └────────┬─────────┘
                           │
              ┌────────────┼─────────────┐
              ▼            ▼             ▼
      [need_clarify]   [ready]      [off_topic]
              │            │             │
              ▼            │             ▼
    ┌──────────────┐       │     ┌──────────────┐
    │ HITL: Ask    │       │     │ Direct       │
    │ User (with   │       │     │ Response     │
    │ interrupt)   │       │     └──────────────┘
    └──────┬───────┘       │
           └───────────────┤
                           ▼
                  ┌──────────────────┐
                  │ Data Inspector   │ ← CSV → PostgreSQL (COPY)
                  │ (Schema detect,  │ ← PII redaction on sample rows
                  │  type inference) │
                  └────────┬─────────┘
                           ▼
              ┌─────────────────────────────┐
              │ Executor Agent (subgraph)    │
              │                             │
              │  Tool Router → dispatch via │
              │  Redis Streams:             │
              │    tasks:sql  ↔ SQL Worker  │
              │    tasks:python ↔ Py Worker │
              │                             │
              │  Local retry (max 2) with   │
              │  structured error repair    │
              └────────────┬────────────────┘
                           ▼
              ┌──────────────────────┐     ┌──────────────┐
              │ Critic Node          │────►│ Replanner    │──┐
              │ (evidence complete?) │ no  │ (max 3 extra │  │
              └────────┬─────────────┘     │  goals)      │  │
                  yes  │                   └──────────────┘  │
                       ▼                         ▲          │
              ┌──────────────────────┐           │          │
              │ Chart Planner →      │           └──────────┘
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
              │ • Step ID existence  │
              └────────┬─────────────┘
              invalid  │  valid
          ┌────────────┴────────┐
          ▼                     ▼
  ┌──────────────┐     ┌──────────────────┐
  │ Retry /      │     │ Finalize Report  │ → Memory Store
  │ Sanitize     │     │ → Final Answer   │
  └──────────────┘     └──────────────────┘
```

---

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Orchestration** | LangGraph StateGraph + SQLite Checkpoints | Stateful multi-agent pipeline with interrupt/resume |
| **LLM Providers** | Groq (gpt-oss-20b/120b), OpenAI, Anthropic, Gemini | Multi-provider support with structured output |
| **Message Bus** | Redis 7 Streams with Consumer Groups | Cross-process tool agent communication |
| **Database** | PostgreSQL 16 | CSV ingestion (COPY), role-based access control |
| **Web API** | FastAPI + SSE Streaming | Real-time progress updates via Server-Sent Events |
| **Frontend** | Vanilla HTML/CSS/JS | Dark mode, glassmorphism, Inter + JetBrains Mono |
| **Charts** | Matplotlib | Deterministic rendering from structured specs (no LLM) |
| **Python Sandbox** | Docker (non-root, read-only, internal network) | Isolated code execution with AST policy guard |
| **Memory** | SQLite | Dataset-hash indexed, TTL-based cleanup |
| **Evaluation** | Property-based golden dataset harness | 30 test cases, 9 categories, baseline regression |
| **Testing** | pytest (116 unit tests), ruff, mypy strict | Full type safety and lint compliance |
| **Package Manager** | uv (with lockfile) | Reproducible dependency resolution |

---

## 📦 Prerequisites

| Requirement | Version | Purpose |
|-------------|---------|---------|
| Python | 3.11+ | Runtime |
| Docker + Docker Compose | Latest | PostgreSQL, Redis, Python sandbox |
| uv | Latest | Python package manager |
| LLM API Key | Any supported provider | Groq (recommended), OpenAI, Anthropic, or Gemini |

---

## 🚀 Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/AI-Data-Analyst-Agent.git
cd AI-Data-Analyst-Agent
```

### 2. Create Python Environment

```bash
# Using conda (recommended)
conda create -n data_analyst_agent python=3.11 -y
conda activate data_analyst_agent

# Or using uv
uv venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
# Using pip (editable mode)
pip install -e ".[dev]"

# Or using uv
uv sync
```

### 4. Start Infrastructure Services

```bash
docker compose up -d
```

This starts:
- **PostgreSQL 16** on port `5433` (with `analyst_admin` user, `analyst` database)
- **Redis 7** on port `6379`

Verify services are healthy:

```bash
docker compose ps
# Both should show "healthy" status
```

### 5. Initialize Database Roles

The database roles are auto-created via `init/01-roles.sql` on first launch:
- `ingest_rw` — read-write role for CSV ingestion
- `executor_ro` — read-only role for query execution (security boundary)

### 6. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys (see Configuration section)
```

---

## ⚙️ Configuration

### Required Environment Variables

```ini
# === LLM Provider (choose one) ===
LLM_PROVIDER=groq                # Options: groq, openai, anthropic, gemini
GROQ_API_KEY=gsk_your_key_here   # Required if LLM_PROVIDER=groq

# === Model Configuration ===
PLANNER_MODEL=openai/gpt-oss-20b     # Groq model for planning
EXECUTOR_MODEL=openai/gpt-oss-20b    # Groq model for SQL/Python generation
CRITIC_MODEL=openai/gpt-oss-20b      # Groq model for evidence review
REPORTER_MODEL=openai/gpt-oss-20b    # Groq model for report generation

# === Infrastructure ===
POSTGRES_INGEST_DSN=postgresql://ingest_rw:ingest_dev_password@localhost:5433/analyst
POSTGRES_EXECUTOR_DSN=postgresql://executor_ro:executor_dev_password@localhost:5433/analyst
REDIS_URL=redis://localhost:6379/0

# === Optional ===
LLM_TIMEOUT_SECONDS=60
ARTIFACTS_DIR=artifacts
CHECKPOINT_DB_PATH=data/checkpoints.sqlite
```

### Alternative LLM Providers

```ini
# OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
PLANNER_MODEL=gpt-4.1-mini

# Anthropic
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
PLANNER_MODEL=claude-sonnet-4-20250514

# Google Gemini
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIza...
PLANNER_MODEL=gemini-2.5-flash
```

---

## 📖 Usage

### 1. Web UI (Recommended)

Start the two required processes:

```bash
# Terminal 1: Start the SQL Tool Worker
python -m analyst_agent.workers.tool_worker sql

# Terminal 2: Start the Web API server
python -m analyst_agent.api.cli --port 8002
```

Open **http://127.0.0.1:8002/** in your browser.

**Features:**
- Select a sample dataset or drag-and-drop your own CSV
- Type an analysis question in any language
- Watch the pipeline execute in real-time via SSE streaming
- View the verified report with charts, findings, and citations
- Resume interrupted analyses after providing clarification

### 2. Command Line Interface

```bash
# Start a new analysis
analyst-agent start data/sample_sales.csv "Analyze revenue trends by region"

# Resume after clarification
analyst-agent resume <thread-id> "I mean North and South regions only"
```

### 3. Evaluation Harness

```bash
# Run with mock LLM (fast, for CI/CD)
python -m eval.eval_runner --mock

# Run with live LLM (requires API key)
python -m eval.eval_runner

# View generated report
cat eval/results/report.html
```

The evaluation harness tests 30 golden cases across 9 categories:

| Category | Description | Test Cases |
|----------|-------------|-----------|
| `trend` | Time series and trend detection | 5 |
| `comparison` | Group comparisons and rankings | 4 |
| `root_cause` | Root cause analysis | 3 |
| `outlier` | Anomaly and outlier detection | 3 |
| `correlation` | Variable correlation analysis | 3 |
| `breakdown` | Dimensional breakdown | 3 |
| `forecast` | Projections and forecasting | 3 |
| `edge_case` | Null handling, empty data, ambiguity | 3 |
| `policy` | Off-topic rejection, PII compliance | 3 |

---

## 📁 Project Structure

```
AI-Data-Analyst-Agent/
├── src/analyst_agent/           # Main source package
│   ├── api/                     # FastAPI application
│   │   ├── app.py               # FastAPI app factory with CORS
│   │   ├── cli.py               # uvicorn entry point
│   │   ├── models.py            # Pydantic request/response models
│   │   └── routes/
│   │       └── analysis.py      # /api/analysis/* endpoints + SSE streaming
│   │
│   ├── nodes/                   # LangGraph node implementations
│   │   ├── planner.py           # Intent classification + plan generation
│   │   ├── data_inspector.py    # CSV → PostgreSQL ingestion & schema detection
│   │   ├── executor_agent.py    # Step executor (subgraph-as-node)
│   │   ├── critic.py            # Evidence completeness reviewer
│   │   ├── replan.py            # Additional plan generation after critic retry
│   │   ├── chart_planner.py     # Chart spec generation (LLM-based)
│   │   ├── chart_creator.py     # Matplotlib rendering (deterministic)
│   │   ├── reporter.py          # Structured report generation with citations
│   │   ├── grounding_verifier.py# Deterministic grounding verification
│   │   ├── ask_user.py          # Human-in-the-loop interrupt
│   │   ├── tool_router.py       # Keyword-based SQL/Python routing
│   │   └── tool_agents/
│   │       ├── sql_agent.py     # SQL generation & repair subgraph
│   │       └── python_agent.py  # Python generation & repair subgraph
│   │
│   ├── memory/                  # Long-term memory system
│   │   ├── store.py             # SQLite-backed memory store with TTL
│   │   └── retriever.py         # Context retrieval for planner injection
│   │
│   ├── workers/
│   │   └── tool_worker.py       # Redis Streams consumer worker
│   │
│   ├── static/                  # Web UI (HTML/CSS/JS SPA)
│   │   ├── index.html           # Main page
│   │   ├── style.css            # Dark mode glassmorphism design
│   │   └── app.js               # SSE client + pipeline visualizer
│   │
│   ├── tools/
│   │   └── sql_tool.py          # Read-only SQL execution via psycopg
│   │
│   ├── config.py                # Pydantic Settings (multi-provider)
│   ├── graph.py                 # LangGraph StateGraph definition
│   ├── state.py                 # TypedDict state schemas (Agent, Executor, Tool)
│   ├── schemas.py               # Pydantic structured output schemas
│   ├── llm.py                   # Multi-provider LLM factory
│   ├── cli.py                   # CLI entry point
│   ├── streams.py               # Redis Streams publish/subscribe/reclaim
│   ├── database.py              # PostgreSQL connection + CSV ingestion
│   ├── sandbox.py               # Docker sandbox execution
│   ├── charts.py                # Matplotlib chart rendering
│   ├── grounding.py             # Deterministic grounding verification logic
│   ├── pii.py                   # PII regex redaction
│   ├── python_guard.py          # AST-level Python policy guard
│   ├── errors.py                # Structured error classification
│   ├── serialization.py         # Metric extraction from query results
│   ├── context.py               # Clarification history formatting
│   ├── checkpointing.py         # SQLite checkpointer factory
│   └── observability.py         # Token counting & cost estimation
│
├── eval/                        # Evaluation framework
│   ├── golden_dataset.json      # 30 golden test cases
│   ├── eval_runner.py           # Evaluation orchestrator
│   ├── eval_checks.py           # Property-based evaluation checkers
│   ├── eval_report.py           # HTML report generator
│   ├── datasets/                # Evaluation CSV datasets
│   ├── baselines/               # Baseline result snapshots
│   └── results/                 # Generated evaluation reports
│
├── tests/                       # Test suite (116 tests)
│   ├── test_phase1.py           # Config, Settings, LLM factory
│   ├── test_phase2.py           # Planner node
│   ├── test_phase3.py           # Data Inspector + SQL execution
│   ├── test_phase4.py           # Executor Agent + Tool routing
│   ├── test_phase5.py           # Critic node
│   ├── test_phase6.py           # Python sandbox + security guard
│   ├── test_phase7.py           # Chart planning + rendering
│   ├── test_phase8.py           # Reporter + grounding verification
│   ├── test_phase8b.py          # Full graph integration
│   ├── test_phase9.py           # Observability + cost tracking
│   ├── test_phase10.py          # Evaluation harness + golden dataset
│   ├── test_phase11.py          # Web API + SSE + PII redaction
│   └── test_phase12.py          # Long-term memory store
│
├── init/
│   └── 01-roles.sql             # PostgreSQL role initialization
│
├── sandbox/
│   └── Dockerfile               # Python sandbox Docker image
│
├── data/                        # Runtime data (sample CSVs, SQLite DBs)
├── artifacts/                   # Generated charts and reports
├── docker-compose.yml           # PostgreSQL + Redis + sandbox
├── pyproject.toml               # Project metadata & dependencies
├── .env.example                 # Environment variable template
└── PROJECT_DESIGN.md            # Detailed design specification
```

---

## 🔬 Pipeline Deep Dive

### Phase 1: Planning
The **Planner Node** receives the user's question and dataset path, retrieves relevant past analyses from memory, and produces a structured plan using LLM structured output (`PlannerOutput` schema). The plan consists of ordered, plain-English analytical goals.

### Phase 2: Data Inspection
The **Data Inspector** ingests the CSV into PostgreSQL via `COPY` protocol, detects column types, counts nulls, and extracts sample rows (with PII redaction). This metadata becomes the dataset schema for all downstream nodes.

### Phase 3: Execution
The **Executor Agent** (a subgraph-as-node) processes each plan step:
1. **Tool Router** selects SQL or Python based on step keywords
2. **Dispatch** publishes a task to `tasks:{tool}` Redis Stream
3. **Tool Worker** (separate process) consumes the task, generates code via LLM, executes it, and publishes the result to `results:{correlation_id}`
4. **Retry** on failure with structured error classification (up to 2 retries per step)

### Phase 4: Critique
The **Critic Node** reviews all evidence and determines if it's sufficient to answer the original question. If insufficient, it requests up to 2 additional rounds of analysis via the **Replanner**.

### Phase 5: Visualization
The **Chart Planner** uses LLM to select the best chart type and columns from available evidence. The **Chart Creator** renders deterministic Matplotlib charts from the structured spec (no LLM involvement in rendering).

### Phase 6: Reporting
The **Reporter Node** generates a structured `FinalReport` with:
- Summary, key findings (with citations), root causes (with citations)
- Numeric claims with step ID references
- Recommendations, confidence level, limitations

### Phase 7: Grounding Verification
The **Grounding Verifier** (pure Python, no LLM) validates every claim:
- All citation step IDs must reference successful analysis steps
- No duplicate citations
- Numeric claims must match actual query metrics within ±1% tolerance
- Invalid claims are removed; the reporter retries or sanitizes

---

## 🔗 Multi-Agent Communication

| Boundary | Transport | Latency | Isolation |
|----------|-----------|---------|-----------|
| Orchestrator ↔ Executor Agent | In-process (subgraph-as-node) | ~0ms | Shared checkpoints |
| Executor Agent ↔ Tool Agent | **Redis Streams** | ~5ms | Full process isolation |
| Tool Agent ↔ PostgreSQL | TCP (psycopg) | ~1ms | Read-only DB role |
| Python Sandbox ↔ Network | Docker internal network | N/A | No public internet |

### Redis Streams Protocol

```
Executor Agent                     Tool Worker
     │                                  │
     │── XADD tasks:sql ──────────────► │  (publish task)
     │                                  │
     │                                  │── Execute SQL
     │                                  │── XADD results:{id}
     │                                  │
     │◄── XREAD results:{id} ──────────│  (await result)
     │                                  │
     │── XACK tasks:sql ──────────────► │  (acknowledge)
```

Features:
- **Consumer Groups** for horizontal scaling of workers
- **Visibility Timeout** (30s) for stuck task reclamation via `XAUTOCLAIM`
- **Correlation ID** namespaced by `run_id` to prevent cross-run collisions

---

## 🧪 Testing

### Running Tests

```bash
# Run all unit tests (116 tests)
pytest tests/ -m "not integration and not sandbox_integration"

# Run with verbose output
pytest tests/ -v -m "not integration and not sandbox_integration"

# Run a specific phase
pytest tests/test_phase8.py -v

# Lint check
ruff check src tests eval

# Type check (strict mode)
mypy src
```

### Test Coverage by Phase

| Phase | File | Tests | Covers |
|-------|------|-------|--------|
| 1 | `test_phase1.py` | 19 | Config, Settings, LLM factory, Groq provider |
| 2 | `test_phase2.py` | 5 | Planner node, structured output, routing |
| 3 | `test_phase3.py` | 5 | Data Inspector, CSV ingestion, SQL execution |
| 4 | `test_phase4.py` | 12 | Executor Agent, tool routing, Redis Streams |
| 5 | `test_phase5.py` | 3 | Critic node, verdict routing |
| 6 | `test_phase6.py` | 9 | Python sandbox, AST policy guard |
| 7 | `test_phase7.py` | 10 | Chart planner, Matplotlib renderer |
| 8 | `test_phase8.py` | 12 | Reporter, grounding verifier, sanitization |
| 8b | `test_phase8b.py` | 11 | Full graph integration, interrupt/resume |
| 9 | `test_phase9.py` | 8 | Observability, token counting, cost estimation |
| 10 | `test_phase10.py` | 7 | Evaluation harness, golden dataset, reports |
| 11 | `test_phase11.py` | 10 | Web API, SSE streaming, PII redaction, CORS |
| 12 | `test_phase12.py` | 5 | Memory store, retriever, TTL cleanup |
| **Total** | | **116** | |

### Quality Assurance

- **ruff** — Linting with rules: E, F, I, UP, B (100% clean)
- **mypy strict** — Full type checking across 48 source files (0 errors)
- **ruff format** — Consistent code formatting

---

## 🔒 Security & PII Protection

### Data Protection Layers

| Layer | Mechanism | Scope |
|-------|-----------|-------|
| **PII Redaction** | Regex patterns for email, phone, credit card, SSN, IP | Applied before any data reaches LLM context |
| **SQL Isolation** | `executor_ro` PostgreSQL role (read-only) | Prevents INSERT, UPDATE, DELETE, DROP |
| **Python Guard** | AST-level import/call blocking | Blocks `os`, `subprocess`, `eval`, `exec`, `open`, etc. |
| **Docker Sandbox** | Non-root, read-only filesystem, internal network | No public internet, no host filesystem access |
| **Input Validation** | Pydantic models, file extension checks | Only `.csv` files accepted via upload |
| **Path Traversal** | `os.path.basename()` + boundary checks | Prevents directory traversal in uploads/charts |

### PII Patterns Redacted

| Type | Example Input | Redacted Output |
|------|---------------|-----------------|
| Email | `user@example.com` | `[EMAIL_REDACTED]` |
| Phone | `+1-555-123-4567` | `[PHONE_REDACTED]` |
| Credit Card | `4111-1111-1111-1111` | `[CREDIT_CARD_REDACTED]` |
| SSN | `123-45-6789` | `[SSN_REDACTED]` |
| IP Address | `192.168.1.1` | `[IP_REDACTED]` |

---

## 📊 Observability & Cost Tracking

### Per-Node Metrics

Every LangGraph node emits:
- **`duration_ms`** — Execution latency
- **`tokens_in` / `tokens_out`** — Token consumption
- **`estimated_cost_usd`** — Cost based on model-specific pricing
- **`model`** — Which LLM model was used
- **`timestamp`** — Unix timestamp

### Supported Pricing Models

| Provider | Models |
|----------|--------|
| **Groq** | `openai/gpt-oss-20b`, `openai/gpt-oss-120b` |
| **OpenAI** | `gpt-4.1-mini`, `gpt-4.1`, `gpt-4o`, `gpt-4o-mini` |
| **Anthropic** | `claude-sonnet-4-*`, `claude-haiku-3-*` |
| **Gemini** | `gemini-2.5-flash`, `gemini-2.5-pro` |

---

## 🧠 Long-Term Memory

The memory system stores past analysis summaries keyed by dataset content hash:

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  Planner Node    │────►│ Memory Retriever │────►│  SQLite Store    │
│  (receives past  │     │ (lookup by       │     │  data/memory.db  │
│   context)       │     │  dataset hash)   │     │                  │
└──────────────────┘     └──────────────────┘     └──────────────────┘
         ▲                                                │
         │                                                │
         └── Memory context injected ─────────────────────┘
```

- **Storage:** SQLite with `dataset_hash`, `question`, `summary`, `created_at`, `expires_at`
- **Retrieval:** Top-5 most recent analyses for the same dataset
- **Cleanup:** TTL-based expiration (configurable, default 30 days)

---

## 💡 Design Decisions

### Why LangGraph over raw LangChain?
LangGraph provides first-class support for stateful, multi-step agent workflows with:
- Built-in checkpointing for interrupt/resume (human-in-the-loop)
- Conditional routing between nodes
- Subgraph-as-node composition for the Executor Agent

### Why Redis Streams instead of direct function calls?
- **Crash isolation:** A failing Tool Agent worker doesn't crash the Orchestrator
- **Horizontal scaling:** Multiple workers can consume from the same stream
- **Visibility timeout:** Stuck tasks are automatically reclaimed by other workers
- **Observability:** Every task is a Redis entry with full audit trail

### Why deterministic grounding instead of LLM self-check?
- LLMs can't reliably detect their own hallucinations
- A pure-code verifier provides **guaranteed** correctness for citation and numeric claims
- The system falls back to sanitization (removing ungrounded claims) if the Reporter can't fix violations after 2 retries

### Why `json_schema` structured output for Groq?
Groq's hosted models (especially `openai/gpt-oss-*`) intermittently fail with `function_calling` mode ("Tool choice is required, but model did not call a tool"). The `json_schema` method is 100% reliable across all Groq models.

---

## 🚧 Limitations & Future Work

### Current Limitations
- **Single CSV:** Currently processes one CSV file per analysis session
- **SQL-first:** Complex statistical analyses default to Python sandbox but chart capabilities are limited to bar/line/scatter
- **No streaming LLM output:** The Reporter generates the full report at once rather than streaming tokens
- **English plan steps:** Plan steps are always in English (for tool routing), though the final report matches the user's language

### Future Work
- [ ] Multi-table JOIN support for relational datasets
- [ ] LLM-as-Judge evaluation (GPT-4 reviewing report quality)
- [ ] RAGAS/DeepEval integration for standard RAG benchmarks
- [ ] Streaming LLM output in the Web UI
- [ ] Multi-user session management with authentication
- [ ] Kubernetes deployment with auto-scaling workers
- [ ] Support for Excel, Parquet, and JSON data sources

---

## 📄 License

This project is developed for academic and research purposes.

---

<div align="center">

**Built with ❤️ using LangGraph, FastAPI, PostgreSQL, and Redis**

</div>
