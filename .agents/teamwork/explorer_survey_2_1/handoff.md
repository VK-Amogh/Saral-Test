# Architecture Survey & Implementation Blueprint: Live UIDAI Portal Automation, Anti-Bot Stealth & Zero-Persistence Challenge Relay

**Agent Identity:** `explorer_survey_2_1`  
**Working Directory:** `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\explorer_survey_2_1\`  
**Target Milestone:** Live UIDAI Portal Automation, Stealth Runner, Route Allowlist & Zero-Persistence Challenge Relay  
**Date:** 2026-10-13  

---

## 1. Observation

Direct code inspections and live environment verifications were performed across all components of the Playwright browser automation worker, FastAPI backend, mock portal, and Flutter mobile client.

### 1.1 Playwright Automation Runner (`backend/app/worker/runner.py`)
- **Selector Definitions (Lines 42–92):**
  ```python
  UID_SELECTORS = [
      "#uid_input",
      "input[name='uid']",
      "input[placeholder*='Enter Aadhaar']",
      "input[placeholder*='Aadhaar Number']",
      "input[aria-label*='Aadhaar']",
  ]
  CAPTCHA_IMG_SELECTORS = [
      "#captcha_img",
      "img[alt*='Captcha']",
      "img[alt*='captcha']",
      "img[src*='captcha']",
      ".captcha-image img",
  ]
  CAPTCHA_INPUT_SELECTORS = [
      "#captcha_input",
      "input[name='captcha']",
      "input[placeholder*='Enter Captcha']",
      "input[aria-label*='Captcha']",
  ]
  SEND_OTP_SELECTORS = [
      "#btn_send_otp",
      "button:has-text('Send OTP')",
      "button:has-text('Login with OTP')",
      "button[type='submit']",
  ]
  OTP_INPUT_SELECTORS = [
      "#otp_input",
      "input[name='otp']",
      "input[placeholder*='Enter OTP']",
      "input[maxlength='6']",
  ]
  VERIFY_DOWNLOAD_SELECTORS = [
      "#btn_verify_download",
      "button:has-text('Verify & Download')",
      "button:has-text('Verify and Download')",
      "button:has-text('Download e-Aadhaar')",
  ]
  ```
- **Browser Launch & Anti-Detection Setup (Lines 173–204):**
  Chromium is launched headless with:
  ```python
  args=[
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-blink-features=AutomationControlled"
  ]
  ```
  And stealth overrides applied via `context.add_init_script`:
  ```python
  await context.add_init_script("""
      Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
      window.chrome = { runtime: {} };
      Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en', 'hi']});
      Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
  """)
  ```
- **In-Memory CAPTCHA Screenshot Extraction (Lines 251–259):**
  ```python
  captcha_elem = await self._find_visible_locator(page, CAPTCHA_IMG_SELECTORS, timeout_ms=10000)
  captcha_bytes = await captcha_elem.screenshot(type="png")
  captcha_b64 = base64.b64encode(captcha_bytes).decode("ascii")
  ```
- **Zero-Persistence Challenge Relay & Cleanup (Lines 261–284, 348–365, 468–498):**
  Input values (`captcha_value`, `otp_value`) are received from `asyncio.Future`, filled via `locator.fill()`, and immediately deleted via `del` statements. Sandboxes and temporary directories created in `tempfile.mkdtemp(prefix=f"saral_task_{task_id}_")` are deleted in `finally` blocks via `shutil.rmtree`.

### 1.2 Route Allowlist Interceptor (`backend/app/worker/allowlist.py` & `backend/app/config.py`)
- In `backend/app/worker/allowlist.py` (Lines 15–21):
  ```python
  DEFAULT_ALLOWED_DOMAINS = [
      "localhost",
      "127.0.0.1",
      "mock-portal.local",
      "uidai.gov.in",
      "myaadhaar.uidai.gov.in",
  ]
  ```
- In `backend/app/config.py` (Lines 29–35):
  ```python
  ALLOWED_DOMAINS: List[str] = [
      "mock-portal.local",
      "127.0.0.1",
      "localhost",
      "uidai.gov.in",
      "myaadhaar.uidai.gov.in",
  ]
  ```
- Subdomain matching logic (Lines 61–67):
  ```python
  for allowed in self.allowed_domains:
      if hostname == allowed:
          return True
      if hostname.endswith("." + allowed):
          return True
  ```
  **Direct Observation:** Neither `DEFAULT_ALLOWED_DOMAINS` nor `config.py` includes `"supabase.co"` or `"rsftbslckmdkynprmpin.supabase.co"`, despite the system using Supabase storage (`https://rsftbslckmdkynprmpin.supabase.co`).

