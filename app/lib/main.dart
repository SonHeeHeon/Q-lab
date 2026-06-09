/// File: app/lib/main.dart
///
/// Flutter app entry point. Wraps the root widget in [ProviderScope]
/// (Riverpod) and hands routing to go_router.
///
/// Run:
///   $ flutter run -d chrome \
///         --dart-define=API_BASE_URL=http://localhost:8000 \
///         --dart-define=WS_BASE_URL=ws://localhost:8000 \
///         --dart-define=USE_MOCK=true
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/config.dart';
import 'core/routes.dart';
import 'core/theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ProviderScope(child: QLabApp()));
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
