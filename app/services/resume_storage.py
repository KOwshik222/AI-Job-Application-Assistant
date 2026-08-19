"""Immutable resume storage — original PDF is never modified."""

import hashlib
import shutil
import uuid
from pathlib import Path

import aiofiles

from app.config import get_settings

settings = get_settings()


def compute_file_hash(file_path: Path) -> str:
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


async def store_resume_pdf(content: bytes, user_id: str) -> tuple[str, str, str]:
    """Save original PDF unchanged. Returns (resume_id, file_path, file_hash)."""
    resume_id = str(uuid.uuid4())
    user_dir = settings.resume_dir / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    dest = user_dir / f"{resume_id}_original.pdf"

    async with aiofiles.open(dest, "wb") as f:
        await f.write(content)

    file_hash = compute_file_hash(dest)
    return resume_id, str(dest.resolve()), file_hash


def verify_resume_integrity(file_path: str, expected_hash: str) -> bool:
    path = Path(file_path)
    if not path.exists():
        return False
    return compute_file_hash(path) == expected_hash