### 1.3 Challenge Broker (`backend/app/broker.py`)
- `ChallengeBroker` manages in-memory `_futures: Dict[str, asyncio.Future[SecretStr]]` and `_captchas: Dict[str, bytes]`.
- Implements `store_captcha(task_id, image_bytes)`, `get_captcha(task_id)`, `resolve_challenge(task_id, value: SecretStr)`.
- Enforces 180s expiration (`expires_at = now + ttl_seconds`), with zero disk or database persistence.

### 1.4 Worker WebSocket Client (`backend/app/worker/client.py`) & Backend Endpoint (`backend/app/api/internal.py`)
- In `backend/app/worker/client.py`:
  - Registers input futures: `register_input_future(task_id, kind) -> asyncio.Future[str]`.
  - Dispatches `relay_input` frame to resolve the registered future.
  - Sends `challenge_required` frame with `challenge_data_b64` to the backend.
- In `backend/app/api/internal.py` (Lines 87–104):
  ```python
  while True:
      raw_msg = await websocket.receive_text()
      data = json.loads(raw_msg)
      msg_type = data.get("type", "")
      if msg_type == "ping":
          await websocket.send_text(json.dumps({"type": "pong", "timestamp": time.time()}))
      elif msg_type == "ready":
          await websocket.send_text(json.dumps({"type": "acknowledged", "status": "idle"}))
      else:
          await websocket.send_text(json.dumps({"type": "received", "data": data}))
  ```
  **Direct Observation:** The WebSocket endpoint `/internal/worker` currently echoes received frames. It does **not** forward `challenge_required` frames to `challenge_broker`, nor does `api/tasks.py` forward `POST /tasks/{id}/input` payloads to the WebSocket connection.

### 1.5 Flutter Secure Input Sheet (`app/lib/features/chat/presentation/widgets/secure_input_sheet.dart`)
- Lines 118–120: Hardens input fields with `enableSuggestions: false`, `autocorrect: false`, `enableInteractiveSelection: false`.
- Lines 453–488: 6-cell OTP input with individual controllers and focus nodes.
- Lines 497–511:
  ```dart
  if (widget.challengeImageUrl != null) ...[
    Container(
      height: 60,
      alignment: Alignment.center,
      child: Text('CAPTCHA: [Image in memory]', ...),
    ),
  ]
  ```
  **Direct Observation:** The widget currently renders text placeholder `'CAPTCHA: [Image in memory]'` rather than decoding and displaying base64 bytes using `Image.memory()`. Also, it lacks an interactive "Refresh CAPTCHA" button.

### 1.6 Current Test Execution Baseline
All existing test suites pass with 100% success rate:
- `backend/app/worker/test_worker.py`: 23 passed in 0.77s (`uv run --with pytest pytest backend/app/worker/test_worker.py -v`)
- `backend/tests/test_backend.py`: 30 passed in 0.35s (`uv run pytest backend/tests/ -v`)
- `mock_portal/tests/test_mock_portal.py`: 18 passed in 0.55s (`uv run pytest mock_portal/tests/ -v`)
- `run_e2e_tests.py` (4 Tiers): 84 passed in 4.51s (`uv run python run_e2e_tests.py`)
- `supabase/tests/verify_schema.py`: 81 passed in 1.1s (`uv run python supabase/tests/verify_schema.py`)

---

## 2. Logic Chain

