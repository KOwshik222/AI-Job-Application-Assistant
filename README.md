# AI Job Application Assistant

A full-stack LangGraph application for automated job search, RAG-based resume matching, and intelligent application tracking.

## Table of Contents
- [Architecture](#architecture)
- [Folder Structure](#folder-structure)
- [Technologies Used](#technologies-used)
- [Setup Instructions](#setup-instructions)
- [Environment Variables](#environment-variables)
- [Database Setup](#database-setup)
- [Running the Application](#running-the-application)
- [End-to-End Workflow](#end-to-end-workflow)
- [Known Limitations](#known-limitations)

## Architecture

The system uses a supervisor agent architecture communicating with tools via MCP (Model Context Protocol).

```text
Browser UI (HTML/JS)
      │
      ▼
FastAPI Backend
      │
      ▼
LangGraph Supervisor Agent
      ├── Job Search Agent ───(MCP)──▶ search_jobs tool
      ├── Resume Match Agent ──(RAG)──▶ ChromaDB (Vector Store) + OpenAI
      ├── Application Agent ──(MCP)──▶ apply_job tool (Playwright)
      └── Notification Agent ─(MCP)──▶ send_email tool (SMTP)
```

## Folder Structure

```text
c:\resume_app\
├── app/                  # FastAPI backend
│   ├── config.py         # Application configuration
│   ├── main.py           # FastAPI application entry point
│   ├── models/           # Pydantic & SQLAlchemy models
│   ├── routers/          # API endpoints
│   └── services/         # Core business logic
├── data/                 # Persistent storage (SQLite, ChromaDB)
├── mcp_server/           # MCP tool implementations
├── scripts/              # Utility scripts (e.g., sample resume gen)
├── static/               # Frontend assets (HTML, CSS, JS)
├── storage/              # Uploaded files (resumes)
├── tests/                # Pytest suite
├── .env.example          # Environment variable template
├── pytest.ini            # Pytest configuration
├── requirements.txt      # Python dependencies
└── run.py                # Application runner
```

## Technologies Used

- **Backend framework**: FastAPI, Uvicorn
- **AI/Agents**: LangGraph, LangChain, OpenAI
- **Vector Database**: ChromaDB
- **Automation/Tools**: Model Context Protocol (MCP), Playwright
- **Database**: SQLite, SQLAlchemy, Alembic (Async)
- **Frontend**: Vanilla HTML/JS/CSS

## Setup Instructions

1. **Clone the repository** and navigate to the project directory:
   ```bash
   cd C:\resume_app
   ```

2. **Create and activate a virtual environment** (recommended):
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Playwright setup** (for the application agent):
   ```bash
   playwright install chromium
   ```

## Environment Variables

Copy `.env.example` to `.env` in the root directory:
```bash
copy .env.example .env
```

**Required variables for full functionality:**

| Variable | Description | Default / Example |
|----------|-------------|-------------------|
| `OPENAI_API_KEY` | OpenAI key for embeddings & LLM | `sk-...` |
| `DATABASE_URL` | SQLite database URI | `sqlite+aiosqlite:///./data/job_assistant.db` |
| `MAX_APPLICATIONS_PER_DAY` | Application limit | `20` |

**Optional variables:**

| Variable | Description |
|----------|-------------|
| `TAVILY_API_KEY` | For live job searching. Falls back to mock data if unset. |
| `LANGCHAIN_API_KEY` | For LangSmith tracing (`LANGCHAIN_TRACING_V2=true`). |
| `SMTP_*` | SMTP configuration for real email notifications. |

## Database Setup

The application uses SQLite and will automatically create the required tables on the first run. The database is stored in the `./data` directory.
If using Alembic for migrations, you can run:
```bash
alembic upgrade head
```

## Running the Application

### How to Run the Backend & Frontend

The application serves both the API and the static frontend from a single FastAPI process.

```bash
python run.py
```
- Web UI: http://localhost:8000
- API Docs: http://localhost:8000/docs

*Note: The frontend is served statically from the `static/` directory.*

### How to Run the MCP Server (Standalone)

The MCP server runs automatically when the LangGraph workflow executes. However, you can run it standalone for debugging:
```bash
python -m mcp_server.server
```

### How to Run Tests

Ensure you have configured `pytest.ini` and installed test dependencies.
```bash
pytest
```
Or use the provided end-to-end test script:
```bash
python scripts/e2e_test.py
```

## End-to-End Workflow

1. **Profile Setup**: User uploads a resume (PDF) and sets preferences (role, experience, locations) via the Web UI.
2. **Job Search**: The LangGraph Supervisor delegates to the *Job Search Agent*, which uses the MCP `search_jobs` tool to find listings matching the criteria.
3. **Resume Match**: The *Resume Match Agent* processes the job descriptions against the uploaded resume using RAG (ChromaDB + OpenAI embeddings) to score compatibility.
4. **Application**: For matches exceeding the threshold, the *Application Agent* uses Playwright (via the MCP `apply_job` tool) to automatically fill out forms. Human-in-the-loop triggers for CAPTCHA or complex logins.
5. **Notification**: The *Notification Agent* sends a summary email with the run's outcomes.

## Known Limitations

- **Complex Logins & CAPTCHAs**: The Playwright automation cannot bypass robust bot protection. These require manual user intervention.
- **Job Board Variability**: The application agent relies on standardized form fields; highly customized portals may fail.
- **Daily Limits**: Hard-capped at 20 applications per day to prevent spamming and rate-limiting.
