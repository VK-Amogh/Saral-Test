import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:saral_app/core/services/screen_security.dart';
import 'package:saral_app/core/theme/tokens.dart';
import 'package:saral_app/core/widgets/glass_surface.dart';
import 'package:saral_app/features/auth/presentation/auth_screen.dart';
import 'package:saral_app/features/chat/presentation/chat_screen.dart';
import 'package:saral_app/features/chat/presentation/widgets/secure_input_sheet.dart';
import 'package:saral_app/features/chat/presentation/widgets/task_stepper_card.dart';
import 'package:saral_app/features/history/presentation/history_drawer.dart';
import 'package:saral_app/features/vault/presentation/vault_screen.dart';

Widget _createTestApp(Widget child) {
  return ProviderScope(
    child: MaterialApp(
      theme: AppTheme.darkTheme,
      home: child,
    ),
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  GoogleFonts.config.allowRuntimeFetching = false;

  setUp(() {
    BlurBudgetManager.reset();
  });

  group('AuthScreen Widget Tests', () {
    testWidgets('Renders brand header, tab pills, and sign in form', (tester) async {
      await tester.pumpWidget(_createTestApp(const AuthScreen()));
      await tester.pumpAndSettle();

      expect(find.text('Saral AI'), findsOneWidget);
      expect(find.text('Sign In'), findsWidgets);
      expect(find.text('Sign Up'), findsOneWidget);
      expect(find.text('Reset'), findsOneWidget);
      expect(find.byType(TextFormField), findsNWidgets(2)); // Email & Password
    });

    testWidgets('Switching to Sign Up displays Confirm Password field', (tester) async {
      await tester.pumpWidget(_createTestApp(const AuthScreen()));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Sign Up'));
      await tester.pumpAndSettle();

      expect(find.text('Create Account'), findsWidgets);
      expect(find.text('Confirm Password'), findsOneWidget);
      expect(find.byType(TextFormField), findsNWidgets(3));
    });

    testWidgets('Switching to Reset Password hides password fields', (tester) async {
      await tester.pumpWidget(_createTestApp(const AuthScreen()));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Reset'));
      await tester.pumpAndSettle();

      expect(find.text('Reset Password'), findsWidgets);
      expect(find.text('Password'), findsNothing);
      expect(find.byType(TextFormField), findsOneWidget); // Email only
    });
  });

  group('ChatScreen Widget Tests', () {
    testWidgets('Renders Arapey greeting, suggestion pills, and composer pill', (tester) async {
      await tester.pumpWidget(_createTestApp(const ChatScreen()));
      await tester.pumpAndSettle();

      expect(find.text('Namaste'), findsOneWidget);
      expect(find.text('How can I help you today?'), findsOneWidget);
      expect(find.text('Download Aadhaar'), findsOneWidget);
      expect(find.text('Check Status'), findsOneWidget);
      expect(find.text('Ask Saral anything...'), findsOneWidget);
      expect(find.byIcon(Icons.mic_none), findsOneWidget);
      expect(find.byIcon(Icons.arrow_upward), findsOneWidget);
    });

    testWidgets('Sending query triggers message flow and task automation', (tester) async {
      await tester.pumpWidget(_createTestApp(const ChatScreen()));
      await tester.pumpAndSettle();

      // Enter query to trigger task
      await tester.enterText(find.byType(TextField).first, 'Download my Aadhaar');
      await tester.tap(find.byIcon(Icons.arrow_upward));
      await tester.pump();

      // Greeting should disappear and message should appear
      expect(find.text('Download my Aadhaar'), findsOneWidget);
      expect(find.byType(TaskStepperCard), findsOneWidget);

      // Drain simulated stream timers completely
      await tester.pump(const Duration(seconds: 2));
    });
  });

  group('TaskStepperCard Widget Tests', () {
    testWidgets('Renders workflow progress, title, and steps', (tester) async {
      await tester.pumpWidget(
        _createTestApp(
          const Scaffold(
            body: TaskStepperCard(
              taskId: 'task-test-1234',
              workflow: 'download_eaadhaar',
              initialStatus: 'RUNNING',
              initialProgress: 50,
            ),
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.text('Download Masked e-Aadhaar'), findsOneWidget);
      expect(find.text('50%'), findsOneWidget);
      expect(find.byType(LinearProgressIndicator), findsOneWidget);
      expect(find.text('Validate request & security policy'), findsOneWidget);
      expect(find.text('Connect to UIDAI portal'), findsOneWidget);
    });

    testWidgets('Displays Provide Secure Input button when status is WAITING_FOR_USER', (tester) async {
      await tester.pumpWidget(
        _createTestApp(
          const Scaffold(
            body: TaskStepperCard(
              taskId: 'task-test-5678',
              workflow: 'download_eaadhaar',
              initialStatus: 'WAITING_FOR_USER',
              initialProgress: 45,
            ),
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.text('Provide Secure Input'), findsOneWidget);
    });
  });

  group('SecureInputSheet Widget Tests', () {
    test('AadhaarMaskingFormatter visually masks first 8 digits as XXXX-XXXX-1234', () {
      final formatter = AadhaarMaskingFormatter();

      const oldValue = TextEditingValue.empty;
      const newValue = TextEditingValue(text: '123456789012');

      final formatted = formatter.formatEditUpdate(oldValue, newValue);
      expect(formatted.text, equals('XXXX-XXXX-9012'));
    });

    testWidgets('Renders Aadhaar input with security safeguards', (tester) async {
      await tester.pumpWidget(
        _createTestApp(
          Scaffold(
            body: SecureInputSheet(
              inputType: SecureInputType.aadhaar,
              title: 'Enter Aadhaar Number',
              onSubmit: (_) {},
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Enter Aadhaar Number'), findsOneWidget);
      expect(find.text('12-Digit Aadhaar Number'), findsOneWidget);

      final textField = tester.widget<TextField>(find.byType(TextField));
      expect(textField.autocorrect, isFalse);
      expect(textField.enableSuggestions, isFalse);
      expect(textField.enableInteractiveSelection, isFalse);
    });

    testWidgets('Renders OTP 180s countdown and 6 single-digit cells', (tester) async {
      await tester.pumpWidget(
        _createTestApp(
          Scaffold(
            body: SecureInputSheet(
              inputType: SecureInputType.otp,
              title: 'Verification OTP',
              onSubmit: (_) {},
            ),
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.text('Verification OTP'), findsOneWidget);
      expect(find.text('OTP Expires In'), findsOneWidget);
      expect(find.text('03:00'), findsOneWidget); // 180 seconds
      expect(find.byType(TextFormField), findsNWidgets(6)); // 6 pin cells
    });

    testWidgets('Renders CAPTCHA base64 image and interactive refresh button', (tester) async {
      bool refreshed = false;
      String submittedValue = '';

      // 1x1 transparent PNG base64
      const testBase64Png =
          'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAA=';

      await tester.pumpWidget(
        _createTestApp(
          Scaffold(
            body: SecureInputSheet(
              inputType: SecureInputType.captcha,
              title: 'Security CAPTCHA',
              challengeImageBase64: testBase64Png,
              onRefreshCaptcha: () {
                refreshed = true;
              },
              onSubmit: (val) {
                submittedValue = val;
              },
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Security CAPTCHA'), findsOneWidget);
      expect(find.byType(Image), findsOneWidget);
      expect(find.byIcon(Icons.refresh), findsOneWidget);

      // Tap refresh button
      await tester.tap(find.byIcon(Icons.refresh));
      await tester.pump();
      expect(refreshed, isTrue);

      // Enter CAPTCHA text and submit
      await tester.enterText(find.byType(TextFormField), 'AB12CD');
      await tester.pump();
      await tester.tap(find.text('Submit Securely'));
      await tester.pump();
      expect(submittedValue, equals('AB12CD'));
    });

    testWidgets('Toggles ScreenSecurity on mount and dispose', (tester) async {
      debugDefaultTargetPlatformOverride = TargetPlatform.android;
      final List<String> channelCalls = [];

      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(ScreenSecurity.channel, (MethodCall methodCall) async {
        channelCalls.add(methodCall.method);
        return true;
      });

      await tester.pumpWidget(
        _createTestApp(
          Scaffold(
            body: Builder(
              builder: (context) => ElevatedButton(
                onPressed: () {
                  SecureInputSheet.show(
                    context: context,
                    inputType: SecureInputType.otp,
                    title: 'Test Shield',
                  );
                },
                child: const Text('Open Sheet'),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Open sheet
      await tester.tap(find.text('Open Sheet'));
      await tester.pumpAndSettle();
      expect(channelCalls, contains('enableSecureWindow'));

      // Close sheet
      await tester.tap(find.byIcon(Icons.close));
      await tester.pumpAndSettle();
      expect(channelCalls, contains('disableSecureWindow'));

      debugDefaultTargetPlatformOverride = null;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(ScreenSecurity.channel, null);
    });
  });

  group('HistoryDrawer Widget Tests', () {
    testWidgets('Renders grouped conversations and search filter', (tester) async {
      await tester.pumpWidget(
        _createTestApp(
          const Scaffold(
            drawer: HistoryDrawer(),
            body: Center(child: Text('Main View')),
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Open drawer
      final scaffoldState = tester.state<ScaffoldState>(find.byType(Scaffold));
      scaffoldState.openDrawer();
      await tester.pumpAndSettle();

      expect(find.text('Conversations'), findsOneWidget);
      expect(find.text('Search chats...'), findsOneWidget);
      expect(find.text('Today'), findsOneWidget);

      // Filter search
      await tester.enterText(find.byType(TextField), 'Masked');
      await tester.pumpAndSettle();
      expect(find.text('Download Masked e-Aadhaar'), findsOneWidget);
    });
  });

  group('VaultScreen Widget Tests', () {
    testWidgets('Renders document cards, auto-delete countdown, and actions', (tester) async {
      await tester.pumpWidget(_createTestApp(const VaultScreen()));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.text('Document Vault'), findsOneWidget);
      expect(find.text('Encrypted Device Storage'), findsOneWidget);
      expect(find.text('eaadhaar_masked.pdf'), findsOneWidget);
      expect(find.text('Open'), findsWidgets);
      expect(find.text('Share'), findsWidgets);
      expect(find.byIcon(Icons.delete_outline), findsWidgets);
    });

    testWidgets('Displays password hint banner and opens password modal on encrypted document', (tester) async {
      await tester.pumpWidget(_createTestApp(const VaultScreen()));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      // Banner is visible on card
      expect(
        find.text('Password: First 4 letters of your name in CAPITAL + 4-digit Year of Birth (e.g., SURE1990)'),
        findsOneWidget,
      );

      // Tap Open on the first (encrypted) document
      await tester.tap(find.text('Open').first);
      await tester.pumpAndSettle();

      // Modal dialog appears
      expect(find.text('Password Protected Document'), findsOneWidget);
      expect(find.text('This official e-Aadhaar PDF is encrypted by UIDAI.'), findsOneWidget);
      expect(find.text('Open Document'), findsOneWidget);
      expect(find.text('Cancel'), findsOneWidget);

      // Tap Cancel dismisses modal
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(find.text('Password Protected Document'), findsNothing);
    });
  });

  group('GlassSurface Widget Tests', () {
    testWidgets('Renders child within RepaintBoundary and respects budget', (tester) async {
      BlurBudgetManager.reset();

      await tester.pumpWidget(
        _createTestApp(
          const Scaffold(
            body: Column(
              children: [
                GlassSurface(child: Text('Surface 1')),
                GlassSurface(child: Text('Surface 2')),
                GlassSurface(child: Text('Surface 3')),
                GlassSurface(child: Text('Surface 4')), // Exceeds budget, falls back gracefully
              ],
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Surface 1'), findsOneWidget);
      expect(find.text('Surface 2'), findsOneWidget);
      expect(find.text('Surface 3'), findsOneWidget);
      expect(find.text('Surface 4'), findsOneWidget);

      // First 3 get blur, 4th gets solid container fallback
      expect(BlurBudgetManager.activeBlurCount, equals(3));
    });
  });
}
