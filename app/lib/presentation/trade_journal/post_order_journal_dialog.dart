/// File: app/lib/presentation/trade_journal/post_order_journal_dialog.dart
///
/// Immediately after a BUY/SELL order succeeds, this bottom sheet pops up
/// to capture: (1) the entry reason, (2) which investment principles apply.
/// Posts to POST /api/trade-journal so the LLM analyzer can run in the
/// background. User can skip with "나중에 작성".
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/portfolio_api.dart';
import '../../data/api/trade_journal_api.dart';
import '../principles/principles_controller.dart';
import '../trade_journal/trade_journal_controller.dart';

Future<void> showPostOrderJournalDialog(
  BuildContext context,
  WidgetRef ref, {
  required String stockCode,
  required String stockName,
  required OrderDirection side,
  required int qty,
  required int tradeId,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => _PostOrderJournalSheet(
      stockCode: stockCode,
      stockName: stockName,
      side: side,
      qty: qty,
      tradeId: tradeId,
    ),
  );
}

class _PostOrderJournalSheet extends ConsumerStatefulWidget {
  const _PostOrderJournalSheet({
    required this.stockCode,
    required this.stockName,
    required this.side,
    required this.qty,
    required this.tradeId,
  });

  final String stockCode;
  final String stockName;
  final OrderDirection side;
  final int qty;
  final int tradeId;

  @override
  ConsumerState<_PostOrderJournalSheet> createState() => _PostOrderJournalSheetState();
}

class _PostOrderJournalSheetState extends ConsumerState<_PostOrderJournalSheet> {
  final _reasonCtrl = TextEditingController();
  final Set<int> _selectedIds = {};
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _reasonCtrl.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final reason = _reasonCtrl.text.trim();
    if (reason.isEmpty) {
      setState(() => _error = '진입 사유를 작성해주세요.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(tradeJournalApiProvider).create(
            tradeId: widget.tradeId,
            reason: reason,
            appliedPrincipleIds: _selectedIds.toList(),
          );
      ref.invalidate(missingTradesProvider);
      ref.invalidate(journalListProvider);
      if (!mounted) return;
      Navigator.of(context).pop();
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('📓 매매일지 저장 완료 — AI 분석이 곧 시작됩니다')),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = '$e';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isBuy = widget.side == OrderDirection.buy;
    final sideColor = isBuy ? Colors.redAccent : Colors.blueAccent;
    final principles = ref.watch(principlesProvider);

    return Padding(
      padding: EdgeInsets.fromLTRB(
        20, 0, 20, MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // ── header ──────────────────────────────────────────────────────
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: sideColor.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: sideColor.withValues(alpha: 0.5)),
                ),
                child: Text(
                  isBuy ? '매수' : '매도',
                  style: TextStyle(
                    color: sideColor,
                    fontWeight: FontWeight.w700,
                    fontSize: 13,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${widget.stockName}  ·  ${widget.qty}주',
                      style: theme.textTheme.titleMedium
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '진입 사유를 기록하면 AI가 원칙 준수 여부를 분석합니다.',
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: theme.colorScheme.outline),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),

          // ── reason field ─────────────────────────────────────────────────
          TextField(
            controller: _reasonCtrl,
            maxLines: 4,
            minLines: 3,
            autofocus: true,
            decoration: InputDecoration(
              labelText: '진입 사유 (필수)',
              hintText: '예: PER 8x 이하 + 분기 영업이익 +30% YoY. 박스권 하단 진입.',
              border: const OutlineInputBorder(),
              errorText: _error,
            ),
            onChanged: (_) {
              if (_error != null) setState(() => _error = null);
            },
          ),
          const SizedBox(height: 16),

          // ── principle chips ──────────────────────────────────────────────
          Text('적용한 투자 원칙 (선택)', style: theme.textTheme.labelMedium),
          const SizedBox(height: 8),
          principles.when(
            data: (list) {
              if (list.isEmpty) {
                return Text(
                  '등록된 투자 원칙 없음 — 원칙 화면에서 먼저 추가하세요.',
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.outline),
                );
              }
              return Wrap(
                spacing: 8,
                runSpacing: 4,
                children: [
                  for (final p in list)
                    FilterChip(
                      label: Text(p.title, style: const TextStyle(fontSize: 12)),
                      selected: _selectedIds.contains(p.id),
                      onSelected: (v) => setState(() {
                        if (v) {
                          _selectedIds.add(p.id);
                        } else {
                          _selectedIds.remove(p.id);
                        }
                      }),
                    ),
                ],
              );
            },
            loading: () => const SizedBox(
              height: 36,
              child: LinearProgressIndicator(),
            ),
            error: (_, __) => Text(
              '원칙 목록 로드 실패 — 나중에 일지 편집에서 추가할 수 있습니다.',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.outline),
            ),
          ),
          const SizedBox(height: 20),

          // ── action buttons ───────────────────────────────────────────────
          Row(
            children: [
              TextButton(
                onPressed: _busy ? null : () => Navigator.of(context).pop(),
                child: const Text('나중에 작성'),
              ),
              const Spacer(),
              FilledButton.icon(
                onPressed: _busy ? null : _save,
                icon: _busy
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : const Icon(Icons.save_outlined, size: 18),
                label: const Text('저장'),
                style: FilledButton.styleFrom(backgroundColor: sideColor),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
