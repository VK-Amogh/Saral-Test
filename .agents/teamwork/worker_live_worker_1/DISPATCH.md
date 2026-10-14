## 2026-10-13T14:36:29Z

Your identity: worker_live_worker_1
Your working directory: d:\Startup\Saral Ai\Saral_app\.agents\teamwork\worker_live_worker_1\
Original request path (MANDATORY TO READ FIRST): d:\Startup\Saral Ai\Saral_app\.agents\teamwork\ORIGINAL_REQUEST.md
Scope path: d:\Startup\Saral Ai\Saral_app\.agents\teamwork\teamwork_preview_orchestrator_2\SCOPE.md
Investigation blueprint: d:\Startup\Saral Ai\Saral_app\.agents\teamwork\explorer_survey_2_1\handoff.md

DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Exclusively Owned Files:
- backend/app/worker/runner.py
- backend/app/worker/allowlist.py
- backend/app/worker/client.py
- backend/app/config.py
- backend/app/api/internal.py
- backend/app/worker/test_worker.py

Mission & Tasks:
1. Implement Live UIDAI Portal Automation & Anti-Bot Stealth in `backend/app/worker/runner.py`:
   - Multi-tier cascading fallback selectors for UIDAI (`https://myaadhaar.uidai.gov.in/gen-download-eaadhaar`): Aadhaar radio selection (`#aadhaar_number`, `input[value='aadhaar']`), UID input, CAPTCHA image, CAPTCHA input, Send OTP button, OTP input, Verify & Download button.
   - React synthetic event synchronization using `press_sequentially` with human typing delays (50-150ms).
   - Dismissal of advisory modals / overlays.
   - Robust anti-bot stealth: `delete Object.getPrototypeOf(navigator).webdriver`, realistic user agent, hardware concurrency (8), device memory (8), WebGL vendor/renderer spoofing (`Google Inc. (NVIDIA)`, `ANGLE (NVIDIA, NVIDIA GeForce RTX ...)`), permissions API mocking, and realistic client hints.
   - In-memory CAPTCHA element screenshot extraction to base64, with interactive refresh handling.
   - Zero-persistence OTP relay from worker `asyncio.Future`, filling via `locator.fill()`, local variable deletion (`del`), and temp directory deletion in `finally`.
2. Update Route Allowlist in `backend/app/worker/allowlist.py` and `backend/app/config.py`:
   - Add `supabase.co` (`rsftbslckmdkynprmpin.supabase.co`) alongside `uidai.gov.in`, `myaadhaar.uidai.gov.in`, `localhost`, `127.0.0.1`, and `mock-portal.local`.
3. Wire WebSocket challenge relay in `backend/app/api/internal.py` and `backend/app/worker/client.py`:
   - Bridge `challenge_required` frames into backend `ChallengeBroker.store_captcha()` and relay citizen responses to the worker `asyncio.Future`.
4. Run tests:
   `uv run --with pytest pytest backend/app/worker/test_worker.py -v`
   Ensure all tests pass.
5. Write your handoff report to:
   `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\worker_live_worker_1\handoff.md`
Then send a brief message with your handoff path.
