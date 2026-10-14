import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// Saral AI Strict Monochrome Design System Tokens per rules.md.
/// Pitch black (#000000), ink (#0A0A0A), graphite (#141414), dark grey (#1A1A1A).
/// White text hierarchy (100%, 64%, 38%, 12%, 10%).
/// Zero accent colors app-wide.
abstract final class AppColors {
  // Core monochrome palette
  static const Color pitchBlack = Color(0xFF000000);
  static const Color ink = Color(0xFF0A0A0A);
  static const Color graphite = Color(0xFF141414);
  static const Color darkGrey = Color(0xFF1A1A1A);

  // Surface aliases
  static const Color background = pitchBlack;
  static const Color surface = ink;
  static const Color surfaceElevated = graphite;
  static const Color card = darkGrey;
  static const Color button = darkGrey;
  static const Color sheet = darkGrey;

  // Text & icon hierarchy (strictly white shades)
  static const Color pureWhite = Color(0xFFFFFFFF);
  static const Color textPrimary = pureWhite;
  static const Color textSecondary = Color(0xA3FFFFFF); // 64% white
  static const Color textTertiary = Color(0x61FFFFFF); // 38% white
  static const Color textDisabled = Color(0x61FFFFFF); // 38% white

  // Interactive & border hierarchy
  static const Color highlightSelected = Color(0x1FFFFFFF); // 12% white
  static const Color borderWhite = Color(0x1AFFFFFF); // 10% white
  static const Color surfaceSubtle = Color(0x0FFFFFFF); // 6% white
  static const Color transparent = Colors.transparent;
}

/// Chrome component dimensions strictly per rules.md.
abstract final class AppChrome {
  static const double bar = 56.0;
  static const double circle = 48.0;
  static const double compactCircle = 40.0;
  static const double compactHitTarget = 48.0;
  static const double capsule = 32.0;
  static const double barIcon = 22.0;
}

/// Spacing rhythm in multiples of 4 dp per rules.md.
abstract final class AppSpacing {
  static const double space2 = 2.0;
  static const double space4 = 4.0;
  static const double space8 = 8.0;
  static const double space12 = 12.0;
  static const double space16 = 16.0;
  static const double space20 = 20.0;
  static const double space24 = 24.0;
  static const double space32 = 32.0;
  static const double space40 = 40.0;
  static const double space48 = 48.0;

  // Semantic layout aliases
  static const double screenMargin = space16;
  static const double headingToContent = space12;
  static const double sectionToSection = space24;
  static const double gridGutter = space12;
}

/// Corner radii per rules.md.
abstract final class AppRadii {
  static const double none = 0.0;
  static const double xs = 4.0;
  static const double sm = 8.0;
  static const double button = 12.0;
  static const double input = 12.0;
  static const double card = 16.0;
  static const double sheet = 24.0;
  static const double pill = 999.0;
  static const double full = 999.0;
}

/// Motion & transition durations.
abstract final class AppDurations {
  static const Duration fast = Duration(milliseconds: 150);
  static const Duration medium = Duration(milliseconds: 300);
  static const Duration morph = Duration(milliseconds: 420);
}

/// Typography strictly adhering to rules.md:
/// Headings: Arapey Regular ONLY (no italics allowed).
/// Body/UI: Inter.
abstract final class AppTypography {
  // Headings (Arapey Regular only)
  static TextStyle screenTitle({Color color = AppColors.textPrimary}) {
    return GoogleFonts.arapey(
      textStyle: TextStyle(
        fontSize: 42.0,
        fontWeight: FontWeight.w400,
        fontStyle: FontStyle.normal,
        color: color,
        letterSpacing: -0.5,
        height: 1.15,
        fontFamilyFallback: const ['serif'],
      ),
    );
  }

  static TextStyle sectionHeading({Color color = AppColors.textPrimary}) {
    return GoogleFonts.arapey(
      textStyle: TextStyle(
        fontSize: 28.0,
        fontWeight: FontWeight.w400,
        fontStyle: FontStyle.normal,
        color: color,
        letterSpacing: -0.2,
        height: 1.2,
        fontFamilyFallback: const ['serif'],
      ),
    );
  }

  static TextStyle cardHeading({Color color = AppColors.textPrimary}) {
    return GoogleFonts.arapey(
      textStyle: TextStyle(
        fontSize: 24.0,
        fontWeight: FontWeight.w400,
        fontStyle: FontStyle.normal,
        color: color,
        fontFamilyFallback: const ['serif'],
      ),
    );
  }

  static TextStyle dayHeader({Color color = AppColors.textPrimary}) {
    return GoogleFonts.arapey(
      textStyle: TextStyle(
        fontSize: 20.0,
        fontWeight: FontWeight.w400,
        fontStyle: FontStyle.normal,
        color: color,
        fontFamilyFallback: const ['serif'],
      ),
    );
  }

