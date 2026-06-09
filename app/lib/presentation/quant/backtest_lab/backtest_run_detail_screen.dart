/// File: app/lib/presentation/quant/backtest_lab/backtest_run_detail_screen.dart
///
/// Backtest run detail — metric dashboard + strategy params card.
library;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../../data/api/backtest_api.dart';
import 'backtest_lab_controller.dart';

final _date = DateFormat('yyyy-MM-dd');
final _krw = NumberFormat('#,##0');

class BacktestRunDetailScreen extends ConsumerWidget {
  const BacktestRunDetailScreen({super.key, required this.runId});
  final String runId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(backtestRunDetailProvider(runId));
    final cached = ref.watch(recentRunResultsProvider)[runId];
    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/quant/backtest'),
        ),
        title: Text(runId, style: const TextStyle(fontFamily: 'monospace', fontSize: 14)),
        actions: [
          IconButton(
            tooltip: '새로고침',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(backtestRunDetailProvider(runId)),
          ),
        ],
      ),
      body: async.when(
        data: (detail) => _Body(detail: detail, cached: cached),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.error_outline, size: 48),
                const SizedBox(height: 8),
                SelectableText('$e', textAlign: TextAlign.center),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: () => ref.invalidate(backtestRunDetailProvider(runId)),
                  child: const Text('다시 시도'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Body extends StatelessWidget {
  const _Body({required this.detail, this.cached});
  final BacktestRunDetail detail;
  final BacktestRunResult? cached;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, c) {
      // 2 cols on narrow, 4 on wide
      final cols = c.maxWidth >= 720 ? 4 : 2;
      return ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _HeaderCard(detail: detail),
          const SizedBox(height: 16),
          _EquityCurveCard(cached: cached),
          const SizedBox(height: 16),
          _MetricsGrid(metrics: detail.metrics, cols: cols),
          const SizedBox(height: 16),
          _StrategyCard(strategy: detail.strategy, gitCommit: detail.gitCommit),
          if (cached != null && cached!.trades.isNotEmpty) ...[
            const SizedBox(height: 16),
            _TradesCard(trades: cached!.trades),
          ],
          if (cached != null && cached!.warnings.isNotEmpty) ...[
            const SizedBox(height: 16),
            _WarningsCard(warnings: cached!.warnings),
          ],
          const SizedBox(height: 24),
        ],
      );
    });
  }
}

// ---------------------------------------------------------------------------
// Equity Curve (LineChart)
// ---------------------------------------------------------------------------

class _EquityCurveCard extends StatelessWidget {
  const _EquityCurveCard({required this.cached});
  final BacktestRunResult? cached;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text('📈 자산곡선 (Equity Curve)',
                    style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
                const Spacer(),
                if (cached != null)
                  Text(
                    '${cached!.equityCurve.length}일',
                    style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline),
                  ),
              ],
            ),
            const SizedBox(height: 12),
            SizedBox(
              height: 280,
              child: cached == null
                  ? _CurvePlaceholder()
                  : _EquityLineChart(curve: cached!.equityCurve, initialNav: cached!.initialNav),
            ),
          ],
        ),
      ),
    );
  }
}

class _CurvePlaceholder extends StatelessWidget {
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
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.show_chart, size: 36, color: theme.colorScheme.outline),
          const SizedBox(height: 6),
          Text('자산곡선 데이터 없음',
              style: theme.textTheme.titleSmall?.copyWith(color: theme.colorScheme.outline)),
          const SizedBox(height: 2),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 24),
            child: Text(
              'GET /api/backtest/runs/{id} 는 metrics + params 만 제공합니다.\n'
              '자산곡선은 빌더에서 [백테스트 실행]으로 새로 돌린 경우에만 표시됩니다.',
              textAlign: TextAlign.center,
              style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.outline),
            ),
          ),
        ],
      ),
    );
  }
}

class _EquityLineChart extends StatelessWidget {
  const _EquityLineChart({required this.curve, required this.initialNav});
  final List<EquityPoint> curve;
  final double initialNav;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (curve.length < 2) {
      return Center(child: Text('데이터 포인트 부족', style: theme.textTheme.bodySmall));
    }

