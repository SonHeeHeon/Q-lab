/// File: app/lib/core/theme.dart
///
/// Material-3 light/dark themes for Q-Lab. Dark is the default.
///
/// Account-banner colors (RED=REAL / YELLOW=ISA / GREEN=PAPER) are exposed
/// via [AccountColors] ThemeExtension so the active-account banner can
/// give an at-a-glance signal of whether the app is talking to a live
/// or paper account. Confusing live with paper is a hard-to-reverse mistake.
library;

import 'package:flutter/material.dart';

class AppTheme {
  const AppTheme._();

  static const _seed = Color(0xFF3B82F6);

  static ThemeData light() {
    final scheme = ColorScheme.fromSeed(seedColor: _seed, brightness: Brightness.light);
    return _base(scheme).copyWith(
      extensions: const [
        AccountColors(real: Color(0xFFDC2626), isa: Color(0xFFD97706), paper: Color(0xFF059669)),
      ],
    );
  }

  static ThemeData dark() {
    final scheme = ColorScheme.fromSeed(seedColor: _seed, brightness: Brightness.dark);
    return _base(scheme).copyWith(
      extensions: const [
        AccountColors(real: Color(0xFFEF4444), isa: Color(0xFFF59E0B), paper: Color(0xFF10B981)),
      ],
    );
  }

  static ThemeData _base(ColorScheme scheme) {
    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      visualDensity: VisualDensity.adaptivePlatformDensity,
      cardTheme: const CardThemeData(
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.all(Radius.circular(12)),
        ),
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: scheme.surface,
        foregroundColor: scheme.onSurface,
        centerTitle: false,
        elevation: 0,
      ),
      navigationRailTheme: NavigationRailThemeData(
        backgroundColor: scheme.surface,
        selectedIconTheme: IconThemeData(color: scheme.primary),
        selectedLabelTextStyle: TextStyle(color: scheme.primary, fontWeight: FontWeight.w600),
      ),
    );
  }
}

@immutable
class AccountColors extends ThemeExtension<AccountColors> {
  const AccountColors({
    required this.real,
    required this.isa,
    required this.paper,
  });

  final Color real;
  final Color isa;
  final Color paper;

  @override
  AccountColors copyWith({Color? real, Color? isa, Color? paper}) =>
      AccountColors(real: real ?? this.real, isa: isa ?? this.isa, paper: paper ?? this.paper);

  @override
  AccountColors lerp(ThemeExtension<AccountColors>? other, double t) {
    if (other is! AccountColors) return this;
    return AccountColors(
      real: Color.lerp(real, other.real, t)!,
      isa: Color.lerp(isa, other.isa, t)!,
      paper: Color.lerp(paper, other.paper, t)!,
    );
  }
}
