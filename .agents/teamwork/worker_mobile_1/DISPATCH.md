## 2026-10-13T14:36:30Z
Your identity: worker_mobile_1
Your working directory: d:\Startup\Saral Ai\Saral_app\.agents\teamwork\worker_mobile_1\
Original request path (MANDATORY TO READ FIRST): d:\Startup\Saral Ai\Saral_app\.agents\teamwork\ORIGINAL_REQUEST.md
Scope path: d:\Startup\Saral Ai\Saral_app\.agents\teamwork\teamwork_preview_orchestrator_2\SCOPE.md
Investigation blueprint: d:\Startup\Saral Ai\Saral_app\.agents\teamwork\explorer_survey_2_3\handoff.md

DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Exclusively Owned Files:
- app/android/app/src/main/kotlin/com/saralai/app/MainActivity.kt
- app/lib/core/services/screen_security.dart
- app/lib/features/chat/presentation/widgets/secure_input_sheet.dart
- app/lib/features/chat/presentation/widgets/task_stepper_card.dart
- app/lib/features/vault/presentation/vault_screen.dart
- app/test/widget_test.dart
- app/test/screen_security_test.dart

Mission & Tasks:
1. Implement Android `FLAG_SECURE` Platform Channel:
   - In `app/android/app/src/main/kotlin/com/saralai/app/MainActivity.kt`: override `configureFlutterEngine()` to register a MethodChannel `com.saralai.app/security` handling `enableSecureWindow` (`window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)`) and `disableSecureWindow` (`window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)`).
   - In `app/lib/core/services/screen_security.dart`: implement `ScreenSecurity` service invoking this channel safely with try/catch fallback on non-Android platforms.
2. Update `SecureInputSheet` (`app/lib/features/chat/presentation/widgets/secure_input_sheet.dart`):
   - Invoke `ScreenSecurity.enableSecureWindow()` on `initState` and `ScreenSecurity.disableSecureWindow()` on `dispose`.
   - In `_buildCaptchaInput()`: decode base64 image bytes from `widget.challengeImageBase64` using `Image.memory(...)` when provided.
   - Add an interactive "Refresh CAPTCHA" button (`IconButton(icon: Icon(Icons.refresh), onPressed: widget.onRefreshCaptcha)`).
   - Ensure 180s countdown ring and 6-cell OTP input with clipboard and keyboard security remain fully functional.
3. Update `VaultScreen` (`app/lib/features/vault/presentation/vault_screen.dart`):
   - When a citizen views or opens a password-protected document (`pdfEncrypted == true`), display an informative banner or modal explaining the UIDAI password formula: "Password: First 4 letters of your name in CAPITAL + 4-digit Year of Birth (e.g., SURE1990)".
4. Tests & Analysis:
   - Add/update unit and widget tests in `app/test/` to cover `ScreenSecurity`, CAPTCHA base64 rendering, refresh callback, and password hint dialog/banner.
   - Run `flutter analyze` and `flutter test` in `app/`. Ensure 0 errors, 0 warnings, and all tests pass.
5. Write your handoff report to:
   `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\worker_mobile_1\handoff.md`
Then send a brief message with your handoff path.
