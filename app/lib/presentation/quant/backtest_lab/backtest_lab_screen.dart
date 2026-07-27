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
final _runTs = DateFormat('yyyy-MM-dd HH:mm');

class BacktestLabScreen extends ConsumerWidget {
  const BacktestLabScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(backtestRunsProvider);
    final sortBy = ref.watch(runSortByProvider);
    final modelFilter = ref.watch(runModelFilterProvider);

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
        data: (runs) {
          // Distinct model names (backend `strategy` field) across every
          // fetched run — drives the filter chip row. Only worth showing
          // when there's more than one model to tell apart.
          final models = {for (final r in runs) r.strategy}.toList()..sort();
          final showModelFilter = models.length > 1;
          final filtered = modelFilter == null
              ? runs
              : runs.where((r) => r.strategy == modelFilter).toList();
          final groupByModel = showModelFilter && modelFilter == null;
          final items = _buildRunListItems(filtered, groupByModel: groupByModel);

          return Column(
            children: [
              const _EquationBuilderBanner(),
              const _PortfolioBacktestBanner(),
              const _AfterTaxToggle(),
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
              if (showModelFilter)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
                  child: SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: Row(
                      children: [
                        Text('모델:', style: Theme.of(context).textTheme.bodySmall),
                        const SizedBox(width: 8),
                        ChoiceChip(
                          label: const Text('전체'),
                          selected: modelFilter == null,
                          onSelected: (_) =>
                              ref.read(runModelFilterProvider.notifier).state = null,
                        ),
                        const SizedBox(width: 4),
                        for (final m in models) ...[
                          ChoiceChip(
                            label: Text(m),
                            selected: modelFilter == m,
                            onSelected: (_) =>
                                ref.read(runModelFilterProvider.notifier).state = m,
                          ),
                          const SizedBox(width: 4),
                        ],
                      ],
                    ),
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
                    : filtered.isEmpty
                        ? const EmptyState(
                            icon: Icons.filter_alt_off_outlined,
                            title: '해당 모델의 결과가 없습니다',
                            subtitle: '다른 모델을 선택하거나 전체 보기로 전환하세요.',
                          )
                        : ListView.builder(
                            padding: const EdgeInsets.symmetric(vertical: 8),
                            itemCount: items.length,
                            itemBuilder: (_, i) {
                              final item = items[i];
                              if (item.header != null) {
                                return _ModelSectionHeader(model: item.header!);
                              }
                              final isLast = i == items.length - 1;
                              final nextIsHeader =
                                  !isLast && items[i + 1].header != null;
                              return Column(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  _RunRow(run: item.run!),
                                  if (!isLast && !nextIsHeader)
                                    const Divider(height: 1),
                                ],
                              );
                            },
                          ),
              ),
            ],
          );
        },
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

/// One entry in the runs list: either a model section header or a run row.
class _RunListItem {
  const _RunListItem.header(String model)
      : header = model,
        run = null;
  const _RunListItem.row(BacktestRunSummary r)
      : header = null,
        run = r;
  final String? header;
  final BacktestRunSummary? run;
}

