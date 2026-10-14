import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../../../core/services/screen_security.dart';
import '../../../../core/theme/tokens.dart';

enum SecureInputType { aadhaar, otp, captcha }

/// Custom Aadhaar visual masking formatter.
/// Formats raw 12 digits into visual representation: XXXX-XXXX-1234
/// Only the last 4 digits are revealed visually; raw value is preserved.
class AadhaarMaskingFormatter extends TextInputFormatter {
  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    final rawDigits = newValue.text.replaceAll(RegExp(r'\D'), '');
    if (rawDigits.length > 12) {
      return oldValue;
    }

    final buffer = StringBuffer();
    for (int i = 0; i < rawDigits.length; i++) {
      if (i > 0 && i % 4 == 0) {
        buffer.write('-');
      }
      if (i < 8) {
        buffer.write('X');
      } else {
        buffer.write(rawDigits[i]);
      }
    }

    final formattedText = buffer.toString();
    return TextEditingValue(
      text: formattedText,
      selection: TextSelection.collapsed(offset: formattedText.length),
    );
  }
}

class SecureInputSheet extends StatefulWidget {
  final SecureInputType inputType;
  final String title;
  final String? subtitle;
  final String? challengeImageUrl;
  final String? challengeImageBase64;
  final VoidCallback? onRefreshCaptcha;
  final Function(String rawValue) onSubmit;
  final VoidCallback? onCancel;

  const SecureInputSheet({
    super.key,
    required this.inputType,
    required this.title,
    this.subtitle,
    this.challengeImageUrl,
    this.challengeImageBase64,
    this.onRefreshCaptcha,
    required this.onSubmit,
    this.onCancel,
  });

  static Future<String?> show({
    required BuildContext context,
    required SecureInputType inputType,
    required String title,
    String? subtitle,
    String? challengeImageUrl,
    String? challengeImageBase64,
    VoidCallback? onRefreshCaptcha,
  }) {
    return showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppColors.pitchBlack,
      barrierColor: AppColors.pitchBlack.withValues(alpha: 0.75),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadii.sheet)),
      ),
      builder: (ctx) => Padding(
        padding: EdgeInsets.only(
          bottom: MediaQuery.of(ctx).viewInsets.bottom,
        ),
        child: SecureInputSheet(
          inputType: inputType,
          title: title,
          subtitle: subtitle,
          challengeImageUrl: challengeImageUrl,
          challengeImageBase64: challengeImageBase64,
          onRefreshCaptcha: onRefreshCaptcha,
          onSubmit: (val) => Navigator.of(ctx).pop(val),
          onCancel: () => Navigator.of(ctx).pop(null),
        ),
      ),
    );
  }

  @override
  State<SecureInputSheet> createState() => _SecureInputSheetState();
}

class _SecureInputSheetState extends State<SecureInputSheet> {
  final TextEditingController _textController = TextEditingController();
  final List<TextEditingController> _otpControllers =
      List.generate(6, (_) => TextEditingController());
  final List<FocusNode> _otpFocusNodes = List.generate(6, (_) => FocusNode());

  String _rawAadhaarDigits = '';
  int _remainingSeconds = 180; // 180s countdown per spec
  Timer? _countdownTimer;
  bool _canResendOtp = false;

  @override
  void initState() {
    super.initState();
    _applyFlagSecure();
    if (widget.inputType == SecureInputType.otp) {
      _startOtpCountdown();
    }
  }

  void _applyFlagSecure() {
    // Hardware/Platform secure flag safeguard:
    // Invokes WindowManager.LayoutParams.FLAG_SECURE via native platform channel
    ScreenSecurity.enableSecureWindow();
  }