    final spots = <FlSpot>[
      for (var i = 0; i < curve.length; i++) FlSpot(i.toDouble(), curve[i].nav),
    ];
    final minY = spots.map((s) => s.y).reduce((a, b) => a < b ? a : b);
    final maxY = spots.map((s) => s.y).reduce((a, b) => a > b ? a : b);
    final padY = (maxY - minY) * 0.08;
    final finalGain = (curve.last.nav / initialNav - 1) * 100;
    final lineColor = finalGain >= 0 ? Colors.redAccent : Colors.blueAccent;

    // 4 evenly-spaced date labels along x
    final labelStep = (curve.length / 4).floor().clamp(1, curve.length);
    final fmtDate = DateFormat('yy-MM');

    return LineChart(
      LineChartData(
        minY: minY - padY,
        maxY: maxY + padY,
        minX: 0,
        maxX: (curve.length - 1).toDouble(),
        gridData: FlGridData(
          show: true,
          drawVerticalLine: false,
          horizontalInterval: (maxY - minY) / 4,
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
              reservedSize: 64,
              getTitlesWidget: (v, _) => Text(
                _formatNav(v),
                style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline),
              ),
              interval: (maxY - minY) / 4,
            ),
          ),
          bottomTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 24,
              interval: labelStep.toDouble(),
              getTitlesWidget: (v, _) {
                final idx = v.toInt();
                if (idx < 0 || idx >= curve.length) return const SizedBox.shrink();
                return Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                    fmtDate.format(curve[idx].date),
                    style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline),
                  ),
                );
              },
            ),
          ),
        ),
        // Baseline at initialNav
        extraLinesData: ExtraLinesData(horizontalLines: [
          HorizontalLine(
            y: initialNav,
            color: theme.colorScheme.outline.withValues(alpha: 0.5),
            strokeWidth: 1,
            dashArray: [4, 4],
            label: HorizontalLineLabel(
              show: true,
              alignment: Alignment.centerLeft,
              padding: const EdgeInsets.only(left: 4, bottom: 2),
              style: TextStyle(
                color: theme.colorScheme.outline,
                fontSize: 10,
              ),
              labelResolver: (_) => '시작',
            ),
          ),
        ]),
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
                colors: [
                  lineColor.withValues(alpha: 0.32),
                  lineColor.withValues(alpha: 0.02),
                ],
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
              final pct = (pt.nav / initialNav - 1) * 100;
              return LineTooltipItem(
                '${DateFormat('yyyy-MM-dd').format(pt.date)}\n'
                '₩${NumberFormat('#,##0').format(pt.nav)}\n'
                '${pct >= 0 ? '+' : ''}${pct.toStringAsFixed(2)}%',
                TextStyle(
                  color: theme.colorScheme.onInverseSurface,
                  fontSize: 11,
                ),
              );
            }).toList(),
          ),
        ),
      ),
    );
  }
}

String _formatNav(double v) {
  if (v >= 1e8) return '${(v / 1e8).toStringAsFixed(1)}억';
  if (v >= 1e7) return '${(v / 1e7).toStringAsFixed(1)}천';
  if (v >= 1e4) return '${(v / 1e4).toStringAsFixed(0)}만';
  return v.toStringAsFixed(0);
}

// ---------------------------------------------------------------------------
// Trades + Warnings (only present for fresh runs from the builder)
// ---------------------------------------------------------------------------

