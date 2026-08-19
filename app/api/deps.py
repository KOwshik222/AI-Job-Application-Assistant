"""FastAPI route dependencies."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session

__all__ = ["get_db"]


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_session():
        yield session
