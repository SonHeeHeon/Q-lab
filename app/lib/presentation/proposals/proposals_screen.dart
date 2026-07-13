/// File: app/lib/presentation/proposals/proposals_screen.dart
///
/// "오늘의 제안" — approval-based semi-auto trading (PROJECT_BLUEPRINT.md §4.2).
/// The backend proposes orders daily from the promoted equation + validated
/// intra-period rules; the user approves/rejects each here. Approve routes
/// through the SAME broker safety gateway as manual orders — a kill-switch /
/// daily-loss block returns 403 and the card flips to 실패.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../data/api/api_client.dart' show ApiError;
import '../../data/api/proposals_api.dart';
import '../../domain/entities/proposal.dart';
import '../../shared/widgets/empty_state.dart';
import 'proposals_controller.dart';

final _krw = NumberFormat('#,##0');
final _dateTime = DateFormat('MM-dd HH:mm');

/// 한국 관례: 매수=빨강, 매도=파랑.
const _buyColor = Colors.redAccent;
const _sellColor = Colors.blueAccent;

class ProposalsScreen extends ConsumerStatefulWidget {
  const ProposalsScreen({super.key});

  @override
  ConsumerState<ProposalsScreen> createState() => _ProposalsScreenState();
}

class _ProposalsScreenState extends ConsumerState<ProposalsScreen> {
  final Set<int> _busy = {};
  bool _batchBusy = false;

  Future<void> _approve(Proposal p) async {
    if (_busy.contains(p.id)) return;
    setState(() => _busy.add(p.id));
    try {
      await ref.read(proposalsApiProvider).approve(p.id);
      _toast('승인 → 주문 제출: ${p.stockCode}');
      ref.invalidate(allProposalsProvider);
    } on ApiError catch (e) {
      _toast(e.code == 'ORDER_BLOCKED'
          ? '차단됨: ${e.message}'
          : '승인 실패: ${e.message}');
      ref.invalidate(allProposalsProvider);
    } catch (e) {
      _toast('승인 실패: $e');
    } finally {
      if (mounted) setState(() => _busy.remove(p.id));
    }
  }

  Future<void> _reject(Proposal p) async {
    if (_busy.contains(p.id)) return;
    setState(() => _busy.add(p.id));
    try {
      await ref.read(proposalsApiProvider).reject(p.id);
      ref.invalidate(allProposalsProvider);
    } catch (e) {
      _toast('거절 실패: $e');
    } finally {
      if (mounted) setState(() => _busy.remove(p.id));
    }
  }

  Future<void> _approveBatch(String batchId, List<Proposal> pending) async {
    if (_batchBusy) return;
    final total = pending.fold<double>(
        0, (s, p) => s + (p.estimatedNotional ?? 0));
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('일괄 승인'),
        content: Text(
          '${pending.length}건을 모두 승인하고 주문을 제출합니다.\n'
          '예상 총액 약 ${_krw.format(total)}원 (매도 우선 실행).\n'
          '킬스위치·일일손실 한도에 걸리는 건은 자동 차단됩니다.',
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('취소')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('일괄 승인')),
        ],
      ),
    );
    if (ok != true) return;
    setState(() => _batchBusy = true);
    try {
      final r = await ref.read(proposalsApiProvider).approveBatch(batchId);
      _toast('제출 ${r['submitted'] ?? 0} · 차단 ${r['blocked'] ?? 0} · '
          '실패 ${r['failed'] ?? 0}');
      ref.invalidate(allProposalsProvider);
    } catch (e) {
      _toast('일괄 승인 실패: $e');
    } finally {
      if (mounted) setState(() => _batchBusy = false);
    }
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(msg)));
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(allProposalsProvider);
    final filter = ref.watch(proposalFilterProvider);
    final items = ref.watch(filteredProposalsProvider);
    final pendingCount = ref.watch(pendingProposalCountProvider);

    // Batch id of the current pending set (all share one daily batch).
    final pending =
        items.where((p) => p.status == ProposalStatus.proposed).toList();
    final batchId = pending.isNotEmpty ? pending.first.batchId : null;

    return Scaffold(
      appBar: AppBar(
        title: const Text('오늘의 제안'),
        actions: [
          IconButton(
            tooltip: '새로고침',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(allProposalsProvider),
          ),
        ],
      ),
      floatingActionButton: (batchId != null && filter != ProposalFilter.history)
          ? FloatingActionButton.extended(
              icon: _batchBusy
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.done_all),
              label: Text('일괄 승인 ($pendingCount)'),
              onPressed:
                  _batchBusy ? null : () => _approveBatch(batchId, pending),
            )
          : null,
      body: Column(
        children: [
          _FilterBar(filter: filter, pendingCount: pendingCount),
          Expanded(
            child: async.when(
              data: (_) => items.isEmpty
                  ? _emptyFor(filter)
                  : RefreshIndicator(
                      onRefresh: () async =>
                          ref.invalidate(allProposalsProvider),
                      child: ListView.builder(
                        padding: const EdgeInsets.fromLTRB(12, 8, 12, 96),
                        itemCount: items.length,
                        itemBuilder: (_, i) => _ProposalCard(
                          proposal: items[i],
                          busy: _busy.contains(items[i].id),
                          onApprove: () => _approve(items[i]),
                          onReject: () => _reject(items[i]),
                        ),
                      ),
                    ),
              loading: () =>
                  const Center(child: CircularProgressIndicator()),
              error: (e, _) => _emptyError(e),
            ),
          ),
        ],
      ),
    );
  }

  Widget _emptyFor(ProposalFilter filter) => EmptyState(
        icon: Icons.inbox_outlined,
        title: filter == ProposalFilter.pending
            ? '대기 중인 제안이 없습니다'
            : '제안이 없습니다',
        subtitle: '매 영업일 장 마감 후 방정식이 제안을 생성합니다.',
      );

  Widget _emptyError(Object e) => EmptyState(
        icon: Icons.error_outline,
        title: '제안을 불러오지 못했습니다',
        subtitle: '$e',
        action: FilledButton.tonal(
          onPressed: () => ref.invalidate(allProposalsProvider),
          child: const Text('다시 시도'),
        ),
      );
}

