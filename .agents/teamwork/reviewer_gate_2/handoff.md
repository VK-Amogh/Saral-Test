# Gate 2 Independent Review & Adversarial Challenge Report

**Reviewer Identity:** `reviewer_gate_2`  
**Working Directory:** `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\reviewer_gate_2\`  
**Target Milestones:** Milestone M1 (Live UIDAI Worker & Stealth Runner) & Milestone M3 (Flutter Mobile Client Hardening)  
**Date:** 2026-10-13  
**Verdict:** **`REQUEST_CHANGES`**  
*(Milestone M3 is fully APPROVED; Milestone M1 requires 2 surgical security & state-machine fixes before promotion)*

---

## 1. Review Summary

An independent, objective review and adversarial stress-testing were conducted across all files committed for Milestone M1 (Live UIDAI Worker) and Milestone M3 (Flutter Mobile Client Hardening).

### Integrity Check: PASS (Zero Integrity Violations)
- **Hardcoded test cheats / embedded facade outputs:** None found.
- **Dummy or facade implementations:** None found. All components contain real, robust logic.
- **Shortcuts bypassing the task:** None found.
- **Fabricated verification outputs or logs:** None found.

### Verdict Rationale: `REQUEST_CHANGES`
While Milestone M3 (Flutter Mobile Hardening) passed all quality, security, and widget tests with zero defects, Milestone M1 (Worker & Backend) contains two material flaws uncovered during adversarial testing and code inspection:
1. **SSRF / Protocol Smuggling in `allowlist.py` (Major Security Finding):** `DomainAllowlistInterceptor.is_url_allowed()` does not validate the URL scheme, permitting dangerous non-HTTP schemes (`gopher://127.0.0.1:6379/_flushall`, `file://127.0.0.1/...`, `ftp://127.0.0.1/...`) when the hostname matches an allowlisted host.
2. **Deterministic State Machine Bypass in `internal.py` (Major Architectural Finding):** `internal.py` directly mutates `store.tasks[task_id]["status"] = "COMPLETED"` upon receiving `task_completed` from the worker WebSocket, bypassing the non-negotiable Rule 2 Verifier-Only Completion Gate enforced by `transition(task, TaskState.COMPLETED, actor="verifier")`.

---

## 2. Findings

### [Major / Security] Finding 1: Protocol Smuggling & SSRF via Missing Scheme Validation in `allowlist.py`
- **What:** `DomainAllowlistInterceptor.is_url_allowed(url)` permits arbitrary URI schemes (e.g. `gopher://`, `file://`, `ftp://`) if the parsed hostname matches an allowlisted domain.
- **Where:** `backend/app/worker/allowlist.py`, lines 52–69.
- **Why:** 
  ```python
  # allowlist.py: lines 57-68
  parsed = urlparse(url)
  hostname = parsed.hostname
  if not hostname:
      return False
  hostname = hostname.lower()

  for allowed in self.allowed_domains:
      if hostname == allowed:
          return True
  ```
  `urlparse("gopher://127.0.0.1:6379/_flushall").hostname` yields `"127.0.0.1"`. Because `"127.0.0.1"` is present in `DEFAULT_ALLOWED_DOMAINS`, `is_url_allowed` returns `True`. In an automated Chromium browser instance, this permits outbound protocol smuggling and local SSRF (e.g., targeting local Redis/internal daemons).
  This was verified by running:
  ```bash
  uv run python -c "from backend.app.worker.allowlist import DomainAllowlistInterceptor; i = DomainAllowlistInterceptor(); print(i.is_url_allowed('gopher://127.0.0.1:6379/_flushall'))"
  # Output: True
  ```
- **Suggestion:** In `backend/app/worker/allowlist.py`, enforce that for network requests, `parsed.scheme in ("http", "https")`:
  ```python
  if parsed.scheme not in ("http", "https"):
      return False
  ```

---

### [Major / Architecture] Finding 2: Invariant Bypass of Deterministic State Machine in `internal.py`
- **What:** `/internal/worker` WebSocket handler directly modifies task dictionary status values instead of executing the transition through the deterministic state machine.
- **Where:** `backend/app/api/internal.py`, lines 140–145, lines 181–189.
- **Why:**
  AGENTS.md Non-Negotiable Invariant Rule 2 explicitly mandates:
  > *"A task can ONLY transition from VERIFYING to COMPLETED if and only if: 1. The actor is explicitly actor="verifier". 2. The 5-point document security inspection passes."*
  
  In `internal.py`:
  ```python
  # internal.py: lines 181-189
  elif msg_type == "task_completed":
      task_id = data.get("task_id")
      if task_id:
          with store._lock:
              if task_id in store.tasks:
                  store.tasks[task_id]["status"] = "COMPLETED"
                  store.tasks[task_id]["finished_at"] = time.time()
  ```
  Direct mutation (`store.tasks[task_id]["status"] = "COMPLETED"`) completely bypasses `transition()` and `can_transition()`, making state changes unverifiable by the state machine and vulnerable to unauthorized actor spoofing.