  static TextStyle greeting({Color color = AppColors.textPrimary}) {
    return GoogleFonts.arapey(
      textStyle: TextStyle(
        fontSize: 34.0,
        fontWeight: FontWeight.w400,
        fontStyle: FontStyle.normal,
        color: color,
        letterSpacing: -0.3,
        height: 1.2,
        fontFamilyFallback: const ['serif'],
      ),
    );
  }

  // Body & UI (Inter)
  static TextStyle bodyLarge({Color color = AppColors.textPrimary, FontWeight fontWeight = FontWeight.w400}) {
    return GoogleFonts.inter(
      textStyle: TextStyle(
        fontSize: 16.0,
        fontWeight: fontWeight,
        color: color,
        height: 1.4,
        fontFamilyFallback: const ['sans-serif'],
      ),
    );
  }

  static TextStyle bodyMedium({Color color = AppColors.textSecondary, FontWeight fontWeight = FontWeight.w400}) {
    return GoogleFonts.inter(
      textStyle: TextStyle(
        fontSize: 14.0,
        fontWeight: fontWeight,
        color: color,
        height: 1.4,
        fontFamilyFallback: const ['sans-serif'],
      ),
    );
  }

  static TextStyle bodySmall({Color color = AppColors.textTertiary, FontWeight fontWeight = FontWeight.w400}) {
    return GoogleFonts.inter(
      textStyle: TextStyle(
        fontSize: 12.0,
        fontWeight: fontWeight,
        color: color,
        height: 1.35,
        fontFamilyFallback: const ['sans-serif'],
      ),
    );
  }

  static TextStyle labelLarge({Color color = AppColors.textPrimary, FontWeight fontWeight = FontWeight.w600}) {
    return GoogleFonts.inter(
      textStyle: TextStyle(
        fontSize: 14.0,
        fontWeight: fontWeight,
        color: color,
        letterSpacing: 0.2,
        fontFamilyFallback: const ['sans-serif'],
      ),
    );
  }

  static TextStyle labelMedium({Color color = AppColors.textSecondary, FontWeight fontWeight = FontWeight.w500}) {
    return GoogleFonts.inter(
      textStyle: TextStyle(
        fontSize: 12.0,
        fontWeight: fontWeight,
        color: color,
        letterSpacing: 0.3,
        fontFamilyFallback: const ['sans-serif'],
      ),
    );
  }

  static TextStyle labelSmall({Color color = AppColors.textTertiary, FontWeight fontWeight = FontWeight.w500}) {
    return GoogleFonts.inter(
      textStyle: TextStyle(
        fontSize: 10.0,
        fontWeight: fontWeight,
        color: color,
        letterSpacing: 0.4,
        fontFamilyFallback: const ['sans-serif'],
      ),
    );
  }

  static TextStyle code({Color color = AppColors.textPrimary}) {
    return GoogleFonts.jetBrainsMono(
      textStyle: TextStyle(
        fontSize: 13.0,
        fontWeight: FontWeight.w400,
        color: color,
        fontFamilyFallback: const ['monospace'],
      ),
    );
  }
}

/// AppTheme configuration strictly enforcing Dark Monochrome theme.
abstract final class AppTheme {
  static ThemeData get darkTheme {
    return ThemeData(
      brightness: Brightness.dark,
      scaffoldBackgroundColor: AppColors.pitchBlack,
      primaryColor: AppColors.pureWhite,
      colorScheme: const ColorScheme(
        brightness: Brightness.dark,
        primary: AppColors.pureWhite,
        onPrimary: AppColors.pitchBlack,
        secondary: AppColors.textSecondary,
        onSecondary: AppColors.pitchBlack,
        error: AppColors.pureWhite,
        onError: AppColors.pitchBlack,
        surface: AppColors.darkGrey,
        onSurface: AppColors.pureWhite,
      ),
      canvasColor: AppColors.pitchBlack,
      cardColor: AppColors.darkGrey,
      dividerColor: AppColors.borderWhite,
      splashColor: AppColors.highlightSelected,
      highlightColor: AppColors.highlightSelected,
      fontFamily: 'Inter',
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.pitchBlack,
        foregroundColor: AppColors.pureWhite,
        elevation: 0,
        scrolledUnderElevation: 0,
      ),
      bottomSheetTheme: const BottomSheetThemeData(
        backgroundColor: AppColors.darkGrey,
        modalBackgroundColor: AppColors.darkGrey,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadii.sheet)),
        ),
      ),
      snackBarTheme: const SnackBarThemeData(
        backgroundColor: AppColors.darkGrey,
        contentTextStyle: TextStyle(color: AppColors.pureWhite),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.darkGrey,
        hintStyle: const TextStyle(color: AppColors.textTertiary),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.space16,
          vertical: AppSpacing.space12,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadii.input),
          borderSide: const BorderSide(color: AppColors.borderWhite, width: 1.0),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadii.input),
          borderSide: const BorderSide(color: AppColors.borderWhite, width: 1.0),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadii.input),
          borderSide: const BorderSide(color: AppColors.pureWhite, width: 1.0),
        ),
      ),
    );
  }
}
