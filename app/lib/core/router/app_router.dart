import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../features/auth/presentation/auth_screen.dart';
import '../../features/auth/providers/auth_provider.dart';
import '../../features/chat/presentation/chat_screen.dart';
import '../../features/vault/presentation/vault_screen.dart';

final appRouterProvider = Provider<GoRouter>((ref) {
  final authState = ref.watch(authProvider);

  return GoRouter(
    initialLocation: '/chat',
    refreshListenable: _AuthStateChangeNotifier(ref),
    redirect: (BuildContext context, GoRouterState state) {
      final isAuthenticated = authState.isAuthenticated;
      final isAuthRoute = state.matchedLocation == '/auth';

      // If user is not authenticated and trying to access protected screens
      if (!isAuthenticated && !isAuthRoute) {
        return '/auth';
      }

      // If user is authenticated and navigating to auth screen or root
      if (isAuthenticated && isAuthRoute) {
        return '/chat';
      }

      return null;
    },
    routes: [
      GoRoute(
        path: '/auth',
        name: 'auth',
        builder: (context, state) => const AuthScreen(),
      ),
      GoRoute(
        path: '/chat',
        name: 'chat',
        builder: (context, state) => const ChatScreen(),
      ),
      GoRoute(
        path: '/vault',
        name: 'vault',
        builder: (context, state) => const VaultScreen(),
      ),
    ],
  );
});

class _AuthStateChangeNotifier extends ChangeNotifier {
  _AuthStateChangeNotifier(Ref ref) {
    ref.listen<AuthState>(authProvider, (previous, next) {
      notifyListeners();
    });
  }
}