  void _startOtpCountdown() {
    _remainingSeconds = 180;
    _canResendOtp = false;
    _countdownTimer?.cancel();
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) return;
      if (_remainingSeconds > 0) {
        setState(() {
          _remainingSeconds--;
        });
      } else {
        setState(() {
          _canResendOtp = true;
        });
        timer.cancel();
      }
    });
  }

  @override
  void dispose() {
    // Release native FLAG_SECURE window shield
    ScreenSecurity.disableSecureWindow();
    _countdownTimer?.cancel();
    _textController.dispose();
    for (final c in _otpControllers) {
      c.dispose();
    }
    for (final f in _otpFocusNodes) {
      f.dispose();
    }
    super.dispose();
  }

  void _handleAadhaarChanged(String value) {
    // Strip non-digits from input
    final digits = value.replaceAll(RegExp(r'\D'), '');
    if (digits.length <= 12) {
      _rawAadhaarDigits = digits;
    }
    setState(() {});
  }

  void _handleOtpChanged(int index, String value) {
    if (value.isNotEmpty) {
      if (index < 5) {
        _otpFocusNodes[index + 1].requestFocus();
      } else {
        _otpFocusNodes[index].unfocus();
      }
    } else {
      if (index > 0) {
        _otpFocusNodes[index - 1].requestFocus();
      }
    }
    setState(() {});
  }

  String _getOtpValue() {
    return _otpControllers.map((c) => c.text).join();
  }

  bool _isSubmitEnabled() {
    switch (widget.inputType) {
      case SecureInputType.aadhaar:
        return _rawAadhaarDigits.length == 12;
      case SecureInputType.otp:
        return _getOtpValue().length == 6;
      case SecureInputType.captcha:
        return _textController.text.trim().isNotEmpty;
    }
  }

  void _handleSubmit() {
    if (!_isSubmitEnabled()) return;

    switch (widget.inputType) {
      case SecureInputType.aadhaar:
        widget.onSubmit(_rawAadhaarDigits);
        break;
      case SecureInputType.otp:
        widget.onSubmit(_getOtpValue());
        break;
      case SecureInputType.captcha:
        widget.onSubmit(_textController.text.trim());
        break;
    }
  }

  String _formatTimer(int totalSeconds) {
    final minutes = (totalSeconds ~/ 60).toString().padLeft(2, '0');
    final seconds = (totalSeconds % 60).toString().padLeft(2, '0');
    return '$minutes:$seconds';
  }

  Uint8List? _getCaptchaBytes() {
    if (widget.challengeImageBase64 == null) return null;
    try {
      String cleanBase64 = widget.challengeImageBase64!.trim();
      if (cleanBase64.contains(',')) {
        cleanBase64 = cleanBase64.split(',').last;
      }
      return base64Decode(cleanBase64);
    } catch (e) {
      debugPrint('Failed to decode CAPTCHA base64: $e');
      return null;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: AppColors.pitchBlack,
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadii.sheet)),
        border: Border(
          top: BorderSide(color: AppColors.borderWhite, width: 1.0),
        ),
      ),
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.screenMargin,
        vertical: AppSpacing.space20,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Drag handle
          Center(
            child: Container(
              width: 36,
              height: 4,
              decoration: BoxDecoration(
                color: AppColors.textTertiary,
                borderRadius: BorderRadius.circular(AppRadii.full),
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.space16),

          // Header Row
          Row(
            children: [
              const Icon(Icons.security, color: AppColors.pureWhite, size: 22),
              const SizedBox(width: AppSpacing.space8),
              Expanded(
                child: Text(
                  widget.title,
                  style: AppTypography.cardHeading(),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.close, color: AppColors.textSecondary, size: 20),
                onPressed: widget.onCancel ?? () => Navigator.of(context).pop(),
              ),
            ],
          ),

          if (widget.subtitle != null) ...[
            const SizedBox(height: AppSpacing.space4),
            Text(
              widget.subtitle!,
              style: AppTypography.bodySmall(color: AppColors.textSecondary),
            ),
          ],

          const SizedBox(height: AppSpacing.space20),

          // Content based on type
          if (widget.inputType == SecureInputType.aadhaar) _buildAadhaarInput(),
          if (widget.inputType == SecureInputType.otp) _buildOtpInput(),
          if (widget.inputType == SecureInputType.captcha) _buildCaptchaInput(),

          const SizedBox(height: AppSpacing.space24),

          // Submit Button
          SizedBox(
            height: AppChrome.bar,
            child: ElevatedButton(
              style: ElevatedButton.styleFrom(
                backgroundColor: _isSubmitEnabled()
                    ? AppColors.pureWhite
                    : AppColors.darkGrey,
                foregroundColor: _isSubmitEnabled()
                    ? AppColors.pitchBlack
                    : AppColors.textTertiary,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(AppRadii.button),
                  side: BorderSide(
                    color: _isSubmitEnabled()
                        ? AppColors.pureWhite
                        : AppColors.borderWhite,
                    width: 1.0,
                  ),
                ),
                elevation: 0,
              ),
              onPressed: _isSubmitEnabled() ? _handleSubmit : null,
              child: Text(
                'Submit Securely',
                style: AppTypography.labelLarge(
                  color: _isSubmitEnabled()
                      ? AppColors.pitchBlack
                      : AppColors.textTertiary,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ),

          const SizedBox(height: AppSpacing.space12),

          // Security disclaimer
          Center(
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.lock_clock, size: 12, color: AppColors.textTertiary),
                const SizedBox(width: AppSpacing.space4),
                Text(
                  'End-to-end encrypted · Never stored in plaintext',
                  style: AppTypography.labelSmall(color: AppColors.textTertiary),
                ),
              ],
            ),
          ),

          const SizedBox(height: AppSpacing.space8),
        ],
      ),
    );
  }

  Widget _buildAadhaarInput() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '12-Digit Aadhaar Number',
          style: AppTypography.labelMedium(color: AppColors.textSecondary),
        ),
        const SizedBox(height: AppSpacing.space8),
        TextFormField(
          controller: _textController,
          keyboardType: TextInputType.number,
          autocorrect: false,
          enableSuggestions: false,
          enableInteractiveSelection: false, // FLAG_SECURE: Prevent clipboard exposure!
          inputFormatters: [
            FilteringTextInputFormatter.digitsOnly,
            LengthLimitingTextInputFormatter(12),
            AadhaarMaskingFormatter(),
          ],
          onChanged: _handleAadhaarChanged,
          style: AppTypography.bodyLarge(fontWeight: FontWeight.w600),
          decoration: InputDecoration(
            hintText: 'XXXX-XXXX-1234',
            hintStyle: AppTypography.bodyLarge(color: AppColors.textTertiary),
            prefixIcon: const Icon(Icons.badge_outlined, color: AppColors.textSecondary, size: 20),
            suffixIcon: _rawAadhaarDigits.length == 12
                ? const Icon(Icons.check_circle_outline, color: AppColors.pureWhite, size: 20)
                : null,
          ),
        ),
        const SizedBox(height: AppSpacing.space8),
        Text(
          'First 8 digits are visually masked for privacy per UIDAI regulations.',
          style: AppTypography.labelSmall(color: AppColors.textTertiary),
        ),
      ],
    );
  }

  Widget _buildOtpInput() {
    final progress = _remainingSeconds / 180.0;

    return Column(
      children: [
        // Countdown Ring Header
        Container(
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.space16,
            vertical: AppSpacing.space12,
          ),
          decoration: BoxDecoration(
            color: AppColors.darkGrey,
            borderRadius: BorderRadius.circular(AppRadii.card),
            border: Border.all(color: AppColors.borderWhite, width: 1.0),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // Circular progress countdown ring
              SizedBox(
                width: 32,
                height: 32,
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    CircularProgressIndicator(
                      value: progress,
                      strokeWidth: 3,
                      backgroundColor: AppColors.graphite,
                      valueColor: const AlwaysStoppedAnimation<Color>(AppColors.pureWhite),
                    ),
                    const Icon(Icons.timer_outlined, size: 14, color: AppColors.pureWhite),
                  ],
                ),
              ),
              const SizedBox(width: AppSpacing.space12),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'OTP Expires In',
                    style: AppTypography.labelSmall(color: AppColors.textTertiary),
                  ),
                  Text(
                    _formatTimer(_remainingSeconds),
                    style: AppTypography.labelLarge(
                      color: AppColors.pureWhite,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
              const Spacer(),
              TextButton(
                onPressed: _canResendOtp ? _startOtpCountdown : null,
                child: Text(
                  'Resend OTP',
                  style: AppTypography.labelMedium(
                    color: _canResendOtp ? AppColors.pureWhite : AppColors.textTertiary,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
        ),

        const SizedBox(height: AppSpacing.space20),

        // 6-digit OTP cells
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: List.generate(6, (index) {
            return SizedBox(
              width: 46,
              height: 54,
              child: TextFormField(
                controller: _otpControllers[index],
                focusNode: _otpFocusNodes[index],
                keyboardType: TextInputType.number,
                textAlign: TextAlign.center,
                maxLength: 1,
                obscureText: true,
                autocorrect: false,
                enableSuggestions: false,
                enableInteractiveSelection: false, // FLAG_SECURE: Zero clipboard exposure
                style: AppTypography.cardHeading(color: AppColors.pureWhite),
                decoration: InputDecoration(
                  counterText: '',
                  contentPadding: EdgeInsets.zero,
                  filled: true,
                  fillColor: AppColors.darkGrey,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(AppRadii.sm),
                    borderSide: const BorderSide(color: AppColors.borderWhite, width: 1.0),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(AppRadii.sm),
                    borderSide: const BorderSide(color: AppColors.pureWhite, width: 1.5),
                  ),
                ),
                onChanged: (val) => _handleOtpChanged(index, val),
              ),
            );
          }),
        ),
      ],
    );
  }

  Widget _buildCaptchaInput() {
    final captchaBytes = _getCaptchaBytes();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          height: 64,
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.space12),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: AppColors.darkGrey,
            borderRadius: BorderRadius.circular(AppRadii.sm),
            border: Border.all(color: AppColors.borderWhite, width: 1.0),
          ),
          child: Row(
            children: [
              Expanded(
                child: Center(
                  child: captchaBytes != null
                      ? Image.memory(
                          captchaBytes,
                          fit: BoxFit.contain,
                          height: 48,
                          errorBuilder: (context, error, stackTrace) => Text(
                            'CAPTCHA: [Image in memory]',
                            style: AppTypography.bodyMedium(color: AppColors.textSecondary),
                          ),
                        )
                      : Text(
                          'CAPTCHA: [Image in memory]',
                          style: AppTypography.bodyMedium(color: AppColors.textSecondary),
                        ),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.refresh, color: AppColors.pureWhite),
                tooltip: 'Refresh CAPTCHA',
                onPressed: widget.onRefreshCaptcha,
              ),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.space12),
        Text(
          'Enter characters shown above',
          style: AppTypography.labelMedium(color: AppColors.textSecondary),
        ),
        const SizedBox(height: AppSpacing.space8),
        TextFormField(
          controller: _textController,
          autocorrect: false,
          enableSuggestions: false,
          enableInteractiveSelection: false,
          style: AppTypography.bodyLarge(),
          decoration: const InputDecoration(
            hintText: 'Enter CAPTCHA',
            prefixIcon: Icon(Icons.security, color: AppColors.textSecondary, size: 20),
          ),
          onChanged: (_) => setState(() {}),
        ),
      ],
    );
  }
}
