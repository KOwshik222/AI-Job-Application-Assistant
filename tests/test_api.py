"""Tests for FastAPI API endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import init_db
from app.main import app


@pytest.fixture(autouse=True)
async def setup_db():
    """Initialize the database for each test."""
    await init_db()


@pytest.fixture
async def client():
    from app.services.mcp_client import get_mcp_client, shutdown_mcp_client

    await shutdown_mcp_client()
    mcp = get_mcp_client()
    await mcp.connect()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c

    await shutdown_mcp_client()


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_config(client):
    resp = await client.get("/api/v1/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "demo_mode" in data
    assert "max_applications_per_day" in data
    assert data["max_applications_per_day"] == 20


@pytest.mark.asyncio
async def test_upload_resume(client, sample_pdf_path):
    with open(sample_pdf_path, "rb") as f:
        resp = await client.post(
            "/api/v1/upload-resume",
            files={"file": ("test_resume.pdf", f, "application/pdf")},
            data={"email": "apitest@example.com"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "user_id" in data
    assert "resume_id" in data
    assert "file_hash" in data
    assert data["chunks_indexed"] > 0


@pytest.mark.asyncio
async def test_upload_resume_non_pdf(client):
    resp = await client.post(
        "/api/v1/upload-resume",
        files={"file": ("resume.txt", b"not a pdf", "text/plain")},
        data={"email": "test@example.com"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_applications_empty(client):
    """Applications list should return empty for unknown user."""
    resp = await client.get("/api/v1/applications?user_id=nonexistent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["applications"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_manual_actions_empty(client):
    resp = await client.get("/api/v1/manual-actions?user_id=nonexistent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["manual_actions"] == []


@pytest.mark.asyncio
async def test_application_summary_no_run(client):
    resp = await client.get("/api/v1/application-summary?run_id=nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_application_summary_no_params(client):
    resp = await client.get("/api/v1/application-summary")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_email_log_not_found(client):
    resp = await client.get("/api/v1/email-log/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_full_upload_and_workflow(client, sample_pdf_path):
    """Integration test: upload resume then start sync workflow."""
    # Upload
    with open(sample_pdf_path, "rb") as f:
        resp = await client.post(
            "/api/v1/upload-resume",
            files={"file": ("resume.pdf", f, "application/pdf")},
            data={"email": "integration@test.com"},
        )
    assert resp.status_code == 200
    upload = resp.json()

    # Start sync workflow
    resp = await client.post(
        "/api/v1/start-job-search/sync",
        json={
            "user_id": upload["user_id"],
            "resume_id": upload["resume_id"],
            "role": "Java Developer",
            "skills": ["Java", "Spring Boot", "Microservices", "SQL"],
            "experience": 3,
            "locations": ["Pune", "Mumbai", "Bangalore"],
            "email": "integration@test.com",
        },
    )
    assert resp.status_code == 200
    run = resp.json()
    assert run["status"] == "COMPLETED"
    assert run["run_id"]

    # Check summary
    resp = await client.get(f"/api/v1/application-summary?run_id={run['run_id']}")
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["status"] == "COMPLETED"
    assert summary["matched_jobs"] > 0

    # Check applications
    resp = await client.get(f"/api/v1/applications?user_id={upload['user_id']}")
    assert resp.status_code == 200
    apps = resp.json()
    assert apps["total"] > 0
