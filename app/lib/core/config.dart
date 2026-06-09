/// File: app/lib/core/config.dart
///
/// App-wide runtime configuration that the user can change in Settings.
/// Persisted via shared_preferences.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Theme mode (dark is default per design).
final themeModeProvider = StateProvider<ThemeMode>((ref) => ThemeMode.dark);

/// Active KIS account selection (paper / real / isa). Defaults to paper for safety.
enum KisAccountType { paper, real, isa }

final activeAccountProvider = StateProvider<KisAccountType>((ref) => KisAccountType.paper);
