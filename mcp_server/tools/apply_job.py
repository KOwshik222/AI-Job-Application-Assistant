"""MCP tool: apply_job — browser automation with adapter architecture, verification, and human-in-the-loop."""

import json
import logging
import os
import re
import sys
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

MANUAL_TRIGGERS = [
    "captcha",
    "recaptcha",
    "hcaptcha",
    "turnstile",
    "cloudflare",
    "just a moment",
    "login",
    "sign in",
    "sign up",
    "register",
    "otp",
    "verification code",
    "multi-factor",
    "mfa",
    "two-factor",
    "2fa",
    "create an account",
]

CONFIRMATION_PATTERNS = [
    r"thank\s+you\s+for\s+applying",
    r"application\s+(?:has\s+been\s+)?submitted",
    r"application\s+received",
    r"we(?:\'ve|\s+have)\s+received\s+your\s+application",
    r"successfully\s+applied",
    r"application\s+confirmation",
    r"your\s+application\s+was\s+sent",
    r"thanks\s+for\s+your\s+interest",
    r"confirmation\s+(?:number|id|code|#)\s*:\s*[\w-]+",
]

CONFIRMATION_URL_PATTERNS = [
    r"/thanks",
    r"/thank-you",
    r"/thank_you",
    r"/confirmation",
    r"/success",
    r"/applied",
    r"/submitted",
]


def _compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    import hashlib
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


async def _detect_security_barrier(page) -> str | None:
    """Detect if page requires human intervention (CAPTCHA, Login, OTP, Cloudflare)."""
    try:
        content = (await page.content()).lower()
        for trigger in MANUAL_TRIGGERS:
            if trigger in content:
                return trigger.upper().replace(" ", "_")
    except Exception:
        pass
    return None


async def _verify_submission_success(page, initial_url: str) -> tuple[bool, str]:
    """Verify whether application was genuinely submitted based on page evidence."""
    current_url = page.url.lower()

    # 1. URL pattern check
    for pattern in CONFIRMATION_URL_PATTERNS:
        if re.search(pattern, current_url) and current_url != initial_url.lower():
            return True, f"Verified via confirmation URL: {page.url}"

    # 2. Text evidence check
    try:
        content = await page.content()
        for pattern in CONFIRMATION_PATTERNS:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                snippet = match.group(0)
                return True, f"Verified via confirmation text: '{snippet}'"
    except Exception:
        pass

    return False, "No confirmation message or redirect detected after submission."


class BaseApplicationAdapter:
    """Base adapter for portal automation."""

    def __init__(self, page, user_profile: dict, resume_path: Path):
        self.page = page
        self.profile = user_profile
        self.resume_path = resume_path

    async def fill_and_submit(self) -> tuple[bool, str, str | None]:
        """Returns (success, reason, confirmation_text)."""
        raise NotImplementedError


class GreenhouseAdapter(BaseApplicationAdapter):
    """Adapter for Greenhouse job boards (boards.greenhouse.io)."""

    async def fill_and_submit(self) -> tuple[bool, str, str | None]:
        # Split name into first and last
        full_name = self.profile.get("full_name", "").strip()
        name_parts = full_name.split()
        first_name = name_parts[0] if name_parts else "Candidate"
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else "Applicant"

        # First Name
        for sel in ["#first_name", 'input[name="job_application[first_name]"]', 'input[autocomplete="given-name"]']:
            el = await self.page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill(first_name)
                break

        # Last Name
        for sel in ["#last_name", 'input[name="job_application[last_name]"]', 'input[autocomplete="family-name"]']:
            el = await self.page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill(last_name)
                break

        # Email
        email = self.profile.get("email", "")
        for sel in ["#email", 'input[name="job_application[email]"]', 'input[type="email"]']:
            el = await self.page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill(email)
                break

        # Phone
        phone = self.profile.get("phone", "")
        if phone:
            for sel in ["#phone", 'input[name="job_application[phone]"]', 'input[type="tel"]']:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(phone)
                    break

        # Resume Upload
        for sel in ['input[data-qa="input-resume"]', '#resume', 'input[type="file"]']:
            file_input = await self.page.query_selector(sel)
            if file_input:
                await file_input.set_input_files(str(self.resume_path.resolve()))
                logger.info("📎 Resume attached in Greenhouse form.")
                break

        # Submit
        submit_btn = await self.page.query_selector('#submit_app, button[type="submit"], input[type="submit"]')
        if submit_btn and await submit_btn.is_visible():
            await submit_btn.click()
            await self.page.wait_for_timeout(4000)
            return True, "Submitted form", None

        return False, "Could not locate Greenhouse submit button", None


