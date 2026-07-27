/// File: app/lib/presentation/trade_journal/trade_journal_screen.dart
///
/// Trade Journal — see PROJECT_BLUEPRINT.md §9.4.
/// Two tabs:
///   1. 미작성   — completed trades that don't yet have a journal entry.
///                 Tap → write `reason` → POST /api/trade-journal
///   2. 전체     — all existing journals. Tap → edit reason / add
///                 post_review → PATCH /api/trade-journal/{id}
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/theme.dart';
import '../../data/api/trade_journal_api.dart';
import '../../domain/entities/account.dart';
import '../../shared/widgets/empty_state.dart';
import 'trade_journal_controller.dart';

final _dateTime = DateFormat('MM-dd HH:mm');
final _krw = NumberFormat('#,##0');

/// Toss brand teal — matches the same color used on the portfolio screen
/// and stock detail's broker chip, so a Toss trade reads consistently
/// across the app.
const _tossColor = Color(0xFF3182F6);

class TradeJournalScreen extends ConsumerWidget {
  const TradeJournalScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('매매일지'),
          actions: [
            IconButton(
              tooltip: '새로고침',
              icon: const Icon(Icons.refresh),
              onPressed: () {
                ref.invalidate(missingTradesProvider);
                ref.invalidate(journalListProvider);
              },
            ),
          ],
        ),
        body: const Column(
          children: [
            _AccountFilterBar(),
            Divider(height: 1),
            TabBar(
              tabs: [
                Tab(text: '🚨 미작성'),
                Tab(text: '📓 전체'),
              ],
            ),
            Expanded(
              child: TabBarView(
                children: [
                  _MissingTab(),
                  _AllTab(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Account filter bar — 전체 / 모의 / 실전 / ISA / 토스 (mirrors portfolio's
// _BrokerFilterBar). Filters both tabs client-side; Toss trades (no KIS
// account split) are matched by broker alone via the 토스 chip.
// ---------------------------------------------------------------------------

const _kisFilters = [JournalFilter.paper, JournalFilter.real, JournalFilter.isa];

class _AccountFilterBar extends ConsumerWidget {
  const _AccountFilterBar();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final selected = ref.watch(journalAccountFilterProvider);
    return Padding(
      padding: const EdgeInsets.only(top: 8, bottom: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Row(
              children: [
                ChoiceChip(
                  label: const Text('전체'),
                  selected: selected == JournalFilter.all,
                  onSelected: (_) =>
                      ref.read(journalAccountFilterProvider.notifier).state =
                          JournalFilter.all,
                ),
                for (final f in _kisFilters) ...[
                  const SizedBox(width: 8),
                  ChoiceChip(
                    avatar: CircleAvatar(
                      backgroundColor: _accountColor(context, f.kisAccount!),
                      radius: 8,
                    ),
                    label: Text(f.label),
                    selected: selected == f,
                    onSelected: (_) =>
                        ref.read(journalAccountFilterProvider.notifier).state = f,
                  ),
                ],
                const SizedBox(width: 8),
                ChoiceChip(
                  avatar: const CircleAvatar(backgroundColor: _tossColor, radius: 8),
                  label: Text(JournalFilter.toss.label),
                  selected: selected == JournalFilter.toss,
                  onSelected: (_) =>
                      ref.read(journalAccountFilterProvider.notifier).state =
                          JournalFilter.toss,
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 6, 16, 0),
            child: Text(
              'KIS·토스 체결 거래가 모두 기록됩니다',
              style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline),
            ),
          ),
        ],
      ),
    );
  }
}

/// RED=REAL / YELLOW=ISA / GREEN=PAPER — same coding as the portfolio
/// screen's account banner, so a color means the same thing app-wide.
Color _accountColor(BuildContext context, KisAccount account) {
  final colors = Theme.of(context).extension<AccountColors>()!;
  return switch (account) {
    KisAccount.real => colors.real,
    KisAccount.isa => colors.isa,
    KisAccount.paper => colors.paper,
  };
}

/// Small colored account badge shown on each trade/journal row — replaces
/// the plain "· PAPER" text suffix for at-a-glance scanning. Toss trades
/// carry no KIS account_type (null), so they render a 토스 badge instead.
class _AccountBadge extends StatelessWidget {
  const _AccountBadge({required this.broker, required this.accountType});
  final String broker;
  final String? accountType;

  @override
  Widget build(BuildContext context) {
    final isToss = broker.toUpperCase() == 'TOSS';
    final label = isToss ? '토스' : KisAccount.fromWire(accountType ?? '').label;
    final c = isToss ? _tossColor : _accountColor(context, KisAccount.fromWire(accountType ?? ''));
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: c.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        label,
        style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: c),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Tab 1 — Missing trades (need POST)
// ---------------------------------------------------------------------------

class _MissingTab extends ConsumerWidget {
  const _MissingTab();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(missingTradesProvider);
    final filter = ref.watch(journalAccountFilterProvider);
    return async.when(
      data: (trades) {
        final filtered = trades
            .where((t) => matchesAccountFilter(t.broker, t.accountType, filter))
            .toList();
        if (filtered.isEmpty) {
          final filteredOut = filter != JournalFilter.all && trades.isNotEmpty;
          return EmptyState(
            icon: Icons.check_circle_outline,
            title: filteredOut ? '${filter.label} 계좌: 미작성 거래 없음' : '모두 복기 완료!',
            subtitle: filteredOut
                ? '다른 계좌를 선택하거나 전체 보기로 확인하세요.'
                : '훌륭합니다 — 모든 체결된 거래에 매매일지가 작성되어 있어요.',
            iconColor: Colors.green,
          );
        }
        return ListView.separated(
          padding: const EdgeInsets.symmetric(vertical: 8),
          itemCount: filtered.length,
          separatorBuilder: (_, __) => const Divider(height: 1),
          itemBuilder: (_, i) => _MissingRow(trade: filtered[i]),
        );
      },
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => _ErrorBlock(error: e, onRetry: () => ref.invalidate(missingTradesProvider)),
    );
  }
}

class _MissingRow extends ConsumerWidget {
  const _MissingRow({required this.trade});
  final TradeLite trade;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final isBuy = trade.direction.toUpperCase() == 'BUY';
    final color = isBuy ? Colors.redAccent : Colors.blueAccent;
    return ListTile(
      leading: CircleAvatar(
        backgroundColor: color.withValues(alpha: 0.15),
        child: Text(isBuy ? '매수' : '매도',
            style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w700)),
      ),
      title: Row(
        children: [
          Text(trade.stockCode,
              style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(width: 6),
          _AccountBadge(broker: trade.broker, accountType: trade.accountType),
        ],
      ),
      subtitle: Text(
        '${_dateTime.format(trade.executedAt.toLocal())}  ·  '
        '${trade.quantity}주 @ ₩${_krw.format(trade.price)}',
        style: theme.textTheme.bodySmall,
      ),
      trailing: FilledButton.tonal(
        onPressed: () => _writeJournalDialog(context, ref, trade),
        child: const Text('복기 작성'),
      ),
    );
  }
}

Future<void> _writeJournalDialog(BuildContext context, WidgetRef ref, TradeLite trade) async {
  final reasonCtrl = TextEditingController();
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text('${trade.stockCode} ${trade.direction} 복기'),
      content: SizedBox(
        width: 480,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${_dateTime.format(trade.executedAt.toLocal())}  ·  '
              '${trade.quantity}주 @ ₩${_krw.format(trade.price)}',
              style: Theme.of(ctx).textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: reasonCtrl,
              maxLines: 6,
              minLines: 4,
              autofocus: true,
              decoration: const InputDecoration(
                labelText: '왜 이 거래를 했는가? (필수)',
                hintText: '예: PER 8x 이하 + 분기 영업이익 +30% YoY. 가격 박스권 하단 진입.',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 6),
            const Text('적용한 투자 원칙 선택은 다음 단계에서 추가됩니다.',
                style: TextStyle(fontSize: 11)),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('취소')),
        FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('저장')),
      ],
    ),
  );
  if (ok != true) return;
  final reason = reasonCtrl.text.trim();
  if (reason.isEmpty) return;

  try {
    await ref.read(tradeJournalApiProvider).create(tradeId: trade.id, reason: reason);
    ref.invalidate(missingTradesProvider);
    ref.invalidate(journalListProvider);
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('${trade.stockCode} 복기 저장 완료')));
    }
  } catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('저장 실패: $e'), backgroundColor: Colors.redAccent),
      );
    }
  }
}

