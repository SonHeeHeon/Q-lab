/// File: app/lib/presentation/performance/performance_screen.dart
///
/// 성과 분석 (Performance Analysis) — compares a quant strategy across
/// three regimes: 백테스트 (BACKTEST) / 모의투자 (PAPER) / 실전투자 (REAL).
///
/// Layout:
///   1. Header — strategy dropdown (refresh lives in the AppBar, matching
///      every other screen in this app).
///   2. 비교 (Comparison) — the centerpiece: up to 3 equity curves
///      normalized to base 100 overlaid on one chart, plus a metrics
///      comparison table. Degrades gracefully when a mode is unavailable
///      (see performance_controller.dart).
///   3. 모드별 상세 — a SegmentedButton (matching the existing 3-way
///      mode-switch idiom in settings_screen.dart's `_ActiveAccountBlock`)
///      swaps between per-mode absolute equity-curve + metrics grid.
///
/// Color language:
///   - Mode identity (chart lines / legend / badges): 백테스트=회색,
///     모의=파랑, 실전=빨강 — red intentionally matches
///     `AccountColors.real` (core/theme.dart) so "실전=red=real money" reads
///     the same way it already does on the nav-rail account badge.
///   - Gain/loss (table cells, single-mode charts, return badges): the
///     existing Korean-market convention already used everywhere else in
///     this app — 상승/이익=redAccent, 하락/손실=blueAccent.
library;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../data/api/api_client.dart';
import '../../data/api/performance_api.dart';
import '../../shared/format/money.dart';
import '../../shared/widgets/empty_state.dart';
import 'performance_controller.dart';

final _pctFmt = NumberFormat('+0.00;-0.00');
final _dateFmt = DateFormat('yy-MM-dd');
final _dateFmtShort = DateFormat('MM-dd');
final _navFmt = NumberFormat('#,##0');

// Mode-identity palette — deliberately independent of the app's seed-blue
// ColorScheme since these encode WHICH series, not surface chrome.
// `_paperColor` doubles as the app's own primary seed (0xFF3B82F6); `_realColor`
// intentionally matches AccountColors.real's dark value (core/theme.dart) —
// same "실전=red" mental model as the nav-rail account badge.
const _backtestColor = Color(0xFF94A3B8);
const _paperColor = Color(0xFF3B82F6);
const _realColor = Color(0xFFEF4444);

Color _modeColor(String mode) => switch (mode.toUpperCase()) {
      'PAPER' => _paperColor,
      'REAL' => _realColor,
      _ => _backtestColor,
    };

String _modeLabel(String mode) => switch (mode.toUpperCase()) {
      'PAPER' => '모의투자',
      'REAL' => '실전투자',
      _ => '백테스트',
    };

/// Korean market convention: gains/이익 = red, losses/손실 = blue.
Color _gainColor(double v) => v >= 0 ? Colors.redAccent : Colors.blueAccent;

// =============================================================================
// Screen
// =============================================================================

class PerformanceScreen extends ConsumerStatefulWidget {
  const PerformanceScreen({super.key});

  @override
  ConsumerState<PerformanceScreen> createState() => _PerformanceScreenState();
}

class _PerformanceScreenState extends ConsumerState<PerformanceScreen> {
  bool _refreshing = false;