class LeverAdapter(BaseApplicationAdapter):
    """Adapter for Lever job boards (jobs.lever.co)."""

    async def fill_and_submit(self) -> tuple[bool, str, str | None]:
        full_name = self.profile.get("full_name", "").strip()
        email = self.profile.get("email", "")
        phone = self.profile.get("phone", "")

        # Name
        name_input = await self.page.query_selector('input[name="name"]')
        if name_input and await name_input.is_visible():
            await name_input.fill(full_name)

        # Email
        email_input = await self.page.query_selector('input[name="email"]')
        if email_input and await email_input.is_visible():
            await email_input.fill(email)

        # Phone
        if phone:
            phone_input = await self.page.query_selector('input[name="phone"]')
            if phone_input and await phone_input.is_visible():
                await phone_input.fill(phone)

        # Resume
        file_input = await self.page.query_selector('input[type="file"], input[name="resume"]')
        if file_input:
            await file_input.set_input_files(str(self.resume_path.resolve()))
            logger.info("📎 Resume attached in Lever form.")

        # Submit
        submit_btn = await self.page.query_selector('button[data-qa="btn-submit"], button[type="submit"], #btn-submit')
        if submit_btn and await submit_btn.is_visible():
            await submit_btn.click()
            await self.page.wait_for_timeout(4000)
            return True, "Submitted Lever form", None

        return False, "Could not locate Lever submit button", None


class GenericATSAdapter(BaseApplicationAdapter):
    """Generic form automation adapter with intelligent selector matching."""

    async def fill_and_submit(self) -> tuple[bool, str, str | None]:
        full_name = self.profile.get("full_name", "").strip()
        email = self.profile.get("email", "")
        phone = self.profile.get("phone", "")

        # 1. Resume upload
        file_inputs = await self.page.query_selector_all('input[type="file"]')
        if file_inputs:
            for fi in file_inputs:
                try:
                    await fi.set_input_files(str(self.resume_path.resolve()))
                    logger.info("📎 Resume file uploaded to file input.")
                    break
                except Exception:
                    continue

        # 2. Email
        if email:
            for sel in ['input[type="email"]', 'input[name*="email" i]', 'input[placeholder*="email" i]', 'input[id*="email" i]']:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    try:
                        await el.fill(email)
                        break
                    except Exception:
                        continue

        # 3. Name
        if full_name:
            # Check for first/last split
            first_name_input = await self.page.query_selector('input[name*="first" i], input[placeholder*="first" i]')
            last_name_input = await self.page.query_selector('input[name*="last" i], input[placeholder*="last" i]')
            if first_name_input and last_name_input and await first_name_input.is_visible() and await last_name_input.is_visible():
                name_parts = full_name.split()
                await first_name_input.fill(name_parts[0])
                await last_name_input.fill(" ".join(name_parts[1:]) if len(name_parts) > 1 else "")
            else:
                for sel in ['input[name*="name" i]', 'input[placeholder*="name" i]', 'input[id*="name" i]']:
                    el = await self.page.query_selector(sel)
                    if el and await el.is_visible():
                        try:
                            await el.fill(full_name)
                            break
                        except Exception:
                            continue

        # 4. Phone
        if phone:
            for sel in ['input[type="tel"]', 'input[name*="phone" i]', 'input[placeholder*="phone" i]', 'input[id*="phone" i]']:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    try:
                        await el.fill(phone)
                        break
                    except Exception:
                        continue

        # 5. Look for submit button
        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Submit Application")',
            'button:has-text("Apply Now")',
            'button:has-text("Send Application")',
            'button:has-text("Submit")',
        ]
        for sel in submit_selectors:
            btn = await self.page.query_selector(sel)
            if btn and await btn.is_visible():
                try:
                    await btn.click()
                    await self.page.wait_for_timeout(3500)
                    return True, "Clicked submit button", None
                except Exception as e:
                    logger.debug("Click failed on %s: %s", sel, e)

        return False, "No clickable submit button found on page", None


