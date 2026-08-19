"""End-to-end integration test for the full application."""

import asyncio
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "static" / "assets" / "sample_resume.pdf"
BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")


async def main():
    if not SAMPLE.exists():
        print("Sample resume missing. Run: python scripts/generate_sample_resume.py")
        sys.exit(1)

    async with httpx.AsyncClient(base_url=BASE, timeout=120.0) as client:
        # Health
        r = await client.get("/health")
        assert r.status_code == 200, f"Health check failed: {r.status_code}"

        # Config
        r = await client.get("/api/v1/config")
        cfg = r.json()
        print(f"Mode: {'demo' if cfg['demo_mode'] else 'live'}")

        # Upload
        with open(SAMPLE, "rb") as f:
            r = await client.post(
                "/api/v1/upload-resume",
                files={"file": ("sample_resume.pdf", f, "application/pdf")},
                data={"email": "e2e@test.com"},
            )
        assert r.status_code == 200, r.text
        upload = r.json()
        print(f"Uploaded: user={upload['user_id'][:8]}… chunks={upload['chunks_indexed']}")

        # Sync workflow
        r = await client.post(
            "/api/v1/start-job-search/sync",
            json={
                "user_id": upload["user_id"],
                "resume_id": upload["resume_id"],
                "role": "Java Developer",
                "skills": ["Java", "Spring Boot", "Microservices", "SQL"],
                "experience": 3,
                "locations": ["Pune", "Mumbai", "Bangalore"],
                "email": "e2e@test.com",
            },
        )
        assert r.status_code == 200, r.text
        run = r.json()
        print(f"Workflow: run_id={run['run_id'][:8]}… status={run['status']}")

        # Summary
        r = await client.get(f"/api/v1/application-summary?run_id={run['run_id']}")
        summary = r.json()
        print(f"Summary: applied={summary['applied_successfully']} manual={summary['manual_action_required']} failed={summary['failed']} matched={summary['matched_jobs']}")

        # Applications
        r = await client.get(f"/api/v1/applications?user_id={upload['user_id']}")
        apps = r.json()
        print(f"Applications in DB: {apps['total']}")

        assert summary["status"] == "COMPLETED"
        assert summary["matched_jobs"] > 0
        print("\nE2E test PASSED")


if __name__ == "__main__":
    asyncio.run(main())