class _FilterBar extends ConsumerWidget {
  const _FilterBar({required this.filter, required this.pendingCount});
  final ProposalFilter filter;
  final int pendingCount;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
      child: Row(
        children: [
          for (final f in ProposalFilter.values)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(
                label: Text(switch (f) {
                  ProposalFilter.pending => '대기 ($pendingCount)',
                  ProposalFilter.all => '전체',
                  ProposalFilter.history => '처리됨',
                }),
                selected: filter == f,
                onSelected: (_) =>
                    ref.read(proposalFilterProvider.notifier).state = f,
              ),
            ),
        ],
      ),
    );
  }
}

class _ProposalCard extends StatelessWidget {
  const _ProposalCard({
    required this.proposal,
    required this.busy,
    required this.onApprove,
    required this.onReject,
  });

  final Proposal proposal;
  final bool busy;
  final VoidCallback onApprove;
  final VoidCallback onReject;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final p = proposal;
    final sideColor = p.isBuy ? _buyColor : _sellColor;
    final actionable = p.status.isActionable;

    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                _Badge(
                    text: p.isBuy ? '매수' : '매도',
                    color: sideColor),
                const SizedBox(width: 8),
                Text(p.stockCode,
                    style: theme.textTheme.titleMedium
                        ?.copyWith(fontWeight: FontWeight.bold)),
                const SizedBox(width: 6),
                _MarketTag(market: p.market, account: p.accountType),
                const Spacer(),
                if (!actionable) _StatusChip(status: p.status),
              ],
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 6,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                _ReasonChip(label: p.ruleLabel, color: sideColor),
                Text('${_krw.format(p.qty)}주',
                    style: theme.textTheme.bodyMedium),
                if (p.limitPrice != null)
                  Text('· 지정가 ${_krw.format(p.limitPrice)}원',
                      style: theme.textTheme.bodyMedium),
                if (p.estimatedNotional != null)
                  Text('· 약 ${_krw.format(p.estimatedNotional)}원',
                      style: theme.textTheme.bodyMedium
                          ?.copyWith(color: theme.colorScheme.outline)),
              ],
            ),
            if ((p.reason['replaces'] as String?)?.isNotEmpty ?? false) ...[
              const SizedBox(height: 4),
              Text('교체 대상: ${p.reason['replaces']}',
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.outline)),
            ],
            if (actionable) ...[
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: busy ? null : onReject,
                      child: const Text('거절'),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: FilledButton(
                      onPressed: busy ? null : onApprove,
                      child: busy
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child:
                                  CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Text('승인'),
                    ),
                  ),
                ],
              ),
            ] else ...[
              const SizedBox(height: 6),
              Text(
                p.tradeId != null
                    ? '체결 연동 #${p.tradeId} · ${_dateTime.format(p.createdAt)}'
                    : _dateTime.format(p.createdAt),
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.outline),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  const _Badge({required this.text, required this.color});
  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.15),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Text(text,
            style: TextStyle(
                color: color, fontWeight: FontWeight.bold, fontSize: 12)),
      );
}

class _ReasonChip extends StatelessWidget {
  const _ReasonChip({required this.label, required this.color});
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(
          border: Border.all(color: color.withValues(alpha: 0.5)),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Text(label, style: TextStyle(color: color, fontSize: 12)),
      );
}

class _MarketTag extends StatelessWidget {
  const _MarketTag({required this.market, required this.account});
  final String market;
  final String account;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final label = '${market == 'US' ? '미장' : '국장'} · $account';
    return Text(label,
        style: theme.textTheme.bodySmall
            ?.copyWith(color: theme.colorScheme.outline));
  }
}

class _StatusChip extends StatelessWidget {
  const _StatusChip({required this.status});
  final ProposalStatus status;

  @override
  Widget build(BuildContext context) {
    final color = switch (status) {
      ProposalStatus.submitted || ProposalStatus.filled => Colors.green,
      ProposalStatus.rejected || ProposalStatus.expired => Colors.grey,
      ProposalStatus.failed => Colors.orange,
      _ => Theme.of(context).colorScheme.primary,
    };
    return _ReasonChip(label: status.label, color: color);
  }
}
