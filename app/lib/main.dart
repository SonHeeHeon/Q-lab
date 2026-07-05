/// File: app/lib/main.dart
///
/// Flutter app entry point. Wraps the root widget in [ProviderScope]
/// (Riverpod) and hands routing to go_router.
///
/// SharedPreferences is loaded once before `runApp` and injected into
/// the provider tree via override so theme / active-account choices
/// survive across app restarts (see `core/preferences.dart`).
///
/// Run:
///   $ flutter run -d chrome \
///         --dart-define=API_BASE_URL=http://localhost:8000 \
///         --dart-define=WS_BASE_URL=ws://localhost:8000 \
///         --dart-define=USE_MOCK=true
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'core/config.dart';
import 'core/preferences.dart';
import 'core/routes.dart';
import 'core/theme.dart';

void main() {
  runZonedGuarded(() async {
    WidgetsFlutterBinding.ensureInitialized();

    FlutterError.onError = (FlutterErrorDetails details) {
      FlutterError.presentError(details);
      debugPrint('[FlutterError] ${details.exceptionAsString()}');
    };
    ErrorWidget.builder = (details) => _ErrorFallback(details: details);

    final prefs = await SharedPreferences.getInstance();
    runApp(
      ProviderScope(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
        ],
        child: const QLabApp(),
      ),
    );
  }, (error, stack) {
    debugPrint('[uncaught] $error\n$stack');
  });
}

/// Friendly fallback shown in place of a widget that threw during build.
/// Theme-agnostic (no [MaterialApp]/[Theme] ancestor assumed) so it still
/// renders correctly even if the error happens before the app's own
/// Material scope is mounted.
class _ErrorFallback extends StatelessWidget {
  const _ErrorFallback({required this.details});
  final FlutterErrorDetails details;

  @override
  Widget build(BuildContext context) {
    return Directionality(
      textDirection: TextDirection.ltr,
      child: Material(
        color: const Color(0xFFF5F5F5),
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text(
                    '화면 오류가 발생했어요',
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 12),
                  SelectableText(
                    details.exceptionAsString(),
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 12, color: Color(0xFF666666)),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class QLabApp extends ConsumerWidget {
  const QLabApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    final mode = ref.watch(themeModeProvider);
    return MaterialApp.router(
      title: 'Q-Lab',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: mode,
      routerConfig: router,
    );
  }
}
