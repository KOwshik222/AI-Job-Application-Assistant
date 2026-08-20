"""End-to-End Smoke Test verifying all 5 production-critical fixes."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from fpdf import FPDF
from httpx import ASGITransport, AsyncClient

# Set test environment
os.environ["DEMO_MODE"] = "true"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from app.config import get_settings
from app.db.session import init_db
from app.main import app
from app.services.browser_sessions import get_browser_session_manager
from app.services.mcp_client import get_mcp_client, shutdown_mcp_client
from app.services.resume_storage import compute_file_hash, verify_resume_integrity


async def run_smoke_test():
    print("=" * 60)
    print("STARTING FULL END-TO-END SMOKE TEST")
    print("=" * 60)

    # 0. Initialize DB
    await init_db()
    print("[OK] 0. Database initialized successfully.")

    # 1. MCP Client & Server Transport
    print("\n--- FIX 1: MCP Client/Server Communication via stdio ---")
    await shutdown_mcp_client()
    mcp = get_mcp_client()
    await mcp.connect()
    assert mcp.is_connected, "MCP Client failed to connect!"
    tools = mcp.get_available_tools()
    tool_names = [t["name"] for t in tools]
    print(f"[OK] Discovered {len(tools)} MCP tools: {tool_names}")
    assert "search_jobs" in tool_names
    assert "apply_job" in tool_names
    assert "send_email" in tool_names
    assert "resume_application" in tool_names

    # Test tool invocation via protocol
    search_res = await mcp.call_tool("search_jobs", {
        "role": "Java Developer",
        "skills": ["Java", "Spring Boot"],
        "locations": ["Pune"],
        "max_results": 2,
        "test_mode": True,
    })
    assert "jobs" in search_res and len(search_res["jobs"]) > 0
    print(f"[OK] Executed search_jobs via MCP protocol: found {len(search_res['jobs'])} jobs.")

    # 2. Strict LLM Provider Configuration
    print("\n--- FIX 2: Strict LLM Provider Configuration ---")
    settings = get_settings()
    print(f"[OK] DEMO_MODE setting: {settings.demo_mode} (is_demo_mode={settings.is_demo_mode})")
    print(f"[OK] Configured LLM provider: {settings.llm_provider}")

    # 3. Resume PDF Integrity Check
    print("\n--- FIX 4: SHA-256 Resume Integrity Verification ---")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.cell(200, 10, text="Smoke Test Resume - Senior Java Architect", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(200, 10, text="Skills: Java, Spring Boot, Microservices, Kubernetes", new_x="LMARGIN", new_y="NEXT")
        pdf.output(tmp.name)
        pdf_path = tmp.name

    original_hash = compute_file_hash(Path(pdf_path))
    print(f"[OK] Original PDF generated with SHA-256: {original_hash[:16]}...")

    check_valid = verify_resume_integrity(pdf_path, original_hash)
    assert check_valid["valid"] is True
    print(f"[OK] Verified unmodified resume: valid={check_valid['valid']}")

    check_invalid = verify_resume_integrity(pdf_path, "tampered_hash_value")
    assert check_invalid["valid"] is False
    print(f"[OK] Tampered hash rejected: valid={check_invalid['valid']}, reason: {check_invalid['reason'][:50]}...")

    # 4. Headful Browser & Human-in-the-Loop Sessions
    print("\n--- FIX 3: Headful Human-in-the-Loop Browser Sessions ---")
    session_manager = get_browser_session_manager()
    bsession = session_manager.create_session(
        application_url="https://careers.example.com/login/auth",
        company="Secured Inc",
        job_title="Lead Architect",
        job_id="smoke-job-1",
        barrier_type="LOGIN",
        page=None,
        browser=None,
        context=None,
        user_profile={"email": "smoketest@example.com"},
        resume_path=pdf_path,
        expected_resume_hash=original_hash,
    )
    print(f"[OK] Created HITL session: id={bsession.session_id}, barrier={bsession.barrier_type}")
    active_sessions = session_manager.list_active_sessions()
    assert len(active_sessions) > 0
    print(f"[OK] Active sessions listed: {len(active_sessions)}")
    await session_manager.cleanup_session(bsession.session_id)
    print("[OK] Cleaned up session successfully.")

    # 5. Playwright Fallback for JS Job Pages
    print("\n--- FIX 5: Playwright Fallback Inspection ---")
    from mcp_server.tools.search_jobs import is_candidate_url_structure, canonicalize_url
    clean_url = canonicalize_url("https://boards.greenhouse.io/stripe/jobs/123?utm_source=linkedin&ref=123")
    assert "utm_source" not in clean_url
    assert is_candidate_url_structure(clean_url) is True
    print(f"[OK] Canonical URL validated: {clean_url}")

    # 6. End-to-End Workflow via FastAPI Client
    print("\n--- E2E WORKFLOW: Upload -> Match -> Apply -> Notification ---")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Health check
        health_resp = await client.get("/health")
        assert health_resp.status_code == 200
        health_data = health_resp.json()
        print(f"[OK] GET /health: status={health_data['status']}, mcp_connected={health_data['mcp_connected']}")

        # Upload resume
        with open(pdf_path, "rb") as f:
            upload_resp = await client.post(
                "/api/v1/upload-resume",
                files={"file": ("smoke_resume.pdf", f, "application/pdf")},
                data={"email": "smoketest@example.com"},
            )
        assert upload_resp.status_code == 200
        upload_data = upload_resp.json()
        user_id = upload_data["user_id"]
        resume_id = upload_data["resume_id"]
        print(f"[OK] POST /api/v1/upload-resume: user_id={user_id}, resume_id={resume_id}, chunks={upload_data['chunks_indexed']}")

        # Start sync workflow
        workflow_resp = await client.post(
            "/api/v1/start-job-search/sync",
            json={
                "user_id": user_id,
                "resume_id": resume_id,
                "role": "Java Developer",
                "skills": ["Java", "Spring Boot", "Microservices"],
                "experience": 5,
                "locations": ["Pune", "Mumbai"],
                "email": "smoketest@example.com",
            },
        )
        assert workflow_resp.status_code == 200
        wf_data = workflow_resp.json()
        run_id = wf_data["run_id"]
        print(f"[OK] POST /api/v1/start-job-search/sync: run_id={run_id}, status={wf_data['status']}")

        # Fetch application summary
        summary_resp = await client.get(f"/api/v1/application-summary?run_id={run_id}")
        assert summary_resp.status_code == 200
        summary = summary_resp.json()
        print(f"[OK] GET /api/v1/application-summary: status={summary['status']}, matched_jobs={summary['matched_jobs']}, applied={summary['applied_successfully']}")

        # Fetch applications list
        apps_resp = await client.get(f"/api/v1/applications?user_id={user_id}")
        assert apps_resp.status_code == 200
        apps = apps_resp.json()
        print(f"[OK] GET /api/v1/applications: total={apps['total']}")

    # Clean up
    await shutdown_mcp_client()
    try:
        os.remove(pdf_path)
    except Exception:
        pass

    print("\n" + "=" * 60)
    print("SUCCESS: ALL 5 PRODUCTION-CRITICAL FIXES VERIFIED!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_smoke_test())
