"""Data access layer."""

import json
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Application,
    ApplicationLog,
    DailyApplicationCount,
    Job,
    ManualAction,
    Resume,
    User,
)
from app.schemas import JobListing, ManualActionItem, MatchedJob, UserProfile


class Repository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create_user(self, email: str, preferences: dict | None = None) -> User:
        result = await self.session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            return user
        user = User(email=email, preferences=json.dumps(preferences or {}))
        self.session.add(user)
        await self.session.flush()
        return user

    async def create_resume(self, user_id: str, file_path: str, file_hash: str) -> Resume:
        resume = Resume(user_id=user_id, file_path=file_path, file_hash=file_hash)
        self.session.add(resume)
        await self.session.flush()
        return resume

    async def get_resume(self, resume_id: str) -> Resume | None:
        result = await self.session.execute(select(Resume).where(Resume.resume_id == resume_id))
        return result.scalar_one_or_none()

    async def get_resume_by_hash(self, user_id: str, file_hash: str) -> Resume | None:
        result = await self.session.execute(
            select(Resume).where(Resume.user_id == user_id, Resume.file_hash == file_hash)
        )
        return result.scalar_one_or_none()

    async def upsert_job(self, listing: JobListing) -> Job:
        result = await self.session.execute(
            select(Job).where(Job.company == listing.company, Job.url == listing.application_url)
        )
        job = result.scalar_one_or_none()
        if job:
            listing.job_id = job.job_id
            return job
        try:
            async with self.session.begin_nested():
                job = Job(
                    title=listing.title,
                    company=listing.company,
                    location=listing.location,
                    description=listing.description,
                    url=listing.application_url,
                    source=listing.source,
                )
                self.session.add(job)
                await self.session.flush()
                listing.job_id = job.job_id
                return job
        except Exception:
            result = await self.session.execute(
                select(Job).where(Job.company == listing.company, Job.url == listing.application_url)
            )
            job = result.scalar_one_or_none()
            if job:
                listing.job_id = job.job_id
                return job
            raise

    async def create_application(
        self,
        user_id: str,
        job_id: str,
        resume_id: str,
        status: str,
        match_score: int | None,
        run_id: str,
    ) -> Application:
        existing = await self.get_application_by_user_job(user_id, job_id)
        if existing:
            existing.status = status
            existing.match_score = match_score
            existing.run_id = run_id
            if status == "SUCCESS":
                existing.applied_at = datetime.now(UTC)
            await self.session.flush()
            return existing

        try:
            async with self.session.begin_nested():
                app = Application(
                    user_id=user_id,
                    job_id=job_id,
                    resume_id=resume_id,
                    status=status,
                    match_score=match_score,
                    applied_at=datetime.now(UTC) if status == "SUCCESS" else None,
                    run_id=run_id,
                )
                self.session.add(app)
                await self.session.flush()
                return app
        except Exception:
            existing = await self.get_application_by_user_job(user_id, job_id)
            if existing:
                existing.status = status
                existing.match_score = match_score
                existing.run_id = run_id
                await self.session.flush()
                return existing
            raise

    async def get_application_by_user_job(self, user_id: str, job_id: str) -> Application | None:
        result = await self.session.execute(
            select(Application).where(Application.user_id == user_id, Application.job_id == job_id)
        )
        return result.scalar_one_or_none()

    async def has_recent_company_application(
        self, user_id: str, company: str, cooldown_days: int
    ) -> bool:
        cutoff = datetime.now(UTC) - timedelta(days=cooldown_days)
        result = await self.session.execute(
            select(Application)
            .join(Job, Application.job_id == Job.job_id)
            .where(
                Application.user_id == user_id,
                Job.company == company,
                Application.status == "SUCCESS",
                Application.applied_at >= cutoff,
            )
        )
        return result.scalar_one_or_none() is not None

    async def get_daily_count(self, user_id: str) -> int:
        today = date.today()
        result = await self.session.execute(
            select(DailyApplicationCount).where(
                DailyApplicationCount.user_id == user_id,
                DailyApplicationCount.application_date == today,
            )
        )
        row = result.scalar_one_or_none()
        return row.count if row else 0

    async def increment_daily_count(self, user_id: str) -> int:
        today = date.today()
        result = await self.session.execute(
            select(DailyApplicationCount).where(
                DailyApplicationCount.user_id == user_id,
                DailyApplicationCount.application_date == today,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.count += 1
            new_count = row.count
        else:
            row = DailyApplicationCount(user_id=user_id, application_date=today, count=1)
            self.session.add(row)
            new_count = 1
        await self.session.flush()
        return new_count

    async def create_manual_action(
        self,
        user_id: str,
        item: ManualActionItem,
        application_id: str | None = None,
    ) -> ManualAction:
        action = ManualAction(
            user_id=user_id,
            application_id=application_id,
            company=item.company,
            url=item.job_url,
            reason=item.reason,
            status=item.status,
        )
        self.session.add(action)
        await self.session.flush()
        return action

    async def log_event(
        self,
        run_id: str,
        user_id: str,
        agent_name: str,
        event_type: str,
        payload: dict,
    ) -> None:
        log = ApplicationLog(
            run_id=run_id,
            user_id=user_id,
            agent_name=agent_name,
            event_type=event_type,
            payload=json.dumps(payload),
        )
        self.session.add(log)

    async def list_applications(
        self,
        user_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[tuple[Application, Job]], int]:
        query = (
            select(Application, Job)
            .join(Job, Application.job_id == Job.job_id)
            .where(Application.user_id == user_id)
        )
        if status:
            query = query.where(Application.status == status)
        result = await self.session.execute(
            query.order_by(Application.applied_at.desc().nullslast(), Application.application_id.desc())
        )
        rows = result.all()
        total = len(rows)
        return rows[offset : offset + limit], total

    async def list_manual_actions(
        self, user_id: str, status: str | None = None
    ) -> list[ManualAction]:
        query = select(ManualAction).where(ManualAction.user_id == user_id)
        if status:
            query = query.where(ManualAction.status == status)
        result = await self.session.execute(query.order_by(ManualAction.created_at.desc()))
        return list(result.scalars().all())

    async def get_job(self, job_id: str) -> Job | None:
        result = await self.session.execute(select(Job).where(Job.job_id == job_id))
        return result.scalar_one_or_none()

    async def commit(self) -> None:
        await self.session.commit()
