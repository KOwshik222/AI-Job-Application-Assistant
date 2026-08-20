"""Tests for resume integrity verification.

Verifies:
- Original hash stored on upload
- Same file passes verification
- Modified file fails verification
- Different file fails verification
- Failed integrity check prevents application
"""

import os
import tempfile
import pytest

os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")


def test_compute_file_hash_deterministic(sample_pdf_path):
    """Same file should produce same hash every time."""
    from app.services.resume_storage import compute_file_hash
    from pathlib import Path

    hash1 = compute_file_hash(Path(sample_pdf_path))
    hash2 = compute_file_hash(Path(sample_pdf_path))
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex digest length


def test_verify_integrity_same_file_passes(sample_pdf_path):
    """Original file passes integrity check."""
    from app.services.resume_storage import compute_file_hash, verify_resume_integrity
    from pathlib import Path

    expected_hash = compute_file_hash(Path(sample_pdf_path))
    result = verify_resume_integrity(sample_pdf_path, expected_hash)

    assert result["valid"] is True
    assert result["expected_hash"] == expected_hash
    assert result["actual_hash"] == expected_hash
    assert "SHA-256 matches" in result["reason"]


def test_verify_integrity_modified_file_fails(sample_pdf_path):
    """Modified file fails integrity check."""
    from app.services.resume_storage import compute_file_hash, verify_resume_integrity
    from pathlib import Path

    # Get original hash
    original_hash = compute_file_hash(Path(sample_pdf_path))

    # Modify the file
    with open(sample_pdf_path, "ab") as f:
        f.write(b"\n%% TAMPERED CONTENT %%\n")

    # Verify should fail
    result = verify_resume_integrity(sample_pdf_path, original_hash)

    assert result["valid"] is False
    assert result["expected_hash"] == original_hash
    assert result["actual_hash"] != original_hash
    assert "integrity check failed" in result["reason"].lower()


def test_verify_integrity_different_file_fails():
    """Completely different file fails integrity check."""
    from app.services.resume_storage import verify_resume_integrity

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(b"This is a completely different file")
        tmp_path = tmp.name

    try:
        result = verify_resume_integrity(
            tmp_path,
            "0000000000000000000000000000000000000000000000000000000000000000",
        )
        assert result["valid"] is False
        assert result["actual_hash"] != result["expected_hash"]
    finally:
        os.remove(tmp_path)


def test_verify_integrity_missing_file_fails():
    """Missing file fails integrity check."""
    from app.services.resume_storage import verify_resume_integrity

    result = verify_resume_integrity(
        "/nonexistent/path/resume.pdf",
        "abc123",
    )
    assert result["valid"] is False
    assert "not found" in result["reason"].lower()


def test_verify_integrity_returns_structured_dict(sample_pdf_path):
    """Verify result is always a structured dict with required fields."""
    from app.services.resume_storage import compute_file_hash, verify_resume_integrity
    from pathlib import Path

    expected_hash = compute_file_hash(Path(sample_pdf_path))
    result = verify_resume_integrity(sample_pdf_path, expected_hash)

    # Must have all required fields
    assert "valid" in result
    assert "expected_hash" in result
    assert "actual_hash" in result
    assert "reason" in result
    assert isinstance(result["valid"], bool)
    assert isinstance(result["expected_hash"], str)
    assert isinstance(result["actual_hash"], str)
    assert isinstance(result["reason"], str)


@pytest.mark.asyncio
async def test_store_resume_and_verify():
    """End-to-end: store resume → verify → same hash."""
    from app.services.resume_storage import store_resume_pdf, verify_resume_integrity
    from fpdf import FPDF
    import io

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(200, 10, text="Test Resume Content", new_x="LMARGIN", new_y="NEXT")
    content = pdf.output()

    resume_id, file_path, file_hash = await store_resume_pdf(content, "test-user-integrity")

    assert resume_id
    assert file_hash
    assert len(file_hash) == 64

    # Verify integrity
    result = verify_resume_integrity(file_path, file_hash)
    assert result["valid"] is True

    # Clean up
    os.remove(file_path)
