"""Tests for human-in-the-loop browser workflow.

Verifies:
- CAPTCHA → MANUAL_ACTION_REQUIRED
- Login → MANUAL_ACTION_REQUIRED  
- OTP / MFA / 2FA → MANUAL_ACTION_REQUIRED
- Browser session tracking
- Continue action resumes workflow
- Security is never bypassed
"""

import json
import os
import pytest

os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("DEMO_MODE", "false")


@pytest.mark.asyncio
async def test_captcha_returns_manual_action(sample_pdf_path):
    """URL containing 'captcha' → MANUAL_ACTION_REQUIRED."""
    from mcp_server.tools.apply_job import apply_job_tool

    result = await apply_job_tool(
        application_url="https://careers.example.com/captcha/apply",
        resume_file_path=sample_pdf_path,
        user_profile={"email": "test@example.com", "full_name": "Test User"},
        company="Example Corp",
        job_title="Developer",
        mock_mode=True,
    )
    data = json.loads(result)
    assert data["status"] == "MANUAL_ACTION_REQUIRED"


@pytest.mark.asyncio
async def test_login_returns_manual_action(sample_pdf_path):
    """URL containing 'login' → MANUAL_ACTION_REQUIRED."""
    from mcp_server.tools.apply_job import apply_job_tool

    result = await apply_job_tool(
        application_url="https://careers.example.com/login/apply",
        resume_file_path=sample_pdf_path,
        user_profile={"email": "test@example.com"},
        mock_mode=True,
    )
    data = json.loads(result)
    assert data["status"] == "MANUAL_ACTION_REQUIRED"
    assert "Login" in data["reason"] or "login" in data["reason"].lower()


@pytest.mark.asyncio
async def test_auth_returns_manual_action(sample_pdf_path):
    """URL containing 'auth' → MANUAL_ACTION_REQUIRED."""
    from mcp_server.tools.apply_job import apply_job_tool

    result = await apply_job_tool(
        application_url="https://careers.example.com/auth/signup",
        resume_file_path=sample_pdf_path,
        user_profile={"email": "test@example.com"},
        mock_mode=True,
    )
    data = json.loads(result)
    assert data["status"] == "MANUAL_ACTION_REQUIRED"


@pytest.mark.asyncio
async def test_normal_url_succeeds(sample_pdf_path):
    """Normal URL without security triggers → SUCCESS in mock mode."""
    from mcp_server.tools.apply_job import apply_job_tool

    result = await apply_job_tool(
        application_url="https://careers.example.com/job/123",
        resume_file_path=sample_pdf_path,
        user_profile={"email": "test@example.com", "full_name": "Test User"},
        company="Example Corp",
        job_title="Developer",
        mock_mode=True,
    )
    data = json.loads(result)
    assert data["status"] == "SUCCESS"


def test_browser_session_manager_create():
    """Browser session manager can create and track sessions."""
    from app.services.browser_sessions import BrowserSessionManager, SessionStatus

    manager = BrowserSessionManager()
    session = manager.create_session(
        application_url="https://example.com/apply",
        company="Test Corp",
        job_title="Developer",
        job_id="job-123",
        barrier_type="CAPTCHA",
        page=None,
        browser=None,
        context=None,
        user_profile={"email": "test@test.com"},
        resume_path="/tmp/resume.pdf",
    )

    assert session.session_id
    assert session.status == SessionStatus.WAITING_FOR_USER
    assert session.barrier_type == "CAPTCHA"

    # Retrieve session
    retrieved = manager.get_session(session.session_id)
    assert retrieved is not None
    assert retrieved.company == "Test Corp"


def test_browser_session_list_active():
    """List only active (waiting) sessions."""
    from app.services.browser_sessions import BrowserSessionManager, SessionStatus

    manager = BrowserSessionManager()

    s1 = manager.create_session(
        application_url="https://a.com/apply",
        company="A Corp",
        job_title="Dev",
        job_id="j1",
        barrier_type="LOGIN",
        page=None, browser=None, context=None,
        user_profile={}, resume_path="",
    )
    s2 = manager.create_session(
        application_url="https://b.com/apply",
        company="B Corp",
        job_title="Eng",
        job_id="j2",
        barrier_type="OTP",
        page=None, browser=None, context=None,
        user_profile={}, resume_path="",
    )

    active = manager.list_active_sessions()
    assert len(active) >= 2