  Future<void> _refresh() async {
    setState(() => _refreshing = true);
    ref.invalidate(performanceComparisonProvider);
    ref.invalidate(backtestRunsForStrategyProvider);
    ref.invalidate(backtestPerfProvider);
    ref.invalidate(paperPerfProvider);
    ref.invalidate(realPerfProvider);
    try {
      // Await just the headline so the spinner has a meaningful duration;
      // the detail tabs resolve independently via their own .when().
      await ref.read(performanceComparisonProvider.future);
    } catch (_) {
      // Surfaced via the section's own error view — nothing to do here.
    }
    if (mounted) setState(() => _refreshing = false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('성과 분석'),
        actions: [
          IconButton(
            tooltip: '새로고침',
            icon: _refreshing
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.refresh),
            onPressed: _refreshing ? null : _refresh,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: const [
            _StrategyHeaderRow(),
            SizedBox(height: 16),
            _ComparisonSection(),
            SizedBox(height: 24),
            Divider(),
            SizedBox(height: 12),
            _DetailSection(),
            SizedBox(height: 24),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Header — strategy selector
// ---------------------------------------------------------------------------

class _StrategyHeaderRow extends ConsumerWidget {
  const _StrategyHeaderRow();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final strategy = ref.watch(selectedPerformanceStrategyProvider);
    return DropdownButtonFormField<String>(
      initialValue: strategy,
      isDense: true,
      decoration: const InputDecoration(
        labelText: '전략',
        isDense: true,
        prefixIcon: Icon(Icons.psychology_outlined),
      ),
      items: [
        for (final s in kPerformanceStrategies)
          DropdownMenuItem(value: s, child: Text(s, style: const TextStyle(fontFamily: 'monospace'))),
      ],
      onChanged: (v) {
        if (v == null) return;
        ref.read(selectedPerformanceStrategyProvider.notifier).state = v;
      },
    );
  }
}

// ---------------------------------------------------------------------------
// 비교 (Comparison) — the centerpiece
// ---------------------------------------------------------------------------

class _ComparisonSection extends ConsumerWidget {
  const _ComparisonSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final async = ref.watch(performanceComparisonProvider);
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text('📊 성과 비교',
                    style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
                const Spacer(),
                Text('기준 100 정규화',
                    style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline)),
              ],
            ),
            const SizedBox(height: 8),
            async.when(
              data: (cmp) => _ComparisonBody(comparison: cmp),
              loading: () => const Padding(
                padding: EdgeInsets.symmetric(vertical: 48),
                child: Center(child: CircularProgressIndicator()),
              ),
              error: (e, _) => _ComparisonError(error: e),
            ),
          ],
        ),
      ),
    );
  }
}

class _ComparisonError extends ConsumerWidget {
  const _ComparisonError({required this.error});
  final Object error;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 24),
      child: Column(
        children: [
          Icon(Icons.error_outline, size: 36, color: theme.colorScheme.error),
          const SizedBox(height: 8),
          SelectableText('$error', textAlign: TextAlign.center, style: theme.textTheme.bodySmall),
          const SizedBox(height: 12),
          FilledButton.tonal(
            onPressed: () => ref.invalidate(performanceComparisonProvider),
            child: const Text('다시 시도'),
          ),
        ],
      ),
    );
  }
}

class _ComparisonBody extends StatelessWidget {
  const _ComparisonBody({required this.comparison});
  final PerfComparison comparison;

  @override
  Widget build(BuildContext context) {
    final modes = <PerfModeResult>[
      if (comparison.backtest != null) comparison.backtest!,
      if (comparison.paper != null) comparison.paper!,
      if (comparison.real != null) comparison.real!,
    ];

    if (modes.isEmpty) {
      return EmptyState(
        icon: Icons.query_stats_outlined,
        title: '비교할 성과 데이터가 없습니다',
        subtitle: '퀀트 > 빌더에서 전략을 백테스트하면 여기에 표시됩니다.',
        padding: const EdgeInsets.symmetric(vertical: 24),
        action: FilledButton.icon(
          icon: const Icon(Icons.science_outlined),
          label: const Text('빌더로 이동'),
          onPressed: () => context.go('/quant/builder'),
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _LegendRow(modes: modes),
        const SizedBox(height: 12),
        SizedBox(height: 260, child: _NormalizedOverlayChart(modes: modes)),
        const SizedBox(height: 20),
        _MetricsComparisonTable(comparison: comparison),
      ],
    );
  }
}

class _LegendRow extends StatelessWidget {
  const _LegendRow({required this.modes});
  final List<PerfModeResult> modes;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 6,
      children: [for (final m in modes) _LegendChip(mode: m.mode)],
    );
  }
}

class _LegendChip extends StatelessWidget {
  const _LegendChip({required this.mode});
  final String mode;

  @override
  Widget build(BuildContext context) {
    final color = _modeColor(mode);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(width: 8, height: 8, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
          const SizedBox(width: 6),
          Text(_modeLabel(mode), style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 12)),
        ],
      ),
    );
  }
}

/// One mode's equity curve rebased to 100 at its own first point, indexed
/// by relative position (not calendar date) so curves of different
/// lengths/date ranges still overlay meaningfully.
class _NormalizedSeries {
  _NormalizedSeries({required this.mode, required this.points});
  final String mode;
  final List<FlSpot> points;
}

