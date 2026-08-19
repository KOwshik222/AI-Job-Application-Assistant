"""MCP tool: send_email — application summary report."""

import json
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def _build_html(summary: dict) -> str:
    pending = summary.get("pending_manual_jobs", [])
    pending_html = ""
    for job in pending:
        pending_html += f"""
        <li><strong>{job.get('company')}</strong><br/>
        URL: <a href="{job.get('job_url')}">{job.get('job_url')}</a><br/>
        Reason: {job.get('reason')}</li>"""

    applied = summary.get("applied_jobs", [])
    applied_html = ""
    for job in applied:
        applied_html += f"<li>{job.get('company')} — {job.get('status', 'SUCCESS')}</li>"

    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
    <h2>Job Application Summary</h2>
    <p>Run ID: {summary.get('run_id', 'N/A')}</p>
    <ul>
      <li><strong>Applied Successfully:</strong> {summary.get('applied_successfully', 0)}</li>
      <li><strong>Manual Action Required:</strong> {summary.get('manual_action_required', 0)}</li>
      <li><strong>Failed Applications:</strong> {summary.get('failed', 0)}</li>
    </ul>
    <h3>Applied Jobs</h3>
    <ol>{applied_html or '<li>None</li>'}</ol>
    <h3>Pending Manual Jobs</h3>
    <ol>{pending_html or '<li>None</li>'}</ol>
    </body></html>
    """


def _save_local_copy(run_id: str, to_email: str, subject: str, html: str) -> Path:
    log_dir = settings.data_dir / "email_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{run_id}.html"
    header = f"<!-- To: {to_email} | Subject: {subject} -->\n"
    path.write_text(header + html, encoding="utf-8")
    return path


def is_smtp_configured() -> bool:
    return bool(settings.smtp_user and settings.smtp_password)


async def send_email_tool(to_email: str, subject: str, summary: dict) -> str:
    html = _build_html(summary)
    run_id = summary.get("run_id", "unknown")

    if not is_smtp_configured():
        path = _save_local_copy(run_id, to_email, subject, html)
        logger.warning(
            "SMTP not configured — email saved locally: %s (intended recipient: %s)",
            path,
            to_email,
        )
        return json.dumps({
            "status": "NOT_CONFIGURED",
            "delivered": False,
            "message_id": None,
            "local_log": str(path),
            "note": (
                "SMTP is not configured. Summary saved to data/email_logs/. "
                "Set SMTP_USER and SMTP_PASSWORD in .env to send real emails."
            ),
            "to_email": to_email,
        })

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(msg["From"], [to_email], msg.as_string())
        logger.info("Email sent to %s for run %s", to_email, run_id)
        _save_local_copy(run_id, to_email, subject, html)
        return json.dumps({
            "status": "SENT",
            "delivered": True,
            "message_id": f"run-{run_id[:8]}",
            "to_email": to_email,
        })
    except Exception as exc:
        logger.error("Email failed for run %s: %s", run_id, exc)
        path = _save_local_copy(run_id, to_email, subject, html)
        return json.dumps({
            "status": "FAILED",
            "delivered": False,
            "reason": str(exc),
            "local_log": str(path),
            "note": f"SMTP error: {exc}. Summary saved locally at {path}",
            "to_email": to_email,
        })
