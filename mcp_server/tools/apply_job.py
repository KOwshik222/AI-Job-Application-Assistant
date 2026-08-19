"""MCP tool: apply_job — browser automation with human-in-the-loop stops."""

import json
import logging
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

MANUAL_TRIGGERS = [
    "captcha",
    "recaptcha",
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
    "cloudflare",
    "just a moment",
]

# Domains that are job search directories or heavily bot-protected aggregators
AGGREGATOR_DOMAINS = [
    "linkedin.com",
    "indeed.com",
    "naukri.com",
    "glassdoor.com",
    "hirist.tech",
    "wellfound.com",
    "builtin.com",
    "builtinpune.in",
    "internshala.com",
    "monster.com",
    "foundit.in",
]


def _is_aggregator_url(url: str) -> bool:
    parsed = urlparse(url.lower())
    netloc = parsed.netloc
    path = parsed.path
    if any(domain in netloc for domain in AGGREGATOR_DOMAINS):
        return True
    if any(segment in path for segment in ["/jobs/", "/q-", "/role/l/"]):
        return True
    return False


async def _detect_manual_required(page) -> str | None:
    try:
        content = (await page.content()).lower()
        for trigger in MANUAL_TRIGGERS:
            if trigger in content:
                return trigger.upper().replace(" ", "_")
    except Exception:
        pass
    return None


async def _wait_for_user_action(page, reason: str, timeout_ms: int = 60000) -> str | None:
    """Wait for user to complete manual action (login/captcha) in the visible browser."""
    logger.info(
        "⏳ MANUAL ACTION REQUIRED: %s — Complete it in the browser window. "
        "You have %d seconds.", reason, timeout_ms // 1000
    )
    elapsed = 0
    poll_interval = 3000
    while elapsed < timeout_ms:
        await page.wait_for_timeout(poll_interval)
        elapsed += poll_interval
        still_blocked = await _detect_manual_required(page)
        if not still_blocked:
            logger.info("✅ Manual action completed! Continuing application...")
            return None
    return reason


async def _fill_form_fields(page, user_profile: dict, resume_path: Path):
    """Fill common application form fields."""
    try:
        file_inputs = await page.query_selector_all('input[type="file"]')
        if file_inputs:
            await file_inputs[0].set_input_files(str(resume_path.resolve()))
            logger.info("📎 Resume uploaded")
    except Exception as e:
        logger.debug("File upload error: %s", e)

    email = user_profile.get("email", "")
    if email:
        for selector in [
            'input[type="email"]',
            'input[name*="email" i]',
            'input[placeholder*="email" i]',
            'input[id*="email" i]',
        ]:
            try:
                el = await page.query_selector(selector)
                if el and await el.is_visible():
                    await el.fill(email)
                    logger.info("📧 Email filled")
                    break
            except Exception:
                continue

    name = user_profile.get("full_name", "")
    if name:
        for selector in [
            'input[name*="name" i]',
            'input[placeholder*="name" i]',
            'input[id*="name" i]',
            'input[autocomplete="name"]',
        ]:
            try:
                el = await page.query_selector(selector)
                if el and await el.is_visible():
                    await el.fill(name)
                    logger.info("👤 Name filled")
                    break
            except Exception:
                continue

    phone = user_profile.get("phone", "")
    if phone:
        for selector in [
            'input[type="tel"]',
            'input[name*="phone" i]',
            'input[placeholder*="phone" i]',
            'input[id*="phone" i]',
        ]:
            try:
                el = await page.query_selector(selector)
                if el and await el.is_visible():
                    await el.fill(phone)
                    logger.info("📱 Phone filled")
                    break
            except Exception:
                continue


