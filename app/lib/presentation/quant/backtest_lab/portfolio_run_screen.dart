/// File: app/lib/presentation/quant/backtest_lab/portfolio_run_screen.dart
///
/// Multi-sleeve portfolio backtest (Backtest Lab, T-P3) — pick 2-6 strategy
/// presets ("sleeves") + blend weights, run a combined backtest, and
/// optionally search for better weights (in-sample, with an OOS
/// walk-forward cross-check).
///
/// Visual language matches the rest of the Backtest Lab (Material 3 cards,
/// emoji section headers, monospace numerics, 매수=빨강/매도=파랑 metric
/// coloring — see `backtest_run_detail_screen.dart`) plus one addition
/// specific to this screen: every sleeve gets a stable identity color (see
/// [sleeveColor]) carried through its dropdown row, its weight slider, the
/// allocation bar, and the per-sleeve breakdown table — so a 2-6 strategy
/// blend reads as one shape instead of a bare list of rows.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../data/api/backtest_api.dart';
import '../builder/builder_controller.dart' show strategyPresetsProvider;
import 'portfolio_run_controller.dart';

// ---------------------------------------------------------------------------
// Sleeve identity palette
// ---------------------------------------------------------------------------

/// Deliberately disjoint from the app-wide 매수(빨강)/매도(파랑) gain/loss
/// semantic (`rating_chip.dart`, `_MetricChip` in `backtest_lab_screen.dart`)
/// so a sleeve's identity color never gets misread as a return signal.
/// Length matches [kMaxSleeves] so every allowed sleeve index gets its own
/// color — never wraps within a single portfolio.
const _sleeveColors = <Color>[
  Colors.teal,
  Colors.deepPurple,
  Color(0xFFB8860B), // dark goldenrod
  Colors.indigo,
  Colors.pink,
  Color(0xFF00838F), // cyan 700
];

Color sleeveColor(int index) => _sleeveColors[index % _sleeveColors.length];

class PortfolioRunScreen extends ConsumerWidget {
  const PortfolioRunScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(portfolioRunProvider);
    final notifier = ref.read(portfolioRunProvider.notifier);

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/quant/backtest'),
        ),
        title: const Text('포트폴리오 백테스트'),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: !state.isValid || state.busy ? null : () => notifier.run(),
        icon: state.busy
            ? const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
              )
            : const Icon(Icons.play_arrow_rounded),
        label: Text(state.busy ? '실행 중... (최대 30초)' : '포트폴리오 실행'),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
        children: [
          _SleevePickerCard(state: state, notifier: notifier),
          const SizedBox(height: 16),
          _ControlsCard(state: state, notifier: notifier),
          if (state.lastError != null) ...[
            const SizedBox(height: 16),
            _ErrorBanner(message: state.lastError!),
          ],
          if (state.result != null) ...[
            const SizedBox(height: 16),
            _ResultView(result: state.result!),
          ],
        ],
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.message});
  final String message;
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.redAccent.withValues(alpha: 0.1),
        border: Border.all(color: Colors.redAccent.withValues(alpha: 0.5)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: SelectableText('⚠️ $message', style: const TextStyle(color: Colors.redAccent)),
    );
  }
}

// ---------------------------------------------------------------------------
// Sleeve picker
// ---------------------------------------------------------------------------

