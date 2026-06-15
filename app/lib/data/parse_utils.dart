/// File: app/lib/data/parse_utils.dart
///
/// Centralized JSON-value coercion. Backend responses mix three numeric
/// representations:
///   - `int` (e.g. `quantity`, `id`)
///   - `double` (e.g. `change_pct` in heatmap)
///   - `String` (Pydantic `Decimal` serializes as `"10000000"`, `"0E-8"`)
///
/// Per-API duplication of these helpers used to silently swallow malformed
/// inputs (`"N/A"`, `"--"`, etc.) and return 0, hiding real backend bugs.
/// This module centralizes the pattern with optional `debugPrint` warnings
/// so the developer sees what got coerced and why.
library;

import 'package:flutter/foundation.dart';

/// Coerce [v] to a `double`. Accepts `num`, `String`, or `null`.
///
/// - `null` / non-numeric strings → [fallback] (default 0.0), with a
///   debug log when [warnOnFallback] is true so unexpected payloads are
///   visible during development.
/// - Empty strings are treated as null without a warning.
double safeDouble(
  Object? v, {
  double fallback = 0.0,
  bool warnOnFallback = true,
  String? hint,
}) {
  if (v == null) return fallback;
  if (v is num) return v.toDouble();
  if (v is String) {
    if (v.isEmpty) return fallback;
    final parsed = double.tryParse(v);
    if (parsed != null) return parsed;
    if (warnOnFallback) {
      debugPrint('[parse] safeDouble fallback for ${hint ?? ""}: $v');
    }
    return fallback;
  }
  if (warnOnFallback) {
    debugPrint('[parse] safeDouble unexpected type ${v.runtimeType} for ${hint ?? ""}');
  }
  return fallback;
}

/// Nullable variant — returns `null` if the value can't be parsed,
/// distinguishing "missing field" from "field equals 0".
double? safeDoubleOrNull(Object? v, {String? hint}) {
  if (v == null) return null;
  if (v is num) return v.toDouble();
  if (v is String) {
    if (v.isEmpty) return null;
    final parsed = double.tryParse(v);
    if (parsed == null) {
      debugPrint('[parse] safeDoubleOrNull fallback for ${hint ?? ""}: $v');
    }
    return parsed;
  }
  return null;
}

/// Coerce [v] to an `int`. Accepts `int`, `double` (truncated),
/// `String`, or `null`.
int safeInt(
  Object? v, {
  int fallback = 0,
  bool warnOnFallback = true,
  String? hint,
}) {
  if (v == null) return fallback;
  if (v is int) return v;
  if (v is num) return v.toInt();
  if (v is String) {
    if (v.isEmpty) return fallback;
    final asInt = int.tryParse(v);
    if (asInt != null) return asInt;
    final asDouble = double.tryParse(v);
    if (asDouble != null) return asDouble.toInt();
    if (warnOnFallback) {
      debugPrint('[parse] safeInt fallback for ${hint ?? ""}: $v');
    }
    return fallback;
  }
  if (warnOnFallback) {
    debugPrint('[parse] safeInt unexpected type ${v.runtimeType} for ${hint ?? ""}');
  }
  return fallback;
}
