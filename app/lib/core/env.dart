/// File: app/lib/core/env.dart
///
/// Compile-time environment for the Flutter app.
/// All values come from `--dart-define=...` (kept out of bundle).
///
/// Build flag examples:
///   $ flutter run -d chrome \
///         --dart-define=API_BASE_URL=http://localhost:8000 \
///         --dart-define=WS_BASE_URL=ws://localhost:8000 \
///         --dart-define=USE_MOCK=true
class Env {
  const Env._();

  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  static const String wsBaseUrl = String.fromEnvironment(
    'WS_BASE_URL',
    defaultValue: 'ws://127.0.0.1:8000',
  );

  /// When true, the Dio client short-circuits all `/api/...` requests
  /// with in-memory fixtures (see data/api/mock_interceptor.dart).
  /// Default is `false` since Phase 4 of the backend is live — flip
  /// to `true` for offline UI work without spinning up the server.
  static const bool useMock = bool.fromEnvironment(
    'USE_MOCK',
    defaultValue: false,
  );

  /// "dev" | "prod" — controls log verbosity.
  static const String environment = String.fromEnvironment(
    'ENVIRONMENT',
    defaultValue: 'dev',
  );

  static bool get isDev => environment == 'dev';
}