class _NormalizedOverlayChart extends StatelessWidget {
  const _NormalizedOverlayChart({required this.modes});
  final List<PerfModeResult> modes;

  _NormalizedSeries _normalize(PerfModeResult m) {
    final base = m.equityCurve.first.nav;
    final points = <FlSpot>[
      for (var i = 0; i < m.equityCurve.length; i++)
        FlSpot(i.toDouble(), base == 0 ? 100 : (m.equityCurve[i].nav / base) * 100),
    ];
    return _NormalizedSeries(mode: m.mode, points: points);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final series = <_NormalizedSeries>[
      for (final m in modes)
        if (m.equityCurve.length >= 2) _normalize(m),
    ];

    if (series.isEmpty) {
      return const _ChartPlaceholder(
        text: '자산곡선 데이터가 있는 모드가 없습니다\n(지표는 아래 표에서 확인 가능)',
      );
    }

    final maxLen = series.map((s) => s.points.length).reduce((a, b) => a > b ? a : b);
    final allY = [for (final s in series) ...s.points.map((p) => p.y)];
    final minY = allY.reduce((a, b) => a < b ? a : b);
    final maxY = allY.reduce((a, b) => a > b ? a : b);
    final rawPad = (maxY - minY) * 0.1;
    final padY = rawPad <= 0 ? 2.0 : rawPad;
    final step = (maxLen / 4).floor().clamp(1, maxLen);

    return LineChart(
      LineChartData(
        minX: 0,
        maxX: (maxLen - 1).toDouble(),
        minY: minY - padY,
        maxY: maxY + padY,
        gridData: FlGridData(
          show: true,
          drawVerticalLine: false,
          getDrawingHorizontalLine: (_) => FlLine(
            color: theme.colorScheme.outlineVariant.withValues(alpha: 0.5),
            strokeWidth: 1,
          ),
        ),
        borderData: FlBorderData(show: false),
        titlesData: FlTitlesData(
          topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          leftTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 40,
              getTitlesWidget: (v, _) => Text(
                v.toStringAsFixed(0),
                style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline),
              ),
            ),
          ),
          bottomTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 22,
              interval: step.toDouble(),
              getTitlesWidget: (v, _) {
                final idx = v.toInt();
                if (idx < 0 || idx >= maxLen) return const SizedBox.shrink();
                return Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text('D+$idx',
                      style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline)),
                );
              },
            ),
          ),
        ),
        extraLinesData: ExtraLinesData(horizontalLines: [
          HorizontalLine(
            y: 100,
            color: theme.colorScheme.outline.withValues(alpha: 0.5),
            strokeWidth: 1,
            dashArray: const [4, 4],
            label: HorizontalLineLabel(
              show: true,
              alignment: Alignment.topLeft,
              padding: const EdgeInsets.only(left: 4, bottom: 2),
              style: TextStyle(color: theme.colorScheme.outline, fontSize: 10),
              labelResolver: (_) => '기준 100',
            ),
          ),
        ]),
        lineBarsData: [
          for (final s in series)
            LineChartBarData(
              spots: s.points,
              isCurved: true,
              color: _modeColor(s.mode),
              barWidth: s.mode.toUpperCase() == 'REAL' ? 3 : 2.2,
              dotData: const FlDotData(show: false),
              belowBarData: BarAreaData(show: false),
            ),
        ],
        lineTouchData: LineTouchData(
          touchTooltipData: LineTouchTooltipData(
            getTooltipColor: (_) => theme.colorScheme.inverseSurface,
            getTooltipItems: (spots) => spots.map((s) {
              final match = series[s.barIndex];
              return LineTooltipItem(
                '${_modeLabel(match.mode)}\n${s.y.toStringAsFixed(1)}',
                TextStyle(
                  color: theme.colorScheme.onInverseSurface,
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                ),
              );
            }).toList(),
          ),
        ),
      ),
    );
  }
}

class _ChartPlaceholder extends StatelessWidget {
  const _ChartPlaceholder({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHigh,
        border: Border.all(color: theme.colorScheme.outlineVariant),
        borderRadius: BorderRadius.circular(8),
      ),
      alignment: Alignment.center,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.show_chart, size: 32, color: theme.colorScheme.outline),
            const SizedBox(height: 8),
            Text(text,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.outline)),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Metrics comparison table