async def apply_job_tool(
    application_url: str,
    resume_file_path: str,
    user_profile: dict,
    company: str = "",
    job_title: str = "",
    mock_mode: bool = False,
) -> str:
    parsed = urlparse(application_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return json.dumps({
            "status": "FAILED",
            "reason": "Invalid application URL",
            "resume_used": resume_file_path,
        })

    resume_path = Path(resume_file_path)
    if not resume_path.exists():
        return json.dumps({
            "status": "FAILED",
            "reason": "Original resume file not found",
            "resume_used": resume_file_path,
        })

    if mock_mode:
        url_lower = application_url.lower()
        if any(t in url_lower for t in ("login", "captcha", "signup")):
            return json.dumps({
                "status": "MANUAL_ACTION_REQUIRED",
                "reason": "Login Required",
                "resume_used": str(resume_path.resolve()),
            })
        return json.dumps({
            "status": "SUCCESS",
            "reason": "Application submitted (mock mode)",
            "resume_used": str(resume_path.resolve()),
            "submitted_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        })

    # If the URL is a search directory or aggregator, route directly to Manual Action
    if _is_aggregator_url(application_url):
        logger.info("ℹ️ Aggregator/Directory URL detected for %s: %s", company, application_url)
        return json.dumps({
            "status": "MANUAL_ACTION_REQUIRED",
            "reason": "Job Directory / Search Listing — open URL to view postings",
            "resume_used": str(resume_path.resolve()),
            "url": application_url,
        })

    # --- REAL APPLICATION MODE FOR DIRECT JOB PAGES ---
    logger.info("🌐 Opening browser for direct application: %s (%s)", company, job_title)
    logger.info("🔗 URL: %s", application_url)

    import sys
    import asyncio
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
            "reason": "Playwright not installed",
            "resume_used": str(resume_path.resolve()),
        })

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            slow_mo=300,
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        try:
            logger.info("📄 Navigating to application page...")
            await page.goto(application_url, timeout=15000, wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)

            manual = await _detect_manual_required(page)
            if manual:
                logger.info("🔐 Detected: %s — waiting for user input...", manual)
                still_blocked = await _wait_for_user_action(page, manual)
                if still_blocked:
                    return json.dumps({
                        "status": "MANUAL_ACTION_REQUIRED",
                        "reason": f"{manual.replace('_', ' ').title()} required",
                        "resume_used": str(resume_path.resolve()),
                        "url": application_url,
                    })

            await _fill_form_fields(page, user_profile, resume_path)

            submit = await page.query_selector(
                'button[type="submit"], '
                'input[type="submit"], '
                'button:has-text("Apply"), '
                'button:has-text("Submit"), '
                'a:has-text("Apply Now"), '
                'button:has-text("Send Application")'
            )

            if submit and await submit.is_visible():
                logger.info("🖱️ Clicking submit button...")
                await submit.click()
                await page.wait_for_timeout(3000)

                manual = await _detect_manual_required(page)
                if manual:
                    still_blocked = await _wait_for_user_action(page, manual)
                    if still_blocked:
                        return json.dumps({
                            "status": "MANUAL_ACTION_REQUIRED",
                            "reason": f"{manual.replace('_', ' ').title()} required after submit",
                            "resume_used": str(resume_path.resolve()),
                            "url": application_url,
                        })

                logger.info("✅ Application submitted for %s!", company)
                await page.wait_for_timeout(2000)
                return json.dumps({
                    "status": "SUCCESS",
                    "reason": "Application submitted via browser",
                    "resume_used": str(resume_path.resolve()),
                    "url": application_url,
                    "submitted_at": __import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ).isoformat(),
                })

            return json.dumps({
                "status": "MANUAL_ACTION_REQUIRED",
                "reason": "Direct form not automatically fillable — please apply manually",
                "resume_used": str(resume_path.resolve()),
                "url": application_url,
            })

        except Exception as exc:
            logger.info("⚠️ Browser navigation issue for %s: %s", company, exc)
            return json.dumps({
                "status": "MANUAL_ACTION_REQUIRED",
                "reason": f"Page load or bot protection check — open URL to view posting",
                "resume_used": str(resume_path.resolve()),
                "url": application_url,
            })
        finally:
            await browser.close()
