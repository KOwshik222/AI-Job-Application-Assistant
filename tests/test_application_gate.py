"""Tests for the 75% application gate — ensures low-score jobs never reach apply_job."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.application import application_agent
from app.config import get_settings

settings = get_settings()


def _make_state(matched_jobs: list[dict], **overrides) -> dict:
    """Build a minimal AgentState with matched_jobs."""
    base = {
        "user_id": "test-user",
        "resume_id": "test-resume",
        "resume_file_path": "/tmp/resume.pdf",
        "run_id": "test-run",
        "user_profile": {
            "role": "AI Developer",
            "skills": ["Python"],
            "experience": 1,
            "locations": ["Hyderabad"],
            "email": "test@example.com",
            "full_name": "Test User",
            "phone": "",
        },
        "matched_jobs": matched_jobs,
        "applications_attempted": 0,
        "max_applications_per_run": 10,
    }
    base.update(overrides)
    return base


def _make_job(score: int, company: str = "TestCorp", title: str = "AI Dev") -> dict:
    """Build a matched job dict with a specific score."""
    return {
        "job_id": f"job-{score}",
        "title": title,
        "company": company,
        "location": "Hyderabad",
        "description": "Test job",
        "application_url": f"https://example.com/apply/{score}",
        "source": "test",
        "posted_at": None,
        "match_score": score,
        "matching_skills": ["Python"],
        "missing_skills": [],
        "match_rationale": "Test match",
    }


@pytest.fixture
def mock_session():
    session = AsyncMock()
    return session


@pytest.fixture
def mock_repo():
    with patch("app.agents.application.Repository") as MockRepo:
        repo = MockRepo.return_value
        repo.get_resume = AsyncMock(return_value=MagicMock(file_hash="abc123"))
        repo.upsert_job = AsyncMock(return_value=MagicMock(job_id="db-job-1"))
        repo.create_application = AsyncMock()
        repo.create_manual_action = AsyncMock()
        repo.commit = AsyncMock()
        yield repo


@pytest.fixture
def mock_mcp():
    with patch("app.agents.application.get_mcp_client") as MockMCP:
        client = MockMCP.return_value
        client.call_tool = AsyncMock(return_value={
            "status": "SUCCESS",
            "company": "TestCorp",
            "confirmation": "Confirmed",
            "submitted_at": "2026-01-01T00:00:00Z",
        })
        yield client


@pytest.fixture
def mock_integrity():
    with patch("app.agents.application.verify_resume_integrity") as mock:
        mock.return_value = {"valid": True}
        yield mock


@pytest.fixture
def mock_guardrails():
    with patch("app.agents.application.Guardrails") as MockGuard:
        guard = MockGuard.return_value
        guard.can_apply = AsyncMock(return_value=(True, "OK"))
        guard.record_application_attempt = AsyncMock()
        yield guard


class TestApplicationGateLowScores:
    """All scores below threshold should be blocked — never reach apply_job."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("score", [0, 15, 30, 40, 47, 58, 65, 74])
    async def test_low_scores_blocked(
        self, score, mock_session, mock_repo, mock_mcp, mock_integrity, mock_guardrails,
    ):
        """Jobs with score < 75 must be skipped, not applied to."""
        state = _make_state([_make_job(score)])
        result = await application_agent(state, mock_session)

        # The MCP apply_job tool should NEVER be called
        mock_mcp.call_tool.assert_not_called()
        assert len(result["applied_jobs"]) == 0
        assert result["applications_attempted"] == 0


class TestApplicationGateBoundary:
    """Boundary tests at the exact threshold (75)."""

    @pytest.mark.asyncio
    async def test_score_74_blocked(
        self, mock_session, mock_repo, mock_mcp, mock_integrity, mock_guardrails,
    ):
        """Score 74 is below threshold — must be blocked."""
        state = _make_state([_make_job(74)])
        result = await application_agent(state, mock_session)

        mock_mcp.call_tool.assert_not_called()
        assert len(result["applied_jobs"]) == 0

    @pytest.mark.asyncio
    async def test_score_75_eligible(
        self, mock_session, mock_repo, mock_mcp, mock_integrity, mock_guardrails,
    ):
        """Score 75 meets threshold — should proceed to application."""
        state = _make_state([_make_job(75)])
        result = await application_agent(state, mock_session)

        # apply_job should have been called
        mock_mcp.call_tool.assert_called_once()
        assert result["applications_attempted"] == 1

    @pytest.mark.asyncio
    async def test_score_76_eligible(
        self, mock_session, mock_repo, mock_mcp, mock_integrity, mock_guardrails,
    ):
        """Score 76 exceeds threshold — should proceed to application."""
        state = _make_state([_make_job(76)])
        result = await application_agent(state, mock_session)

        mock_mcp.call_tool.assert_called_once()
        assert result["applications_attempted"] == 1


class TestApplicationGateMixedScores:
    """When a batch has mixed scores, only eligible jobs proceed."""

    @pytest.mark.asyncio
    async def test_mixed_scores_only_eligible_applied(
        self, mock_session, mock_repo, mock_mcp, mock_integrity, mock_guardrails,
    ):
        """Only jobs >= 75 should reach MCP, rest should be skipped."""
        jobs = [
            _make_job(30, company="LowCorp"),
            _make_job(85, company="HighCorp"),
            _make_job(74, company="BorderCorp"),
            _make_job(90, company="TopCorp"),
        ]
        state = _make_state(jobs)
        result = await application_agent(state, mock_session)

        # Only 2 jobs (85, 90) should have attempted application
        assert result["applications_attempted"] == 2
        assert mock_mcp.call_tool.call_count == 2