// ---------------------------------------------------------------------------

class _MetricRow {
  const _MetricRow(this.label, this.pick, {required this.isPct, required this.colorByValue});
  final String label;
  final double Function(PerfMetrics) pick;
  final bool isPct;
  final bool colorByValue;
}

class _MetricsComparisonTable extends StatelessWidget {
  const _MetricsComparisonTable({required this.comparison});
  final PerfComparison comparison;

  static final _rows = <_MetricRow>[
    _MetricRow('누적수익률', (m) => m.totalReturn, isPct: true, colorByValue: true),
    _MetricRow('CAGR', (m) => m.cagr, isPct: true, colorByValue: true),
    _MetricRow('MDD', (m) => m.mdd, isPct: true, colorByValue: true),
    _MetricRow('Sharpe', (m) => m.sharpe, isPct: false, colorByValue: false),
    _MetricRow('승률', (m) => m.winRate, isPct: true, colorByValue: false),
  ];

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cols = <(String, PerfModeResult?)>[
      ('백테스트', comparison.backtest),
      ('모의', comparison.paper),
      ('실전', comparison.real),
    ];

    Widget cell(PerfModeResult? result, _MetricRow def) {
      if (result == null) {
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 4),
          child: Text('—',
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.outline)),
        );
      }
      final v = def.pick(result.metrics);
      final text = def.isPct ? '${_pctFmt.format(v * 100)}%' : v.toStringAsFixed(2);
      final color = def.colorByValue ? _gainColor(v) : theme.colorScheme.onSurface;
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 4),
        child: Text(
          text,
          textAlign: TextAlign.center,
          style: theme.textTheme.bodyMedium
              ?.copyWith(fontFamily: 'monospace', fontWeight: FontWeight.w700, color: color),
        ),
      );
    }

    return Table(
      columnWidths: const {0: FlexColumnWidth(1.25)},
      children: [
        TableRow(
          decoration: BoxDecoration(
            border: Border(bottom: BorderSide(color: theme.colorScheme.outlineVariant)),
          ),
          children: [
            const SizedBox(),
            for (final c in cols)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text(c.$1,
                    textAlign: TextAlign.center,
                    style: theme.textTheme.labelMedium?.copyWith(fontWeight: FontWeight.w700)),
              ),
          ],
        ),
        for (final def in _rows)
          TableRow(
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text(def.label,
                    style: theme.textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w600)),
              ),
              for (final c in cols) cell(c.$2, def),
            ],
          ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// 모드별 상세 (per-mode detail)
// ---------------------------------------------------------------------------

class _DetailSection extends ConsumerWidget {
  const _DetailSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final mode = ref.watch(performanceDetailModeProvider);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('🔎 모드별 상세', style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
        const SizedBox(height: 10),
        SegmentedButton<PerfDetailMode>(
          segments: const [
            ButtonSegment(value: PerfDetailMode.backtest, label: Text('백테스트')),
            ButtonSegment(value: PerfDetailMode.paper, label: Text('모의투자')),
            ButtonSegment(value: PerfDetailMode.real, label: Text('실전투자')),
          ],
          selected: {mode},
          onSelectionChanged: (s) => ref.read(performanceDetailModeProvider.notifier).state = s.first,
        ),
        const SizedBox(height: 16),
        AnimatedSwitcher(
          duration: const Duration(milliseconds: 220),
          child: switch (mode) {
            PerfDetailMode.backtest => const _BacktestDetailTab(key: ValueKey('backtest')),
            PerfDetailMode.paper => const _PaperDetailTab(key: ValueKey('paper')),
            PerfDetailMode.real => const _RealDetailTab(key: ValueKey('real')),
          },
        ),
      ],
    );
  }
}

class _BacktestDetailTab extends ConsumerWidget {
  const _BacktestDetailTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(backtestPerfProvider);
    return async.when(
      data: (perf) {
        if (perf == null) {
          return EmptyState(
            icon: Icons.science_outlined,
            title: '이 전략의 백테스트 기록이 없습니다',
            subtitle: '퀀트 > 빌더에서 백테스트를 실행하면 여기에 표시됩니다.',
            padding: const EdgeInsets.symmetric(vertical: 24),
            action: FilledButton.icon(
              icon: const Icon(Icons.science_outlined),
              label: const Text('빌더로 이동'),
              onPressed: () => context.go('/quant/builder'),
            ),
          );
        }
        return _ModeDetailBody(perf: perf);
      },
      loading: () => const _DetailLoading(),
      error: (e, _) => _DetailErrorBlock(
        error: e,
        onRetry: () {
          ref.invalidate(backtestRunsForStrategyProvider);
          ref.invalidate(backtestPerfProvider);
        },
      ),
    );
  }
}