class _SleevePickerCard extends ConsumerWidget {
  const _SleevePickerCard({required this.state, required this.notifier});
  final PortfolioRunState state;
  final PortfolioRunNotifier notifier;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final presetsAsync = ref.watch(strategyPresetsProvider);
    final sumGood = state.weightSumValid;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('🧩 슬리브 구성',
                          style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
                      Text('여러 전략을 섞어 하나의 포트폴리오로 백테스트합니다.',
                          style:
                              theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.outline)),
                    ],
                  ),
                ),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      '합계 ${(state.weightSum * 100).toStringAsFixed(0)}%',
                      style: theme.textTheme.labelMedium?.copyWith(
                        color: sumGood ? Colors.green : Colors.amber.shade800,
                        fontWeight: FontWeight.w800,
                        fontFamily: 'monospace',
                      ),
                    ),
                    IconButton(
                      tooltip: '정규화 (합계=100%)',
                      icon: const Icon(Icons.balance),
                      visualDensity: VisualDensity.compact,
                      onPressed: state.weightSum > 0 ? notifier.normalizeWeights : null,
                    ),
                  ],
                ),
              ],
            ),
            presetsAsync.when(
              data: (presets) => Column(
                children: [
                  for (var i = 0; i < state.sleeves.length; i++)
                    _SleeveRow(
                      index: i,
                      sleeve: state.sleeves[i],
                      presets: presets,
                      allSleeves: state.sleeves,
                      notifier: notifier,
                      removable: state.sleeves.length > kMinSleeves,
                    ),
                ],
              ),
              loading: () => const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: LinearProgressIndicator(),
              ),
              error: (e, _) => Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Text('전략 목록을 불러오지 못했습니다: $e',
                    style: theme.textTheme.bodySmall?.copyWith(color: Colors.redAccent)),
              ),
            ),
            const SizedBox(height: 4),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                icon: const Icon(Icons.add),
                label: Text(state.sleeves.length >= kMaxSleeves ? '최대 $kMaxSleeves개' : '슬리브 추가'),
                onPressed: state.sleeves.length >= kMaxSleeves ? null : notifier.addSleeve,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SleeveRow extends StatelessWidget {
  const _SleeveRow({
    required this.index,
    required this.sleeve,
    required this.presets,
    required this.allSleeves,
    required this.notifier,
    required this.removable,
  });
  final int index;
  final SleeveDraft sleeve;
  final List<StrategyPresetSummary> presets;
  final List<SleeveDraft> allSleeves;
  final PortfolioRunNotifier notifier;
  final bool removable;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = sleeveColor(index);
    final names = presets.map((p) => p.name).toSet();
    // Strategies already picked by *other* sleeve rows are shown but
    // disabled — same "no duplicate picks" guard as the builder's factor
    // dropdown (`_FactorRow` in `builder_screen.dart`), just applied across
    // rows instead of within one.
    final usedElsewhere = {
      for (var i = 0; i < allSleeves.length; i++)
        if (i != index) allSleeves[i].strategyName,
    };
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Container(
                width: 10,
                height: 10,
                margin: const EdgeInsets.only(right: 8),
                decoration: BoxDecoration(color: color, shape: BoxShape.circle),
              ),
              Expanded(
                child: DropdownButtonFormField<String>(
                  initialValue: sleeve.strategyName.isEmpty ? null : sleeve.strategyName,
                  isDense: true,
                  decoration: InputDecoration(labelText: '슬리브 ${index + 1} 전략', isDense: true),
                  items: [
                    for (final p in presets)
                      DropdownMenuItem<String>(
                        value: p.name,
                        enabled: p.name == sleeve.strategyName || !usedElsewhere.contains(p.name),
                        child: Text(
                          '${p.isGrouped ? '📐' : '🧮'} ${p.name}${p.isPrivate ? ' 🔒' : ''}',
                          style: const TextStyle(fontSize: 13),
                        ),
                      ),
                    // 방어: 선택된 전략이 목록에서 사라진 경우(새로고침 등)에도
                    // Dropdown의 "값이 항목과 정확히 하나 일치해야 함" 단언이
                    // 터지지 않도록 항목을 보강한다.
                    if (sleeve.strategyName.isNotEmpty && !names.contains(sleeve.strategyName))
                      DropdownMenuItem<String>(
                        value: sleeve.strategyName,
                        child: Text('${sleeve.strategyName} (목록에 없음)'),
                      ),
                  ],
                  onChanged: (v) {
                    if (v != null) notifier.setStrategyName(index, v);
                  },
                ),
              ),
              IconButton(
                tooltip: '삭제',
                icon: const Icon(Icons.remove_circle_outline),
                color: removable ? Colors.redAccent : theme.colorScheme.outlineVariant,
                onPressed: removable ? () => notifier.removeSleeve(index) : null,
              ),
            ],
          ),
          Row(
            children: [
              SizedBox(
                width: 52,
                child: Text(
                  '${(sleeve.weight * 100).toStringAsFixed(0)}%',
                  style: theme.textTheme.titleSmall
                      ?.copyWith(fontWeight: FontWeight.w700, fontFamily: 'monospace', color: color),
                ),
              ),
              Expanded(
                child: Slider(
                  value: sleeve.weight.clamp(0.0, 1.0),
                  activeColor: color,
                  divisions: 20,
                  label: '${(sleeve.weight * 100).toStringAsFixed(0)}%',
                  onChanged: (v) => notifier.setWeight(index, v),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Run controls
// ---------------------------------------------------------------------------

class _ControlsCard extends StatelessWidget {
  const _ControlsCard({required this.state, required this.notifier});
  final PortfolioRunState state;
  final PortfolioRunNotifier notifier;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('⚙️ 실행 설정',
                style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final r in BacktestRebalanceFreq.values)
                  ChoiceChip(
                    label: Text('${r.label} 리밸런싱'),
                    selected: state.rebalance == r,
                    onSelected: (_) => notifier.setRebalance(r),
                  ),
              ],
            ),
            const Divider(height: 24),
            SwitchListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              secondary: Icon(Icons.receipt_long_outlined,
                  color: state.afterTax ? theme.colorScheme.primary : theme.colorScheme.outline),
              title: const Text('세후 수익률(KR)'),
              subtitle: const Text(
                '거래세+과세 ETF 매매차익 15.4% 반영 (배당 제외)',
                style: TextStyle(fontSize: 11),
              ),
              value: state.afterTax,
              onChanged: notifier.setAfterTax,
            ),
            SwitchListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              secondary: Icon(Icons.auto_graph,
                  color: state.optimize ? theme.colorScheme.primary : theme.colorScheme.outline),
              title: const Text('최적 비중 찾기'),
              subtitle: const Text(
                '슬리브 비중을 탐색해 성과가 더 좋은 조합을 함께 제시합니다.',
                style: TextStyle(fontSize: 11),
              ),
              value: state.optimize,
              onChanged: notifier.setOptimize,
            ),
            if (state.optimize)
              Padding(
                padding: const EdgeInsets.only(left: 16),
                child: CheckboxListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  title: const Text('OOS 검증', style: TextStyle(fontSize: 13)),
                  subtitle: const Text(
                    '워크포워드 폴드로 탐색 결과를 교차검증합니다 (더 오래 걸림).',
                    style: TextStyle(fontSize: 11),
                  ),
                  value: state.oos,
                  onChanged: (v) => notifier.setOos(v ?? false),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Result view
// ---------------------------------------------------------------------------

class _ResultView extends StatelessWidget {
  const _ResultView({required this.result});
  final PortfolioRunResult result;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, c) {
        final cols = c.maxWidth >= 720 ? 4 : 2;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _CombinedMetricsCard(
              metrics: result.combinedMetrics,
              cols: cols,
              portfolioId: result.portfolioId,
            ),
            const SizedBox(height: 16),
            _AllocationCard(sleeves: result.sleeves),
            const SizedBox(height: 16),
            _SleeveBreakdownCard(sleeves: result.sleeves),
            if (!result.optimal.isEmpty) ...[
              const SizedBox(height: 16),
              _OptimalWeightsCard(optimal: result.optimal, sleeves: result.sleeves),
            ],
          ],
        );
      },
    );
  }
}