- **Suggestion:** In `backend/app/api/internal.py`:
  Import `from ..state_machine import transition, TaskState`
  On `task_completed`:
  ```python
  with store._lock:
      if task_id in store.tasks:
          task = store.tasks[task_id]
          transition(task, TaskState.COMPLETED, actor="verifier")
          task["finished_at"] = time.time()
  ```
  On `challenge_required`:
  ```python
  with store._lock:
      if task_id in store.tasks:
          task = store.tasks[task_id]
          transition(task, TaskState.WAITING_FOR_USER, actor="orchestrator")
          task["pending_input"] = kind
  ```

---

## 3. Milestone M3 (Flutter Mobile Hardening) Evaluation: APPROVED

The Flutter mobile implementation was reviewed in detail and confirmed to be completely compliant, high-quality, and robust:
1. **OS-Level Window Security (Android `FLAG_SECURE`):**
   - `MainActivity.kt` registers `MethodChannel("com.saralai.app/security")`.
   - `enableSecureWindow` calls `window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)`.
   - `disableSecureWindow` calls `window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)`.
   - `ScreenSecurity` service encapsulates the platform channel with defensive checks (`kIsWeb`, `Platform.isAndroid`), handling `MissingPluginException` and `PlatformException` safely.
2. **Sensitive Input Shielding (`secure_input_sheet.dart`):**
   - Calls `ScreenSecurity.enableSecureWindow()` in `initState()` and `ScreenSecurity.disableSecureWindow()` in `dispose()`.
   - `autocorrect: false`, `enableSuggestions: false`, `enableInteractiveSelection: false` strictly prevent clipboard and keyboard dictionary exposure.
   - 12-digit Aadhaar input uses `AadhaarMaskingFormatter` masking the first 8 digits as `XXXX-XXXX-1234`.
   - 180-second countdown circular progress ring with live second-by-second updates.
   - Dynamic base64 CAPTCHA decoding (`_getCaptchaBytes()`) renders `Image.memory` with error fallback.
   - Interactive refresh button (`IconButton(icon: Icon(Icons.refresh), onPressed: widget.onRefreshCaptcha)`).
3. **Document Vault Security & Guidance (`vault_screen.dart`):**
   - Informative password formula banner on encrypted cards: `"Password: First 4 letters of your name in CAPITAL + 4-digit Year of Birth (e.g., SURE1990)"`.
   - Interactive modal dialog `_showPasswordHintDialog` triggered when the user taps "Open" on an encrypted document.
   - Retention countdown pill badge and SHA-256 checksum displayed on all document cards.
4. **Design Token Compliance:**
   - Strict monochrome palette (`#000000`, `#0A0A0A`, `#141414`, `#1A1A1A`, `#FFFFFF`) with zero accent colors.
   - Glass surfaces respect blur budget (`<= 3` per screen).
5. **Static Analysis & Tests:**
   - `flutter analyze` reports 0 errors and 0 warnings.
   - `flutter test` executes 28/28 passing unit and widget tests.

---

## 4. Observation

The following direct observations were recorded:

1. **Worker Test Suite Execution:**
   - Command: `uv run --with pytest pytest backend/app/worker/test_worker.py -v`
   - Result: 28 passed in 1.44s.
   - Verifies 5-point document security inspection (missing header, truncate, oversize, EOF, malicious javascript/launch), allowlist matching, WebSocket client future resolution/cancellation, runner sandbox tempdir deletion, cascading UIDAI selectors, Supabase inclusion, and humanlike typing delays.
2. **Flutter Test Suite Execution:**
   - Command: `flutter test` inside `app/`
   - Result: 28 passed in 2.0s.
   - Verifies `ScreenSecurity` channel invocation, non-Android bypass, exception handling, design tokens, Auth, Chat, TaskStepperCard, SecureInputSheet masking, OTP countdown, CAPTCHA base64 rendering & refresh, ScreenSecurity toggle on mount/dispose, HistoryDrawer, VaultScreen password hint banner & modal, and GlassSurface blur budget.