class _PaperDetailTab extends ConsumerWidget {
  const _PaperDetailTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(paperPerfProvider);
    return async.when(
      data: (perf) => _ModeDetailBody(perf: perf),
      loading: () => const _DetailLoading(),
      error: (e, _) {
        if (e is ApiError && e.statusCode == 404) {
          return _BackendMissingCard(
            message: '모의투자 성과 API 준비 중 — 백엔드(Codex) 작업 필요',
            onRetry: () => ref.invalidate(paperPerfProvider),
          );
        }
        return _DetailErrorBlock(error: e, onRetry: () => ref.invalidate(paperPerfProvider));
      },
    );
  }
}

class _RealDetailTab extends ConsumerWidget {
  const _RealDetailTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(realPerfProvider);
    return async.when(
      data: (perf) => _ModeDetailBody(perf: perf),
      loading: () => const _DetailLoading(),
      error: (e, _) {
        if (e is ApiError && e.statusCode == 404) {
          return _BackendMissingCard(
            message: '실전투자 성과 API 준비 중 — 백엔드(Codex) 작업 필요',
            onRetry: () => ref.invalidate(realPerfProvider),
          );
        }
        return _DetailErrorBlock(error: e, onRetry: () => ref.invalidate(realPerfProvider));
      },
    );
  }
}

class _DetailLoading extends StatelessWidget {
  const _DetailLoading();
  @override
  Widget build(BuildContext context) => const Padding(
        padding: EdgeInsets.symmetric(vertical: 48),
        child: Center(child: CircularProgressIndicator()),
      );
}

class _DetailErrorBlock extends StatelessWidget {
  const _DetailErrorBlock({required this.error, required this.onRetry});
  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.error_outline, size: 40),
          const SizedBox(height: 8),
          SelectableText('$error', textAlign: TextAlign.center),
          const SizedBox(height: 12),
          FilledButton(onPressed: onRetry, child: const Text('다시 시도')),
        ],
      ),
    );
  }
}

/// Friendly "not built yet" card for the PAPER/REAL endpoints — mirrors
/// `presentation/settings/settings_screen.dart`'s `_BackendMissingBlock`.
class _BackendMissingCard extends StatelessWidget {
  const _BackendMissingCard({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      color: theme.colorScheme.errorContainer,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.construction_outlined, color: theme.colorScheme.onErrorContainer, size: 20),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    message,
                    style: theme.textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                      color: theme.colorScheme.onErrorContainer,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              '백엔드 라우트가 배포되면 자동으로 데이터가 표시됩니다.',
              style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onErrorContainer),
            ),
            const SizedBox(height: 10),
            FilledButton.tonal(onPressed: onRetry, child: const Text('다시 시도')),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Shared per-mode body: header stat card + absolute equity chart + metrics
// ---------------------------------------------------------------------------

class _ModeDetailBody extends StatelessWidget {
  const _ModeDetailBody({required this.perf});
  final PerfModeResult perf;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _ModeHeaderCard(perf: perf, color: _modeColor(perf.mode)),
        const SizedBox(height: 12),
        Card(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('자산곡선', style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
                const SizedBox(height: 12),
                SizedBox(
                  height: 240,
                  child: perf.equityCurve.length < 2
                      ? _ChartPlaceholder(
                          text: perf.mode.toUpperCase() == 'BACKTEST'
                              ? '자산곡선 데이터 없음\n'
                                  'GET /api/backtest/runs/{id} 는 metrics만 제공합니다.\n'
                                  '빌더에서 새로 실행한 백테스트만 곡선이 표시됩니다.'
                              : '자산곡선 데이터 없음',
                        )
                      : _AbsoluteEquityChart(curve: perf.equityCurve),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        _ModeMetricsGrid(metrics: perf.metrics),
      ],
    );
  }
}

