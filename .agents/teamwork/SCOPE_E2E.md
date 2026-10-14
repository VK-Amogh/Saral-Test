# Scope: E2E Testing Track (Parallel)

## Architecture & Responsibilities
- Opaque-box, requirement-driven test suite derived from `ORIGINAL_REQUEST.md` and `PROJECT.md § Feature Inventory`.
- Create `TEST_INFRA.md` at project root.
- Implement test runner, test harness, and tests in `tests/e2e/`.
- Publishes `TEST_READY.md` at project root upon completion.

## Test Methodology (4 Tiers)
1. **Tier 1: Feature Coverage (>=5 per feature)**:
   - Happy path tests verifying each feature in isolation using simplest verification channel.
2. **Tier 2: Boundary & Corner Cases (>=5 per feature)**:
   - Limits, empty inputs, max-size, wrong credentials, expired tokens, corrupt PDFs, timeout.
3. **Tier 3: Cross-Feature Combinations (pairwise coverage)**:
   - Auth + chat + task creation, task state transitions + worker challenge relay + OTP input, download verification + signed URL retrieval.
4. **Tier 4: Real-World Application Scenarios (>=5 realistic scenarios)**:
   - Full end-to-end user journey: Login → Chat request → Mock Portal navigation → CAPTCHA solved → OTP verified → PDF encrypted validated → Storage uploaded → Vault delivered.
   - Failure recovery journeys: Wrong CAPTCHA retry, OTP retry, expired OTP, cancellation mid-flight.

## Write Ownership
- Exclusive ownership: `TEST_INFRA.md`, `TEST_READY.md`, `tests/e2e/`.