3. **Flutter Static Analysis:**
   - Command: `flutter analyze` inside `app/`
   - Result: `No issues found! (ran in 1.8s)`.
4. **E2E 4-Tier Test Suite Execution:**
   - Command: `uv run python run_e2e_tests.py`
   - Result: 84/84 passed in 4.52s.
5. **Adversarial Scheme Attack Verification:**
   - Observation: Calling `DomainAllowlistInterceptor.is_url_allowed("gopher://127.0.0.1:6379/_flushall")` evaluates to `True`.
   - Reason: Scheme was not verified to be `http` or `https`.
6. **State Machine Invariant Verification in `internal.py`:**
   - Observation: Direct assignment `store.tasks[task_id]["status"] = "COMPLETED"` at line 186 of `backend/app/api/internal.py`.

---

## 5. Logic Chain

1. **Integrity Validation:**
   - *Observation:* Code inspection of `runner.py`, `client.py`, `internal.py`, `MainActivity.kt`, `screen_security.dart`, `secure_input_sheet.dart`, and `vault_screen.dart` reveals real functional code, real event listeners, real cryptographic checks, and real platform channels.
   - *Inference:* No mock facades or integrity cheats are present.
2. **Security Stress-Testing (`allowlist.py`):**
   - *Observation:* `allowlist.py` permits URLs based solely on `parsed.hostname`.
   - *Inference:* An attacker providing `gopher://` or `file://` scheme to `127.0.0.1` can bypass security restrictions.
   - *Inference:* Scheme validation is a critical security requirement for all browser automation workers.
3. **Architectural Invariant Enforcement (`internal.py`):**
   - *Observation:* Rule 2 requires that transitions to `COMPLETED` can only occur via `actor="verifier"` through `transition()`.
   - *Observation:* `internal.py` sets status directly without invoking `transition()`.
   - *Inference:* This is an architectural boundary violation that must be corrected to maintain state machine guarantees across the backend.
4. **Mobile Verification:**
   - *Observation:* All M3 requirements (FLAG_SECURE, countdown ring, OTP cells, base64 CAPTCHA, refresh button, password hint dialog) are fully implemented and verified with 0 lint errors and 28 passing widget tests.
   - *Inference:* M3 satisfies all acceptance criteria.

---

## 6. Caveats

- **Live UIDAI Network Availability:** Live UIDAI portal automation (`https://myaadhaar.uidai.gov.in`) requires live portal availability and real citizen SMS OTP delivery on device. The mock portal test harness remains the deterministic baseline for continuous integration.
- **External PDF Viewer Delegation:** `vault_screen.dart` delegates opening decrypted/encrypted PDFs to the operating system's default PDF viewer (e.g. Adobe Acrobat, Google Drive PDF Viewer). The password prompt is rendered by the external viewer; Saral AI provides the formula hint prior to launching.

---

## 7. Conclusion & Action Items

**Milestone M3 is APPROVED.**  
**Milestone M1 is REQUEST_CHANGES.**

### Action Items for M1 Implementer:
1. In `backend/app/worker/allowlist.py`:
   Add scheme verification in `is_url_allowed`:
   ```python
   if parsed.scheme not in ("http", "https"):
       return False
   ```
2. In `backend/app/api/internal.py`:
   Replace direct status assignments with calls to `transition()`:
   - On `challenge_required`: use `transition(task, TaskState.WAITING_FOR_USER, actor="orchestrator")`.
   - On `task_completed`: use `transition(task, TaskState.COMPLETED, actor="verifier")`.
   - On `task_failed`: use `transition(task, TaskState.FAILED, actor="orchestrator", reason=error_code)`.

Once these two surgical changes are applied, Milestone M1 will be ready for immediate re-approval.

---

## 8. Verification Method

To verify the fixes independently:

```bash
# 1. Verify scheme restriction in allowlist:
uv run python -c "from backend.app.worker.allowlist import DomainAllowlistInterceptor; i = DomainAllowlistInterceptor(); assert i.is_url_allowed('gopher://127.0.0.1:6379/_flushall') is False; assert i.is_url_allowed('http://127.0.0.1:8000/health') is True"

# 2. Run browser worker test suite (28 tests):
uv run --with pytest pytest backend/app/worker/test_worker.py -v

# 3. Run Flutter mobile tests (28 tests):
cd app && flutter test

# 4. Run Flutter static analysis:
cd app && flutter analyze

# 5. Run full E2E test suite (84 tests):
uv run python run_e2e_tests.py
```
