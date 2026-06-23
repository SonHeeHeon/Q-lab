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
import 'session_badge.dart';

final _date = DateFormat('yyyy-MM-dd');
final _time = DateFormat('HH:mm:ss');
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
            tooltip: '새로고침 (강제 갱신)',
            icon: const Icon(Icons.refresh),
            onPressed: () =>
                ref.read(heatmapDataProvider.notifier).refresh(force: true),
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
        _MetaBar(data: data, stockCount: stocks.length),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.all(8),
            child: Treemap<HeatmapNode>(
              animate: true,
              keyOf: (n) => n.id,
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

/// Meta header: separates 가격 기준일 (as_of) from 조회 시각 (served_at)
/// and surfaces price_basis / source / warning as badges.
class _MetaBar extends StatelessWidget {
  const _MetaBar({required this.data, required this.stockCount});
  final HeatmapResponse data;
  final int stockCount;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '${data.market} · ${data.groupBy} · $stockCount종목',
                  style: theme.textTheme.bodySmall,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              const SizedBox(width: 8),
              SessionBadge(response: data),
            ],
          ),
          const SizedBox(height: 6),
          Wrap(
            spacing: 6,
            runSpacing: 4,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              _MetaChip(
                icon: Icons.event_outlined,
                label: '가격 기준일 '
                    '${data.asOf == null ? "-" : _date.format(data.asOf!.toLocal())}',
              ),
              _MetaChip(
                icon: Icons.schedule_outlined,
                label: '조회 시각 '
                    '${data.servedAt == null ? "-" : _time.format(data.servedAt!.toLocal())}',
              ),
              if (data.priceBasis != null)
                _MetaChip(
                  icon: Icons.price_change_outlined,
                  label: _priceBasisLabel(data.priceBasis!),
                ),
              if (data.source != null)
                _MetaChip(icon: Icons.dns_outlined, label: data.source!),
            ],
          ),
          if (data.warning != null) ...[
            const SizedBox(height: 6),
            _WarningBadge(text: data.warning!),
          ],
        ],
      ),
    );
  }
}

String _priceBasisLabel(String basis) {
  switch (basis.toUpperCase()) {
    case 'DB_CLOSE':
      return '종가 기준';
    case 'LIVE':
    case 'SNAPSHOT':
      return '실시간';
    default:
      return basis;
  }
}

class _MetaChip extends StatelessWidget {
  const _MetaChip({required this.icon, required this.label});
  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 13, color: theme.colorScheme.outline),
          const SizedBox(width: 4),
          Text(label, style: theme.textTheme.labelSmall),
        ],
      ),
    );
  }
}

class _WarningBadge extends StatelessWidget {
  const _WarningBadge({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final c = theme.colorScheme.error;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: c.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: c.withValues(alpha: 0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.warning_amber_rounded, size: 14, color: c),
          const SizedBox(width: 6),
          Flexible(
            child: Text(text,
                style: theme.textTheme.labelSmall?.copyWith(color: c)),
          ),
        ],
      ),
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
