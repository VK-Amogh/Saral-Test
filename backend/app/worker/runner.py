"""
Saral AI — Playwright Browser Automation Runner
File: backend/app/worker/runner.py

Orchestrates headless Chromium browser automation for e-Aadhaar download:
1. Isolated ephemeral browser context + temporary directory per task
2. Anti-detection stealth flags & navigator overrides for production portals
3. Multi-selector fallback chains for UIDAI myAadhaar & mock portal compatibility
4. UID entry & in-memory element screenshot CAPTCHA extraction
5. Challenge relay over WebSocket & zero-persistence OTP fill
6. Download interception & single-download guarantee
7. 5-point document security verification
8. Private Supabase Storage upload & cleanup in finally block
"""

import asyncio
import base64
import logging
import os
from pathlib import Path
import random
import shutil
import tempfile
import time
import uuid
from typing import Any, Dict, List, Optional

try:
    from playwright.async_api import Browser, BrowserContext, Page, async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

from .allowlist import DomainAllowlistInterceptor, DEFAULT_ALLOWED_DOMAINS
from .client import WorkerWebSocketClient
from .verifier import DocumentVerifier, VerifierResult
from ..config import get_settings
from ..store import store

logger = logging.getLogger(__name__)

# Universal Selector Fallback Chains (supports Mock Portal + live UIDAI myAadhaar)
AADHAAR_RADIO_SELECTORS = [
    "#aadhaar_number",
    "input[value='aadhaar' i]",
    "input[value='AADHAAR']",
    "input#aadhaar",
    "button:has-text('Aadhaar Number')",
    "label:has-text('Aadhaar Number')",
    "[data-testid='aadhaar-radio']",
]

UID_SELECTORS = [
    "#uid_input",
    "input[name='uid']",
    "input[name='aadhaarNumber']",
    "input[formcontrolname='uid']",
    "input[placeholder*='Enter Aadhaar' i]",
    "input[placeholder*='Aadhaar Number' i]",
    "input[aria-label*='Aadhaar' i]",
    "input[aria-label*='Enter Aadhaar' i]",
    "input[maxlength='12']",
    "label:has-text('Aadhaar') >> .. >> input",
]

CAPTCHA_IMG_SELECTORS = [
    "#captcha_img",
    "img[alt*='Captcha' i]",
    "img[alt*='captcha' i]",
    "img[src*='captcha' i]",
    "img[src*='Captcha' i]",
    ".captcha-image img",
    ".captcha-box img",
    "canvas.captcha-canvas",
    "svg.captcha-svg",
    "[data-testid='captcha-img']",
]

CAPTCHA_INPUT_SELECTORS = [
    "#captcha_input",
    "input[name='captcha']",
    "input[name='captchaInput']",
    "input[formcontrolname='captcha']",
    "input[placeholder*='Enter Captcha' i]",
    "input[placeholder*='Captcha' i]",
    "input[aria-label*='Captcha' i]",
    "[data-testid='captcha-input']",
]

SEND_OTP_SELECTORS = [
    "#btn_send_otp",
    "button:has-text('Send OTP')",
    "button:has-text('Login with OTP')",
    "button[type='submit']:has-text('OTP')",
    "button[type='submit']",
    "[data-testid='send-otp-btn']",
]

OTP_INPUT_SELECTORS = [
    "#otp_input",
    "input[name='otp']",
    "input[formcontrolname='otp']",
    "input[placeholder*='Enter OTP' i]",
    "input[placeholder*='OTP' i]",
    "input[aria-label*='OTP' i]",
    "input[maxlength='6']",
    "[data-testid='otp-input']",
]

VERIFY_DOWNLOAD_SELECTORS = [
    "#btn_verify_download",
    "button:has-text('Verify & Download')",
    "button:has-text('Verify and Download')",
    "button:has-text('Download e-Aadhaar')",
    "button:has-text('Download Aadhaar')",
    "[data-testid='verify-download-btn']",
]

ERROR_BOX_SELECTORS = [
    "#error_msg",
    ".error-msg",
    ".alert-danger",
    "div[role='alert']",
    ".toast-error",
]

ADVISORY_DISMISS_SELECTORS = [
    "button:has-text('OK')",
    "button:has-text('Close')",
    "button[aria-label='Close' i]",
    "button[aria-label='close' i]",
    ".modal-close",
    ".advisory-close",
    ".popup-close",
    "div[role='dialog'] button:has-text('OK')",
    "div[role='dialog'] button:has-text('Close')",
    "[data-testid='modal-dismiss-btn']",
]

