"""Shared test fixtures."""

import os
# Force default settings values for tests to avoid local .env interference
os.environ["MAX_APPLICATIONS_PER_DAY"] = "20"
os.environ["MATCH_THRESHOLD"] = "75"
os.environ["SAME_COMPANY_COOLDOWN_DAYS"] = "30"
os.environ["DEMO_MODE"] = "true"

# Disable external service integrations for test stability and speed
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["SMTP_USER"] = ""
os.environ["SMTP_PASSWORD"] = ""
os.environ["TAVILY_API_KEY"] = ""

import tempfile

import pytest
from fpdf import FPDF

from app.schemas import UserProfile


@pytest.fixture
def sample_pdf_path():
    """Create a temporary sample resume PDF."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.cell(200, 10, text="John Doe - Java Developer", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(200, 10, text="Skills: Java, Spring Boot, Microservices, SQL", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(200, 10, text="Experience: 3 years at ABC Technologies", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(200, 10, text="Education: B.Tech Computer Science", new_x="LMARGIN", new_y="NEXT")
        pdf.output(tmp.name)
        tmp_path = tmp.name

    yield tmp_path

    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except Exception:
            pass


@pytest.fixture
def sample_user_profile():
    """Create a sample user profile for testing."""
    return UserProfile(
        role="Java Developer",
        skills=["Java", "Spring Boot", "Microservices", "SQL"],
        experience=3,
        locations=["Pune", "Mumbai", "Bangalore"],
        email="test@example.com",
        full_name="John Doe",
        phone="+91 98765 43210",
    )


@pytest.fixture
def sample_pdf_bytes(sample_pdf_path):
    """Return sample PDF file content as bytes."""
    with open(sample_pdf_path, "rb") as f:
        return f.read()
