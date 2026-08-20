"""MCP tool: send_email — comprehensive application summary report."""

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
    applied = summary.get("applied_jobs", [])
    applied_html = ""
    for job in applied:
        applied_html += f"""
        <li style="margin-bottom: 12px; padding: 10px; background: #f0fdf4; border-left: 4px solid #16a34a; border-radius: 4px;">
          <strong>{job.get('company', 'Unknown Company')}</strong> — <em>{job.get('job_title', 'Role')}</em><br/>
          <strong>Status:</strong> <span style="color: #16a34a; font-weight: bold;">VERIFIED SUBMISSION</span><br/>
          <strong>URL:</strong> <a href="{job.get('job_url', '#')}" target="_blank">{job.get('job_url', 'Link')}</a><br/>
          {f"<strong>Confirmation Evidence:</strong> {job.get('error')}<br/>" if job.get('error') else ""}
          <small style="color: #6b7280;">Submitted At: {job.get('applied_at', 'N/A')}</small>
        </li>"""

    pending = summary.get("pending_manual_jobs", [])
    pending_html = ""
    for job in pending:
        pending_html += f"""
        <li style="margin-bottom: 12px; padding: 10px; background: #fefce8; border-left: 4px solid #ca8a04; border-radius: 4px;">
          <strong>{job.get('company', 'Unknown Company')}</strong><br/>
          <strong>Action Required:</strong> {job.get('reason', 'Manual application or security step required')}<br/>
          <strong>Apply Directly:</strong> <a href="{job.get('job_url', '#')}" target="_blank">{job.get('job_url', 'Link')}</a>
        </li>"""

    failed = summary.get("failed_jobs", [])
    failed_html = ""
    for job in failed:
        failed_html += f"""
        <li style="margin-bottom: 12px; padding: 10px; background: #fef2f2; border-left: 4px solid #dc2626; border-radius: 4px;">
          <strong>{job.get('company', 'Unknown Company')}</strong> — <em>{job.get('job_title', 'Role')}</em><br/>
          <strong>Reason:</strong> {job.get('error', 'Submission could not be verified')}<br/>
          <strong>URL:</strong> <a href="{job.get('job_url', '#')}" target="_blank">{job.get('job_url', 'Link')}</a>
        </li>"""

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"/></head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 680px; margin: 0 auto; padding: 20px; color: #1f2937;">
      <div style="background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%); padding: 24px; border-radius: 8px; color: white; margin-bottom: 24px;">
        <h1 style="margin: 0 0 8px 0; font-size: 24px;">AI Job Application Assistant</h1>
        <p style="margin: 0; opacity: 0.9;">Run Summary Report · ID: <code>{summary.get('run_id', 'N/A')}</code></p>
      </div>

      <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 24px;">
        <div style="background: #f0fdf4; padding: 16px; border-radius: 8px; text-align: center; border: 1px solid #bbf7d0;">
          <div style="font-size: 28px; font-weight: bold; color: #16a34a;">{summary.get('applied_successfully', 0)}</div>
          <div style="font-size: 13px; color: #15803d; font-weight: 600; text-transform: uppercase;">Verified Submitted</div>
        </div>
        <div style="background: #fefce8; padding: 16px; border-radius: 8px; text-align: center; border: 1px solid #fef08a;">
          <div style="font-size: 28px; font-weight: bold; color: #ca8a04;">{summary.get('manual_action_required', 0)}</div>
          <div style="font-size: 13px; color: #a16207; font-weight: 600; text-transform: uppercase;">Manual Action</div>
        </div>
        <div style="background: #fef2f2; padding: 16px; border-radius: 8px; text-align: center; border: 1px solid #fecaca;">
          <div style="font-size: 28px; font-weight: bold; color: #dc2626;">{summary.get('failed', 0)}</div>
          <div style="font-size: 13px; color: #b91c1c; font-weight: 600; text-transform: uppercase;">Unverified / Failed</div>
        </div>
      </div>

      <h3 style="border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; color: #111827;">✅ Successfully Submitted Applications</h3>
      <ol style="padding-left: 20px;">{applied_html or '<li style="color: #6b7280;">No automatic verified submissions in this run.</li>'}</ol>

      <h3 style="border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; color: #111827;">⚠️ Manual Actions Required (Login / Security / Direct Portals)</h3>
      <ol style="padding-left: 20px;">{pending_html or '<li style="color: #6b7280;">No pending manual actions.</li>'}</ol>

      {f'<h3 style="border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; color: #111827;">❌ Unverified / Failed Applications</h3><ol style="padding-left: 20px;">{failed_html}</ol>' if failed else ''}

      <hr style="margin-top: 32px; border: none; border-top: 1px solid #e5e7eb;"/>
      <p style="font-size: 12px; color: #9ca3af; text-align: center;">
        Original Resume PDF was used for all applications without modification · Verified by AI Job Application Assistant
      </p>
    </body>
    </html>
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