```
[Observation 1.1: runner.py multi-selectors]
               │
               ▼
   [Step 1: Live UIDAI DOM Structure vs Mock Portal]
   - Live myAadhaar portal is a dynamic React SPA with radio button identity selection
   - Input controls use React synthetic event listeners; simple `.fill()` without keystrokes
     leaves React internal state out of sync and "Send OTP" button disabled
   - Frequent modal advisories (PoI/PoA update notices) obstruct clickable elements
               │
               ▼
[Observation 1.1: runner.py stealth init script]
               │
               ▼
   [Step 2: Anti-Bot & WAF Detection Analysis]
   - Government portals are protected by Akamai / Cloudflare / NIC WAF
   - `get: () => undefined` on `navigator.webdriver` is detectable via prototype inspection
   - Headless Chromium leaks SwiftShader / Google in WebGL unmasked vendor, 0 concurrency,
     and non-standard window.screen dimensions
   - Instantaneous 0ms typing triggers statistical bot detection algorithms
               │
               ▼
[Observation 1.2: allowlist.py & config.py missing Supabase]
               │
               ▼
   [Step 3: Route Allowlist Security & Completeness]
   - Allowlist permits *.uidai.gov.in and localhost, but excludes supabase.co
   - Any worker-side interaction or redirection to Supabase storage URL would be aborted
   - Subdomain validation logic correctly prevents phishing suffix attacks
               │
               ▼
[Observation 1.4 & 1.5: WebSocket handler echo & Flutter placeholder]
               │
               ▼
   [Step 4: End-to-End Challenge Relay Protocol Gap]
   - In-memory challenge relay requires a bidirectional bridge:
     Worker (screenshot) ➔ WS /internal/worker ➔ ChallengeBroker ➔ GET /challenge ➔ Flutter
     Flutter (input) ➔ POST /tasks/{id}/input ➔ ChallengeBroker ➔ WS /internal/worker ➔ Worker Future
   - Currently, backend WebSocket echoes without updating broker or forwarding user submissions
   - Flutter client lacks base64 image rendering and interactive CAPTCHA refresh trigger
```

---

## 3. Caveats

1. **Live Portal Availability & Maintenance Windows:**  
   The live UIDAI myAadhaar portal (`https://myaadhaar.uidai.gov.in`) undergoes periodic scheduled maintenance and unscheduled downtime. The mock portal (`mock_portal/`) must remain the primary automated CI/CD deterministic test oracle.
2. **Citizen SMS OTP Delivery Rate:**  
   Live testing requires an actual citizen UID and access to the linked mobile SIM. UIDAI imposes a 180-second validity window on SMS OTPs and locks out residents after 3 failed attempts in a 24-hour cycle. Automated tests must never spam real citizen credentials.
3. **Audio vs Visual CAPTCHA:**  
   UIDAI supports an audio CAPTCHA button alongside the visual image. The automation scope is focused on visual image extraction (element screenshot) relayed to the human citizen.
4. **Platform Execution Environment (Windows vs Linux/Render):**  
   Local development is on Windows (PowerShell), while Render free tier runs Linux containers. Chromium launch arguments (`--no-sandbox`, `--disable-dev-shm-usage`, `--disable-gpu`) are required for Linux container stability.

---

## 4. Conclusion & Architectural Recommendations

The survey establishes concrete design requirements across four implementation pillars:

### Pillar 1: Live UIDAI Portal Automation (`https://myaadhaar.uidai.gov.in/gen-download-eaadhaar`)
1. **Radio Tab Selection:**  
   Before UID entry, ensure the "Aadhaar Number" radio/tab is active:
   ```python
   aadhaar_tab = page.locator("input[value='AADHAAR'], button:has-text('Aadhaar Number'), label:has-text('Aadhaar Number')").first
   if await aadhaar_tab.is_visible():
       await aadhaar_tab.click()
   ```