class _ModeHeaderCard extends StatelessWidget {
  const _ModeHeaderCard({required this.perf, required this.color});
  final PerfModeResult perf;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final totalReturn = perf.metrics.totalReturn;
    final initialNav = perf.initialNav;
    final currentNav = perf.currentNav;
    final asOf = perf.asOf;

    final navText = currentNav == null
        ? '—'
        : (initialNav == null
            ? krwFmt.format(currentNav)
            : '${krwFmt.format(initialNav)} → ${krwFmt.format(currentNav)}');

    return Card(
      color: theme.colorScheme.surfaceContainerHighest,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Wrap(
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: 12,
          runSpacing: 8,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(8)),
              child: Text(_modeLabel(perf.mode),
                  style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 12)),
            ),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(navText,
                    style: theme.textTheme.titleMedium
                        ?.copyWith(fontWeight: FontWeight.w900, fontFamily: 'monospace')),
                if (asOf != null)
                  Text('기준일 ${_dateFmt.format(asOf.toLocal())}',
                      style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline)),
              ],
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                color: _gainColor(totalReturn).withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Text(
                '${_pctFmt.format(totalReturn * 100)}%',
                style: TextStyle(
                  color: _gainColor(totalReturn),
                  fontWeight: FontWeight.w800,
                  fontFamily: 'monospace',
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AbsoluteEquityChart extends StatelessWidget {
  const _AbsoluteEquityChart({required this.curve});
  final List<PerfSeriesPoint> curve;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final spots = <FlSpot>[
      for (var i = 0; i < curve.length; i++) FlSpot(i.toDouble(), curve[i].nav),
    ];
    final minY = spots.map((s) => s.y).reduce((a, b) => a < b ? a : b);
    final maxY = spots.map((s) => s.y).reduce((a, b) => a > b ? a : b);
    final rawPad = (maxY - minY) * 0.08;
    final padY = rawPad <= 0 ? 1.0 : rawPad;
    final gain = curve.last.nav - curve.first.nav;
    final lineColor = gain >= 0 ? Colors.redAccent : Colors.blueAccent;
    final labelStep = (curve.length / 4).floor().clamp(1, curve.length);

    return LineChart(
      LineChartData(
        minX: 0,
        maxX: (curve.length - 1).toDouble(),
        minY: minY - padY,
        maxY: maxY + padY,
        gridData: FlGridData(
          show: true,
          drawVerticalLine: false,
          getDrawingHorizontalLine: (_) => FlLine(
            color: theme.colorScheme.outlineVariant.withValues(alpha: 0.5),
            strokeWidth: 1,
          ),
        ),
        borderData: FlBorderData(show: false),
        titlesData: FlTitlesData(
          topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          leftTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 60,
              getTitlesWidget: (v, _) => Text(_formatNav(v),
                  style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline)),
            ),
          ),
          bottomTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 22,
              interval: labelStep.toDouble(),
              getTitlesWidget: (v, _) {
                final idx = v.toInt();
                if (idx < 0 || idx >= curve.length) return const SizedBox.shrink();
                return Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(_dateFmtShort.format(curve[idx].date),
                      style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline)),
                );
              },
            ),
          ),
        ),
        lineBarsData: [
          LineChartBarData(
            spots: spots,
            isCurved: true,
            color: lineColor,
            barWidth: 2.5,
            dotData: const FlDotData(show: false),
            belowBarData: BarAreaData(
              show: true,
              gradient: LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: [lineColor.withValues(alpha: 0.32), lineColor.withValues(alpha: 0.02)],
              ),
            ),
          ),
        ],
        lineTouchData: LineTouchData(
          touchTooltipData: LineTouchTooltipData(
            getTooltipColor: (_) => theme.colorScheme.inverseSurface,
            getTooltipItems: (spots) => spots.map((s) {
              final idx = s.x.toInt();
              final pt = curve[idx];
              return LineTooltipItem(
                '${DateFormat('yyyy-MM-dd').format(pt.date)}\n₩${_navFmt.format(pt.nav)}',
                TextStyle(color: theme.colorScheme.onInverseSurface, fontSize: 11),
              );
            }).toList(),
          ),
        ),
      ),
    );
  }
}

String _formatNav(double v) {
  final abs = v.abs();
  if (abs >= 1e8) return '${(v / 1e8).toStringAsFixed(1)}억';
  if (abs >= 1e7) return '${(v / 1e7).toStringAsFixed(1)}천';
  if (abs >= 1e4) return '${(v / 1e4).toStringAsFixed(0)}만';
  return v.toStringAsFixed(0);
}

