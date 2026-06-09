/// File: app/lib/presentation/quant/insights_tab/insights_screen.dart
///
/// Quant & AI — Insights tab. See PROJECT_BLUEPRINT.md §9.7 Tab 1.
///
/// Top → bottom:
///   - Tab switcher (Insights / Backtest Lab)
///   - Heatmap placeholder (backend `/api/heatmap` arriving — Codex)
///   - LLM commentary (Markdown, top-ranked item)
///   - Top N undervalued cards (rank, code, name, score, market, sector)
library;

import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../../data/api/heatmap_api.dart';
import '../../../data/api/quant_api.dart';
import '../../../shared/widgets/empty_state.dart';
import '../../../shared/widgets/treemap.dart';
import '../../heatmap/heatmap_controller.dart';
import 'insights_controller.dart';

final _date = DateFormat('yyyy-MM-dd');

class InsightsScreen extends ConsumerWidget {
  const InsightsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncReport = ref.watch(undervaluedReportProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('퀀트 & AI'),
        bottom: const PreferredSize(
          preferredSize: Size.fromHeight(48),
          child: _TabBar(active: 'insights'),
        ),
        actions: [
          IconButton(
            tooltip: '새로고침',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(undervaluedReportProvider),
          ),
        ],
      ),
      body: asyncReport.when(
        data: (r) => _Body(report: r),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, st) => _Error(
          error: e,
          stack: st,
          onRetry: () => ref.invalidate(undervaluedReportProvider),
        ),
      ),
    );
  }
}

class _TabBar extends StatelessWidget {
  const _TabBar({required this.active});
  final String active;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        const SizedBox(width: 16),
        FilledButton.tonal(
          onPressed: active == 'insights' ? null : () => context.go('/quant'),
          child: const Text('인사이트'),
        ),
        const SizedBox(width: 8),
        TextButton(
          onPressed: () => context.go('/quant/backtest'),
          child: const Text('백테스트 랩'),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------

class _Body extends StatelessWidget {
  const _Body({required this.report});
  final UndervaluedReport report;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final items = report.items;
    final topCommentary = items.isEmpty ? null : items.first.llmCommentary;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _HeaderBar(report: report),
        const SizedBox(height: 12),
        const _MiniHeatmap(),
        const SizedBox(height: 16),
        Text('🤖 AI 코멘터리',
            style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        _LlmCommentaryCard(text: topCommentary),
        const SizedBox(height: 24),
        Text('📊 저평가 종목 Top ${items.length}',
            style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        if (items.isEmpty)
          _EmptyState()
        else
          for (final item in items.take(10)) ...[
            _ItemCard(item: item),
            const SizedBox(height: 8),
          ],
        const SizedBox(height: 24),
      ],
    );
  }
}

class _HeaderBar extends StatelessWidget {
  const _HeaderBar({required this.report});
  final UndervaluedReport report;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      color: theme.colorScheme.surfaceContainerHighest,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            const Icon(Icons.calendar_today_outlined, size: 18),
            const SizedBox(width: 6),
            Text(_date.format(report.analysisDate.toLocal()),
                style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600)),
            const Spacer(),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: theme.colorScheme.primaryContainer,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Text('전략: ${report.strategyName}',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onPrimaryContainer,
                    fontWeight: FontWeight.w600,
                  )),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Heatmap placeholder
// ---------------------------------------------------------------------------