// ---------------------------------------------------------------------------
// Tab 2 — All journals (PATCH-able)
// ---------------------------------------------------------------------------

class _AllTab extends ConsumerWidget {
  const _AllTab();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(journalListProvider);
    final filter = ref.watch(journalAccountFilterProvider);
    return async.when(
      data: (list) {
        final filtered = list
            .where((j) => matchesAccountFilter(j.trade.broker, j.trade.accountType, filter))
            .toList();
        if (filtered.isEmpty) {
          final filteredOut = filter != JournalFilter.all && list.isNotEmpty;
          return EmptyState(
            icon: Icons.menu_book_outlined,
            title: filteredOut ? '${filter.label} 계좌 일지가 없습니다' : '아직 저장된 매매일지가 없습니다',
            subtitle: filteredOut
                ? '다른 계좌를 선택하거나 전체 보기로 확인하세요.'
                : '거래 후 미작성 탭에서 복기를 작성하면 여기에 누적됩니다.',
          );
        }
        return ListView.separated(
          padding: const EdgeInsets.symmetric(vertical: 8),
          itemCount: filtered.length,
          separatorBuilder: (_, __) => const Divider(height: 1),
          itemBuilder: (_, i) => _JournalRow(journal: filtered[i]),
        );
      },
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => _ErrorBlock(error: e, onRetry: () => ref.invalidate(journalListProvider)),
    );
  }
}

