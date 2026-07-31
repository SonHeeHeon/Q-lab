/// File: app/lib/core/config.dart
///
/// App-wide runtime configuration that the user can change in Settings.
/// Persisted across app restarts via `shared_preferences` (see
/// `core/preferences.dart` for the actual storage notifiers).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'preferences.dart';

/// Active KIS account selection. Defaults to paper for safety.
/// dc/irp/pension = 연금 계좌들(2026-07 5계좌 확장 — 미연결이면 조회만 실패).
enum KisAccountType { paper, real, isa, dc, irp, pension }

/// Theme mode — backed by [persistedThemeModeProvider] under the hood.
/// Reads return the persisted value; writes funnel through `.set(...)`
/// so SharedPreferences stays in sync.
///
/// Existing call sites use `ref.read(themeModeProvider.notifier).state = X`
/// (StateController style). We expose a compatibility shim so they keep
/// working — Settings UI has been migrated to call `.set(...)` directly.
final themeModeProvider = Provider<ThemeMode>(
  (ref) => ref.watch(persistedThemeModeProvider),
);

/// Active account — backed by [persistedActiveAccountProvider].
final activeAccountProvider = Provider<KisAccountType>(
  (ref) => ref.watch(persistedActiveAccountProvider),
);
