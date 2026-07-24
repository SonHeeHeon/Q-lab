/// File: app/lib/shared/widgets/rating_chip.dart
///
/// Renders the logic-based (non-LLM) buy/sell rating axes from
/// `data/api/ratings_api.dart` (`StockRating.buyGrade`,
/// `PositionRating.sellGrade`) as a compact bordered chip — same visual
/// language as `reason_chip.dart` (rounded 6px, tinted border, colored
/// text, `dense` mode) so ratings read as part of the same chip family.
///
/// Two axes, two color ramps, one shared neutral tone:
///   - Buy axis (STRONG_BUY→AVOID): deep red → grey → deep blue. Mirrors
///     the app-wide convention (매수=빨강/매도=파랑) end to end — AVOID is
///     "as bearish as it gets" on the buy axis, so it lands on the same
///     deep blue as the sell axis's most urgent tier.
///   - Sell axis (SELL_NOW→KEEP): deep blue → grey → green. KEEP means
///     "this position is fine," so it breaks from blue into green rather
///     than fading to grey — a deliberately different endpoint from HOLD.
///   - WATCH (관망) is the one deliberate hue departure: amber/orange
///     instead of a lighter blue. It is not a sell signal, so coding it as
///     "attention" rather than "more/less sell" reads more honestly than
///     a paler shade of the sell color would.
/// All tones sit in the shade600-700 / Accent range (never shade800+/300-)
/// so contrast holds on both light and dark surfaces.
library;

import 'package:flutter/material.dart';

import '../../data/parse_utils.dart';

// ---------------------------------------------------------------------------
// Buy axis (STRONG_BUY -> AVOID): red -> grey -> blue.
// ---------------------------------------------------------------------------
const _strongBuyColor = Color(0xFFD32F2F); // red 700 — deep
const _buyColorTone = Color(0xFFFF5252); // redAccent
const _neutralColor = Color(0xFF757575); // grey 600 — shared NEUTRAL/HOLD
const _reduceColor = Color(0xFF448AFF); // blueAccent
const _avoidColor = Color(0xFF1976D2); // blue 700 — deep

// ---------------------------------------------------------------------------
// Sell axis (SELL_NOW -> KEEP): blue -> grey -> green, WATCH = amber accent.
// ---------------------------------------------------------------------------
const _sellNowColor = Color(0xFF1976D2); // blue 700 — deep, most urgent
const _sellColorTone = Color(0xFF448AFF); // blueAccent
const _watchColor = Color(0xFFF57C00); // orange 700 — deliberate hue break
const _keepColor = Color(0xFF43A047); // green 600 — safe/positive

/// Compact chip for a stock's buy-axis or sell-axis rating.
///
/// - `RatingChip.buy(buyGrade, status: ...)` — buy axis. `status` != 'OK'
///   (NO_DATA/UNSUPPORTED) short-circuits to a muted label regardless of
///   `buyGrade`. `buyGrade == null` (defensive — shouldn't happen when
///   `status == 'OK'`) renders a neutral dash instead of crashing.
/// - `RatingChip.sell(sellGrade, reason: ...)` — sell axis. `reason` (when
///   given) drives a [Tooltip] via [reasonText].
class RatingChip extends StatelessWidget {
  const RatingChip.buy(
    this.buyGrade, {
    super.key,
    this.status = 'OK',
    this.dense = false,
  })  : sellGrade = null,
        reason = null,
        _isSell = false;

  const RatingChip.sell(
    this.sellGrade, {
    super.key,
    this.reason,
    this.dense = false,
  })  : buyGrade = null,
        status = 'OK',
        _isSell = true;

  /// STRONG_BUY/BUY/NEUTRAL/REDUCE/AVOID. Only read on the `.buy` axis.
  final String? buyGrade;

  /// SELL_NOW/SELL/WATCH/HOLD/KEEP. Only read on the `.sell` axis.
  final String? sellGrade;

  /// Buy-axis backend status: 'OK' | 'NO_DATA' | 'UNSUPPORTED'. Ignored on
  /// the `.sell` axis (a persisted position rating is always current).
  final String status;

  /// Sell-axis structured reason, e.g. `{"rule": "STOP_LOSS", "pl_rate":
  /// -12.3, "threshold": -10.0}`. Ignored on the `.buy` axis.
  final Map<String, dynamic>? reason;

  /// Tighter padding/font for dense rows (matches `ReasonChip.dense`).
  final bool dense;

  final bool _isSell;

  // ---- buy axis: label / color -------------------------------------------

  /// Korean label for a buy grade. Unrecognized (non-empty) grades fall
  /// back to the raw string so future backend tiers don't render blank.
  static String buyLabelFor(String grade) => switch (grade.toUpperCase()) {
        'STRONG_BUY' => '적극매수',
        'BUY' => '매수',
        'NEUTRAL' => '중립',
        'REDUCE' => '비중축소',
        'AVOID' => '매수회피',
        _ => grade.isEmpty ? '—' : grade,
      };

