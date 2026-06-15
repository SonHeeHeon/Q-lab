/// File: app/lib/core/preferences.dart
///
/// Thin wrapper around `shared_preferences` for app-wide settings that
/// must survive an app restart (theme mode, active KIS account).
///
/// Why a single sink:
///   * `SharedPreferences` is initialized once and reused (avoids the
///     async-await chain in every Notifier).
///   * Keys are centralized so renames don't drift across providers.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'config.dart';

class _Keys {
  static const themeMode = 'theme_mode';
  static const activeAccount = 'active_account';
}

/// Resolves once at app start (see main.dart override). Throws if read
/// before the override is installed — that's a programmer error, not a
/// runtime one, so the assertion is loud on purpose.
final sharedPreferencesProvider = Provider<SharedPreferences>(
  (ref) => throw UnimplementedError(
    'sharedPreferencesProvider must be overridden in ProviderScope',
  ),
);

// ---------------------------------------------------------------------------
// Theme mode
// ---------------------------------------------------------------------------

class ThemeModeNotifier extends Notifier<ThemeMode> {
  @override
  ThemeMode build() {
    final prefs = ref.read(sharedPreferencesProvider);
    final raw = prefs.getString(_Keys.themeMode);
    return _decodeThemeMode(raw);
  }

  Future<void> set(ThemeMode mode) async {
    state = mode;
    final prefs = ref.read(sharedPreferencesProvider);
    await prefs.setString(_Keys.themeMode, _encodeThemeMode(mode));
  }
}

final persistedThemeModeProvider =
    NotifierProvider<ThemeModeNotifier, ThemeMode>(ThemeModeNotifier.new);

ThemeMode _decodeThemeMode(String? raw) {
  switch (raw) {
    case 'light':
      return ThemeMode.light;
    case 'system':
      return ThemeMode.system;
    case 'dark':
    default:
      return ThemeMode.dark;
  }
}

String _encodeThemeMode(ThemeMode m) => switch (m) {
      ThemeMode.light => 'light',
      ThemeMode.system => 'system',
      ThemeMode.dark => 'dark',
    };

// ---------------------------------------------------------------------------
// Active KIS account
// ---------------------------------------------------------------------------

class ActiveAccountNotifier extends Notifier<KisAccountType> {
  @override
  KisAccountType build() {
    final prefs = ref.read(sharedPreferencesProvider);
    final raw = prefs.getString(_Keys.activeAccount);
    return _decodeAccount(raw);
  }

  Future<void> set(KisAccountType acc) async {
    state = acc;
    final prefs = ref.read(sharedPreferencesProvider);
    await prefs.setString(_Keys.activeAccount, acc.name);
  }
}

final persistedActiveAccountProvider =
    NotifierProvider<ActiveAccountNotifier, KisAccountType>(
  ActiveAccountNotifier.new,
);

KisAccountType _decodeAccount(String? raw) {
  for (final v in KisAccountType.values) {
    if (v.name == raw) return v;
  }
  // Safe default: PAPER (never accidentally operate on real money).
  return KisAccountType.paper;
}