// ---------------------------------------------------------------------------
// Per-mode metrics grid — visual style matches
// backtest_run_detail_screen.dart's `_MetricTile` (icon + label, big
// monospace value, hint subtitle).
// ---------------------------------------------------------------------------

class _ModeMetricsGrid extends StatelessWidget {
  const _ModeMetricsGrid({required this.metrics});
  final PerfMetrics metrics;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, c) {
      final cols = c.maxWidth >= 720 ? 4 : 2;
      final tiles = <Widget>[
        _PerfMetricTile(
          label: '누적수익률',
          value: '${_pctFmt.format(metrics.totalReturn * 100)}%',
          hint: '기간 누적 수익률',
          color: _gainColor(metrics.totalReturn),
          icon: Icons.stacked_line_chart,
        ),
        _PerfMetricTile(
          label: 'CAGR',
          value: '${_pctFmt.format(metrics.cagr * 100)}%',
          hint: '연복리수익률',
          color: _gainColor(metrics.cagr),
          icon: Icons.trending_up,
        ),
        _PerfMetricTile(
          label: 'MDD',
          value: '${_pctFmt.format(metrics.mdd * 100)}%',
          hint: '최대낙폭 (Max Drawdown)',
          color: Colors.blueAccent,
          icon: Icons.trending_down,
        ),
        _PerfMetricTile(
          label: 'Sharpe',
          value: metrics.sharpe.toStringAsFixed(2),
          hint: '위험조정수익률',
          color: metrics.sharpe >= 1
              ? Colors.green
              : (metrics.sharpe >= 0 ? Colors.amber : Colors.redAccent),
          icon: Icons.balance,
        ),
        _PerfMetricTile(
          label: '승률',
          value: '${(metrics.winRate * 100).toStringAsFixed(1)}%',
          hint: 'Win Rate',
          color: metrics.winRate >= 0.5 ? Colors.green : Colors.amber,
          icon: Icons.emoji_events_outlined,
        ),
        if (metrics.sortino != null)
          _PerfMetricTile(
            label: 'Sortino',
            value: metrics.sortino!.toStringAsFixed(2),
            hint: '하방위험 조정수익률',
            color: metrics.sortino! >= 1 ? Colors.green : Colors.amber,
            icon: Icons.shield_outlined,
          ),
        if (metrics.nTrades != null)
          _PerfMetricTile(
            label: '#Trades',
            value: '${metrics.nTrades}',
            hint: '총 매매 횟수',
            color: Colors.purpleAccent,
            icon: Icons.repeat,
          ),
        if (metrics.turnover != null)
          _PerfMetricTile(
            label: '회전율',
            value: metrics.turnover!.toStringAsFixed(2),
            hint: 'Turnover',
            color: Colors.deepPurple,
            icon: Icons.swap_horiz,
          ),
      ];
      return GridView.count(
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        crossAxisCount: cols,
        mainAxisSpacing: 10,
        crossAxisSpacing: 10,
        childAspectRatio: 1.15,
        children: tiles,
      );
    });
  }
}

class _PerfMetricTile extends StatelessWidget {
  const _PerfMetricTile({
    required this.label,
    required this.value,
    required this.hint,
    required this.color,
    required this.icon,
  });
  final String label;
  final String value;
  final String hint;
  final Color color;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, size: 14, color: color),
                const SizedBox(width: 5),
                Expanded(
                  child: Text(label,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.labelMedium
                          ?.copyWith(fontWeight: FontWeight.w800, color: color)),
                ),
              ],
            ),
            const SizedBox(height: 4),
            // FittedBox guarantees the headline value never overflows the
            // tile regardless of digit count or the user's system font
            // scale — GridView.count fixes this cell's height, so the
            // content must shrink to fit rather than the other way around.
            Flexible(
              child: FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Text(value,
                    style: theme.textTheme.headlineSmall
                        ?.copyWith(fontWeight: FontWeight.w900, fontFamily: 'monospace')),
              ),
            ),
            const SizedBox(height: 2),
            Text(hint,
                overflow: TextOverflow.ellipsis,
                style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline)),
          ],
        ),
      ),
    );
  }
}
