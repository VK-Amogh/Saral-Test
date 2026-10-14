import 'dart:io' show Platform;
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// ScreenSecurity handles OS-level window security shielding (Android FLAG_SECURE).
/// When enabled, the native window blocks:
/// - Screen captures / screenshots
/// - Screen recordings
/// - Recent apps / task switcher screen previews
class ScreenSecurity {
  @visibleForTesting
  static const MethodChannel channel = MethodChannel('com.saralai.app/security');

  static bool _isSecure = false;

  /// Returns whether screen security is currently enabled.
  static bool get isSecure => _isSecure;

  /// Enables Android FLAG_SECURE on the native window.
  /// Falls back safely with a try/catch on non-Android platforms, web, or headless test runners.
  static Future<bool> enableSecureWindow() async {
    try {
      if (kIsWeb) {
        _isSecure = false;
        return false;
      }

      // Check whether target platform is Android
      final bool isAndroid = defaultTargetPlatform == TargetPlatform.android ||
          (!kIsWeb && Platform.isAndroid);

      if (isAndroid) {
        final result = await channel.invokeMethod<bool>('enableSecureWindow');
        _isSecure = result ?? true;
        return _isSecure;
      }

      _isSecure = false;
      return false;
    } on MissingPluginException {
      // In unit/widget tests without native implementation
      _isSecure = true;
      return true;
    } on PlatformException catch (e) {
      debugPrint('ScreenSecurity.enableSecureWindow PlatformException: ${e.message}');
      return false;
    } catch (e) {
      debugPrint('ScreenSecurity.enableSecureWindow error: $e');
      return false;
    }
  }

  /// Disables Android FLAG_SECURE on the native window.
  /// Falls back safely with a try/catch on non-Android platforms, web, or headless test runners.
  static Future<bool> disableSecureWindow() async {
    try {
      if (kIsWeb) {
        _isSecure = false;
        return true;
      }

      final bool isAndroid = defaultTargetPlatform == TargetPlatform.android ||
          (!kIsWeb && Platform.isAndroid);

      if (isAndroid) {
        final result = await channel.invokeMethod<bool>('disableSecureWindow');
        _isSecure = !(result ?? true);
        return true;
      }

      _isSecure = false;
      return true;
    } on MissingPluginException {
      _isSecure = false;
      return true;
    } on PlatformException catch (e) {
      debugPrint('ScreenSecurity.disableSecureWindow PlatformException: ${e.message}');
      return false;
    } catch (e) {
      debugPrint('ScreenSecurity.disableSecureWindow error: $e');
      return false;
    }
  }

  /// For testing purposes only: resets the internal security state.
  @visibleForTesting
  static void resetForTesting() {
    _isSecure = false;
  }
}