class _TradesCard extends StatelessWidget {
  const _TradesCard({required this.trades});
  final List<TradeRecord> trades;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final fmt = DateFormat('yyyy-MM-dd');
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('🔁 체결 내역  (${trades.length})',
                style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
            const SizedBox(height: 8),
            SizedBox(
              height: 240,
              child: ListView.separated(
                itemCount: trades.length,
                separatorBuilder: (_, __) => Divider(
                  height: 1,
                  color: theme.colorScheme.outlineVariant.withValues(alpha: 0.5),
                ),
                itemBuilder: (_, i) {
                  final t = trades[i];
                  final isBuy = t.side.toUpperCase() == 'BUY';
                  final color = isBuy ? Colors.redAccent : Colors.blueAccent;
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    child: Row(
                      children: [
                        SizedBox(width: 88, child: Text(fmt.format(t.date), style: theme.textTheme.bodySmall)),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                          decoration: BoxDecoration(
                            color: color.withValues(alpha: 0.15),
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Text(t.side,
                              style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w700)),
                        ),
                        const SizedBox(width: 8),
                        SizedBox(
                          width: 72,
                          child: Text(t.code,
                              style: theme.textTheme.bodySmall?.copyWith(fontFamily: 'monospace')),
                        ),
                        Expanded(
                          child: Text('${t.qty}주 @ ₩${NumberFormat('#,##0').format(t.price)}',
                              style: theme.textTheme.bodySmall),
                        ),
                      ],
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _WarningsCard extends StatelessWidget {
  const _WarningsCard({required this.warnings});
  final List<String> warnings;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      color: Colors.amber.withValues(alpha: 0.1),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('⚠️ 경고 (${warnings.length})',
                style: theme.textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.w800,
                  color: Colors.amber.shade900,
                )),
            const SizedBox(height: 6),
            for (final w in warnings) Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Text('• $w', style: theme.textTheme.bodySmall),
            ),
          ],
        ),
      ),
    );
  }
}

class _HeaderCard extends StatelessWidget {
  const _HeaderCard({required this.detail});
  final BacktestRunDetail detail;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final s = detail.strategy;
    return Card(
      color: theme.colorScheme.surfaceContainerHighest,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: theme.colorScheme.primary,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(s.name,
                      style: TextStyle(
                        color: theme.colorScheme.onPrimary,
                        fontWeight: FontWeight.w800,
                      )),
                ),
                const SizedBox(width: 8),
                if (s.description != null)
                  Expanded(
                    child: Text(s.description!,
                        style: theme.textTheme.bodyMedium,
                        overflow: TextOverflow.ellipsis,
                        maxLines: 2),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 10,
              runSpacing: 4,
              children: [
                _Kv(label: '기간', value: '${_date.format(s.startDate)} → ${_date.format(s.endDate)}'),
                _Kv(label: '유니버스', value: s.universe),
                _Kv(label: '리밸런싱', value: s.rebalanceFreq),
                _Kv(label: 'Top N', value: '${s.topN}'),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Kv extends StatelessWidget {
  const _Kv({required this.label, required this.value});
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Text('$label ', style: theme.textTheme.bodySmall),
      Text(value,
          style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w700)),
    ]);
  }
}

// ---------------------------------------------------------------------------
// Metrics dashboard
// ---------------------------------------------------------------------------

class _MetricsGrid extends StatelessWidget {
  const _MetricsGrid({required this.metrics, required this.cols});
  final BacktestMetrics metrics;
  final int cols;

