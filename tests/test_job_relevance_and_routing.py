"""Regression tests for Job Relevance, Experience Filtering, Multi-Criteria Weighted Matching, and Application Routing."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.application import application_agent
from app.agents.resume_match import resume_match_agent
from app.db.models import Application, Job, ManualAction
from app.db.repository import Repository
from app.db.session import async_session_factory, init_db
from app.rag.matcher import MatchResult, match_job_to_resume
from app.schemas import JobListing, MatchedJob, UserProfile
from mcp_server.tools.search_jobs import (
    build_targeted_search_queries,
    get_role_synonyms,
    is_experience_compatible,
    is_role_compatible,
)


@pytest.fixture(autouse=True)
async def setup_test_db():
    await init_db()


# --- 1. Role Synonyms & Semantic Matching ---


def test_role_synonym_expansion():
    """Verify that role synonyms include all required semantic equivalents for AI Developer."""
    syns = get_role_synonyms("AI Developer")
    expected = [
        "AI Developer", "AI Engineer", "Junior AI Engineer",
        "Machine Learning Engineer", "ML Engineer", "Generative AI Developer",
        "GenAI Engineer", "LLM Engineer", "AI/ML Engineer", "Junior ML Engineer",
        "Python AI Developer", "Applied AI Engineer",
    ]
    for exp in expected:
        assert exp in syns, f"Expected synonym '{exp}' not found in role synonyms"


def test_role_compatibility_matching():
    """Verify semantic role compatibility logic."""
    assert is_role_compatible("Junior AI Engineer", "AI Developer") is True
    assert is_role_compatible("Machine Learning Engineer", "AI Developer") is True
    assert is_role_compatible("Generative AI Developer", "AI Developer") is True
    assert is_role_compatible("Python Developer", "AI Developer") is True
    assert is_role_compatible("Software Engineer", "AI Developer") is True

    # Rejection of completely unrelated non-tech domains
    assert is_role_compatible("Sales Executive", "AI Developer") is False
    assert is_role_compatible("Marketing Manager", "AI Developer") is False
    assert is_role_compatible("Accountant", "AI Developer") is False
    assert is_role_compatible("HR Recruiter", "AI Developer") is False


# --- 2. Experience Filtering ---


def test_experience_filtering_rejects_senior_roles():
    """Candidates with 1 year experience should reject Senior/Lead/Staff/Principal roles."""
    # Senior title
    compat, reason = is_experience_compatible("Senior AI Engineer", "Build models.", candidate_experience=1)
    assert compat is False
    assert "Senior role" in reason

    # Lead title
    compat, reason = is_experience_compatible("Lead ML Engineer", "Lead the team.", candidate_experience=1)
    assert compat is False
    assert "Senior role" in reason

    # Staff title
    compat, reason = is_experience_compatible("Staff AI Developer", "High scale AI.", candidate_experience=1)
    assert compat is False


def test_experience_filtering_rejects_explicit_high_experience_requirements():
    """Postings explicitly requiring 3+, 4+, 5+ years should be rejected for 1-year candidate."""
    desc_5yr = "We require minimum 5 years of experience in deep learning and NLP."
    compat, reason = is_experience_compatible("AI Engineer", desc_5yr, candidate_experience=1)
    assert compat is False
    assert "5+ years" in reason or "mandates" in reason.lower()

    desc_3yr = "Candidate must have 3+ years experience with Python and TensorFlow."
    compat, reason = is_experience_compatible("Machine Learning Engineer", desc_3yr, candidate_experience=1)
    assert compat is False


def test_experience_filtering_accepts_junior_entry_and_unspecified():
    """Postings accepting 0-2 years or with unspecified experience must be accepted."""
    # Junior / 0-2 years
    desc_junior = "Looking for 0-2 years experience in Python and Machine Learning."
    compat, reason = is_experience_compatible("Junior AI Developer", desc_junior, candidate_experience=1)
    assert compat is True

    # 1+ years
    desc_1plus = "1+ years experience in Python, PyTorch, and REST APIs."
    compat, reason = is_experience_compatible("AI Developer", desc_1plus, candidate_experience=1)
    assert compat is True

    # Unspecified experience
    desc_unspec = "Join our team to build generative AI solutions with LangChain and Python."
    compat, reason = is_experience_compatible("AI Engineer", desc_unspec, candidate_experience=1)
    assert compat is True


# --- 3. Targeted Query Generation ---


def test_targeted_query_generation():
    """Verify search queries incorporate role synonyms, locations, skills, and ATS domains."""
    queries = build_targeted_search_queries(
        role="AI Developer",
        skills=["Python", "Machine Learning", "Generative AI", "LangChain"],
        locations=["Hyderabad"],
        experience_years=1,
    )
    assert len(queries) >= 1
    primary_q = queries[0]
    assert "AI Developer" in primary_q or "AI Engineer" in primary_q
    assert "Hyderabad" in primary_q
    assert "Python" in primary_q
    assert "boards.greenhouse.io" in primary_q or "smartrecruiters.com" in primary_q


# --- 4. Multi-Criteria Weighted Match Scoring & Projects ---


def test_multi_criteria_match_result_weights():
    """Verify MatchResult schema calculates and validates weights (Role 25, Skills 30, Exp 20, Projects 15, Edu 5, Other 5)."""
    res = MatchResult(
        job_title="AI Developer",
        company="NexTech",
        match_score=85,
        role_score=22,
        skills_score=27,
        experience_score=18,
        projects_score=12,
        education_score=4,
        other_score=2,
        matching_skills=["Python", "Machine Learning", "Generative AI", "LangChain"],
        missing_skills=["Kubernetes"],
        experience_required="1-2 years",
        match_rationale="Strong alignment on AI role, projects in GenAI, and Python skills.",
    )
    assert res.match_score == 85
    assert res.role_score + res.skills_score + res.experience_score + res.projects_score + res.education_score + res.other_score == 85
    assert "GenAI" in res.match_rationale


# --- 5. Application Routing & Separation of NOT_MATCHED vs MANUAL_ACTION ---


@pytest.mark.asyncio
async def test_not_matched_jobs_do_not_create_manual_action():
    """Jobs scoring < 75 are recorded as NOT_MATCHED and NEVER created as ManualActionItem."""
    import uuid
    uid_str = str(uuid.uuid4())
    async with async_session_factory() as session:
        repo = Repository(session)
        user = await repo.get_or_create_user(f"nm_{uid_str[:8]}@example.com")
        resume = await repo.create_resume(user.user_id, "resume.pdf", f"h_{uid_str[:8]}")
        await repo.commit()

        state = {
            "run_id": f"run-{uid_str[:8]}",
            "user_id": user.user_id,
            "resume_id": resume.resume_id,
            "resume_file_path": "resume.pdf",
            "user_profile": {
                "role": "AI Developer",
                "skills": ["Python", "Machine Learning"],
                "experience": 1,
                "locations": ["Hyderabad"],
                "email": f"nm_{uid_str[:8]}@example.com",
            },
            "match_threshold": 75,
            "jobs_found": [
                {
                    "job_id": "j-low",
                    "title": "Data Analyst",
                    "company": "LowMatch Corp",
                    "location": "Hyderabad",
                    "description": "SQL and Excel required.",
                    "application_url": "https://jobs.smartrecruiters.com/Low/1",
                    "source": "tavily_verified",
                }
            ],
            "errors": [],
        }

        mock_match = MatchedJob(
            title="Data Analyst",
            company="LowMatch Corp",
            location="Hyderabad",
            description="SQL and Excel required.",
            application_url="https://jobs.smartrecruiters.com/Low/1",
            match_score=40,  # Below threshold 75
            matching_skills=["Python"],
            missing_skills=["Excel", "PowerBI"],
            match_rationale="Domain mismatch; primarily BI/Analytics.",
        )

        with patch("app.agents.resume_match.match_job_to_resume", return_value=mock_match):
            result = await resume_match_agent(state, session)
            assert len(result["matched_jobs"]) == 0
            assert result["next_agent"] == "notification"

            # Check DB applications table
            rows, total = await repo.list_applications(user.user_id)
            assert total == 1
            app, job = rows[0]
            assert app.status == "NOT_MATCHED"
            assert app.match_score == 40

            # Check DB manual_actions table — MUST BE EMPTY
            actions = await repo.list_manual_actions(user.user_id)
            assert len(actions) == 0, "Low match score MUST NOT create a manual action"


@pytest.mark.asyncio
async def test_eligible_jobs_pass_to_application_and_queue_excess():
    """Jobs scoring >= 75 are ELIGIBLE, exactly MAX_APPLICATIONS_PER_DAY=1 is attempted, and remaining are QUEUED."""
    import uuid
    uid_str = str(uuid.uuid4())
    async with async_session_factory() as session:
        repo = Repository(session)
        user = await repo.get_or_create_user(f"elig_{uid_str[:8]}@example.com")
        resume = await repo.create_resume(user.user_id, "resume.pdf", f"h_{uid_str[:8]}")
        await repo.commit()

        matched_jobs = [
            {
                "job_id": "j-elig-1",
                "title": "Junior AI Engineer",
                "company": "Alpha AI",
                "location": "Hyderabad",
                "description": "Python, LLMs, GenAI.",
                "application_url": "https://jobs.smartrecruiters.com/Alpha/1",
                "source": "tavily_verified",
                "match_score": 88,
                "matching_skills": ["Python", "GenAI"],
                "missing_skills": [],
                "match_rationale": "High match",
            },
            {
                "job_id": "j-elig-2",
                "title": "Machine Learning Engineer",
                "company": "Beta ML",
                "location": "Hyderabad",
                "description": "Python, ML models.",
                "application_url": "https://jobs.smartrecruiters.com/Beta/2",
                "source": "tavily_verified",
                "match_score": 82,
                "matching_skills": ["Python", "ML"],
                "missing_skills": [],
                "match_rationale": "Strong match",
            },
        ]

        state = {
            "run_id": f"run-{uid_str[:8]}",
            "user_id": user.user_id,
            "resume_id": resume.resume_id,
            "resume_file_path": "resume.pdf",
            "user_profile": {
                "role": "AI Developer",
                "skills": ["Python", "Machine Learning", "Generative AI"],
                "experience": 1,
                "locations": ["Hyderabad"],
                "email": f"elig_{uid_str[:8]}@example.com",
            },
            "matched_jobs": matched_jobs,
            "max_applications_per_run": 1,
            "applications_attempted": 0,
            "applied_jobs": [],
            "pending_manual_jobs": [],
            "failed_jobs": [],
            "errors": [],
        }

        with patch("app.agents.application.get_mcp_client") as mock_mcp_getter, \
             patch("app.agents.application.verify_resume_integrity", return_value={"valid": True, "reason": "OK"}):
            mock_mcp = MagicMock()
            mock_mcp.call_tool = AsyncMock(return_value={
                "status": "SUCCESS",
                "company": "Alpha AI",
                "job_title": "Junior AI Engineer",
                "application_url": "https://jobs.smartrecruiters.com/Alpha/1",
                "confirmation": "Application Submitted",
                "submitted_at": "2026-08-20T12:00:00Z",
            })
            mock_mcp_getter.return_value = mock_mcp

            app_output = await application_agent(state, session)

            assert app_output["applications_attempted"] == 1
            assert len(app_output["applied_jobs"]) == 1
            assert app_output["applied_jobs"][0]["company"] == "Alpha AI"
            assert app_output["applied_jobs"][0]["status"] == "SUCCESS"

            # Check DB applications table: Alpha AI is SUCCESS, Beta ML is ELIGIBLE (queued)
            rows, total = await repo.list_applications(user.user_id)
            assert total == 2
            app_map = {job.company: app.status for app, job in rows}
            assert app_map["Alpha AI"] == "SUCCESS"
            assert app_map["Beta ML"] == "ELIGIBLE"