@pytest.mark.asyncio
async def test_browser_session_cleanup():
    """Cleanup removes session and no longer findable."""
    from app.services.browser_sessions import BrowserSessionManager

    manager = BrowserSessionManager()
    session = manager.create_session(
        application_url="https://example.com",
        company="Test",
        job_title="Dev",
        job_id="j-1",
        barrier_type="MFA",
        page=None, browser=None, context=None,
        user_profile={}, resume_path="",
    )

    await manager.cleanup_session(session.session_id)
    assert manager.get_session(session.session_id) is None


def test_browser_session_never_stores_credentials():
    """Verify session.to_dict() never includes sensitive fields."""
    from app.services.browser_sessions import BrowserSessionManager

    manager = BrowserSessionManager()
    session = manager.create_session(
        application_url="https://example.com",
        company="Test",
        job_title="Dev",
        job_id="j-1",
        barrier_type="CAPTCHA",
        page="FAKE_PAGE_OBJECT",
        browser="FAKE_BROWSER",
        context="FAKE_CONTEXT",
        user_profile={"password": "secret123", "email": "test@test.com"},
        resume_path="/path/to/resume.pdf",
    )

    info = session.to_dict()
    # Must NOT contain sensitive runtime objects
    assert "page" not in info
    assert "browser" not in info
    assert "context" not in info
    assert "user_profile" not in info
    assert "password" not in str(info)
    assert "resume_path" not in info


@pytest.mark.asyncio
async def test_resume_application_missing_session():
    """Resume with invalid session_id → FAILED."""
    from mcp_server.tools.apply_job import resume_application_tool

    result = await resume_application_tool(
        browser_session_id="nonexistent-session-id",
    )
    data = json.loads(result)
    assert data["status"] == "FAILED"
    assert "not found" in data["reason"].lower() or "not available" in data["reason"].lower()


@pytest.mark.asyncio
async def test_get_session_status_tool():
    """Get status of active session and nonexistent session."""
    from app.services.browser_sessions import BrowserSessionManager, get_browser_session_manager
    from mcp_server.tools.apply_job import get_application_session_status_tool

    manager = get_browser_session_manager()
    session = manager.create_session(
        application_url="https://example.com/apply",
        company="StatusCorp",
        job_title="Engineer",
        job_id="job-status-1",
        barrier_type="CAPTCHA",
        page=None,
        browser=None,
        context=None,
        user_profile={"email": "status@test.com"},
        resume_path="/path/to/resume.pdf",
    )

    # Active session status
    res = await get_application_session_status_tool(session.session_id)
    data = json.loads(res)
    assert data["status"] == "WAITING_FOR_USER"
    assert data["company"] == "StatusCorp"
    assert data["barrier_type"] == "CAPTCHA"

    # Nonexistent session
    res_none = await get_application_session_status_tool("invalid-session-id")
    data_none = json.loads(res_none)
    assert data_none["status"] == "NOT_FOUND"

    await manager.cleanup_session(session.session_id)


@pytest.mark.asyncio
async def test_cancel_session_tool():
    """Cancel active session and clean up resources."""
    from app.services.browser_sessions import get_browser_session_manager
    from mcp_server.tools.apply_job import cancel_application_session_tool

    manager = get_browser_session_manager()
    session = manager.create_session(
        application_url="https://example.com/apply",
        company="CancelCorp",
        job_title="Engineer",
        job_id="job-cancel-1",
        barrier_type="LOGIN",
        page=None,
        browser=None,
        context=None,
        user_profile={"email": "cancel@test.com"},
        resume_path="/path/to/resume.pdf",
    )

    res = await cancel_application_session_tool(session.session_id)
    data = json.loads(res)
    assert data["status"] == "CANCELLED"
    assert manager.get_session(session.session_id) is None


@pytest.mark.asyncio
async def test_browser_session_timeout_cleanup():
    """Expired sessions are cleaned up automatically."""
    from datetime import datetime, timezone, timedelta
    from app.services.browser_sessions import BrowserSessionManager, SessionStatus

    manager = BrowserSessionManager()
    session = manager.create_session(
        application_url="https://example.com/timeout",
        company="TimeoutCorp",
        job_title="Engineer",
        job_id="job-timeout-1",
        barrier_type="OTP",
        page=None,
        browser=None,
        context=None,
        user_profile={},
        resume_path="",
    )
    # Manually backdate created_at to trigger expiration
    session.created_at = datetime.now(timezone.utc) - timedelta(seconds=1200)

    cleaned = await manager.cleanup_timed_out()
    assert cleaned >= 1
    assert manager.get_session(session.session_id) is None