class _JournalRow extends ConsumerWidget {
  const _JournalRow({required this.journal});
  final TradeJournal journal;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final isBuy = journal.direction.toUpperCase() == 'BUY';
    final color = isBuy ? Colors.redAccent : Colors.blueAccent;
    final t = journal.trade;
    final hasReview = journal.postReview != null && journal.postReview!.trim().isNotEmpty;

    return ListTile(
      isThreeLine: true,
      leading: CircleAvatar(
        backgroundColor: color.withValues(alpha: 0.15),
        child: Text(isBuy ? '매수' : '매도',
            style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w700)),
      ),
      title: Row(
        children: [
          Text(t.stockCode,
              style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(width: 6),
          _AccountBadge(broker: t.broker, accountType: t.accountType),
          const SizedBox(width: 6),
          Flexible(
            child: Text(
              '${_dateTime.format(t.executedAt.toLocal())}  ·  '
              '${t.quantity}주 @ ₩${_krw.format(t.price)}',
              style: theme.textTheme.bodySmall,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          const Spacer(),
          if (!hasReview)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                color: Colors.amber.withValues(alpha: 0.18),
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Text('사후리뷰 미작성',
                  style: TextStyle(color: Colors.amber, fontSize: 11)),
            ),
        ],
      ),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('🎯 사유: ${journal.reason}'),
            if (hasReview) ...[
              const SizedBox(height: 4),
              Text('📝 리뷰: ${journal.postReview}',
                  style: theme.textTheme.bodySmall),
            ],
            if (journal.appliedPrinciples.isNotEmpty) ...[
              const SizedBox(height: 4),
              Wrap(
                spacing: 4,
                children: [
                  for (final p in journal.appliedPrinciples)
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: theme.colorScheme.primaryContainer,
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(p.title,
                          style: theme.textTheme.labelSmall?.copyWith(
                            color: theme.colorScheme.onPrimaryContainer,
                          )),
                    ),
                ],
              ),
            ],
            const SizedBox(height: 8),
            _AiAnalysisBlock(journal: journal),
          ],
        ),
      ),
      trailing: IconButton(
        icon: const Icon(Icons.edit_outlined),
        tooltip: '리뷰 편집',
        onPressed: () => _editJournalDialog(context, ref, journal),
      ),
    );
  }
}

