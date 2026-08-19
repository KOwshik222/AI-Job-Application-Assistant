"""Generate a sample resume PDF for demo purposes."""

from pathlib import Path

try:
    from fpdf import FPDF
except ImportError:
    print("Install fpdf2: pip install fpdf2")
    raise

SAMPLE_TEXT = """JOHN DOE
Java Developer | john.doe@email.com | +91 98765 43210

SUMMARY
Experienced Java Developer with 3+ years building enterprise applications
using Java, Spring Boot, Microservices, and SQL databases.

SKILLS
Java, Spring Boot, Spring MVC, Microservices, REST APIs, SQL, PostgreSQL,
Maven, Git, Agile/Scrum, JUnit, Docker

EXPERIENCE
Software Engineer - ABC Technologies (2022-Present)
- Developed microservices using Java 17 and Spring Boot
- Built REST APIs serving 10K+ daily requests
- Optimized SQL queries reducing response time by 40%

Junior Developer - XYZ Solutions (2020-2022)
- Maintained Java web applications
- Wrote unit tests with JUnit and Mockito

EDUCATION
B.Tech Computer Science - Pune University (2020)
"""


def generate(output_path: Path) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in SAMPLE_TEXT.strip().split("\n"):
        pdf.cell(0, 7, line, new_x="LMARGIN", new_y="NEXT")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))
    print(f"Created {output_path}")


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "static" / "assets" / "sample_resume.pdf"
    generate(out)
