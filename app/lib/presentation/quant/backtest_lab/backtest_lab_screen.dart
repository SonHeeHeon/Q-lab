/// File: app/lib/presentation/quant/backtest_lab/backtest_lab_screen.dart
///
/// Quant & AI — Backtest Lab (Tab 2). Currently shows the runs
/// leaderboard. The equation builder lands in Phase 6.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../../data/api/backtest_api.dart';
import '../../../shared/widgets/empty_state.dart';
import 'backtest_lab_controller.dart';

final _date = DateFormat('yyyy-MM-dd');

class BacktestLabScreen extends ConsumerWidget {
  const BacktestLabScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(backtestRunsProvider);
    final sortBy = ref.watch(runSortByProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('백테스트 랩'),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(48),
          child: Row(
            children: [
              const SizedBox(width: 16),
              TextButton(
                onPressed: () => context.go('/quant'),
                child: const Text('인사이트'),
              ),
              const SizedBox(width: 8),
              FilledButton.tonal(
                onPressed: () {},
                child: const Text('백테스트 랩'),
              ),
              const SizedBox(width: 8),
            ],
          ),
        ),
        actions: [
          IconButton(
            tooltip: '새로고침',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(backtestRunsProvider),
          ),
        ],
      ),
      body: async.when(
        data: (runs) => Column(
          children: [
            const _EquationBuilderBanner(),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
              child: Row(
                children: [
                  Text('정렬:', style: Theme.of(context).textTheme.bodySmall),
                  const SizedBox(width: 8),
                  for (final s in RunSortBy.values) ...[
                    ChoiceChip(
                      label: Text(switch (s) {
                        RunSortBy.date => '최신',
                        RunSortBy.cagr => 'CAGR',
                        RunSortBy.sharpe => 'Sharpe',
                        RunSortBy.mdd => 'MDD',
                        RunSortBy.winRate => '승률',
                      }),
                      selected: sortBy == s,
                      onSelected: (_) =>
                          ref.read(runSortByProvider.notifier).state = s,
                    ),
                    const SizedBox(width: 4),
                  ],
                ],
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: runs.isEmpty
                  ? const EmptyState(
                      icon: Icons.science_outlined,
                      title: '저장된 백테스트 결과가 없습니다',
                      subtitle: '먼저 research/ CLI 또는 (Phase 6 이후) 방정식 빌더로 백테스트를 실행하세요.',
                    )
                  : ListView.separated(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      itemCount: runs.length,
                      separatorBuilder: (_, __) => const Divider(height: 1),
                      itemBuilder: (_, i) => _RunRow(run: runs[i]),
                    ),
            ),
          ],
        ),
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
                  onPressed: () => ref.invalidate(backtestRunsProvider),
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

class _EquationBuilderBanner extends StatelessWidget {
  const _EquationBuilderBanner();
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return InkWell(
      onTap: () => context.go('/quant/builder'),
      borderRadius: BorderRadius.circular(12),
      child: Container(
        margin: const EdgeInsets.fromLTRB(16, 12, 16, 4),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: theme.colorScheme.primaryContainer,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          children: [
            Icon(Icons.calculate_outlined, color: theme.colorScheme.onPrimaryContainer),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('🆕 가치 방정식 빌더',
                      style: theme.textTheme.titleSmall?.copyWith(
                        color: theme.colorScheme.onPrimaryContainer,
                        fontWeight: FontWeight.w700,
                      )),
                  Text('팩터·가중치·필터를 조립하고 즉시 백테스트 → 자산곡선 확인',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onPrimaryContainer,
                      )),
                ],
              ),
            ),
            Icon(Icons.chevron_right, color: theme.colorScheme.onPrimaryContainer),
          ],
        ),
      ),
    );
  }
}

class _RunRow extends ConsumerWidget {
  const _RunRow({required this.run});
  final BacktestRunSummary run;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final cagrPct = run.cagr * 100;
    final mddPct = run.mdd * 100;
    final winPct = run.winRate * 100;
    return InkWell(
      onTap: () => context.go('/quant/backtest/runs/${run.runId}'),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: theme.colorScheme.primaryContainer,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(run.strategy,
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: theme.colorScheme.onPrimaryContainer,
                        fontWeight: FontWeight.w700,
                      )),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(run.runId,
                      style: theme.textTheme.bodySmall
                          ?.copyWith(fontFamily: 'monospace')),
                ),
                const Icon(Icons.chevron_right, size: 18),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              '${_date.format(run.startDate)} → ${_date.format(run.endDate)} · '
              '${run.rebalanceFreq} · top_${run.topN} · ${run.nTrades} trades',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 10,
              runSpacing: 6,
              children: [
                _MetricChip(
                  label: 'CAGR',
                  value: '${cagrPct.toStringAsFixed(2)}%',
                  color: cagrPct >= 0 ? Colors.redAccent : Colors.blueAccent,
                ),
                _MetricChip(
                  label: 'MDD',
                  value: '${mddPct.toStringAsFixed(2)}%',
                  color: Colors.blueAccent,
                ),
                _MetricChip(
                  label: 'Sharpe',
                  value: run.sharpe.toStringAsFixed(2),
                  color: run.sharpe >= 1 ? Colors.green : Colors.amber,
                ),
                _MetricChip(
                  label: '승률',
                  value: '${winPct.toStringAsFixed(1)}%',
                  color: winPct >= 50 ? Colors.green : Colors.amber,
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _MetricChip extends StatelessWidget {
  const _MetricChip({required this.label, required this.value, required this.color});
  final String label;
  final String value;
  final Color color;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        border: Border.all(color: color.withValues(alpha: 0.3)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text('$label ', style: theme.textTheme.labelSmall),
          Text(value,
              style: theme.textTheme.labelMedium?.copyWith(
                color: color,
                fontWeight: FontWeight.w800,
                fontFamily: 'monospace',
              )),
        ],
      ),
    );
  }
}
