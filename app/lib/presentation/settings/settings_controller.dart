/// File: app/lib/presentation/settings/settings_controller.dart
///
/// Settings state: fetches AppSettings from the backend and tracks
/// per-action test results (KIS / Telegram / LLM).
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/settings_api.dart';
import '../../domain/entities/account.dart';

final appSettingsProvider = FutureProvider<AppSettings>((ref) async {
  return ref.read(settingsApiProvider).getAll();
});

/// Test-button feedback per scope. Keyed by:
///   - KIS:       "kis:<wire>"
///   - Telegram:  "telegram"
///   - LLM:       "llm"
final testResultsProvider = StateProvider<Map<String, TestResult>>((ref) => const {});

extension TestResultsX on WidgetRef {
  void setTestResult(String key, TestResult r) {
    final map = read(testResultsProvider);
    read(testResultsProvider.notifier).state = {...map, key: r};
  }
}

String kisTestKey(KisAccount a) => 'kis:${a.wire}';
const telegramTestKey = 'telegram';
const llmTestKey = 'llm';
const tossTestKey = 'toss';
