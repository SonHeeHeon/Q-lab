/// File: app/lib/presentation/proposals/us_advisory_screen.dart
///
/// "US 자문" — 미국 종목 퀀트 방정식(us_value/us_momentum/us_multifactor)이 뽑은
/// 오늘의 목표 포트폴리오를 Toss 보유와 비교해 BUY/HOLD/SELL로 제시한다.
/// ⚠️ 자문 전용: Toss 라이브 주문 미연동 → 실주문/승인 없음(참고용 랭킹).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/proposals_api.dart';
import '../../domain/entities/us_advisory.dart';

/// 한국 관례: 매수=빨강, 매도=파랑, 보유=회색.
const _buyColor = Colors.redAccent;
const _sellColor = Colors.blueAccent;

/// 첫 항목(us_stock_v1)은 공개 기본 방정식 — 오픈소스 클론에서도 항상 동작한다.
/// 나머지는 private/ 전용 튜닝판이라 파일이 없으면 404 안내가 뜬다.
const usStrategies = <String, String>{
  'us_stock_v1': '기본(멀티팩터)',
  'us_value': '밸류(장기 강건)',
  'us_momentum': '모멘텀(단기 공격)',
  'us_multifactor': '멀티팩터(올웨더)',
};

final usStrategyProvider = StateProvider<String>((ref) => 'us_stock_v1');

final usAdvisoryProvider =
    FutureProvider.autoDispose<UsAdvisoryResult>((ref) async {
  final strategy = ref.watch(usStrategyProvider);
  return ref.read(proposalsApiProvider).usAdvisory(strategy: strategy);
});

class UsAdvisoryScreen extends ConsumerWidget {
  const UsAdvisoryScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final strategy = ref.watch(usStrategyProvider);
    final async = ref.watch(usAdvisoryProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('US 자문'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(usAdvisoryProvider),
          ),
        ],
      ),
      body: Column(
        children: [
          const _AdvisoryBanner(),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: Row(
              children: [
                const Text('전략 '),
                const SizedBox(width: 8),
                DropdownButton<String>(
                  value: strategy,
                  items: [
                    for (final e in usStrategies.entries)
                      DropdownMenuItem(value: e.key, child: Text(e.value)),
                  ],
                  onChanged: (v) {
                    if (v != null) {
                      ref.read(usStrategyProvider.notifier).state = v;
                    }
                  },
                ),
              ],
            ),
          ),
          Expanded(
            child: async.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => Center(child: Text('불러오기 실패: $e')),
              data: (r) => RefreshIndicator(
                onRefresh: () async => ref.invalidate(usAdvisoryProvider),
                child: _AdvisoryList(result: r),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _AdvisoryBanner extends StatelessWidget {
  const _AdvisoryBanner();
  @override
  Widget build(BuildContext context) => Container(
        width: double.infinity,
        color: Colors.amber.withValues(alpha: 0.18),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: const Text(
          '⚠️ 자문 전용 — Toss 라이브 주문 미연동이라 실주문/승인은 없습니다. '
          '참고용 랭킹입니다.',
          style: TextStyle(fontSize: 12),
        ),
      );
}

class _AdvisoryList extends StatelessWidget {
  const _AdvisoryList({required this.result});
  final UsAdvisoryResult result;

  @override
  Widget build(BuildContext context) {
    final r = result;
    return ListView(
      padding: const EdgeInsets.only(bottom: 24),
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          child: Text(
            '기준일 ${r.asOf} · ${r.universe} 상위 ${r.targetN}종목 · '
            'Toss보유 ${r.tossConfigured ? "반영" : "미연동"}',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
        if (r.buys.isNotEmpty) _section('신규 매수 (BUY)', r.buys, _buyColor),
        if (r.holds.isNotEmpty) _section('보유 유지 (HOLD)', r.holds, Colors.grey),
        if (r.sells.isNotEmpty) _section('목표 이탈 (SELL)', r.sells, _sellColor),
      ],
    );
  }

  Widget _section(String title, List<UsAdvisoryItem> items, Color color) =>
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
            child: Text(title,
                style: TextStyle(fontWeight: FontWeight.bold, color: color)),
          ),
          for (final i in items) _AdvisoryTile(item: i, color: color),
        ],
      );
}

class _AdvisoryTile extends StatelessWidget {
  const _AdvisoryTile({required this.item, required this.color});
  final UsAdvisoryItem item;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      dense: true,
      leading: _UsBadge(action: item.action, color: color),
      title: Text(item.ticker,
          style: const TextStyle(fontWeight: FontWeight.w600)),
      subtitle: Text(item.reason),
      trailing: item.action == 'SELL'
          ? Text('보유 ${item.heldQty}')
          : Text('목표 ${(item.targetWeight * 100).toStringAsFixed(1)}%'),
    );
  }
}

class _UsBadge extends StatelessWidget {
  const _UsBadge({required this.action, required this.color});
  final String action;
  final Color color;
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.15),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: color.withValues(alpha: 0.5)),
        ),
        child: Text('🇺🇸 $action',
            style: TextStyle(
                fontSize: 11, color: color, fontWeight: FontWeight.bold)),
      );
}
