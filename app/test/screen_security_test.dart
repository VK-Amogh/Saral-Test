import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:saral_app/core/services/screen_security.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  final List<MethodCall> log = <MethodCall>[];

  setUp(() {
    log.clear();
    ScreenSecurity.resetForTesting();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(ScreenSecurity.channel, (MethodCall methodCall) async {
      log.add(methodCall);
      switch (methodCall.method) {
        case 'enableSecureWindow':
          return true;
        case 'disableSecureWindow':
          return true;
        default:
          return null;
      }
    });
  });

  tearDown(() {
    debugDefaultTargetPlatformOverride = null;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(ScreenSecurity.channel, null);
  });

  group('ScreenSecurity Unit Tests', () {
    test('Initial isSecure status is false', () {
      expect(ScreenSecurity.isSecure, isFalse);
    });

    test('Invokes enableSecureWindow on Android and updates isSecure', () async {
      debugDefaultTargetPlatformOverride = TargetPlatform.android;

      expect(ScreenSecurity.isSecure, isFalse);
      final result = await ScreenSecurity.enableSecureWindow();

      expect(result, isTrue);
      expect(ScreenSecurity.isSecure, isTrue);
      expect(log, hasLength(1));
      expect(log.first.method, equals('enableSecureWindow'));
    });

    test('Invokes disableSecureWindow on Android and updates isSecure', () async {
      debugDefaultTargetPlatformOverride = TargetPlatform.android;

      await ScreenSecurity.enableSecureWindow();
      expect(ScreenSecurity.isSecure, isTrue);

      final result = await ScreenSecurity.disableSecureWindow();
      expect(result, isTrue);
      expect(ScreenSecurity.isSecure, isFalse);
      expect(log, hasLength(2));
      expect(log.last.method, equals('disableSecureWindow'));
    });

    test('Safely bypasses invocation on non-Android platform', () async {
      debugDefaultTargetPlatformOverride = TargetPlatform.iOS;

      final result = await ScreenSecurity.enableSecureWindow();
      expect(result, isFalse);
      expect(ScreenSecurity.isSecure, isFalse);
      expect(log, isEmpty);
    });

    test('Gracefully handles PlatformException from native channel', () async {
      debugDefaultTargetPlatformOverride = TargetPlatform.android;

      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(ScreenSecurity.channel, (MethodCall methodCall) async {
        throw PlatformException(code: 'SECURITY_ERROR', message: 'Failed to set FLAG_SECURE');
      });

      final result = await ScreenSecurity.enableSecureWindow();
      expect(result, isFalse);
      expect(ScreenSecurity.isSecure, isFalse);
    });
  });
}