/// Groups [runs] into header+row items — one header per distinct
/// `strategy` (model), ordered by that model's most recent run (`run_id`
/// desc, since it encodes `YYYYMMDD_HHMMSS`) so the most-recently-tested
/// model floats to the top. Each group's internal order is preserved from
/// the incoming (already-sorted) list, so whichever sort the user picked
/// (최신/CAGR/Sharpe/MDD/승률) still applies within a model's section.
///
/// When [groupByModel] is false — a single model is already isolated via
/// the filter chips, or there's only one model total — every run is
/// wrapped as a flat row with no headers, since a single-item grouping
/// would be redundant.
List<_RunListItem> _buildRunListItems(
  List<BacktestRunSummary> runs, {
  required bool groupByModel,
}) {
  if (!groupByModel) {
    return [for (final r in runs) _RunListItem.row(r)];
  }
  final byModel = <String, List<BacktestRunSummary>>{};
  for (final r in runs) {
    byModel.putIfAbsent(r.strategy, () => []).add(r);
  }
  final modelsByRecency = byModel.keys.toList()
    ..sort((a, b) {
      final aLatest =
          byModel[a]!.map((r) => r.runId).reduce((x, y) => x.compareTo(y) >= 0 ? x : y);
      final bLatest =
          byModel[b]!.map((r) => r.runId).reduce((x, y) => x.compareTo(y) >= 0 ? x : y);
      return bLatest.compareTo(aLatest);
    });
  final items = <_RunListItem>[];
  for (final m in modelsByRecency) {
    items.add(_RunListItem.header(m));
    for (final r in byModel[m]!) {
      items.add(_RunListItem.row(r));
    }
  }
  return items;
}

class _ModelSectionHeader extends StatelessWidget {
  const _ModelSectionHeader({required this.model});
  final String model;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      width: double.infinity,
      color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.6),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Text(
        model,
        style: theme.textTheme.labelLarge?.copyWith(
          fontWeight: FontWeight.w800,
          color: theme.colorScheme.primary,
          letterSpacing: 0.2,
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

/// Entry point for the multi-sleeve portfolio backtest (T-P3) — mirrors
/// [_EquationBuilderBanner]'s look (rounded tinted container, icon +
/// title + subtitle + chevron) but on `secondaryContainer` so the two
/// banners read as siblings, not duplicates.
class _PortfolioBacktestBanner extends StatelessWidget {
  const _PortfolioBacktestBanner();
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return InkWell(
      onTap: () => context.go('/quant/backtest/portfolio'),
      borderRadius: BorderRadius.circular(12),
      child: Container(
        margin: const EdgeInsets.fromLTRB(16, 4, 16, 4),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: theme.colorScheme.secondaryContainer,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          children: [
            Icon(Icons.stacked_bar_chart_rounded, color: theme.colorScheme.onSecondaryContainer),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('🧩 포트폴리오 백테스트',
                      style: theme.textTheme.titleSmall?.copyWith(
                        color: theme.colorScheme.onSecondaryContainer,
                        fontWeight: FontWeight.w700,
                      )),
                  Text('여러 전략을 섞어 블렌드 성과 확인 → 최적 비중 탐색',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSecondaryContainer,
                      )),
                ],
              ),
            ),
            Icon(Icons.chevron_right, color: theme.colorScheme.onSecondaryContainer),
          ],
        ),
      ),
    );
  }
}

/// "세후 수익률(KR)" toggle for the next backtest run (two-sleeve tax
/// rollout, T9). Persists to [afterTaxProvider] so whichever screen submits
/// the run form (Equation Builder) can read it — a compact switch rather
/// than a full settings block since it's a per-run preference, not
/// account-level config.
class _AfterTaxToggle extends ConsumerWidget {
  const _AfterTaxToggle();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final enabled = ref.watch(afterTaxProvider);
    return Card(
      margin: const EdgeInsets.fromLTRB(16, 8, 16, 0),
      child: SwitchListTile(
        dense: true,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16),
        secondary: Icon(
          Icons.receipt_long_outlined,
          color: enabled ? theme.colorScheme.primary : theme.colorScheme.outline,
        ),
        title: const Text('세후 수익률(KR)'),
        subtitle: const Text(
          '거래세+과세 ETF 매매차익 15.4% 반영 (배당 제외)',
          style: TextStyle(fontSize: 11),
        ),
        value: enabled,
        onChanged: (v) => ref.read(afterTaxProvider.notifier).state = v,
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
    final runTs = runTimestampFromId(run.runId);
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
            if (runTs != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text(
                  '시행 ${_runTs.format(runTs)}',
                  style: theme.textTheme.labelSmall
                      ?.copyWith(color: theme.colorScheme.outline),
                ),
              ),
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