/// Embedded mini-heatmap on the Insights tab. Re-uses the same
/// `heatmapDataProvider` as the dedicated /heatmap screen so they
/// share a single cache.
class _MiniHeatmap extends ConsumerWidget {
  const _MiniHeatmap();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final async = ref.watch(heatmapDataProvider);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Text('🗺️ 시장 히트맵',
                style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
            const Spacer(),
            TextButton.icon(
              icon: const Icon(Icons.open_in_full, size: 16),
              label: const Text('전체 보기'),
              onPressed: () => context.go('/heatmap'),
            ),
          ],
        ),
        const SizedBox(height: 4),
        SizedBox(
          height: 220,
          child: Card(
            margin: EdgeInsets.zero,
            color: theme.colorScheme.surfaceContainerHighest,
            child: ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: async.when(
                data: (data) {
                  final stocks = data.stocks;
                  if (stocks.isEmpty) {
                    return Center(
                      child: Text('히트맵 데이터 없음', style: theme.textTheme.bodySmall),
                    );
                  }
                  return Treemap<HeatmapNode>(
                    items: [
                      for (final n in stocks)
                        TreemapItem<HeatmapNode>(
                          value: n,
                          size: n.size,
                          colorValue: n.colorValue,
                        ),
                    ],
                    labelBuilder: (n) => n.stockName ?? n.stockCode ?? n.label,
                    minLabelArea: 80 * 40,
                    onCellTap: (_) => context.go('/heatmap'),
                  );
                },
                loading: () => const Center(child: CircularProgressIndicator()),
                error: (e, _) => Center(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Text('히트맵 로드 실패: $e',
                        style: theme.textTheme.bodySmall, textAlign: TextAlign.center),
                  ),
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// LLM commentary card (Markdown)
// ---------------------------------------------------------------------------

class _LlmCommentaryCard extends StatelessWidget {
  const _LlmCommentaryCard({required this.text});
  final String? text;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (text == null || text!.trim().isEmpty) {
      return Card(
        color: theme.colorScheme.surfaceContainerHighest,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Text(
            '오늘 생성된 LLM 코멘터리가 없습니다.',
            style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.outline),
          ),
        ),
      );
    }
    return Card(
      color: theme.colorScheme.surfaceContainerHighest,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: MarkdownBody(
          data: text!,
          selectable: true,
          styleSheet: MarkdownStyleSheet.fromTheme(theme).copyWith(
            p: theme.textTheme.bodyMedium,
            code: theme.textTheme.bodySmall?.copyWith(
              fontFamily: 'monospace',
              backgroundColor: theme.colorScheme.surface,
            ),
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Item card
// ---------------------------------------------------------------------------

class _ItemCard extends StatelessWidget {
  const _ItemCard({required this.item});
  final UndervaluedItem item;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            _RankBadge(rank: item.rank),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(item.name,
                      style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
                  const SizedBox(height: 2),
                  Wrap(
                    spacing: 6,
                    runSpacing: 2,
                    children: [
                      _Chip(label: item.stockCode, mono: true),
                      if (item.market.isNotEmpty) _Chip(label: item.market),
                      if (item.sector != null) _Chip(label: item.sector!),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(width: 12),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text('SCORE', style: theme.textTheme.labelSmall),
                Text(item.score.toStringAsFixed(3),
                    style: theme.textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w700,
                      color: item.score >= 0
                          ? theme.colorScheme.primary
                          : theme.colorScheme.error,
                    )),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _RankBadge extends StatelessWidget {
  const _RankBadge({required this.rank});
  final int rank;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = switch (rank) {
      1 => Colors.amber,
      2 => const Color(0xFFC0C0C0),
      3 => const Color(0xFFCD7F32),
      _ => theme.colorScheme.outline,
    };
    return Container(
      width: 36,
      height: 36,
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.18),
        shape: BoxShape.circle,
        border: Border.all(color: color, width: 2),
      ),
      alignment: Alignment.center,
      child: Text('$rank',
          style: TextStyle(color: color, fontWeight: FontWeight.w800)),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.label, this.mono = false});
  final String label;
  final bool mono;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: theme.colorScheme.surface,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        label,
        style: theme.textTheme.labelSmall?.copyWith(
          fontFamily: mono ? 'monospace' : null,
          color: theme.colorScheme.onSurface,
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------

class _EmptyState extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return const EmptyState(
      icon: Icons.inbox_outlined,
      title: '해당 날짜의 분석 결과가 없습니다',
      subtitle: '백엔드의 nightly 배치가 KOSPI200 점수를 산출한 뒤 여기에 표시됩니다.',
    );
  }
}

class _Error extends StatelessWidget {
  const _Error({required this.error, required this.stack, required this.onRetry});
  final Object error;
  final StackTrace stack;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Icon(Icons.error_outline, size: 48),
          const SizedBox(height: 8),
          const Text('퀀트 데이터를 불러오지 못했습니다.', textAlign: TextAlign.center),
          const SizedBox(height: 8),
          SelectableText('$error', textAlign: TextAlign.center),
          const SizedBox(height: 12),
          ExpansionTile(
            title: const Text('Stack trace'),
            childrenPadding: const EdgeInsets.all(12),
            children: [
              SelectableText(stack.toString(),
                  style: const TextStyle(fontFamily: 'monospace', fontSize: 11)),
            ],
          ),
          const SizedBox(height: 12),
          FilledButton(onPressed: onRetry, child: const Text('다시 시도')),
        ],
      ),
    );
  }
}
