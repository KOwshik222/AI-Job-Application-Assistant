"""Tests for RAG pipeline (loader, keyword matcher, vectorstore)."""

import pytest

from app.rag.keyword_matcher import keyword_match_job
from app.rag.loader import load_and_chunk_resume
from app.schemas import JobListing, UserProfile


def test_load_and_chunk_resume(sample_pdf_path):
    chunks = load_and_chunk_resume(sample_pdf_path)
    assert len(chunks) > 0
    assert all(c.chunk_id for c in chunks)
    assert all(c.content for c in chunks)


def test_load_and_chunk_resume_metadata(sample_pdf_path):
    chunks = load_and_chunk_resume(sample_pdf_path)
    for chunk in chunks:
        assert "source" in chunk.metadata


def test_keyword_match_high_score(sample_user_profile):
    job = JobListing(
        title="Senior Java Developer",
        company="Infosys",
        location="Pune",
        description="Java, Spring Boot, Microservices, SQL. 3+ years experience required.",
        application_url="https://careers.infosys.com/java-dev",
    )
    resume_text = "Java Spring Boot Microservices SQL PostgreSQL REST APIs"
    result = keyword_match_job(job, sample_user_profile, resume_text)

    assert result.match_score > 50
    assert len(result.matching_skills) > 0
    assert result.company == "Infosys"
    assert result.title == "Senior Java Developer"


def test_keyword_match_low_score():
    profile = UserProfile(
        role="Data Scientist",
        skills=["Python", "TensorFlow"],
        experience=2,
        locations=["Delhi"],
        email="ds@test.com",
    )
    job = JobListing(
        title="COBOL Developer",
        company="LegacyCorp",
        location="Mumbai",
        description="COBOL mainframe banking system. 10+ years required.",
        application_url="https://legacycorp.com/apply",
    )
    result = keyword_match_job(job, profile, "Python TensorFlow machine learning")
    assert result.match_score < 80


def test_keyword_match_location_bonus(sample_user_profile):
    job = JobListing(
        title="Java Developer",
        company="TestCo",
        location="Pune",
        description="Java Spring Boot developer needed.",
        application_url="https://testco.com/apply",
    )
    result = keyword_match_job(job, sample_user_profile, "Java Spring Boot")
    # Location match should give bonus
    assert result.match_score >= 50


def test_keyword_match_returns_matched_job(sample_user_profile):
    job = JobListing(
        title="Backend Engineer",
        company="ABC Corp",
        location="Bangalore",
        description="Java microservices",
        application_url="https://abc.com/apply",
    )
    result = keyword_match_job(job, sample_user_profile, "Java Spring Boot")
    assert result.application_url == "https://abc.com/apply"
    assert result.match_rationale != ""
