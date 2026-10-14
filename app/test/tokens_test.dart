import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:saral_app/core/theme/tokens.dart';
import 'package:saral_app/core/widgets/glass_surface.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  GoogleFonts.config.allowRuntimeFetching = false;

  group('Monochrome Design Tokens (rules.md)', () {
    test('Strict monochrome color tokens adhere to exact hex specifications', () {
      expect(AppColors.pitchBlack.toARGB32(), equals(0xFF000000));
      expect(AppColors.ink.toARGB32(), equals(0xFF0A0A0A));
      expect(AppColors.graphite.toARGB32(), equals(0xFF141414));
      expect(AppColors.darkGrey.toARGB32(), equals(0xFF1A1A1A));
      expect(AppColors.pureWhite.toARGB32(), equals(0xFFFFFFFF));
    });

    test('Zero accent color rule: all monochrome shades have equal R, G, B channels', () {
      final monochromeColors = [
        AppColors.pitchBlack,
        AppColors.ink,
        AppColors.graphite,
        AppColors.darkGrey,
        AppColors.pureWhite,
      ];

      for (final color in monochromeColors) {
        // In true monochrome/grayscale, red == green == blue
        final r = (color.r * 255).round();
        final g = (color.g * 255).round();
        final b = (color.b * 255).round();
        expect(r, equals(g), reason: 'Color $color is not grayscale: R=$r != G=$g');
        expect(g, equals(b), reason: 'Color $color is not grayscale: G=$g != B=$b');
      }
    });

    test('White text & interactive opacity hierarchy matches specification', () {
      expect(AppColors.textPrimary.a, closeTo(1.0, 0.01)); // 100%
      expect(AppColors.textSecondary.a, closeTo(0.64, 0.02)); // 64%
      expect(AppColors.textTertiary.a, closeTo(0.38, 0.02)); // 38%
      expect(AppColors.highlightSelected.a, closeTo(0.12, 0.02)); // 12%
      expect(AppColors.borderWhite.a, closeTo(0.10, 0.02)); // 10%
    });

    test('Chrome sizes strictly adhere to rules.md specifications', () {
      expect(AppChrome.bar, equals(56.0));
      expect(AppChrome.circle, equals(48.0));
      expect(AppChrome.compactCircle, equals(40.0));
      expect(AppChrome.compactHitTarget, equals(48.0));
      expect(AppChrome.capsule, equals(32.0));
      expect(AppChrome.barIcon, equals(22.0));
    });

    test('Spacing rhythm adheres to 4 dp multiples', () {
      expect(AppSpacing.screenMargin, equals(16.0));
      expect(AppSpacing.headingToContent, equals(12.0));
      expect(AppSpacing.sectionToSection, equals(24.0));
      expect(AppSpacing.gridGutter, equals(12.0));

      expect(AppSpacing.space4 % 4, equals(0));
      expect(AppSpacing.space8 % 4, equals(0));
      expect(AppSpacing.space12 % 4, equals(0));
      expect(AppSpacing.space16 % 4, equals(0));
      expect(AppSpacing.space20 % 4, equals(0));
      expect(AppSpacing.space24 % 4, equals(0));
      expect(AppSpacing.space32 % 4, equals(0));
    });

    test('Headings use Arapey Regular with upright font style (no italics)', () {
      final title = AppTypography.screenTitle();
      final section = AppTypography.sectionHeading();
      final card = AppTypography.cardHeading();
      final day = AppTypography.dayHeader();

      // Heading sizes per rules.md: 42, 28, 24, 20
      expect(title.fontSize, equals(42.0));
      expect(section.fontSize, equals(28.0));
      expect(card.fontSize, equals(24.0));
      expect(day.fontSize, equals(20.0));

      // Strictly FontStyle.normal (upright, zero italics)
      expect(title.fontStyle, equals(FontStyle.normal));
      expect(section.fontStyle, equals(FontStyle.normal));
      expect(card.fontStyle, equals(FontStyle.normal));
      expect(day.fontStyle, equals(FontStyle.normal));
    });
  });

  group('GlassSurface Blur Budget Manager', () {
    setUp(() {
      BlurBudgetManager.reset();
    });

    test('Enforces <= 3 blurs per screen budget strictly', () {
      expect(BlurBudgetManager.activeBlurCount, equals(0));

      expect(BlurBudgetManager.requestBlurSlot(), isTrue);
      expect(BlurBudgetManager.activeBlurCount, equals(1));

      expect(BlurBudgetManager.requestBlurSlot(), isTrue);
      expect(BlurBudgetManager.activeBlurCount, equals(2));

      expect(BlurBudgetManager.requestBlurSlot(), isTrue);
      expect(BlurBudgetManager.activeBlurCount, equals(3));

      // 4th request must fail to enforce <= 3 blurs per screen
      expect(BlurBudgetManager.requestBlurSlot(), isFalse);
      expect(BlurBudgetManager.activeBlurCount, equals(3));

      // Releasing slot allows a new one
      BlurBudgetManager.releaseBlurSlot();
      expect(BlurBudgetManager.activeBlurCount, equals(2));
      expect(BlurBudgetManager.requestBlurSlot(), isTrue);
      expect(BlurBudgetManager.activeBlurCount, equals(3));
    });
  });
}
