import 'dart:ui';
import 'package:flutter/material.dart';
import '../theme/tokens.dart';

/// Budget manager for active blur surfaces per screen.
/// Adheres strictly to the rule: <= 3 blurs per screen.
class BlurBudgetManager {
  static const int maxBlursPerScreen = 3;
  static int _activeBlurCount = 0;

  static int get activeBlurCount => _activeBlurCount;

  static bool requestBlurSlot() {
    if (_activeBlurCount < maxBlursPerScreen) {
      _activeBlurCount++;
      return true;
    }
    return false;
  }

  static void releaseBlurSlot() {
    if (_activeBlurCount > 0) {
      _activeBlurCount--;
    }
  }

  @visibleForTesting
  static void reset() {
    _activeBlurCount = 0;
  }
}

/// GlassSurface provides a frosted glass effect using [BackdropFilter]
/// bounded by [RepaintBoundary].
///
/// Automatically respects the <= 3 blurs per screen budget. If the budget
/// is exceeded, it gracefully falls back to an opaque dark-grey container.
class GlassSurface extends StatefulWidget {
  final Widget child;
  final BorderRadius? borderRadius;
  final double blur;
  final double opacity;
  final Color? fillColor;
  final Color borderColor;
  final double borderWidth;
  final EdgeInsetsGeometry? padding;
  final EdgeInsetsGeometry? margin;
  final double? width;
  final double? height;
  final Clip clipBehavior;

  const GlassSurface({
    super.key,
    required this.child,
    this.borderRadius,
    this.blur = 12.0,
    this.opacity = 0.65,
    this.fillColor,
    this.borderColor = AppColors.borderWhite,
    this.borderWidth = 1.0,
    this.padding,
    this.margin,
    this.width,
    this.height,
    this.clipBehavior = Clip.antiAlias,
  });

  @override
  State<GlassSurface> createState() => _GlassSurfaceState();
}

class _GlassSurfaceState extends State<GlassSurface> {
  bool _blurAllocated = false;

  @override
  void initState() {
    super.initState();
    _blurAllocated = BlurBudgetManager.requestBlurSlot();
  }

  @override
  void dispose() {
    if (_blurAllocated) {
      BlurBudgetManager.releaseBlurSlot();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final effectiveRadius = widget.borderRadius ?? BorderRadius.circular(AppRadii.card);
    final baseColor = widget.fillColor ?? AppColors.darkGrey;
    final surfaceColor = _blurAllocated
        ? baseColor.withValues(alpha: widget.opacity)
        : baseColor;

    Widget content = Container(
      width: widget.width,
      height: widget.height,
      padding: widget.padding,
      decoration: BoxDecoration(
        color: surfaceColor,
        borderRadius: effectiveRadius,
        border: widget.borderWidth > 0
            ? Border.all(color: widget.borderColor, width: widget.borderWidth)
            : null,
      ),
      child: widget.child,
    );

    if (_blurAllocated) {
      content = ClipRRect(
        borderRadius: effectiveRadius,
        clipBehavior: widget.clipBehavior,
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: widget.blur, sigmaY: widget.blur),
          child: content,
        ),
      );
    }

    if (widget.margin != null) {
      content = Padding(padding: widget.margin!, child: content);
    }

    // Always isolate the glass surface paint layer with RepaintBoundary
    return RepaintBoundary(child: content);
  }
}
