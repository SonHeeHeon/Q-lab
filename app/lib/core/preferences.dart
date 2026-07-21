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
  static const apiKey = 'backend_api_key';
  static const apiBaseUrl = 'backend_base_url';
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

// ---------------------------------------------------------------------------
// Backend API key (optional bearer token) — set in Settings so the same build
// works whether the backend has auth on (phone/remote) or off (local). Empty
// falls back to the compile-time Env.apiKey. Persisted locally on the device;
// never sent anywhere except as the Authorization header to our own backend.
// ---------------------------------------------------------------------------

class ApiKeyNotifier extends Notifier<String> {
  @override
  String build() =>
      ref.read(sharedPreferencesProvider).getString(_Keys.apiKey) ?? '';

  Future<void> set(String key) async {
    final trimmed = key.trim();
    state = trimmed;
    final prefs = ref.read(sharedPreferencesProvider);
    if (trimmed.isEmpty) {
      await prefs.remove(_Keys.apiKey);
    } else {
      await prefs.setString(_Keys.apiKey, trimmed);
    }
  }
}

final persistedApiKeyProvider =
    NotifierProvider<ApiKeyNotifier, String>(ApiKeyNotifier.new);

// ---------------------------------------------------------------------------
// Backend base URL — set in Settings so the app can point at localhost, a LAN
// IP, or a Tailscale host without a rebuild. Empty falls back to Env.apiBaseUrl.
// ---------------------------------------------------------------------------

class ApiBaseUrlNotifier extends Notifier<String> {
  @override
  String build() =>
      ref.read(sharedPreferencesProvider).getString(_Keys.apiBaseUrl) ?? '';

  Future<void> set(String url) async {
    // Strip a trailing slash so `${base}/api/...` never doubles up.
    final trimmed = url.trim().replaceAll(RegExp(r'/+$'), '');
    state = trimmed;
    final prefs = ref.read(sharedPreferencesProvider);
    if (trimmed.isEmpty) {
      await prefs.remove(_Keys.apiBaseUrl);
    } else {
      await prefs.setString(_Keys.apiBaseUrl, trimmed);
    }
  }
}

final persistedApiBaseUrlProvider =
    NotifierProvider<ApiBaseUrlNotifier, String>(ApiBaseUrlNotifier.new);