def _resolve_adapter(url: str, page, profile: dict, resume_path: Path) -> BaseApplicationAdapter:
    """Resolve the appropriate adapter based on URL domain."""
    domain = urlparse(url.lower()).netloc
    if "greenhouse.io" in domain:
        return GreenhouseAdapter(page, profile, resume_path)
    if "lever.co" in domain:
        return LeverAdapter(page, profile, resume_path)
    return GenericATSAdapter(page, profile, resume_path)


def _get_browser_headless() -> bool:
    """Read BROWSER_HEADLESS from environment (MCP server runs as separate process)."""
    val = os.environ.get("BROWSER_HEADLESS", "true").lower()
    return val not in ("false", "0", "no")


async def apply_job_tool(
    application_url: str,
    resume_file_path: str,
    user_profile: dict,
    company: str = "",
    job_title: str = "",
    expected_resume_hash: str = "",
    mock_mode: bool = False,
) -> str:
    """MCP tool: Apply to a specific job opening using the original resume PDF."""
    parsed = urlparse(application_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return json.dumps({
            "status": "FAILED",
            "company": company,
            "job_title": job_title,
            "application_url": application_url,
            "reason": "Invalid application URL scheme or hostname",
            "confirmation": "",
            "submitted_at": None,
            "resume_hash": "",
            "resume_used": str(resume_file_path),
        })

    resume_path = Path(resume_file_path)
    if not resume_path.exists():
        return json.dumps({
            "status": "FAILED",
            "company": company,
            "job_title": job_title,
            "application_url": application_url,
            "reason": "Original resume file not found on disk",
            "confirmation": "",
            "submitted_at": None,
            "resume_hash": "",
            "resume_used": str(resume_file_path),
        })

    # Verify resume integrity BEFORE any upload
    resume_hash = _compute_file_hash(resume_path)
    if expected_resume_hash and resume_hash != expected_resume_hash:
        return json.dumps({
            "status": "FAILED",
            "company": company,
            "job_title": job_title,
            "application_url": application_url,
            "reason": "Original resume integrity check failed — file hash does not match stored original",
            "confirmation": "",
            "submitted_at": None,
            "resume_hash": resume_hash,
            "resume_used": str(resume_file_path),
        })

    # In mock mode (e.g. unit testing or demo simulation), return mock result
    if mock_mode:
        url_lower = application_url.lower()
        if any(t in url_lower for t in ("login", "captcha", "signup", "auth")):
            return json.dumps({
                "status": "MANUAL_ACTION_REQUIRED",
                "company": company,
                "job_title": job_title,
                "application_url": application_url,
                "reason": "Login / Authentication required (mock mode)",
                "confirmation": "",
                "submitted_at": None,
                "resume_hash": resume_hash,
                "resume_used": str(resume_path.resolve()),
                "browser_session_id": "",
            })
        return json.dumps({
            "status": "SUCCESS",
            "company": company,
            "job_title": job_title,
            "application_url": application_url,
            "reason": "Application submitted (mock mode verification)",
            "confirmation": "Mock confirmation: Application received",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "resume_hash": resume_hash,
            "resume_used": str(resume_path.resolve()),
        })

    # --- REAL PRODUCTION PLAYWRIGHT BROWSER AUTOMATION ---
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return json.dumps({
            "status": "FAILED",
            "company": company,
            "job_title": job_title,
            "application_url": application_url,
            "reason": "Playwright is not installed in the environment",
            "confirmation": "",
            "submitted_at": None,
            "resume_hash": resume_hash,
        })

    headless = _get_browser_headless()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            slow_mo=200,
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        try:
            logger.info("🌐 Navigating to job URL: %s (%s at %s)", application_url, job_title, company)
            await page.goto(application_url, timeout=25000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            # 1. Check for security barrier / login / captcha
            barrier = await _detect_security_barrier(page)
            if barrier:
                logger.info("🔐 Security barrier detected: %s for %s", barrier, company)

                # When headless=false (human-in-the-loop mode):
                # Keep the browser alive and return session info
                if not headless:
                    # Import session manager only when needed (lazy)
                    try:
                        from app.services.browser_sessions import get_browser_session_manager
                        manager = get_browser_session_manager()
                        session = manager.create_session(
                            application_url=application_url,
                            company=company,
                            job_title=job_title,
                            job_id="",
                            barrier_type=barrier,
                            page=page,
                            browser=browser,
                            context=context,
                            user_profile=user_profile,
                            resume_path=str(resume_path),
                            expected_resume_hash=expected_resume_hash,
                        )
                        # DO NOT close browser — user needs it
                        return json.dumps({
                            "status": "MANUAL_ACTION_REQUIRED",
                            "company": company,
                            "job_title": job_title,
                            "application_url": application_url,
                            "reason": f"Security barrier / {barrier.replace('_', ' ').title()} required — browser kept alive for manual action",
                            "confirmation": "",
                            "submitted_at": None,
                            "resume_hash": resume_hash,
                            "resume_used": str(resume_path.resolve()),
                            "browser_session_id": session.session_id,
                        })
                    except ImportError:
                        pass  # Session manager not available in MCP server process — fallback below

                # Headless mode — can't keep browser for user
                return json.dumps({
                    "status": "MANUAL_ACTION_REQUIRED",
                    "company": company,
                    "job_title": job_title,
                    "application_url": application_url,
                    "reason": f"Security barrier / {barrier.replace('_', ' ').title()} required",
                    "confirmation": "",
                    "submitted_at": None,
                    "resume_hash": resume_hash,
                    "resume_used": str(resume_path.resolve()),
                    "browser_session_id": "",
                })

            # 2. Resolve adapter & fill form
            adapter = _resolve_adapter(application_url, page, user_profile, resume_path)
            filled, reason, _ = await adapter.fill_and_submit()

            # 3. Check for security barriers appearing after submit
            barrier_post = await _detect_security_barrier(page)
            if barrier_post:
                return json.dumps({
                    "status": "MANUAL_ACTION_REQUIRED",
                    "company": company,
                    "job_title": job_title,
                    "application_url": application_url,
                    "reason": f"Security barrier / {barrier_post.replace('_', ' ').title()} appeared during submission",
                    "confirmation": "",
                    "submitted_at": None,
                    "resume_hash": resume_hash,
                    "resume_used": str(resume_path.resolve()),
                    "browser_session_id": "",
                })

            # 4. Strictly verify submission success evidence
            verified, confirmation_detail = await _verify_submission_success(page, application_url)

            if verified:
                logger.info("✅ Verified submission for %s: %s", company, confirmation_detail)
                return json.dumps({
                    "status": "SUCCESS",
                    "company": company,
                    "job_title": job_title,
                    "application_url": application_url,
                    "reason": "Application submitted and verified",
                    "confirmation": confirmation_detail,
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    "resume_hash": resume_hash,
                    "resume_used": str(resume_path.resolve()),
                })

            if not filled:
                logger.info("⚠️ Form filling incomplete for %s: %s", company, reason)
                return json.dumps({
                    "status": "MANUAL_ACTION_REQUIRED",
                    "company": company,
                    "job_title": job_title,
                    "application_url": application_url,
                    "reason": f"Custom application form layout ({reason}) — please apply directly",
                    "confirmation": "",
                    "submitted_at": None,
                    "resume_hash": resume_hash,
                    "resume_used": str(resume_path.resolve()),
                    "browser_session_id": "",
                })

            # Submit was clicked but success could not be verified
            logger.warning("❌ Submission could not be verified for %s at %s", company, application_url)
            return json.dumps({
                "status": "FAILED",
                "company": company,
                "job_title": job_title,
                "application_url": application_url,
                "reason": "Application submission could not be verified from page response",
                "confirmation": "",
                "submitted_at": None,
                "resume_hash": resume_hash,
                "resume_used": str(resume_path.resolve()),
            })

        except Exception as exc:
            logger.error("❌ Exception during browser application for %s: %s", company, exc)
            return json.dumps({
                "status": "FAILED",
                "company": company,
                "job_title": job_title,
                "application_url": application_url,
                "reason": f"Browser navigation error: {exc}",
                "confirmation": "",
                "submitted_at": None,
                "resume_hash": resume_hash,
                "resume_used": str(resume_path.resolve()),
            })
        finally:
            await browser.close()


async def resume_application_tool(
    browser_session_id: str,
) -> str:
    """MCP tool: Resume a paused application after user completes manual action.
    
    Checks if the security barrier has been cleared, then continues the
    application flow (fill form → submit → verify).
    """
    try:
        from app.services.browser_sessions import get_browser_session_manager
    except ImportError:
        return json.dumps({
            "status": "FAILED",
            "reason": "Browser session manager not available",
            "browser_session_id": browser_session_id,
        })

    manager = get_browser_session_manager()
    session = manager.get_session(browser_session_id)

    if not session:
        return json.dumps({
            "status": "FAILED",
            "reason": f"Browser session '{browser_session_id}' not found or expired",
            "browser_session_id": browser_session_id,
        })

    if not session.page:
        await manager.cleanup_session(browser_session_id)
        return json.dumps({
            "status": "FAILED",
            "reason": "Browser page is no longer available",
            "browser_session_id": browser_session_id,
        })

    try:
        # Check if security barrier is still present
        barrier = await _detect_security_barrier(session.page)
        if barrier:
            return json.dumps({
                "status": "MANUAL_ACTION_REQUIRED",
                "company": session.company,
                "job_title": session.job_title,
                "application_url": session.application_url,
                "reason": f"Security barrier still present: {barrier.replace('_', ' ').title()}",
                "browser_session_id": browser_session_id,
            })

        # Barrier cleared — continue application
        resume_path = Path(session.resume_path)

        # Verify resume integrity again before proceeding
        if session.expected_resume_hash and resume_path.exists():
            current_hash = _compute_file_hash(resume_path)
            if current_hash != session.expected_resume_hash:
                await manager.cleanup_session(browser_session_id)
                return json.dumps({
                    "status": "FAILED",
                    "company": session.company,
                    "job_title": session.job_title,
                    "reason": "Resume integrity check failed during resume flow",
                    "browser_session_id": browser_session_id,
                })

        adapter = _resolve_adapter(
            session.application_url,
            session.page,
            session.user_profile,
            resume_path,
        )
        filled, reason, _ = await adapter.fill_and_submit()

        # Check for new barriers after submit
        barrier_post = await _detect_security_barrier(session.page)
        if barrier_post:
            return json.dumps({
                "status": "MANUAL_ACTION_REQUIRED",
                "company": session.company,
                "job_title": session.job_title,
                "application_url": session.application_url,
                "reason": f"New barrier after submission: {barrier_post.replace('_', ' ').title()}",
                "browser_session_id": browser_session_id,
            })

        # Verify submission
        verified, confirmation = await _verify_submission_success(
            session.page, session.application_url
        )

        # Clean up session
        await manager.cleanup_session(browser_session_id)

        if verified:
            resume_hash = _compute_file_hash(resume_path) if resume_path.exists() else ""
            return json.dumps({
                "status": "SUCCESS",
                "company": session.company,
                "job_title": session.job_title,
                "application_url": session.application_url,
                "reason": "Application submitted after manual action",
                "confirmation": confirmation,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
                "resume_hash": resume_hash,
            })

        if not filled:
            return json.dumps({
                "status": "FAILED",
                "company": session.company,
                "job_title": session.job_title,
                "application_url": session.application_url,
                "reason": f"Could not complete form after manual action: {reason}",
            })

        return json.dumps({
            "status": "FAILED",
            "company": session.company,
            "job_title": session.job_title,
            "application_url": session.application_url,
            "reason": "Submission could not be verified after manual action",
        })

    except Exception as exc:
        logger.error("Error resuming application %s: %s", browser_session_id, exc)
        await manager.cleanup_session(browser_session_id)
        return json.dumps({
            "status": "FAILED",
            "reason": f"Error resuming application: {exc}",
            "browser_session_id": browser_session_id,
        })