2. **Universal 4-Tier Cascading Selector Engine:**  
   Expand selector fallback chains to support both React (myAadhaar) and Angular/legacy versions:
   - **UID Input:**
     `#uid_input`, `input[name='uid']`, `input[formcontrolname='uid']`, `input[aria-label*='Aadhaar' i]`, `input[placeholder*='Aadhaar' i]`, `label:has-text('Aadhaar') >> .. >> input`
   - **CAPTCHA Image:**
     `#captcha_img`, `img[alt*='Captcha' i]`, `img[src*='captcha' i]`, `canvas.captcha-canvas`, `svg.captcha-svg`, `.captcha-box img`
   - **CAPTCHA Input:**
     `#captcha_input`, `input[name='captcha']`, `input[formcontrolname='captcha']`, `input[aria-label*='Captcha' i]`, `input[placeholder*='Captcha' i]`
   - **Send OTP Button:**
     `#btn_send_otp`, `button:has-text('Send OTP')`, `button[type='submit']:has-text('OTP')`
   - **OTP Input:**
     `#otp_input`, `input[name='otp']`, `input[formcontrolname='otp']`, `input[placeholder*='OTP' i]`, `input[maxlength='6']`
   - **Verify & Download Button:**
     `#btn_verify_download`, `button:has-text('Verify & Download')`, `button:has-text('Verify and Download')`
3. **React Controlled Input Synchronization & Button Enable Wait:**  
   Use `press_sequentially` with keystroke delays instead of instant `.fill()`:
   ```python
   await uid_locator.click()
   await uid_locator.press_sequentially(uid, delay=random.uniform(40, 80))
   ```
   Wait explicitly for `SEND_OTP` to be enabled:
   ```python
   await page.wait_for_function("btn => !btn.disabled", arg=submit_btn, timeout=5000)
   ```
4. **Modal Advisory Dismissal:**  
   Inject an automated check for popups/advisories:
   ```python
   dismiss_btn = page.locator("button:has-text('OK'), button:has-text('Close'), button[aria-label='Close'], .modal-close").first
   if await dismiss_btn.is_visible():
       await dismiss_btn.click()
   ```
5. **Masked Aadhaar Checkbox:**  
   Ensure "Do you want a masked Aadhaar?" checkbox (`input[type='checkbox']`) remains unchecked for standard e-KYC.

---

### Pillar 2: Anti-Bot Stealth Mechanisms
Implement a comprehensive stealth profile in `runner.py`:
1. **Clean `navigator.webdriver` Removal:**
   ```javascript
   delete Object.getPrototypeOf(navigator).webdriver;
   Object.defineProperty(navigator, 'webdriver', { get: () => false, configurable: true });
   ```
2. **Hardware Concurrency & Memory Emulation:**
   ```javascript
   Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
   Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
   Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });
   ```
3. **Screen & Viewport Normalization:**
   ```javascript
   Object.defineProperty(screen, 'width', { get: () => 1920 });
   Object.defineProperty(screen, 'height', { get: () => 1080 });
   Object.defineProperty(screen, 'availWidth', { get: () => 1920 });
   Object.defineProperty(screen, 'availHeight', { get: () => 1040 });
   Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
   window.outerWidth = 1920;
   window.outerHeight = 1080;
   ```
4. **WebGL Vendor & Renderer Spoofing:**
   ```javascript
   const getParam = WebGLRenderingContext.prototype.getParameter;
   WebGLRenderingContext.prototype.getParameter = function(param) {
       if (param === 37445) return 'Google Inc. (NVIDIA)';
       if (param === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)';
       return getParam.apply(this, arguments);
   };
   ```
5. **Permissions & Chrome Runtime API Spoofing:**
   ```javascript
   window.chrome = { runtime: { connect: () => {}, sendMessage: () => {} } };
   const origQuery = navigator.permissions.query;
   navigator.permissions.query = (p) => p.name === 'notifications' ? Promise.resolve({ state: Notification.permission }) : origQuery(p);
   ```
6. **Realistic Client Hints & Headers:**
   Pass headers on `browser.new_context`:
   ```python
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
   }
   ```
7. **Human-like Typing & Mouse Jitter:**
   - Keystroke delay: random 50–120ms with natural micro-pauses every 4 digits.
   - Mouse hover before click: `await locator.hover()` followed by 150–300ms pause.

---

### Pillar 3: Strict Route Allowlist
1. **Update Allowed Domains:**  
   Update `DEFAULT_ALLOWED_DOMAINS` in `allowlist.py` and `ALLOWED_DOMAINS` in `config.py` to include:
   ```python
   DEFAULT_ALLOWED_DOMAINS = [
       "localhost",
       "127.0.0.1",
       "mock-portal.local",
       "uidai.gov.in",
       "myaadhaar.uidai.gov.in",
       "supabase.co",
       "rsftbslckmdkynprmpin.supabase.co",
   ]
   ```