  static Color buyColorFor(String grade) => switch (grade.toUpperCase()) {
        'STRONG_BUY' => _strongBuyColor,
        'BUY' => _buyColorTone,
        'NEUTRAL' => _neutralColor,
        'REDUCE' => _reduceColor,
        'AVOID' => _avoidColor,
        _ => _neutralColor,
      };

  // ---- sell axis: label / color -------------------------------------------

  /// Korean label for a sell grade. Unrecognized (non-empty) grades fall
  /// back to the raw string, same defensive behavior as [buyLabelFor].
  static String sellLabelFor(String grade) => switch (grade.toUpperCase()) {
        'SELL_NOW' => '즉시매도',
        'SELL' => '매도',
        'WATCH' => '관망',
        'HOLD' => '보유',
        'KEEP' => '유지',
        _ => grade.isEmpty ? '—' : grade,
      };

  static Color sellColorFor(String grade) => switch (grade.toUpperCase()) {
        'SELL_NOW' => _sellNowColor,
        'SELL' => _sellColorTone,
        'WATCH' => _watchColor,
        'HOLD' => _neutralColor,
        'KEEP' => _keepColor,
        _ => _neutralColor,
      };

  @override
  Widget build(BuildContext context) {
    if (_isSell) {
      final grade = sellGrade;
      if (grade == null || grade.isEmpty) return _muted(context, '—');
      final chip = _chip(sellLabelFor(grade), sellColorFor(grade));
      final r = reason;
      if (r == null || r.isEmpty) return chip;
      return Tooltip(message: reasonText(r), child: chip);
    }

    switch (status.toUpperCase()) {
      case 'NO_DATA':
        return _muted(context, dense ? '—' : '데이터 없음');
      case 'UNSUPPORTED':
        return _muted(context, '미지원');
    }
    final grade = buyGrade;
    if (grade == null || grade.isEmpty) return _muted(context, '—');
    return _chip(buyLabelFor(grade), buyColorFor(grade));
  }

  Widget _chip(String label, Color color) => Container(
        padding: EdgeInsets.symmetric(
          horizontal: dense ? 6 : 8,
          vertical: dense ? 2 : 3,
        ),
        decoration: BoxDecoration(
          border: Border.all(color: color.withValues(alpha: 0.5)),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Text(
          label,
          style: TextStyle(
            color: color,
            fontSize: dense ? 11 : 12,
            fontWeight: FontWeight.w600,
          ),
        ),
      );

  Widget _muted(BuildContext context, String label) => Text(
        label,
        style: TextStyle(
          fontSize: dense ? 11 : 12,
          color: Theme.of(context).colorScheme.outline,
        ),
      );
}

/// Rule → Korean sentence for a sell-axis [PositionRating.reason], with the
/// single most relevant numeric detail appended (mirrors
/// `ReasonChip.detailFor`'s "label + one number" shape). Used as the
/// `.sell` chip's tooltip so the grade's *why* is one long-press away.
///
/// Rule set matches `backend/app/services/ratings/sell_axis.py` exactly:
/// STOP_LOSS/TAKE_PROFIT carry `pl_rate` (already a percent, e.g. `-12.3`),
/// SCORE_PERCENTILE carries `percentile` (+ optional `weakest_group`),
/// BAND_TRIM carries `weight`/`target` (fractions), NO_DATA carries neither.
String reasonText(Map<String, dynamic> reason) {
  final rule = (reason['rule'] as String?)?.toUpperCase() ?? '';
  final label = switch (rule) {
    'STOP_LOSS' => '손절 기준 도달',
    'TAKE_PROFIT' => '목표가 도달',
    'SCORE_PERCENTILE' => '점수 하락',
    'BAND_TRIM' => '비중 과다',
    'NO_DATA' => '데이터 부족',
    _ => rule.isEmpty ? '평가 사유 없음' : rule,
  };
  switch (rule) {
    case 'STOP_LOSS':
    case 'TAKE_PROFIT':
      final pl = safeDoubleOrNull(reason['pl_rate'], hint: 'rating.reason.pl_rate');
      return pl == null ? label : '$label · 손익률 ${_signedPct1(pl)}';
    case 'SCORE_PERCENTILE':
      final pct = safeDoubleOrNull(reason['percentile'], hint: 'rating.reason.percentile');
      final weakest = reason['weakest_group']?.toString();
      var s = label;
      if (pct != null) s += ' · 백분위 ${(pct * 100).round()}%';
      if (weakest != null && weakest.isNotEmpty) s += ' · $weakest 약화';
      return s;
    case 'BAND_TRIM':
      final weight = safeDoubleOrNull(reason['weight'], hint: 'rating.reason.weight');
      return weight == null ? label : '$label · 비중 ${(weight * 100).toStringAsFixed(1)}%';
    default:
      return label;
  }
}

/// `-12.3` -> `'-12.3%'`, `4.0` -> `'+4.0%'`. `pl_rate` arrives already in
/// percent units (broker `unrealized_pl_rate`), unlike `ReasonChip`'s
/// fraction-based `return`/`threshold` fields — no *100 here.
String _signedPct1(num v) => '${v > 0 ? '+' : ''}${v.toStringAsFixed(1)}%';
