# Dispatch Log

## 2026-10-13T14:22:35Z
**Sender:** 274dab0f-fef7-48e1-9abc-7c4dd0c61f7a (Sentinel / Parent)
**Priority:** MESSAGE_PRIORITY_HIGH

You are the PROJECT ORCHESTRATOR for Saral AI.
Your working directory is: d:\Startup\Saral Ai\Saral_app\.agents\teamwork\teamwork_preview_orchestrator_2\
Authoritative user request: d:\Startup\Saral Ai\Saral_app\.agents\teamwork\ORIGINAL_REQUEST.md

User Objective:
Deploy a team of 5-6 specialized autonomous agents to implement real-world e-Aadhaar downloading for Saral AI using a hybrid architecture: live UIDAI portal automation (https://myaadhaar.uidai.gov.in/gen-download-eaadhaar) with anti-bot stealth and dynamic selectors, alongside an official DigiLocker API fallback route. Guarantee smooth end-to-end execution, zero dummy values, real-time citizen credential relays, strict in-memory privacy, and 100% verification across all components.

Key Requirements:
1. R1. Live UIDAI Portal Automation & Anti-Bot Stealth Runner
   - Playwright worker automated against https://myaadhaar.uidai.gov.in/gen-download-eaadhaar with dynamic selector resolution.
   - Anti-bot stealth: navigator.webdriver removal, realistic user agent, hardware concurrency & viewport emulation, human-like typing delays, Cloudflare/Akamai bypass headers.
   - Strict route allowlist: myaadhaar.uidai.gov.in, uidai.gov.in, and Supabase storage.
2. R2. Live In-Memory Citizen Challenge Relay & Zero Persistence
   - In-memory CAPTCHA screenshots streamed as base64 to Flutter app. Interactive refresh support.
   - Real SMS OTP entered by citizen relayed via encrypted WebSocket directly to worker asyncio.Future with zero storage in PostgreSQL, logs, or LLM prompts.
3. R3. Official DigiLocker OAuth2 / IndiaStack Fallback Route
   - Implement alternative legal, high-speed API route using official DigiLocker OAuth2 consent flow for direct e-Aadhaar XML/PDF retrieval without web scraping or CAPTCHA friction.
4. R4. Flutter Mobile Client Real-World Hardening
   - Verify real device flow: FLAG_SECURE screen shielding, real-time 180s countdown ring, real-time OTP input cells, document viewer with password hint (First 4 letters in CAPITAL + 4-digit Year of Birth).
5. R5. 5-Point Cryptographic Verifier & Storage Pipeline
   - Validate %PDF- header, size (100 B - 5 MB), structure %%EOF, zero /JavaScript or /Launch actions, SHA-256 calculation, and password encryption verification.
   - User-isolated Supabase storage upload (documents/<user_id>/<task_id>.pdf).

Key Invariants:
- Zero persistence of OTP / CAPTCHA (in-memory relay only).
- Verifier-only completion gate (only actor="verifier" can transition task to COMPLETED).
- Verhoeff Dihedral D5 algorithm validates all 12-digit Aadhaar numbers, visually masked to XXXX-XXXX-1234.
- All 256 test cases across the test suite continue to pass regression checks.