  @override
  Widget build(BuildContext context) {
    final tiles = <Widget>[
      _MetricTile(
        label: 'CAGR',
        value: '${(metrics.cagr * 100).toStringAsFixed(2)}%',
        hint: '연복리수익률',
        color: metrics.cagr >= 0 ? Colors.redAccent : Colors.blueAccent,
        icon: Icons.trending_up,
        progress: (metrics.cagr.clamp(-1.0, 1.0) + 1) / 2,
      ),
      _MetricTile(
        label: 'MDD',
        value: '${(metrics.mdd * 100).toStringAsFixed(2)}%',
        hint: '최대낙폭 (Max Drawdown)',
        color: Colors.blueAccent,
        icon: Icons.trending_down,
        progress: (1 + metrics.mdd).clamp(0.0, 1.0),
      ),
      _MetricTile(
        label: 'Sharpe',
        value: metrics.sharpe.toStringAsFixed(2),
        hint: '위험조정수익률',
        color: metrics.sharpe >= 1
            ? Colors.green
            : (metrics.sharpe >= 0 ? Colors.amber : Colors.redAccent),
        icon: Icons.balance,
        progress: (metrics.sharpe.clamp(-2.0, 4.0) + 2) / 6,
      ),
      _MetricTile(
        label: '승률',
        value: '${(metrics.winRate * 100).toStringAsFixed(1)}%',
        hint: 'Win Rate',
        color: metrics.winRate >= 0.5 ? Colors.green : Colors.amber,
        icon: Icons.emoji_events_outlined,
        progress: metrics.winRate.clamp(0.0, 1.0),
      ),
      if (metrics.sortino != null)
        _MetricTile(
          label: 'Sortino',
          value: metrics.sortino!.toStringAsFixed(2),
          hint: '하방위험 조정수익률',
          color: metrics.sortino! >= 1 ? Colors.green : Colors.amber,
          icon: Icons.shield_outlined,
          progress: (metrics.sortino!.clamp(-2.0, 4.0) + 2) / 6,
        ),
      _MetricTile(
        label: '#Trades',
        value: '${metrics.nTrades}',
        hint: '총 매매 횟수',
        color: Colors.purpleAccent,
        icon: Icons.repeat,
      ),
      if (metrics.avgHoldingDays != null)
        _MetricTile(
          label: '평균 보유일',
          value: metrics.avgHoldingDays!.toStringAsFixed(1),
          hint: 'Average Holding Days',
          color: Colors.teal,
          icon: Icons.calendar_today_outlined,
        ),
      if (metrics.turnover != null)
        _MetricTile(
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
      childAspectRatio: 1.4,
      children: tiles,
    );
  }
}

class _MetricTile extends StatelessWidget {
  const _MetricTile({
    required this.label,
    required this.value,
    required this.hint,
    required this.color,
    required this.icon,
    this.progress,
  });
  final String label;
  final String value;
  final String hint;
  final Color color;
  final IconData icon;
  final double? progress;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, size: 16, color: color),
                const SizedBox(width: 6),
                Text(label,
                    style: theme.textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w800,
                      color: color,
                    )),
              ],
            ),
            const Spacer(),
            Text(value,
                style: theme.textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w900,
                  fontFamily: 'monospace',
                )),
            const SizedBox(height: 2),
            Text(hint,
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.outline)),
            if (progress != null) ...[
              const SizedBox(height: 8),
              ClipRRect(
                borderRadius: BorderRadius.circular(2),
                child: LinearProgressIndicator(
                  value: progress!.clamp(0.0, 1.0),
                  minHeight: 4,
                  backgroundColor: color.withValues(alpha: 0.12),
                  valueColor: AlwaysStoppedAnimation<Color>(color),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Strategy params
// ---------------------------------------------------------------------------

class _StrategyCard extends StatelessWidget {
  const _StrategyCard({required this.strategy, this.gitCommit});
  final BacktestStrategy strategy;
  final String? gitCommit;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text('🧪 전략 파라미터',
                    style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
                const Spacer(),
                if (gitCommit != null)
                  Text('git $gitCommit',
                      style: theme.textTheme.labelSmall?.copyWith(
                        fontFamily: 'monospace',
                        color: theme.colorScheme.outline,
                      )),
              ],
            ),
            const SizedBox(height: 12),
            Text('팩터',
                style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            if (strategy.factors.isEmpty)
              Text('—', style: theme.textTheme.bodySmall)
            else
              for (final f in strategy.factors)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(
                          color: theme.colorScheme.secondaryContainer,
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(f.factor,
                            style: theme.textTheme.labelMedium?.copyWith(
                              color: theme.colorScheme.onSecondaryContainer,
                              fontWeight: FontWeight.w700,
                              fontFamily: 'monospace',
                            )),
                      ),
                      const SizedBox(width: 8),
                      Text('가중치 ${f.weight.toStringAsFixed(2)}',
                          style: theme.textTheme.bodySmall),
                      if (f.transform != null) ...[
                        const SizedBox(width: 8),
                        Text('· ${f.transform}',
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: theme.colorScheme.outline,
                            )),
                      ],
                    ],
                  ),
                ),
            const SizedBox(height: 12),
            Text('필터',
                style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            if (strategy.filters.isEmpty)
              Text('—', style: theme.textTheme.bodySmall)
            else
              for (final f in strategy.filters)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Text('${f.field} ${f.op} ${f.value}',
                      style: theme.textTheme.bodyMedium
                          ?.copyWith(fontFamily: 'monospace')),
                ),
          ],
        ),
      ),
    );
  }
}
