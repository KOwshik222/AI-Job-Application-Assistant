"""Browser session management for human-in-the-loop workflows.

Tracks active browser sessions so users can complete manual actions
(CAPTCHA, login, OTP, MFA, 2FA) and resume the application flow.

NEVER stores: cookies, passwords, OTPs, authentication credentials.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class SessionStatus(str, Enum):
    WAITING_FOR_USER = "WAITING_FOR_USER"
    USER_COMPLETED = "USER_COMPLETED"
    RESUMED = "RESUMED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


@dataclass
class BrowserSession:
    """Tracks an active browser session for human-in-the-loop."""
    session_id: str
    application_url: str
    company: str
    job_title: str
    job_id: str
    barrier_type: str
    status: SessionStatus
    created_at: datetime
    page: Any = field(default=None, repr=False)  # Playwright page object
    browser: Any = field(default=None, repr=False)  # Playwright browser
    context: Any = field(default=None, repr=False)  # Playwright browser context
    user_profile: dict = field(default_factory=dict, repr=False)
    resume_path: str = ""
    expected_resume_hash: str = ""

    def to_dict(self) -> dict:
        """Return session info (never includes page/browser/credentials)."""
        return {
            "browser_session_id": self.session_id,
            "application_url": self.application_url,
            "company": self.company,
            "job_title": self.job_title,
            "job_id": self.job_id,
            "barrier_type": self.barrier_type,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
        }


class BrowserSessionManager:
    """Manages active browser sessions for human-in-the-loop workflows.
    
    Lifecycle:
        1. Security barrier detected → create_session() → browser stays open
        2. User completes manual action in browser
        3. User clicks "Continue Application" → get_session() → resume
        4. cleanup_session() after SUCCESS/FAILED/timeout
    """

    def __init__(self):
        self._sessions: dict[str, BrowserSession] = {}
        self._cleanup_task: asyncio.Task | None = None

    def create_session(
        self,
        application_url: str,
        company: str,
        job_title: str,
        job_id: str,
        barrier_type: str,
        page: Any,
        browser: Any,
        context: Any,
        user_profile: dict,
        resume_path: str,
        expected_resume_hash: str = "",
    ) -> BrowserSession:
        """Create a new browser session when a security barrier is detected."""
        session_id = str(uuid.uuid4())
        session = BrowserSession(
            session_id=session_id,
            application_url=application_url,
            company=company,
            job_title=job_title,
            job_id=job_id,
            barrier_type=barrier_type,
            status=SessionStatus.WAITING_FOR_USER,
            created_at=datetime.now(timezone.utc),
            page=page,
            browser=browser,
            context=context,
            user_profile=user_profile,
            resume_path=resume_path,
            expected_resume_hash=expected_resume_hash,
        )
        self._sessions[session_id] = session
        logger.info(
            "Browser session created: %s for %s at %s (barrier: %s)",
            session_id, company, application_url, barrier_type,
        )
        return session

    def get_session(self, session_id: str) -> BrowserSession | None:
        """Get a browser session by ID."""
        return self._sessions.get(session_id)

    def list_active_sessions(self) -> list[dict]:
        """List all active (waiting) sessions."""
        return [
            s.to_dict() for s in self._sessions.values()
            if s.status == SessionStatus.WAITING_FOR_USER
        ]

    async def cleanup_session(self, session_id: str) -> None:
        """Clean up a browser session — close browser, remove from tracking."""
        session = self._sessions.pop(session_id, None)
        if not session:
            return

        logger.info("Cleaning up browser session: %s", session_id)
        try:
            if session.browser:
                await session.browser.close()
        except Exception as exc:
            logger.debug("Browser close error (non-fatal): %s", exc)
        session.page = None
        session.browser = None
        session.context = None

    async def cleanup_timed_out(self) -> int:
        """Clean up sessions that have exceeded the timeout."""
        now = datetime.now(timezone.utc)
        timeout_seconds = settings.browser_session_timeout
        timed_out = []

        for sid, session in self._sessions.items():
            if session.status == SessionStatus.WAITING_FOR_USER:
                elapsed = (now - session.created_at).total_seconds()
                if elapsed > timeout_seconds:
                    session.status = SessionStatus.TIMED_OUT
                    timed_out.append(sid)

        for sid in timed_out:
            logger.info("Session %s timed out after %ds", sid, timeout_seconds)
            await self.cleanup_session(sid)

        return len(timed_out)

    async def cleanup_all(self) -> None:
        """Clean up all sessions (shutdown)."""
        session_ids = list(self._sessions.keys())
        for sid in session_ids:
            await self.cleanup_session(sid)


# Module-level singleton
_session_manager: BrowserSessionManager | None = None


def get_browser_session_manager() -> BrowserSessionManager:
    """Get or create the singleton browser session manager."""
    global _session_manager
    if _session_manager is None:
        _session_manager = BrowserSessionManager()
    return _session_manager