/// Combined-blend metrics — mirrors `_MetricsGrid`/`_MetricTile` from
/// `backtest_run_detail_screen.dart` (that pair is file-private, so this is
/// a deliberate visual mirror rather than a shared import), scoped to the
/// four headline tiles: CAGR/MDD/Sharpe/Sortino.
class _CombinedMetricsCard extends StatelessWidget {
  const _CombinedMetricsCard({required this.metrics, required this.cols, required this.portfolioId});
  final BacktestMetrics metrics;
  final int cols;
  final String portfolioId;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final tiles = <Widget>[
      _MetricTile(
        label: 'CAGR',
        value: '${(metrics.cagr * 100).toStringAsFixed(2)}%',
        hint: '연복리수익률 (블렌드)',
        color: metrics.cagr >= 0 ? Colors.redAccent : Colors.blueAccent,
        icon: Icons.trending_up,
        progress: (metrics.cagr.clamp(-1.0, 1.0) + 1) / 2,
      ),
      _MetricTile(
        label: 'MDD',
        value: '${(metrics.mdd * 100).toStringAsFixed(2)}%',
        hint: '최대낙폭 (블렌드)',
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
      if (metrics.sortino != null)
        _MetricTile(
          label: 'Sortino',
          value: metrics.sortino!.toStringAsFixed(2),
          hint: '하방위험 조정수익률',
          color: metrics.sortino! >= 1 ? Colors.green : Colors.amber,
          icon: Icons.shield_outlined,
          progress: (metrics.sortino!.clamp(-2.0, 4.0) + 2) / 6,
        ),
    ];
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text('📊 결합 성과',
                    style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
                const Spacer(),
                Text(portfolioId,
                    style: theme.textTheme.labelSmall
                        ?.copyWith(fontFamily: 'monospace', color: theme.colorScheme.outline)),
              ],
            ),
            const SizedBox(height: 12),
            GridView.count(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              crossAxisCount: cols,
              mainAxisSpacing: 10,
              crossAxisSpacing: 10,
              childAspectRatio: 1.4,
              children: tiles,
            ),
          ],
        ),
      ),
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
                    style: theme.textTheme.titleSmall
                        ?.copyWith(fontWeight: FontWeight.w800, color: color)),
              ],
            ),
            const Spacer(),
            Text(value,
                style:
                    theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w900, fontFamily: 'monospace')),
            const SizedBox(height: 2),
            Text(hint, style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline)),
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

