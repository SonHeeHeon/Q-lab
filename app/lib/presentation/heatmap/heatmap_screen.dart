/// File: app/lib/presentation/heatmap/heatmap_screen.dart
///
/// Market Heatmap — see PROJECT_BLUEPRINT.md §9.6.
/// Squarified treemap with cell-size = market_cap and cell-color =
/// pct_change (red up / blue down — Korean convention).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../data/api/heatmap_api.dart';
import '../../shared/widgets/treemap.dart';
import 'heatmap_controller.dart';

final _date = DateFormat('yyyy-MM-dd');
final _krw = NumberFormat('#,##0');

class HeatmapScreen extends ConsumerWidget {
  const HeatmapScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncData = ref.watch(heatmapDataProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('시장 히트맵'),
        actions: [
          IconButton(
            tooltip: '새로고침',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(heatmapDataProvider),
          ),
        ],
      ),
      body: Column(
        children: [
          const _Toolbar(),
          const Divider(height: 1),
          Expanded(
            child: asyncData.when(
              data: (d) => _Body(data: d),
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, st) => _Error(
                error: e,
                stack: st,
                onRetry: () => ref.invalidate(heatmapDataProvider),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Toolbar extends ConsumerWidget {
  const _Toolbar();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final market = ref.watch(heatmapMarketProvider);
    final groupBy = ref.watch(heatmapGroupByProvider);
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Wrap(
        spacing: 12,
        runSpacing: 8,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          SegmentedButton<HeatmapMarket>(
            segments: const [
              ButtonSegment(value: HeatmapMarket.kospi, label: Text('KOSPI')),
              ButtonSegment(value: HeatmapMarket.kosdaq, label: Text('KOSDAQ')),
            ],
            selected: {market},
            onSelectionChanged: (s) =>
                ref.read(heatmapMarketProvider.notifier).state = s.first,
          ),
          SegmentedButton<HeatmapGroupBy>(
            segments: const [
              ButtonSegment(value: HeatmapGroupBy.sector, label: Text('섹터')),
              ButtonSegment(value: HeatmapGroupBy.industry, label: Text('산업')),
            ],
            selected: {groupBy},
            onSelectionChanged: (s) =>
                ref.read(heatmapGroupByProvider.notifier).state = s.first,
          ),
          const _Legend(),
        ],
      ),
    );
  }
}

class _Legend extends StatelessWidget {
  const _Legend();
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (final pct in const [-4.0, -2.0, 0.0, 2.0, 4.0])
          Container(
            width: 18,
            height: 18,
            margin: const EdgeInsets.symmetric(horizontal: 2),
            color: colorForChangePct(pct),
          ),
        const SizedBox(width: 6),
        Text('-4% → +4%', style: theme.textTheme.bodySmall),
      ],
    );
  }
}

class _Body extends StatelessWidget {
  const _Body({required this.data});
  final HeatmapResponse data;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final stocks = data.stocks;
    if (stocks.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text('히트맵 데이터가 없습니다.', style: theme.textTheme.bodyMedium),
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
          child: Text(
            '${data.market} · ${data.groupBy} · '
            '${data.asOf == null ? "-" : _date.format(data.asOf!.toLocal())} · '
            '${stocks.length}종목',
            style: theme.textTheme.bodySmall,
          ),
        ),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.all(8),
            child: Treemap<HeatmapNode>(
              items: [
                for (final n in stocks)
                  TreemapItem<HeatmapNode>(
                    value: n,
                    size: n.size,
                    colorValue: n.colorValue,
                  ),
              ],
              labelBuilder: (n) => n.stockName ?? n.stockCode ?? n.label,
              onCellTap: (n) => _showStockDetailSheet(context, n),
            ),
          ),
        ),
      ],
    );
  }
}

void _showStockDetailSheet(BuildContext context, HeatmapNode node) {
  showModalBottomSheet(
    context: context,
    showDragHandle: true,
    builder: (_) {
      final theme = Theme.of(context);
      final mc = node.marketCap;
      final close = node.close;
      final vol = node.volume;
      return Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: colorForChangePct(node.colorValue),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    '${node.colorValue >= 0 ? '+' : ''}${node.colorValue.toStringAsFixed(2)}%',
                    style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    node.stockName ?? node.label,
                    style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(node.stockCode ?? '', style: theme.textTheme.bodySmall),
            const SizedBox(height: 16),
            if (close != null)
              _KV(label: '종가', value: '₩${_krw.format(close)}'),
            if (mc != null) _KV(label: '시가총액', value: '₩${_krw.format(mc)}'),
            if (vol != null) _KV(label: '거래량', value: _krw.format(vol)),
            if (node.sector != null) _KV(label: '섹터', value: node.sector!),
            const SizedBox(height: 16),
          ],
        ),
      );
    },
  );
}

class _KV extends StatelessWidget {
  const _KV({required this.label, required this.value});
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          SizedBox(width: 80, child: Text(label, style: theme.textTheme.bodySmall)),
          Text(value, style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
        ],
      ),
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
          SelectableText('$error', textAlign: TextAlign.center),
          const SizedBox(height: 12),
          ExpansionTile(
            title: const Text('Stack trace'),
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
