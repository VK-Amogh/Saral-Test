import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/tokens.dart';
import '../../../core/widgets/glass_surface.dart';
import '../providers/auth_provider.dart';

enum AuthMode { signIn, signUp, forgotPassword }

class AuthScreen extends ConsumerStatefulWidget {
  const AuthScreen({super.key});

  @override
  ConsumerState<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends ConsumerState<AuthScreen> {
  final _formKey = GlobalKey<FormState>();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();

  AuthMode _authMode = AuthMode.signIn;
  bool _obscurePassword = true;
  bool _obscureConfirmPassword = true;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    _confirmPasswordController.dispose();
    super.dispose();
  }

  void _switchMode(AuthMode mode) {
    setState(() {
      _authMode = mode;
      ref.read(authProvider.notifier).clearMessages();
    });
  }

  Future<void> _handleSubmit() async {
    if (!_formKey.currentState!.validate()) return;

    final authNotifier = ref.read(authProvider.notifier);
    final email = _emailController.text.trim();
    final password = _passwordController.text;

    bool success = false;
    if (_authMode == AuthMode.signIn) {
      success = await authNotifier.signIn(email: email, password: password);
    } else if (_authMode == AuthMode.signUp) {
      success = await authNotifier.signUp(email: email, password: password);
    } else if (_authMode == AuthMode.forgotPassword) {
      success = await authNotifier.resetPassword(email: email);
    }

    if (success && mounted) {
      if (_authMode == AuthMode.signIn || _authMode == AuthMode.signUp) {
        context.go('/chat');
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final authState = ref.watch(authProvider);

    return Scaffold(
      backgroundColor: AppColors.pitchBlack,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.screenMargin),
            child: Form(
              key: _formKey,
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const SizedBox(height: AppSpacing.space24),

                  // Brand Title
                  Text(
                    'Saral AI',
                    textAlign: TextAlign.center,
                    style: AppTypography.screenTitle(),
                  ),
                  const SizedBox(height: AppSpacing.space8),
                  Text(
                    'Simple, secure government services assistant',
                    textAlign: TextAlign.center,
                    style: AppTypography.bodyMedium(color: AppColors.textSecondary),
                  ),

                  const SizedBox(height: AppSpacing.space32),

                  // Tab Switcher Pill
                  Center(
                    child: Container(
                      padding: const EdgeInsets.all(AppSpacing.space4),
                      decoration: BoxDecoration(
                        color: AppColors.darkGrey,
                        borderRadius: BorderRadius.circular(AppRadii.pill),
                        border: Border.all(color: AppColors.borderWhite, width: 1),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          _buildTabButton('Sign In', AuthMode.signIn),
                          _buildTabButton('Sign Up', AuthMode.signUp),
                          _buildTabButton('Reset', AuthMode.forgotPassword),
                        ],
                      ),
                    ),
                  ),

                  const SizedBox(height: AppSpacing.space24),

                  // Card container for form inputs
                  GlassSurface(
                    padding: const EdgeInsets.all(AppSpacing.space20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        // Mode title
                        Text(
                          _getModeTitle(),
                          style: AppTypography.cardHeading(),
                        ),
                        const SizedBox(height: AppSpacing.headingToContent),

                        // Error Banner (Monochrome per rules.md: icon + text, zero color)
                        if (authState.errorMessage != null) ...[
                          Container(
                            padding: const EdgeInsets.all(AppSpacing.space12),
                            decoration: BoxDecoration(
                              color: AppColors.graphite,
                              borderRadius: BorderRadius.circular(AppRadii.sm),
                              border: Border.all(color: AppColors.borderWhite, width: 1),
                            ),
                            child: Row(
                              children: [
                                const Icon(Icons.info_outline, color: AppColors.pureWhite, size: 18),
                                const SizedBox(width: AppSpacing.space8),
                                Expanded(
                                  child: Text(
                                    authState.errorMessage!,
                                    style: AppTypography.bodySmall(color: AppColors.pureWhite),
                                  ),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(height: AppSpacing.space16),
                        ],

                        // Info Banner
                        if (authState.infoMessage != null) ...[
                          Container(
                            padding: const EdgeInsets.all(AppSpacing.space12),
                            decoration: BoxDecoration(
                              color: AppColors.graphite,
                              borderRadius: BorderRadius.circular(AppRadii.sm),
                              border: Border.all(color: AppColors.borderWhite, width: 1),
                            ),
                            child: Row(
                              children: [
                                const Icon(Icons.check_circle_outline, color: AppColors.pureWhite, size: 18),
                                const SizedBox(width: AppSpacing.space8),
                                Expanded(
                                  child: Text(
                                    authState.infoMessage!,
                                    style: AppTypography.bodySmall(color: AppColors.pureWhite),
                                  ),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(height: AppSpacing.space16),
                        ],

                        // Email Field
                        TextFormField(
                          controller: _emailController,
                          keyboardType: TextInputType.emailAddress,
                          autocorrect: false,
                          style: AppTypography.bodyLarge(),
                          decoration: InputDecoration(
                            labelText: 'Email Address',
                            labelStyle: AppTypography.labelMedium(color: AppColors.textTertiary),
                            hintText: 'name@example.com',
                            prefixIcon: const Icon(Icons.mail_outline, color: AppColors.textSecondary, size: 20),
                          ),
                          validator: (value) {
                            if (value == null || value.trim().isEmpty) {
                              return 'Please enter your email';
                            }
                            if (!value.contains('@') || !value.contains('.')) {
                              return 'Please enter a valid email';
                            }
                            return null;
                          },
                        ),

                        // Password Field
                        if (_authMode != AuthMode.forgotPassword) ...[
                          const SizedBox(height: AppSpacing.space16),
                          TextFormField(
                            controller: _passwordController,
                            obscureText: _obscurePassword,
                            autocorrect: false,
                            enableSuggestions: false,
                            style: AppTypography.bodyLarge(),
                            decoration: InputDecoration(
                              labelText: 'Password',
                              labelStyle: AppTypography.labelMedium(color: AppColors.textTertiary),
                              hintText: 'Enter your password',
                              prefixIcon: const Icon(Icons.lock_outline, color: AppColors.textSecondary, size: 20),
                              suffixIcon: IconButton(
                                icon: Icon(
                                  _obscurePassword ? Icons.visibility_off_outlined : Icons.visibility_outlined,
                                  color: AppColors.textSecondary,
                                  size: 20,
                                ),
                                onPressed: () {
                                  setState(() => _obscurePassword = !_obscurePassword);
                                },
                              ),
                            ),
                            validator: (value) {
                              if (value == null || value.isEmpty) {
                                return 'Please enter your password';
                              }
                              if (value.length < 6) {
                                return 'Password must be at least 6 characters';
                              }
                              return null;
                            },
                          ),
                        ],

                        // Confirm Password (Sign Up only)
                        if (_authMode == AuthMode.signUp) ...[
                          const SizedBox(height: AppSpacing.space16),
                          TextFormField(
                            controller: _confirmPasswordController,
                            obscureText: _obscureConfirmPassword,
                            autocorrect: false,
                            enableSuggestions: false,
                            style: AppTypography.bodyLarge(),
                            decoration: InputDecoration(
                              labelText: 'Confirm Password',
                              labelStyle: AppTypography.labelMedium(color: AppColors.textTertiary),
                              hintText: 'Re-enter your password',
                              prefixIcon: const Icon(Icons.lock_outline, color: AppColors.textSecondary, size: 20),
                              suffixIcon: IconButton(
                                icon: Icon(
                                  _obscureConfirmPassword ? Icons.visibility_off_outlined : Icons.visibility_outlined,
                                  color: AppColors.textSecondary,
                                  size: 20,
                                ),
                                onPressed: () {
                                  setState(() => _obscureConfirmPassword = !_obscureConfirmPassword);
                                },
                              ),
                            ),
                            validator: (value) {
                              if (_authMode == AuthMode.signUp && value != _passwordController.text) {
                                return 'Passwords do not match';
                              }
                              return null;
                            },
                          ),
                        ],

                        const SizedBox(height: AppSpacing.space24),

                        // Action Button
                        SizedBox(
                          height: AppChrome.bar,
                          child: ElevatedButton(
                            style: ElevatedButton.styleFrom(
                              backgroundColor: AppColors.pureWhite,
                              foregroundColor: AppColors.pitchBlack,
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(AppRadii.button),
                              ),
                              elevation: 0,
                            ),
                            onPressed: authState.isLoading ? null : _handleSubmit,
                            child: authState.isLoading
                                ? const SizedBox(
                                    width: 22,
                                    height: 22,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                      valueColor: AlwaysStoppedAnimation<Color>(AppColors.pitchBlack),
                                    ),
                                  )
                                : Text(
                                    _getButtonLabel(),
                                    style: AppTypography.labelLarge(
                                      color: AppColors.pitchBlack,
                                      fontWeight: FontWeight.w700,
                                    ),
                                  ),
                          ),
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: AppSpacing.space32),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildTabButton(String label, AuthMode mode) {
    final isSelected = _authMode == mode;
    return GestureDetector(
      onTap: () => _switchMode(mode),
      child: Container(
        height: AppChrome.capsule,
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.space16),
        decoration: BoxDecoration(
          color: isSelected ? AppColors.pureWhite : AppColors.transparent,
          borderRadius: BorderRadius.circular(AppRadii.pill),
        ),
        alignment: Alignment.center,
        child: Text(
          label,
          style: isSelected
              ? AppTypography.labelMedium(color: AppColors.pitchBlack, fontWeight: FontWeight.w600)
              : AppTypography.labelMedium(color: AppColors.textSecondary),
        ),
      ),
    );
  }

  String _getModeTitle() {
    switch (_authMode) {
      case AuthMode.signIn:
        return 'Sign In';
      case AuthMode.signUp:
        return 'Create Account';
      case AuthMode.forgotPassword:
        return 'Reset Password';
    }
  }

  String _getButtonLabel() {
    switch (_authMode) {
      case AuthMode.signIn:
        return 'Sign In';
      case AuthMode.signUp:
        return 'Create Account';
      case AuthMode.forgotPassword:
        return 'Send Reset Link';
    }
  }
}
