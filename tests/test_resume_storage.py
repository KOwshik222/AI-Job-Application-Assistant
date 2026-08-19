"""Tests for resume storage service."""

import os
import tempfile

import pytest

from app.services.resume_storage import compute_file_hash, verify_resume_integrity


def test_compute_file_hash(sample_pdf_path):
    hash1 = compute_file_hash(sample_pdf_path)
    assert isinstance(hash1, str)
    assert len(hash1) == 64  # SHA256 hex


def test_compute_file_hash_deterministic(sample_pdf_path):
    hash1 = compute_file_hash(sample_pdf_path)
    hash2 = compute_file_hash(sample_pdf_path)
    assert hash1 == hash2


def test_verify_resume_integrity_valid(sample_pdf_path):
    expected = compute_file_hash(sample_pdf_path)
    assert verify_resume_integrity(sample_pdf_path, expected) is True


def test_verify_resume_integrity_invalid(sample_pdf_path):
    assert verify_resume_integrity(sample_pdf_path, "wrong_hash") is False


def test_verify_resume_integrity_missing_file():
    assert verify_resume_integrity("/nonexistent/file.pdf", "abc") is False


def test_different_files_different_hashes(sample_pdf_path):
    hash1 = compute_file_hash(sample_pdf_path)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(b"completely different content")
        tmp_path = tmp.name

    try:
        hash2 = compute_file_hash(tmp_path)
        assert hash1 != hash2
    finally:
        os.remove(tmp_path)
