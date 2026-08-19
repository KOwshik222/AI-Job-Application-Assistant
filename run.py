"""Start the AI Job Application Assistant."""

import subprocess
import sys
import asyncio
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

ROOT = Path(__file__).resolve().parent


def main():
    # Generate sample resume if missing
    sample = ROOT / "static" / "assets" / "sample_resume.pdf"
    if not sample.exists():
        print("Generating sample resume...")
        try:
            subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_sample_resume.py")], check=True)
        except Exception:
            print("Warning: Could not generate sample resume. Install fpdf2: pip install fpdf2")

    import uvicorn

    print("\n  AI Job Application Assistant")
    print("  http://localhost:8000\n")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