2. **Main-Frame Redirection Interception:**  
   Verify that any non-allowlisted top-level redirection aborts immediately with `SecurityPolicyViolation` to prevent phishing or credential exfiltration.

---

### Pillar 4: Live In-Memory Citizen Challenge Relay & Zero Persistence
1. **Backend WebSocket Bridge (`/internal/worker` ⟷ `challenge_broker`):**
   - Store active worker WebSocket connections in an in-memory registry: `worker_registry: Dict[str, WebSocket]`.
   - When the worker sends `{"type": "challenge_required", "task_id": "...", "challenge_data_b64": "..."}`:
     - Decode base64 bytes and call `challenge_broker.store_captcha(task_id, bytes)`.
     - Update task status: `store.tasks[task_id]["status"] = "WAITING_FOR_USER"`.
   - When the citizen submits input at `POST /api/v1/tasks/{id}/input`:
     - Retrieve secret value (`SecretStr`).
     - Resolve `challenge_broker.resolve_challenge(task_id, secret_val)`.
     - Forward WebSocket frame to active worker:
       ```json
       {"type": "relay_input", "task_id": task_id, "kind": kind, "value": secret_val.get_secret_value()}
       ```
2. **Interactive CAPTCHA Refresh Endpoint:**
   - Add `POST /api/v1/tasks/{task_id}/refresh-captcha`.
   - Forwards `{"type": "refresh_captcha", "task_id": task_id}` over WebSocket to the worker.
   - Worker clicks `#btn_refresh_captcha`, captures fresh screenshot, and returns updated `challenge_required` frame with fresh base64 image bytes.
3. **Flutter Client Base64 Rendering & Refresh Button:**
   - In `SecureInputSheet` (`secure_input_sheet.dart`), when `challengeImageUrl` (or `challengeImageBase64`) is present:
     - Render `Image.memory(base64Decode(cleanedBase64))` with a high-contrast container.
     - Add an interactive "Refresh CAPTCHA" button that calls the refresh endpoint and updates the displayed image.

---

## 5. Verification Method

### 5.1 Command Line Verification Suite
To independently verify that the system maintains 100% test integrity and satisfies all contracts:

```bash
# 1. Run browser worker tests (23 tests: verifier, allowlist, client, runner)
uv run --with pytest pytest backend/app/worker/test_worker.py -v

# 2. Run backend API & core service tests (30 tests: auth, scrubber, state machine, broker, tasks, chat)
uv run pytest backend/tests/ -v

# 3. Run mock portal test suite (18 tests: happy path, 10 failure switches, changed selectors)
uv run pytest mock_portal/tests/ -v

# 4. Run database schema & security verification (81 tests: tables, RLS, indexes, constraints)
uv run python supabase/tests/verify_schema.py

# 5. Run full 4-Tier E2E test suite (84 tests across all tiers)
uv run python run_e2e_tests.py
```

### 5.2 Verification Files to Inspect
- `backend/app/worker/runner.py`: Verify selector fallback lists and anti-bot stealth hooks.
- `backend/app/worker/allowlist.py`: Verify domain allowlist entries and subdomain logic.
- `backend/app/worker/client.py`: Verify WebSocket challenge futures and relay frames.
- `backend/app/broker.py`: Verify in-memory ChallengeBroker zero-persistence invariants.
- `backend/app/api/internal.py`: Verify WebSocket connection handling and frame routing.
- `app/lib/features/chat/presentation/widgets/secure_input_sheet.dart`: Verify input shielding and image rendering.

### 5.3 Invalidation Conditions
The architectural recommendations are invalidated if:
1. UIDAI implements an SMS OTP-less flow (e.g. mandatory facial recognition or hardware biometric dongles).
2. UIDAI switches entirely to a third-party CAPTCHA provider (e.g. Cloudflare Turnstile or Google reCAPTCHA v3) that cannot be solved by visual challenge relay. In that scenario, the official DigiLocker OAuth2 IndiaStack route (Milestone Requirement R3) must serve as the primary automated pathway.
