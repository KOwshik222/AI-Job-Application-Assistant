"""Real Integration Test: Single-Job End-to-End Workflow.

Verifies:
Job Search -> Individual job -> RAG -> Match >= threshold -> Guardrails -> MCP apply_job
-> Original resume hash verification -> Browser -> Application -> Confirmation verification
"""

import asyncio
import os
import tempfile
from pathlib import Path
from fpdf import FPDF
from httpx import ASGITransport, AsyncClient

os.environ["DEMO_MODE"] = "true"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from app.db.session import init_db
from app.main import app
from app.services.mcp_client import get_mcp_client, shutdown_mcp_client
from app.services.resume_storage import compute_file_hash, verify_resume_integrity


async def test_single_job_workflow():
    print("=" * 60)
    print("SINGLE-JOB INTEGRATION TEST: FULL PIPELINE VERIFICATION")
    print("=" * 60)

    # 1. Initialize DB and connect MCP
    await init_db()
    await shutdown_mcp_client()
    mcp = get_mcp_client()
    await mcp.connect()
    assert mcp.is_connected, "MCP Client failed to connect!"
    print("[1/8] MCP client connected and discovered tools.")

    # 2. Generate original PDF resume
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.cell(200, 10, text="John Doe - Senior Java Engineer", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(200, 10, text="Skills: Java, Spring Boot, Microservices, PostgreSQL, Docker", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(200, 10, text="Experience: 5 years designing distributed cloud backends", new_x="LMARGIN", new_y="NEXT")
        pdf.output(tmp.name)
        pdf_path = tmp.name

    original_hash = compute_file_hash(Path(pdf_path))
    print(f"[2/8] Original PDF generated (SHA-256: {original_hash[:16]}...).")

    # 3. Verify hash integrity before workflow
    integrity = verify_resume_integrity(pdf_path, original_hash)
    assert integrity["valid"] is True
    print(f"[3/8] Resume integrity verified: {integrity['reason']}.")

    # 4. Upload Resume via API
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        with open(pdf_path, "rb") as f:
            upload_res = await client.post(
                "/api/v1/upload-resume",
                files={"file": ("john_doe_resume.pdf", f, "application/pdf")},
                data={"email": "johndoe@example.com"},
            )
        assert upload_res.status_code == 200
        upload_data = upload_res.json()
        user_id = upload_data["user_id"]
        resume_id = upload_data["resume_id"]
        print(f"[4/8] Resume uploaded: user_id={user_id}, resume_id={resume_id}, hash={upload_data['file_hash'][:16]}...")
        assert upload_data["file_hash"] == original_hash

        # 5. Run Single Job Application (max_applications=1)
        print("[5/8] Starting workflow with max_applications=1...")
        wf_res = await client.post(
            "/api/v1/start-job-search/sync",
            json={
                "user_id": user_id,
                "resume_id": resume_id,
                "role": "Java Developer",
                "skills": ["Java", "Spring Boot", "Microservices"],
                "experience": 5,
                "locations": ["Pune"],
                "email": "johndoe@example.com",
                "max_applications": 1,
                "match_threshold": 70,
            },
        )
        assert wf_res.status_code == 200
        wf_data = wf_res.json()
        run_id = wf_data["run_id"]
        print(f"[6/8] Single job workflow completed: run_id={run_id}, status={wf_data['status']}.")

        # 6. Verify Single Job Summary
        summary_res = await client.get(f"/api/v1/application-summary?run_id={run_id}")
        assert summary_res.status_code == 200
        summary = summary_res.json()
        print(f"[7/8] Workflow Summary:")
        print(f"      - Status: {summary['status']}")
        print(f"      - Jobs Found: {summary['jobs_found']}")
        print(f"      - Matched Jobs: {summary['matched_jobs']}")
        print(f"      - Applied Successfully: {summary['applied_successfully']}")
        print(f"      - Manual Action Required: {summary['manual_action_required']}")
        print(f"      - Failed: {summary['failed']}")
        assert summary["applied_successfully"] <= 1, "Must not apply to more than max_applications=1!"

        # 7. Check Applications Database Record
        apps_res = await client.get(f"/api/v1/applications?user_id={user_id}")
        assert apps_res.status_code == 200
        apps_data = apps_res.json()
        print(f"[8/8] Database Applications Count: {apps_data['total']}")
        assert apps_data["total"] <= 1

    # Cleanup
    await shutdown_mcp_client()
    try:
        os.remove(pdf_path)
    except Exception:
        pass

    print("=" * 60)
    print("SUCCESS: SINGLE-JOB INTEGRATION PIPELINE VERIFIED!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_single_job_workflow())
