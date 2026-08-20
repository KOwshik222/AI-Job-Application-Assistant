"""Tests for end-to-end data flow: Search -> Supervisor -> RAG Match -> Decision -> Persistence -> Summary."""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.graph import get_graph
from app.agents.job_search import job_search_agent
from app.agents.resume_match import resume_match_agent
from app.agents.state import AgentState
from app.db.models import Application, Job, ManualAction
from app.db.repository import Repository
from app.db.session import async_session_factory, init_db
from app.schemas import JobListing, MatchedJob, StartJobSearchRequest, UserProfile
from app.services.workflow_runner import run_workflow, get_run_status

os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("DEMO_MODE", "false")


@pytest.fixture(autouse=True)
async def setup_test_db():
    await init_db()


@pytest.mark.asyncio
async def test_search_results_flow_to_resume_match():
    """Verify that jobs from job_search_agent flow into resume_match_agent without being lost."""
    mock_jobs = [
        {
            "job_id": "j1",
            "title": "Senior Java Developer",
            "company": "Tech Corp",
            "location": "Pune",
            "description": "Java and Spring Boot microservices.",
            "application_url": "https://jobs.smartrecruiters.com/TechCorp/123",
            "source": "tavily_verified",
        },
        {
            "job_id": "j2",
            "title": "Java Cloud Architect",
            "company": "Cloud Corp",
            "location": "Pune",
            "description": "Design cloud architecture with Java.",
            "application_url": "https://jobs.smartrecruiters.com/CloudCorp/456",
            "source": "tavily_verified",
        },
    ]

    with patch("app.agents.job_search.get_mcp_client") as mock_mcp_getter:
        mock_mcp = MagicMock()
        mock_mcp.call_tool = AsyncMock(return_value={"status": "SUCCESS", "jobs": mock_jobs})
        mock_mcp_getter.return_value = mock_mcp

        initial_state = {
            "user_profile": {
                "role": "Java Developer",
                "skills": ["Java", "Spring Boot"],
                "experience": 3,
                "locations": ["Pune"],
                "email": "test@example.com",
            }
        }

        search_output = await job_search_agent(initial_state)
        assert len(search_output["jobs_found"]) == 2
        assert search_output["next_agent"] == "resume_match"


@pytest.mark.asyncio
async def test_below_threshold_jobs_are_persisted_not_discarded():
    """Jobs with score < threshold are saved to DB with status NOT_MATCHED (not confused with manual action)."""
    import uuid
    uid_str = str(uuid.uuid4())
    async with async_session_factory() as session:
        repo = Repository(session)
        user = await repo.get_or_create_user(f"flow_{uid_str[:8]}@example.com")
        resume = await repo.create_resume(user.user_id, "dummy.pdf", f"hash_{uid_str[:8]}")
        await repo.commit()

        state = {
            "run_id": "run-test-123",
            "user_id": user.user_id,
            "resume_id": resume.resume_id,
            "resume_file_path": "dummy.pdf",
            "user_profile": {
                "role": "Java Developer",
                "skills": ["Java"],
                "experience": 2,
                "locations": ["Pune"],
                "email": "user_flow@example.com",
            },
            "match_threshold": 75,
            "jobs_found": [
                {
                    "job_id": "j1",
                    "title": "Senior Java Developer",
                    "company": "Acme Corp",
                    "location": "Pune",
                    "description": "Requires 8 years Java.",
                    "application_url": "https://jobs.smartrecruiters.com/Acme/1",
                    "source": "tavily_verified",
                }
            ],
            "errors": [],
        }

        mock_matched = MatchedJob(
            title="Senior Java Developer",
            company="Acme Corp",
            location="Pune",
            description="Requires 8 years Java.",
            application_url="https://jobs.smartrecruiters.com/Acme/1",
            match_score=60,  # Below threshold 75
            matching_skills=["Java"],
            missing_skills=["Kubernetes"],
            match_rationale="Candidate has 2 years experience, 8 required.",
        )

        with patch("app.agents.resume_match.match_job_to_resume", return_value=mock_matched):
            result = await resume_match_agent(state, session)

            assert len(result["matched_jobs"]) == 0
            assert result["next_agent"] == "notification"

            # Verify persisted in database as NOT_MATCHED (not confused with manual action)
            rows, total = await repo.list_applications(user.user_id)
            assert total == 1
            app, job = rows[0]
            assert job.company == "Acme Corp"
            assert app.status == "NOT_MATCHED"
            assert app.match_score == 60


@pytest.mark.asyncio
async def test_above_threshold_jobs_proceed_to_application():
    """Jobs with score >= threshold are added to matched_jobs for application."""
    state = {
        "run_id": "run-test-456",
        "user_id": "user-456",
        "resume_id": "res-456",
        "resume_file_path": "dummy.pdf",
        "user_profile": {
            "role": "Java Developer",
            "skills": ["Java", "Spring Boot"],
            "experience": 3,
            "locations": ["Pune"],
            "email": "user456@example.com",
        },
        "match_threshold": 75,
        "jobs_found": [
            {
                "job_id": "j2",
                "title": "Java Developer",
                "company": "Target Corp",
                "location": "Pune",
                "description": "Java Spring Boot developer with 3 years experience.",
                "application_url": "https://jobs.smartrecruiters.com/Target/2",
                "source": "tavily_verified",
            }
        ],
        "errors": [],
    }

    mock_matched = MatchedJob(
        title="Java Developer",
        company="Target Corp",
        location="Pune",
        description="Java Spring Boot developer.",
        application_url="https://jobs.smartrecruiters.com/Target/2",
        match_score=90,  # Above threshold 75
        matching_skills=["Java", "Spring Boot"],
        missing_skills=[],
        match_rationale="Strong technical match.",
    )

    with patch("app.agents.resume_match.match_job_to_resume", return_value=mock_matched):
        result = await resume_match_agent(state, None)
        assert len(result["matched_jobs"]) == 1
        assert result["matched_jobs"][0]["match_score"] == 90
        assert result["next_agent"] == "application"