CAPTCHA_REFRESH_SELECTORS = [
    "#btn_refresh_captcha",
    "button:has-text('Refresh')",
    "button[aria-label*='Refresh' i]",
    "button[aria-label*='refresh' i]",
    ".refresh-captcha",
    "[data-testid='refresh-captcha-btn']",
]


class AutomationTaskError(Exception):
    """Domain exception raised during browser automation."""
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class AadhaarDownloadAutomationRunner:
    """Hardened browser automation worker for official UIDAI / Mock portal flows."""

    def __init__(
        self,
        allowed_domains: Optional[List[str]] = None,
        verifier: Optional[DocumentVerifier] = None,
        ws_client: Optional[WorkerWebSocketClient] = None,
    ):
        settings = get_settings()
        domains = allowed_domains or settings.ALLOWED_DOMAINS or DEFAULT_ALLOWED_DOMAINS
        self.allowlist_interceptor = DomainAllowlistInterceptor(domains)
        self.verifier = verifier or DocumentVerifier(min_size_bytes=100, max_size_mb=5)
        self.ws_client = ws_client

    async def _find_visible_locator(
        self,
        page: Any,
        selectors: List[str],
        timeout_ms: int = 10000
    ) -> Optional[Any]:
        """Find the first matching and visible element from a list of selector candidates."""
        # Fast path: check current visibility
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible():
                    return loc
            except Exception:
                continue

        # Wait path: await visibility on candidates
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                await loc.wait_for(state="visible", timeout=min(timeout_ms, 2500))
                return loc
            except Exception:
                continue

        return None

    async def _dismiss_advisories_if_present(self, page: Any) -> None:
        """Detect and dismiss advisory popups, cookie banners, or modal overlays."""
        for sel in ADVISORY_DISMISS_SELECTORS:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible():
                    await loc.click(timeout=1000)
                    logger.info("Dismissed advisory overlay using selector: %s", sel)
                    await asyncio.sleep(0.3)
                    break
            except Exception:
                continue

    async def _type_humanlike_sync(self, locator: Any, text: str) -> None:
        """Type text using press_sequentially with human delays (50-150ms) and synthetic event sync."""
        try:
            await locator.click()
            if hasattr(locator, "press_sequentially"):
                delay_ms = random.randint(50, 150)
                await locator.press_sequentially(text, delay=delay_ms)
            else:
                await locator.fill(text)
        except Exception:
            await locator.fill(text)

        # Trigger React and Angular synthetic change/input events
        try:
            await locator.dispatch_event("input")
            await locator.dispatch_event("change")
        except Exception:
            pass

    async def execute_task(
        self,
        task_id: str,
        user_id: str,
        portal_url: str,
        uid: str,
        browser: Optional[Any] = None,
        max_captcha_attempts: int = 3,
        navigation_retries: int = 2,
    ) -> Dict[str, Any]:
        """Execute full end-to-end automation workflow with guaranteed sandbox cleanup."""
        task_temp_dir = tempfile.mkdtemp(prefix=f"saral_task_{task_id}_")
        context: Optional[Any] = None
        page: Optional[Any] = None
        playwright_obj: Optional[Any] = None
        own_browser = False

        # Support overriding portal URL via environment (e.g. pointing directly to real UIDAI portal)
        effective_portal_url = os.getenv("UIDAI_PORTAL_URL", portal_url)

        try:
            # 1. Initialize Playwright & Browser Context
            if not PLAYWRIGHT_AVAILABLE:
                raise AutomationTaskError("PLAYWRIGHT_UNAVAILABLE", "Playwright is not installed in current environment")

            if browser is None:
                try:
                    playwright_obj = await async_playwright().start()
                    browser = await playwright_obj.chromium.launch(
                        headless=True,
                        args=[
                            "--no-sandbox",
                            "--disable-setuid-sandbox",
                            "--disable-dev-shm-usage",
                            "--disable-gpu",
                            "--no-first-run",
                            "--no-default-browser-check",
                            "--disable-blink-features=AutomationControlled"
                        ]
                    )
                    own_browser = True
                except Exception as e:
                    raise AutomationTaskError("PLAYWRIGHT_UNAVAILABLE", f"Playwright browser launch failed: {str(e)}")

            # Ephemeral context per task with stealth properties & realistic client hints
            context = await browser.new_context(
                accept_downloads=True,
                ignore_https_errors=True,
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
                    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "sec-fetch-dest": "document",
                    "sec-fetch-mode": "navigate",
                    "sec-fetch-site": "none",
                    "sec-fetch-user": "?1",
                    "upgrade-insecure-requests": "1",
                },
            )

            # Robust Anti-Bot Stealth Overrides
            await context.add_init_script("""
                // 1. Prototype and navigator.webdriver removal
                try {
                    delete Object.getPrototypeOf(navigator).webdriver;
                } catch (e) {}
                Object.defineProperty(navigator, 'webdriver', { get: () => false, configurable: true });

                // 2. Hardware Concurrency, Device Memory & Touch Points
                Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8, configurable: true });
                Object.defineProperty(navigator, 'deviceMemory', { get: () => 8, configurable: true });
                Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0, configurable: true });

                // 3. Languages and Plugins
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'hi'], configurable: true });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5], configurable: true });

                // 4. Chrome Runtime Mock
                window.chrome = {
                    runtime: {
                        connect: () => {},
                        sendMessage: () => {},
                    }
                };

                // 5. Permissions API Mock
                try {
                    const origQuery = navigator.permissions.query;
                    navigator.permissions.query = (p) => (p && p.name === 'notifications')
                        ? Promise.resolve({ state: Notification.permission })
                        : (origQuery ? origQuery(p) : Promise.resolve({ state: 'prompt' }));
                } catch (e) {}

                // 6. WebGL Vendor & Renderer Spoofing
                const spoofVendor = 'Google Inc. (NVIDIA)';
                const spoofRenderer = 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)';

                if (typeof WebGLRenderingContext !== 'undefined') {
                    const origGetParam = WebGLRenderingContext.prototype.getParameter;
                    WebGLRenderingContext.prototype.getParameter = function(param) {
                        if (param === 37445) return spoofVendor;
                        if (param === 37446) return spoofRenderer;
                        return origGetParam.apply(this, arguments);
                    };
                }
                if (typeof WebGL2RenderingContext !== 'undefined') {
                    const origGetParam2 = WebGL2RenderingContext.prototype.getParameter;
                    WebGL2RenderingContext.prototype.getParameter = function(param) {
                        if (param === 37445) return spoofVendor;
                        if (param === 37446) return spoofRenderer;
                        return origGetParam2.apply(this, arguments);
                    };
                }

                // 7. Screen and Viewport Normalization
                Object.defineProperty(screen, 'width', { get: () => 1920 });
                Object.defineProperty(screen, 'height', { get: () => 1080 });
                Object.defineProperty(screen, 'availWidth', { get: () => 1920 });
                Object.defineProperty(screen, 'availHeight', { get: () => 1040 });
                Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
                window.outerWidth = 1920;
                window.outerHeight = 1080;
            """)

            # Attach route-level domain allowlist interceptor
            await self.allowlist_interceptor.attach_to_context(context)

            page = await context.new_page()

            # Set reasonable timeouts
            page.set_default_timeout(20000)
            page.set_default_navigation_timeout(30000)

            if self.ws_client:
                await self.ws_client.send_task_progress(task_id, 10, "RUNNING", "Navigating to portal...")

            # 2. Step 1: Portal Navigation with bounded retries
            navigated = False
            last_nav_err = None
            for attempt in range(navigation_retries + 1):
                try:
                    await page.goto(effective_portal_url, wait_until="networkidle", timeout=30000)
                    navigated = True
                    break
                except Exception as e:
                    last_nav_err = e
                    logger.warning("Navigation to %s failed (attempt %d/%d): %s", effective_portal_url, attempt + 1, navigation_retries + 1, str(e))
                    if attempt < navigation_retries:
                        await asyncio.sleep(2.0)

            if not navigated:
                raise AutomationTaskError("NAVIGATION_TIMEOUT", f"Failed to load portal at {effective_portal_url}: {str(last_nav_err)}")

            # Dismiss any initial advisory modal / banner
            await self._dismiss_advisories_if_present(page)

            # Check if task was cancelled
            if self.ws_client and self.ws_client.is_task_cancelled(task_id):
                raise AutomationTaskError("CANCELLED", "Task cancelled by user")

            # 3. Step 2: Credential Entry & CAPTCHA Extraction Loop
            captcha_attempts_used = 0
            login_success = False

            while captcha_attempts_used < max_captcha_attempts:
                # Dismiss advisories if any popped up
                await self._dismiss_advisories_if_present(page)

                # Ensure Aadhaar radio / tab is active if present
                for sel in AADHAAR_RADIO_SELECTORS:
                    try:
                        radio = page.locator(sel).first
                        if await radio.is_visible():
                            await radio.click()
                            logger.info("Selected Aadhaar radio tab using: %s", sel)
                            await asyncio.sleep(0.3)
                            break
                    except Exception:
                        continue

                # Find UID field using multi-selector fallback
                uid_locator = await self._find_visible_locator(page, UID_SELECTORS, timeout_ms=10000)
                if not uid_locator:
                    raise AutomationTaskError("DOM_SELECTOR_MISMATCH", "Required UID input selector not found on page")

                # Type UID with React synthetic event sync and human keystroke pacing
                await self._type_humanlike_sync(uid_locator, uid)

                # Capture CAPTCHA image element directly into memory via screenshot
                captcha_elem = await self._find_visible_locator(page, CAPTCHA_IMG_SELECTORS, timeout_ms=10000)
                if not captcha_elem:
                    raise AutomationTaskError("CAPTCHA_LOAD_ERROR", "Failed to extract CAPTCHA challenge element")

                captcha_bytes = await captcha_elem.screenshot(type="png")

                # Relay challenge to user over WebSocket or broker
                captcha_b64 = base64.b64encode(captcha_bytes).decode("ascii")
                if self.ws_client:
                    await self.ws_client.send_task_progress(task_id, 25, "WAITING_FOR_USER", "CAPTCHA challenge required")
                    await self.ws_client.send_challenge_required(
                        task_id=task_id,
                        kind="captcha",
                        prompt="Enter characters shown in CAPTCHA challenge",
                        challenge_data_b64=captcha_b64,
                        attempts_left=max_captcha_attempts - captcha_attempts_used
                    )
                    # Await user input
                    input_fut = self.ws_client.register_input_future(task_id, "captcha")
                    refresh_ev = self.ws_client.register_refresh_event(task_id)

                    try:
                        input_task = asyncio.create_task(input_fut)
                        refresh_task = asyncio.create_task(refresh_ev.wait())
                        done, pending = await asyncio.wait(
                            [input_task, refresh_task],
                            timeout=180.0,
                            return_when=asyncio.FIRST_COMPLETED
                        )

                        if not done:
                            for p in pending:
                                p.cancel()
                            raise AutomationTaskError("INPUT_TIMEOUT", "User did not submit CAPTCHA within 180 seconds")

                        if refresh_task in done:
                            for p in pending:
                                p.cancel()
                            logger.info("Interactive CAPTCHA refresh event detected")
                            for sel in CAPTCHA_REFRESH_SELECTORS:
                                try:
                                    r_btn = page.locator(sel).first
                                    if await r_btn.is_visible():
                                        await r_btn.click()
                                        await asyncio.sleep(1.0)
                                        break
                                except Exception:
                                    continue
                            continue  # Loop again with fresh CAPTCHA screenshot

                        captcha_value = await input_task
                        for p in pending:
                            p.cancel()
                    except AutomationTaskError:
                        raise
                    except asyncio.TimeoutError:
                        raise AutomationTaskError("INPUT_TIMEOUT", "User did not submit CAPTCHA within 180 seconds")
                else:
                    captcha_value = "VALID_CAP"

                # Check if citizen submitted "REFRESH" value
                if isinstance(captcha_value, str) and captcha_value.strip().upper() == "REFRESH":
                    logger.info("Interactive CAPTCHA refresh requested via input value")
                    for sel in CAPTCHA_REFRESH_SELECTORS:
                        try:
                            r_btn = page.locator(sel).first
                            if await r_btn.is_visible():
                                await r_btn.click()
                                await asyncio.sleep(1.0)
                                break
                        except Exception:
                            continue
                    del captcha_value
                    continue

                # Fill CAPTCHA input
                captcha_input = await self._find_visible_locator(page, CAPTCHA_INPUT_SELECTORS, timeout_ms=5000)
                if not captcha_input:
                    del captcha_value
                    raise AutomationTaskError("DOM_SELECTOR_MISMATCH", "CAPTCHA input field not found on page")

                await captcha_input.fill(captcha_value)
                try:
                    await captcha_input.dispatch_event("input")
                    await captcha_input.dispatch_event("change")
                except Exception:
                    pass
                del captcha_value  # Immediately drop reference for zero-persistence

                # Dismiss advisories if any appeared
                await self._dismiss_advisories_if_present(page)

                # Submit login form
                submit_btn = await self._find_visible_locator(page, SEND_OTP_SELECTORS, timeout_ms=5000)
                if not submit_btn:
                    raise AutomationTaskError("DOM_SELECTOR_MISMATCH", "Send OTP button not found on page")

                await submit_btn.click()

                # Race check: Did error appear, or did we advance to OTP?
                try:
                    for _ in range(40):
                        otp_field = await self._find_visible_locator(page, OTP_INPUT_SELECTORS, timeout_ms=500)
                        if otp_field:
                            login_success = True
                            break

                        error_box = await self._find_visible_locator(page, ERROR_BOX_SELECTORS, timeout_ms=500)
                        if error_box:
                            err_text = await error_box.inner_text()
                            if "captcha" in err_text.lower():
                                break

                        await asyncio.sleep(0.25)

                    if login_success:
                        break

                    captcha_attempts_used += 1
                    if captcha_attempts_used >= max_captcha_attempts:
                        raise AutomationTaskError("CAPTCHA_ATTEMPTS_EXCEEDED", "Maximum CAPTCHA attempts (3) exceeded")

                    # Refresh CAPTCHA and retry loop
                    refresh_btn = page.locator("#btn_refresh_captcha, button:has-text('Refresh')").first
                    if await refresh_btn.is_visible():
                        await refresh_btn.click()
                        await asyncio.sleep(1.0)
                except AutomationTaskError:
                    raise
                except Exception as e:
                    logger.warning("Error during CAPTCHA evaluation: %s", str(e))
                    captcha_attempts_used += 1

            if not login_success:
                raise AutomationTaskError("LOGIN_FAILED", "Could not advance to OTP verification step")

            if self.ws_client:
                await self.ws_client.send_task_progress(task_id, 50, "RUNNING", "Login verified. Awaiting OTP...")

            # 4. Step 3: OTP Verification & Download Interception
            otp_attempts_left = 3
            download_obj = None

            while otp_attempts_left > 0:
                if self.ws_client and self.ws_client.is_task_cancelled(task_id):
                    raise AutomationTaskError("CANCELLED", "Task cancelled by user during OTP step")

                # Verify OTP input selector exists
                otp_locator = await self._find_visible_locator(page, OTP_INPUT_SELECTORS, timeout_ms=10000)
                if not otp_locator:
                    raise AutomationTaskError("DOM_SELECTOR_MISMATCH", "OTP input field not found on verification page")

                # Relay OTP challenge to user
                if self.ws_client:
                    await self.ws_client.send_task_progress(task_id, 60, "WAITING_FOR_USER", "OTP required")
                    await self.ws_client.send_challenge_required(
                        task_id=task_id,
                        kind="otp",
                        prompt="Enter 6-digit OTP received on mobile",
                        attempts_left=otp_attempts_left
                    )
                    input_fut = self.ws_client.register_input_future(task_id, "otp")
                    try:
                        otp_value = await asyncio.wait_for(input_fut, timeout=180.0)
                    except asyncio.TimeoutError:
                        raise AutomationTaskError("INPUT_TIMEOUT", "User did not submit OTP within 180 seconds")
                else:
                    otp_value = "123456"

                # Zero-persistence OTP fill
                await otp_locator.fill(otp_value)
                try:
                    await otp_locator.dispatch_event("input")
                    await otp_locator.dispatch_event("change")
                except Exception:
                    pass
                del otp_value  # Drop reference immediately

                # Dismiss advisories if any appeared
                await self._dismiss_advisories_if_present(page)

                # Locate download submit button
                download_btn = await self._find_visible_locator(page, VERIFY_DOWNLOAD_SELECTORS, timeout_ms=5000)
                if not download_btn:
                    raise AutomationTaskError("DOM_SELECTOR_MISMATCH", "Verify & Download button not found")

                # Intercept download event while clicking submit
                try:
                    async with page.expect_download(timeout=10000) as download_info:
                        await download_btn.click()

                    download_obj = await download_info.value
                    break  # Download initiated successfully!
                except Exception:
                    # Download didn't trigger, check for error box
                    error_box = await self._find_visible_locator(page, ERROR_BOX_SELECTORS, timeout_ms=2000)
                    if error_box:
                        err_text = await error_box.inner_text()
                        if "expired" in err_text.lower():
                            raise AutomationTaskError("OTP_EXPIRED", "The submitted OTP has expired")
                        otp_attempts_left -= 1
                        if otp_attempts_left <= 0:
                            raise AutomationTaskError("MAX_OTP_ATTEMPTS_EXCEEDED", "Maximum OTP verification attempts exceeded")
                    else:
                        raise AutomationTaskError("DOWNLOAD_FAILED", "Download event not triggered and no error displayed")

            if not download_obj:
                raise AutomationTaskError("DOWNLOAD_FAILED", "Download could not be initiated")

            # Save download into task temp dir
            download_filename = download_obj.suggested_filename or f"eaadhaar_{task_id[:8]}.pdf"
            local_target_path = os.path.join(task_temp_dir, download_filename)
            await download_obj.save_as(local_target_path)

            if self.ws_client:
                await self.ws_client.send_task_progress(task_id, 85, "DOWNLOADING", "File intercepted. Verifying...")

            # 5. Step 4: 5-Point Document Security Verification
            file_bytes = Path(local_target_path).read_bytes()
            verifier_result: VerifierResult = self.verifier.verify(file_bytes)

            if not verifier_result.is_valid:
                raise AutomationTaskError(
                    verifier_result.error_code or "DOCUMENT_VERIFICATION_FAILED",
                    verifier_result.error_message or "Document failed security verification"
                )

            # 6. Step 5: Storage Upload & Document Record Creation
            storage_path = f"{user_id}/{task_id}.pdf"
            doc_id = str(uuid.uuid4())

            # Upload to store in-memory storage simulation / Supabase
            with store._lock:
                store.storage_objects[storage_path] = file_bytes
                store.documents[doc_id] = {
                    "id": doc_id,
                    "user_id": user_id,
                    "task_id": task_id,
                    "doc_type": "aadhaar",
                    "file_name": download_filename,
                    "storage_path": storage_path,
                    "size_bytes": verifier_result.size_bytes,
                    "sha256": verifier_result.sha256,
                    "pdf_encrypted": verifier_result.pdf_encrypted,
                    "created_at": time.time(),
                    "delete_after": time.time() + 86400,
                }

            if self.ws_client:
                await self.ws_client.send_task_progress(task_id, 100, "COMPLETED", "Task completed successfully")
                await self.ws_client.send_task_completed(
                    task_id=task_id,
                    document_id=doc_id,
                    storage_path=storage_path,
                    file_name=download_filename,
                    size_bytes=verifier_result.size_bytes,
                    sha256=verifier_result.sha256 or "",
                    pdf_encrypted=verifier_result.pdf_encrypted
                )

            return {
                "status": "COMPLETED",
                "task_id": task_id,
                "document_id": doc_id,
                "storage_path": storage_path,
                "file_name": download_filename,
                "size_bytes": verifier_result.size_bytes,
                "sha256": verifier_result.sha256,
                "pdf_encrypted": verifier_result.pdf_encrypted,
            }

        except AutomationTaskError as e:
            logger.error("Automation error for task %s: [%s] %s", task_id, e.error_code, e.message)
            if self.ws_client:
                await self.ws_client.send_task_failed(task_id, e.error_code, e.message)
            raise
        except Exception as e:
            logger.exception("Unexpected error in automation runner for task %s", task_id)
            if self.ws_client:
                await self.ws_client.send_task_failed(task_id, "RUNNER_INTERNAL_ERROR", str(e))
            raise AutomationTaskError("RUNNER_INTERNAL_ERROR", str(e))

        finally:
            # 7. Guaranteed Teardown Contract
            if page and hasattr(page, "is_closed") and not page.is_closed():
                try:
                    await page.close()
                except Exception:
                    pass

            if context:
                try:
                    await context.close()
                except Exception:
                    pass

            if own_browser and browser:
                try:
                    await browser.close()
                except Exception:
                    pass

            if playwright_obj:
                try:
                    await playwright_obj.stop()
                except Exception:
                    pass

            # Wipe temporary directory and nullify references
            if task_temp_dir and os.path.exists(task_temp_dir):
                shutil.rmtree(task_temp_dir, ignore_errors=True)

            if self.ws_client:
                self.ws_client.clear_task_futures(task_id)
