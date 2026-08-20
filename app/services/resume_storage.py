"""Immutable resume storage — original PDF is never modified.

Provides SHA-256 integrity verification before every application.
"""

import hashlib
import uuid
from pathlib import Path

import aiofiles
from langsmith import traceable

from app.config import get_settings

settings = get_settings()


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
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


@traceable(name="verify_resume_integrity")
def verify_resume_integrity(file_path: str, expected_hash: str) -> dict:
    """Verify original resume integrity via SHA-256 comparison.
    
    Returns structured result:
        {
            "valid": True/False,
            "expected_hash": "...",
            "actual_hash": "...",
            "reason": "..."
        }
    
    If mismatch: the file must NOT be uploaded.
    """
    path = Path(file_path)

    if not path.exists():
        return {
            "valid": False,
            "expected_hash": expected_hash,
            "actual_hash": "",
            "reason": f"Resume file not found at: {file_path}",
        }

    actual_hash = compute_file_hash(path)

    if actual_hash == expected_hash:
        return {
            "valid": True,
            "expected_hash": expected_hash,
            "actual_hash": actual_hash,
            "reason": "SHA-256 matches original upload",
        }

    return {
        "valid": False,
        "expected_hash": expected_hash,
        "actual_hash": actual_hash,
        "reason": (
            "Original resume integrity check failed — "
            "file has been modified since upload. "
            f"Expected SHA-256: {expected_hash[:16]}..., "
            f"Actual SHA-256: {actual_hash[:16]}..."
        ),
    }
