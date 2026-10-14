## 2026-10-13T06:17:21Z
You are spec_miner_survey_2 (Worker & Mock Portal Spec Miner).
Working directory: d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_2\
Project root: d:\Startup\Saral Ai\Saral_app\

Authoritative specifications to read:
- d:\Startup\Saral Ai\Saral_app\.agents\teamwork\ORIGINAL_REQUEST.md
- d:\Startup\Saral Ai\Saral_app\SARAL_AI_IMPLEMENTATION_PLAN.md (Sections 6, 7, 8, 11, 14, 16)
- d:\Startup\Saral Ai\Saral_app\rules.md

Your Mission:
Mine, extract, and document all precise requirements, feature inventory items, constraints, contracts, and failure modes for:
1. Mock Government Portal (`mock_portal/`):
   - Standalone FastAPI service simulating an official government portal.
   - Flow: Login (Aadhaar/VID) → CAPTCHA challenge image generation & verification → OTP verification → Secure PDF generation and download.
   - Comprehensive simulation of failure modes: wrong CAPTCHA, expired OTP, wrong OTP (up to 3 attempts), corrupt PDF, timeout, slow page response.
2. Playwright Headless Browser Worker:
   - Python worker running Playwright + Chromium.
   - Outbound WebSocket connection to backend `WS /internal/worker` using `WORKER_SHARED_SECRET`.
   - Isolated browser context per task.
   - Network route filtering: strict domain allowlist checking (abort non-allowlisted requests).
   - CAPTCHA extraction and relay to broker; OTP fill via `locator.fill()`; download interception.
   - Document verifier: validate `%PDF-` header, structure, parse with pypdf, verify no `/JavaScript` or `/Launch` actions, compute SHA-256 hash.
   - Upload verified PDF to private Supabase Storage (`documents/<user_id>/<task_id>.pdf`).
   - Cleanup: delete temp directory in `finally` blocks. No traces, video, or HAR in production.

Output requirements:
- Write your comprehensive specification report to: `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_2\survey_report.md`
- Write your handoff report to: `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_2\handoff.md`
- Once complete, notify the orchestrator (caller) using send_message with a summary and file paths.

DO NOT write source code or run builds. You are an exploratory spec miner.
