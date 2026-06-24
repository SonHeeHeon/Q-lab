/// File: app/lib/shared/format/money.dart
///
/// Currency-aware money formatting shared across screens.
///
/// Korean market convention: KRW shown as ₩ with no decimals, USD as $
/// with 2 decimals. US (미장) holdings price in native USD; the portfolio
/// converts to KRW for the primary figure using the snapshot fx_rate.
library;

import 'package:intl/intl.dart';

final krwFmt = NumberFormat.currency(symbol: '₩', decimalDigits: 0);
final usdFmt = NumberFormat.currency(symbol: '\$', decimalDigits: 2);

/// Formats [amount] in its native [currency] ('USD' → $, else ₩).
String formatNative(double amount, String currency) =>
    currency.toUpperCase() == 'USD' ? usdFmt.format(amount) : krwFmt.format(amount);

/// Converts a USD [amount] to KRW using [fxRate]. Returns null when the
/// rate is unknown so callers can render a '--' placeholder instead of a
/// wrong number.
double? usdToKrw(double amount, double? fxRate) =>
    fxRate == null ? null : amount * fxRate;

/// KRW string for a value held in [currency]: passes KRW through, converts
/// USD via [fxRate]. Returns '--' when a USD value can't be converted yet.
String krwFromNative(double amount, String currency, double? fxRate) {
  if (currency.toUpperCase() != 'USD') return krwFmt.format(amount);
  final krw = usdToKrw(amount, fxRate);
  return krw == null ? '--' : krwFmt.format(krw);
}