/// The one visual signature of this screen: a segmented horizontal bar
/// where each sleeve's share of width == its blend weight, in that
/// sleeve's identity color, plus a matching legend row. Turns "N rows of
/// numbers" into one glanceable shape.
class _AllocationCard extends StatelessWidget {
  const _AllocationCard({required this.sleeves});
  final List<PortfolioSleeve> sleeves;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('🧬 비중 구성',
                style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
            const SizedBox(height: 12),
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: SizedBox(
                height: 22,
                child: Row(
                  children: [
                    for (var i = 0; i < sleeves.length; i++)
                      Expanded(
                        // flex must stay >=1 — a near-zero-weight sleeve
                        // still gets a visible hairline rather than
                        // vanishing from the bar entirely.
                        flex: (sleeves[i].weight * 1000).round().clamp(1, 1000),
                        child: Container(color: sleeveColor(i)),
                      ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 14,
              runSpacing: 6,
              children: [
                for (var i = 0; i < sleeves.length; i++)
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 10,
                        height: 10,
                        decoration: BoxDecoration(color: sleeveColor(i), shape: BoxShape.circle),
                      ),
                      const SizedBox(width: 6),
                      Text(sleeves[i].strategyName,
                          style: theme.textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w600)),
                      const SizedBox(width: 4),
                      Text(
                        '${(sleeves[i].weight * 100).toStringAsFixed(0)}%',
                        style: theme.textTheme.bodySmall
                            ?.copyWith(fontFamily: 'monospace', color: theme.colorScheme.outline),
                      ),
                    ],
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _SleeveBreakdownCard extends StatelessWidget {
  const _SleeveBreakdownCard({required this.sleeves});
  final List<PortfolioSleeve> sleeves;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('🧾 슬리브별 성과',
                style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
            const SizedBox(height: 12),
            Row(
              children: [
                const SizedBox(width: 18),
                Expanded(flex: 4, child: Text('전략', style: theme.textTheme.labelSmall)),
                Expanded(
                    flex: 2,
                    child: Text('비중', style: theme.textTheme.labelSmall, textAlign: TextAlign.right)),
                Expanded(
                    flex: 2,
                    child:
                        Text('CAGR', style: theme.textTheme.labelSmall, textAlign: TextAlign.right)),
                Expanded(
                    flex: 2,
                    child: Text('MDD', style: theme.textTheme.labelSmall, textAlign: TextAlign.right)),
                Expanded(
                    flex: 2,
                    child: Text('Sharpe',
                        style: theme.textTheme.labelSmall, textAlign: TextAlign.right)),
              ],
            ),
            const Divider(height: 12),
            for (var i = 0; i < sleeves.length; i++) ...[
              _SleeveBreakdownRow(index: i, sleeve: sleeves[i]),
              if (i != sleeves.length - 1)
                Divider(height: 1, color: theme.colorScheme.outlineVariant.withValues(alpha: 0.5)),
            ],
          ],
        ),
      ),
    );
  }
}

