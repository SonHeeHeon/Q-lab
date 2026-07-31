/// File: app/lib/presentation/portfolio/allocation_screen.dart
///
/// 자산배분 파이 차트 — 전체(통합) / 계좌별 종목 비중 + 계좌 배분.
/// 데이터는 통합 포트폴리오 1콜(모의 제외), US 포지션은 서버 환율로 KRW 환산.
library;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../data/api/portfolio_api.dart';

final _krw = NumberFormat('#,###');

final allocationPortfolioProvider = FutureProvider<UnifiedPortfolio>(
  (ref) => ref
      .read(portfolioApiProvider)
      .getUnifiedPortfolio(BrokerFilter.all, excludePaper: true),
);

/// 'ALL' 또는 계좌 키('KIS:REAL', 'TOSS')
final allocationSelectionProvider = StateProvider<String>((_) => 'ALL');

String _accountKeyOf(UnifiedPosition p) => p.broker == BrokerType.TOSS
    ? 'TOSS'
    : 'KIS:${p.accountType?.wire ?? '?'}';

String _accountLabelOf(String key, UnifiedPortfolio portfolio) {
  if (key == 'ALL') return '전체';
  if (key == 'TOSS') return '토스(US)';
  final wire = key.split(':').last;
  for (final account in portfolio.accounts) {
    if (account.broker == BrokerType.KIS && account.accountType?.wire == wire) {
      return account.accountType?.label ?? wire;
    }
  }
  return wire;
}

class AllocationScreen extends ConsumerWidget {
  const AllocationScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(allocationPortfolioProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('자산 배분')),
      body: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('포트폴리오를 불러오지 못했습니다\n$e')),
        data: (portfolio) => _AllocationBody(portfolio: portfolio),
      ),
    );
  }
}

class _AllocationBody extends ConsumerWidget {
  const _AllocationBody({required this.portfolio});
  final UnifiedPortfolio portfolio;

  double _krwValue(UnifiedPosition p) =>
      p.isUs ? p.marketValue * (portfolio.fxRate ?? 1300.0) : p.marketValue;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selection = ref.watch(allocationSelectionProvider);
    final accountKeys = <String>[
      'ALL',
      ...{for (final p in portfolio.positions) _accountKeyOf(p)},
    ];
    final positions = selection == 'ALL'
        ? portfolio.positions
        : [
            for (final p in portfolio.positions)
              if (_accountKeyOf(p) == selection) p,
          ];

    // 종목별 KRW 평가금액 합산 (여러 계좌의 같은 종목은 합침)
    final byName = <String, double>{};
    for (final p in positions) {
      final name = p.stockName.isEmpty ? p.stockCode : p.stockName;
      byName[name] = (byName[name] ?? 0) + _krwValue(p);
    }

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Wrap(
          spacing: 8,
          children: [
            for (final key in accountKeys)
              ChoiceChip(
                label: Text(_accountLabelOf(key, portfolio)),
                selected: selection == key,
                onSelected: (_) =>
                    ref.read(allocationSelectionProvider.notifier).state = key,
              ),
          ],
        ),
        const SizedBox(height: 16),
        if (byName.isEmpty)
          const Padding(
            padding: EdgeInsets.all(32),
            child: Center(child: Text('보유 종목이 없습니다')),
          )
        else
          _PieCard(
            title: selection == 'ALL' ? '종목별 비중 (전체·원화 환산)' : '종목별 비중',
            entries: byName,
          ),
        if (selection == 'ALL') ...[
          const SizedBox(height: 16),
          _PieCard(
            title: '계좌별 배분',
            entries: {
              for (final account in portfolio.accounts)
                if (account.totalValue > 0)
                  (account.broker == BrokerType.TOSS
                      ? '토스(US)'
                      : account.accountType?.label ??
                          account.accountType?.wire ??
                          '?'): account.totalValue,
            },
          ),
        ],
      ],
    );
  }
}

class _PieCard extends StatelessWidget {
  const _PieCard({required this.title, required this.entries});
  final String title;
  final Map<String, double> entries;

  static const _maxSlices = 10;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final sorted = entries.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    final top = sorted.take(_maxSlices).toList();
    final restSum =
        sorted.skip(_maxSlices).fold<double>(0, (a, e) => a + e.value);
    final slices = [
      ...top,
      if (restSum > 0) MapEntry('기타 (${sorted.length - _maxSlices})', restSum),
    ];
    final total = slices.fold<double>(0, (a, e) => a + e.value);
    if (total <= 0) return const SizedBox.shrink();

    Color colorAt(int i) => Colors.primaries[i % Colors.primaries.length];

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title,
                style: theme.textTheme.titleSmall
                    ?.copyWith(fontWeight: FontWeight.w600)),
            const SizedBox(height: 12),
            SizedBox(
              height: 220,
              child: PieChart(
                PieChartData(
                  sectionsSpace: 2,
                  centerSpaceRadius: 44,
                  sections: [
                    for (var i = 0; i < slices.length; i++)
                      PieChartSectionData(
                        value: slices[i].value,
                        color: colorAt(i),
                        radius: 62,
                        title:
                            '${(100 * slices[i].value / total).toStringAsFixed(0)}%',
                        titleStyle: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                          color: Colors.white,
                        ),
                        showTitle: slices[i].value / total >= 0.05,
                      ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 12),
            for (var i = 0; i < slices.length; i++)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(
                  children: [
                    Container(
                      width: 10,
                      height: 10,
                      decoration: BoxDecoration(
                        color: colorAt(i),
                        shape: BoxShape.circle,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(slices[i].key,
                          style: theme.textTheme.bodySmall,
                          overflow: TextOverflow.ellipsis),
                    ),
                    Text(
                      '₩${_krw.format(slices[i].value)}  '
                      '${(100 * slices[i].value / total).toStringAsFixed(1)}%',
                      style: theme.textTheme.bodySmall
                          ?.copyWith(fontWeight: FontWeight.w600),
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
