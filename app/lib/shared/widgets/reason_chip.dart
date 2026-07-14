/// File: app/lib/shared/widgets/reason_chip.dart
///
/// Renders *why* a trade happened — the backend's structured
/// `reason` object (`{"rule": "STOP_LOSS", "return": -0.12}`, ...) attached
/// to backtest trades and order proposals. This is the single source of
/// truth for the rule → Korean label / detail / color mapping so the
/// backtest trade log and the "오늘의 제안" cards read identically.
///
/// Visual language matches the existing bordered chip already used by
/// `presentation/proposals/proposals_screen.dart` (rounded 6px, tinted
/// border, colored text) — this widget just makes it shared and reason-aware.
library;

import 'package:flutter/material.dart';

import '../../data/parse_utils.dart';

/// 한국 관례: 매수(진입)=빨강, 매도(축소/이탈)=파랑 — portfolio_screen.dart /
/// proposals_screen.dart 와 동일한 색상 규약을 따른다.
const _buyColor = Colors.redAccent;
const _sellColor = Colors.blueAccent;

/// Rules that read as a "buy-ish" action (new/replacement entry, exposure
/// restored). Every other rule — including unknown/future ones — renders
/// sell-ish, since exits/trims/de-risking dominate the vocabulary.
const _buyRules = {'REBALANCE_IN', 'SCORE_EXIT_REPLACE', 'REGIME_RERISK'};

/// Compact chip that renders a backtest/proposal trade's structured
/// `reason`: Korean rule label + the single most relevant numeric detail.
///
/// - `null` reason (or one without a `rule`) renders a neutral dash so
///   older persisted runs without structured reasons don't look broken.
/// - Unknown rules fall back to the raw rule string, colored sell-ish.
class ReasonChip extends StatelessWidget {
  const ReasonChip({super.key, required this.reason, this.dense = false});

  /// `{"rule": <RULE>, ...}` from the backend. Nullable — older persisted
  /// backtest runs and malformed payloads may not carry one.
  final Map<String, dynamic>? reason;

  /// Tighter padding/font for already-dense rows (e.g. the backtest trade
  /// log). Defaults to the same size as the original proposals chip.
  final bool dense;

  /// Rule → Korean label. Unknown rules fall back to the raw (uppercased)
  /// rule string; a missing/empty rule falls back to '제안'.
  static String labelFor(Map<String, dynamic> reason) {
    final rule = (reason['rule'] as String?)?.toUpperCase() ?? '';
    return switch (rule) {
      'REBALANCE_IN' => '신규 편입',
      'REBALANCE_OUT' => '리밸런스 제외',
      'STOP_LOSS' => '손절',
      'TAKE_PROFIT' => '익절',
      'BAND_TRIM' => '비중 트림',
      'SCORE_EXIT' => '점수 이탈',
      'SCORE_EXIT_REPLACE' => '교체 편입',
      'REGIME_DERISK' => '레짐 축소',
      'REGIME_RERISK' => '레짐 복원',
      _ => rule.isEmpty ? '제안' : rule,
    };
  }

  /// Label plus the single most relevant extra detail, e.g. `손절 · -12.0%`.
  /// Falls back to the bare label when the expected extra key is absent
  /// (defensive: reason shapes evolve on the backend).
  static String detailFor(Map<String, dynamic> reason) {
    final rule = (reason['rule'] as String?)?.toUpperCase() ?? '';
    final label = labelFor(reason);
    switch (rule) {
      case 'REBALANCE_IN':
        final rank =
            safeDoubleOrNull(reason['rank'], hint: 'reason.rank')?.round();
        final score = safeDoubleOrNull(reason['score'], hint: 'reason.score');
        var s = label;
        if (rank != null) s += ' · 순위 $rank';
        if (score != null) s += ' · 점수 ${score.toStringAsFixed(2)}';
        return s;
      case 'STOP_LOSS':
      case 'TAKE_PROFIT':
        final ret = safeDoubleOrNull(reason['return'], hint: 'reason.return');
        return ret == null ? label : '$label · ${_signedPct(ret)}';
      case 'BAND_TRIM':
        final th =
            safeDoubleOrNull(reason['threshold'], hint: 'reason.threshold');
        return th == null ? label : '$label · 임계 ${_pct(th)}';
      case 'SCORE_EXIT':
        final by = reason['replaced_by']?.toString();
        return (by == null || by.isEmpty) ? label : '$label → $by';
      case 'SCORE_EXIT_REPLACE':
        final of = reason['replaces']?.toString();
        return (of == null || of.isEmpty) ? label : '$label ← $of';
      case 'REGIME_DERISK':
        final from = safeDoubleOrNull(reason['from_exposure'],
            hint: 'reason.from_exposure');
        final to = safeDoubleOrNull(reason['to_exposure'],
            hint: 'reason.to_exposure');
        return (from == null || to == null)
            ? label
            : '$label ${_pctInt(from)}→${_pctInt(to)}%';
      case 'REGIME_RERISK':
        final to = safeDoubleOrNull(reason['to_exposure'],
            hint: 'reason.to_exposure');
        return to == null ? label : '$label →${_pctInt(to)}%';
      default:
        return label;
    }
  }

  /// Buy-ish rules render red, everything else (incl. unknown rules)
  /// renders blue — see [_buyRules].
  static Color colorFor(Map<String, dynamic> reason) {
    final rule = (reason['rule'] as String?)?.toUpperCase() ?? '';
    return _buyRules.contains(rule) ? _buyColor : _sellColor;
  }

  static String _signedPct(num v) {
    final pct = v * 100;
    return '${pct > 0 ? '+' : ''}${pct.toStringAsFixed(1)}%';
  }

  static String _pct(num v) => '${(v * 100).toStringAsFixed(1)}%';

  static int _pctInt(num v) => (v * 100).round();

  @override
  Widget build(BuildContext context) {
    final r = reason;
    final rule = r == null ? null : r['rule'] as String?;
    if (r == null || rule == null || rule.isEmpty) {
      return Text(
        '—',
        style: TextStyle(
          fontSize: dense ? 11 : 12,
          color: Theme.of(context).colorScheme.outline,
        ),
      );
    }
    final color = colorFor(r);
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: dense ? 6 : 8,
        vertical: dense ? 2 : 3,
      ),
      decoration: BoxDecoration(
        border: Border.all(color: color.withValues(alpha: 0.5)),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        detailFor(r),
        style: TextStyle(color: color, fontSize: dense ? 11 : 12),
      ),
    );
  }
}