class _SleeveBreakdownRow extends StatelessWidget {
  const _SleeveBreakdownRow({required this.index, required this.sleeve});
  final int index;
  final PortfolioSleeve sleeve;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final m = sleeve.metrics;
    final cagrPct = m.cagr * 100;
    final mddPct = m.mdd * 100;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        children: [
          Container(
            width: 10,
            height: 10,
            margin: const EdgeInsets.only(right: 8),
            decoration: BoxDecoration(color: sleeveColor(index), shape: BoxShape.circle),
          ),
          Expanded(
            flex: 4,
            child: Text(
              sleeve.strategyName,
              style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          Expanded(
            flex: 2,
            child: Text(
              '${(sleeve.weight * 100).toStringAsFixed(0)}%',
              textAlign: TextAlign.right,
              style: theme.textTheme.bodyMedium?.copyWith(fontFamily: 'monospace'),
            ),
          ),
          Expanded(
            flex: 2,
            child: Text(
              '${cagrPct.toStringAsFixed(1)}%',
              textAlign: TextAlign.right,
              style: TextStyle(
                fontFamily: 'monospace',
                fontWeight: FontWeight.w700,
                color: cagrPct >= 0 ? Colors.redAccent : Colors.blueAccent,
              ),
            ),
          ),
          Expanded(
            flex: 2,
            child: Text(
              '${mddPct.toStringAsFixed(1)}%',
              textAlign: TextAlign.right,
              style: const TextStyle(fontFamily: 'monospace', color: Colors.blueAccent),
            ),
          ),
          Expanded(
            flex: 2,
            child: Text(
              m.sharpe.toStringAsFixed(2),
              textAlign: TextAlign.right,
              style: TextStyle(
                fontFamily: 'monospace',
                fontWeight: FontWeight.w700,
                color: m.sharpe >= 1 ? Colors.green : Colors.amber.shade800,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// `optimal.insample`/`optimal.oos` weight-search results, mapped back to
/// strategy names by zipping index-for-index against [sleeves] (both
/// arrays are ordered the same way the request was submitted). Ends with
/// an explicit, honest caption — an in-sample-only result is exactly the
/// kind of number that looks great and doesn't hold up, so the UI says so
/// rather than let a bare "최적" label imply otherwise.
class _OptimalWeightsCard extends StatelessWidget {
  const _OptimalWeightsCard({required this.optimal, required this.sleeves});
  final PortfolioOptimal optimal;
  final List<PortfolioSleeve> sleeves;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final names = [for (final s in sleeves) s.strategyName];
    final insample = optimal.insample;
    final oos = optimal.oos;
    return Card(
      color: theme.colorScheme.primaryContainer.withValues(alpha: 0.35),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('🎯 최적 비중',
                style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
            if (insample != null) ...[
              const SizedBox(height: 12),
              Text('인샘플 탐색', style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
              const SizedBox(height: 4),
              _WeightList(names: names, weights: insample.weights),
              const SizedBox(height: 4),
              Text(
                '목표: ${insample.objective} · 값 ${insample.value.toStringAsFixed(3)} · '
                '${insample.trials}회 탐색',
                style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline),
              ),
            ],
            if (oos != null) ...[
              const SizedBox(height: 14),
              Text('OOS 검증', style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
              const SizedBox(height: 4),
              _WeightList(names: names, weights: oos.weights),
              const SizedBox(height: 4),
              Text(
                '${oos.folds}개 폴드 평균 지표 ${oos.oosMetricMean.toStringAsFixed(3)}',
                style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline),
              ),
            ],
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: Colors.amber.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(Icons.info_outline, size: 16, color: Colors.amber.shade900),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      '인샘플은 탐색용, OOS 검증분이 채택 근거 — 과적합 주의',
                      style: theme.textTheme.bodySmall?.copyWith(color: Colors.amber.shade900),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _WeightList extends StatelessWidget {
  const _WeightList({required this.names, required this.weights});
  final List<String> names;
  final List<double> weights;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    // Defensive: zips only up to the shorter length so an optimizer weight
    // vector that (unexpectedly) doesn't match the sleeve roster length
    // can't throw a RangeError here.
    final n = names.length < weights.length ? names.length : weights.length;
    return Wrap(
      spacing: 12,
      runSpacing: 4,
      children: [
        for (var i = 0; i < n; i++)
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 8,
                height: 8,
                decoration: BoxDecoration(color: sleeveColor(i), shape: BoxShape.circle),
              ),
              const SizedBox(width: 4),
              Text(
                '${names[i]} ${(weights[i] * 100).toStringAsFixed(1)}%',
                style: theme.textTheme.bodySmall
                    ?.copyWith(fontFamily: 'monospace', fontWeight: FontWeight.w600),
              ),
            ],
          ),
      ],
    );
  }
}