Future<void> _editJournalDialog(BuildContext context, WidgetRef ref, TradeJournal journal) async {
  final reasonCtrl = TextEditingController(text: journal.reason);
  final reviewCtrl = TextEditingController(text: journal.postReview ?? '');
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text('${journal.trade.stockCode} 일지 편집'),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: reasonCtrl,
                maxLines: 4,
                minLines: 3,
                decoration: const InputDecoration(
                  labelText: '진입 사유 (필수)',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: reviewCtrl,
                maxLines: 6,
                minLines: 4,
                decoration: const InputDecoration(
                  labelText: '사후 리뷰 (선택)',
                  hintText: '포지션 청산 후 결과 + 배운점',
                  border: OutlineInputBorder(),
                ),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('취소')),
        FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('저장')),
      ],
    ),
  );
  if (ok != true) return;
  final reason = reasonCtrl.text.trim();
  final review = reviewCtrl.text.trim();
  if (reason.isEmpty) return;

  try {
    await ref.read(tradeJournalApiProvider).patch(
      journal.id,
      reason: reason == journal.reason ? null : reason,
      postReview: review == (journal.postReview ?? '') ? null : review,
    );
    ref.invalidate(journalListProvider);
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('일지 저장 완료')));
    }
  } catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('저장 실패: $e'), backgroundColor: Colors.redAccent),
      );
    }
  }
}

// ---------------------------------------------------------------------------
// AI feedback block (LLM principle-violation analysis)
// ---------------------------------------------------------------------------

class _AiAnalysisBlock extends StatelessWidget {
  const _AiAnalysisBlock({required this.journal});
  final TradeJournal journal;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    if (!journal.hasLlmAnalysis) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          color: theme.colorScheme.surfaceContainerHigh,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: theme.colorScheme.outlineVariant),
        ),
        child: Row(
          children: [
            Icon(Icons.psychology_outlined, size: 16, color: theme.colorScheme.outline),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                '🤖 AI 분석 대기 중 — 백그라운드에서 원칙 위반 여부를 분석 중입니다.',
                style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.outline),
              ),
            ),
          ],
        ),
      );
    }

    final verdict = journal.llmVerdict;
    final (badgeBg, badgeLabel, headerIcon) = switch (verdict) {
      'violation' => (Colors.redAccent, '⚠️ 원칙 위반 감지', Icons.report_outlined),
      _ => (Colors.green.shade700, '✅ 원칙 준수', Icons.verified_outlined),
    };

    final fmt = DateFormat('MM-dd HH:mm');
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: badgeBg.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: badgeBg.withValues(alpha: 0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(headerIcon, size: 16, color: badgeBg),
              const SizedBox(width: 6),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: badgeBg,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(badgeLabel,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                    )),
              ),
              const Spacer(),
              if (journal.llmAnalyzedAt != null)
                Text(fmt.format(journal.llmAnalyzedAt!.toLocal()),
                    style: theme.textTheme.labelSmall),
            ],
          ),
          if (journal.llmViolationTags.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: [
                for (final tag in journal.llmViolationTags)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                    decoration: BoxDecoration(
                      color: badgeBg.withValues(alpha: 0.15),
                      border: Border.all(color: badgeBg.withValues(alpha: 0.5)),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Text('#$tag 🚨',
                        style: TextStyle(
                          color: badgeBg,
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                        )),
                  ),
              ],
            ),
          ],
          if (journal.llmAnalysisSummary != null &&
              journal.llmAnalysisSummary!.trim().isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(journal.llmAnalysisSummary!,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurface,
                  fontStyle: FontStyle.italic,
                )),
          ],
          if (journal.llmAnalysisModel != null) ...[
            const SizedBox(height: 6),
            Text('— ${journal.llmAnalysisModel}',
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.outline)),
          ],
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Common
// ---------------------------------------------------------------------------

class _ErrorBlock extends StatelessWidget {
  const _ErrorBlock({required this.error, required this.onRetry});
  final Object error;
  final VoidCallback onRetry;
  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, size: 48),
            const SizedBox(height: 8),
            SelectableText('$error', textAlign: TextAlign.center),
            const SizedBox(height: 12),
            FilledButton(onPressed: onRetry, child: const Text('다시 시도')),
          ],
        ),
      ),
    );
  }
}
