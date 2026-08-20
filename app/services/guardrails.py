"""Guardrails: duplicate prevention, rate limits, URL validation, and resume verification."""

import re
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.repository import Repository
from app.schemas import MatchedJob
from app.services.resume_storage import verify_resume_integrity

settings = get_settings()

URL_PATTERN = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)


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
        return bool(parsed.netloc and parsed.scheme in ("http", "https"))

    async def can_apply(
        self,
        user_id: str,
        job: MatchedJob,
        resume_file_path: str | None = None,
        expected_resume_hash: str | None = None,
    ) -> tuple[bool, str]:
        # 1. URL validity check
        if not self.is_valid_url(job.application_url):
            return False, "Invalid application URL scheme or structure"

        # 2. Company check
        if not job.company or len(job.company.strip()) < 2:
            return False, "Invalid or missing company name"

        # 3. Job title check
        if not job.title or len(job.title.strip()) < 3:
            return False, "Invalid or missing job title"

        # 4. Threshold check
        if job.match_score < self.settings.match_threshold:
            return False, f"Match score {job.match_score} is below threshold {self.settings.match_threshold}"

        # 5. Resume integrity check
        if resume_file_path and expected_resume_hash:
            if not verify_resume_integrity(resume_file_path, expected_resume_hash):
                return False, "Original resume integrity verification failed"

        # 6. Duplicate application check
        existing = await self.repo.get_application_by_user_job(user_id, job.job_id)
        if existing and existing.status == "SUCCESS":
            return False, f"Already successfully applied to this job on {existing.applied_at}"

        # 7. Same company cooldown
        if await self.repo.has_recent_company_application(
            user_id, job.company, self.settings.same_company_cooldown_days
        ):
            return False, f"Cooldown active: Already applied to {job.company} within past {self.settings.same_company_cooldown_days} days"

        # 8. Daily count limit
        daily = await self.repo.get_daily_count(user_id)
        if daily >= self.settings.max_applications_per_day:
            return False, f"Daily limit of {self.settings.max_applications_per_day} applications reached"

        return True, "OK"

    async def record_application_attempt(self, user_id: str) -> None:
        await self.repo.increment_daily_count(user_id)
