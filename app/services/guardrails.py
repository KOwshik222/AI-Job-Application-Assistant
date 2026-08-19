"""Guardrails: duplicate prevention, rate limits, URL validation."""

import re
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.repository import Repository
from app.schemas import MatchedJob

settings = get_settings()

URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)


class GuardrailViolation(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class Guardrails:
    def __init__(self, session: AsyncSession):
        self.repo = Repository(session)
        self.settings = get_settings()

    @staticmethod
    def is_valid_url(url: str) -> bool:
        if not url or not URL_PATTERN.match(url):
            return False
        parsed = urlparse(url)
        return bool(parsed.netloc)

    async def can_apply(self, user_id: str, job: MatchedJob) -> tuple[bool, str]:
        if not self.is_valid_url(job.application_url):
            return False, "Invalid application URL"

        existing = await self.repo.get_application_by_user_job(user_id, job.job_id)
        if existing:
            return False, f"Duplicate application (status: {existing.status})"

        if await self.repo.has_recent_company_application(
            user_id, job.company, self.settings.same_company_cooldown_days
        ):
            return False, f"Already applied to {job.company} recently"

        daily = await self.repo.get_daily_count(user_id)
        if daily >= self.settings.max_applications_per_day:
            return False, f"Daily limit of {self.settings.max_applications_per_day} reached"

        return True, "OK"

    async def record_application_attempt(self, user_id: str) -> None:
        await self.repo.increment_daily_count(user_id)
