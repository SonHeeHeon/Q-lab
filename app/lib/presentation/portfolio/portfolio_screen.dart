/// File: app/lib/presentation/portfolio/portfolio_screen.dart
///
/// Portfolio screen — see PROJECT_BLUEPRINT.md §9.2.
/// Broker filter bar switches between KIS tab view (모의/실전/ISA) and
/// unified cross-broker view (토스 / 전체). Holdings table with live WS
/// prices that flash on every tick (red = up, blue = down — KR convention).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/theme.dart';
import '../../data/api/portfolio_api.dart';
import '../../data/ws/quotes_ws_client.dart';
import '../../domain/entities/account.dart';
import '../../domain/entities/position.dart';
import '../../shared/widgets/empty_state.dart';
import 'order_sheet.dart';
import 'portfolio_controller.dart';

const _tossColor = Color(0xFF3182F6);

final _krw = NumberFormat.currency(symbol: '₩', decimalDigits: 0);
final _qty = NumberFormat('#,##0');
final _pct = NumberFormat('+0.00;-0.00');
final _timeFmt = DateFormat('MM/dd HH:mm');

class PortfolioScreen extends ConsumerWidget {
  const PortfolioScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final filter = ref.watch(brokerFilterProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('포트폴리오'),
        actions: [
          IconButton(
            tooltip: '새로고침',
            icon: const Icon(Icons.refresh),
            onPressed: () {
              ref.invalidate(accountDetailProvider);
              ref.invalidate(unifiedPortfolioProvider);
            },
          ),
        ],
      ),
      body: Column(
        children: [
          _BrokerFilterBar(
            filter: filter,
            onChanged: (f) => ref.read(brokerFilterProvider.notifier).state = f,
          ),
          const Divider(height: 1),
          Expanded(
            child: filter == BrokerFilter.kis ? const _KisPane() : const _UnifiedPane(),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Broker filter bar
// ---------------------------------------------------------------------------

class _BrokerFilterBar extends StatelessWidget {
  const _BrokerFilterBar({required this.filter, required this.onChanged});
  final BrokerFilter filter;
  final ValueChanged<BrokerFilter> onChanged;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          ChoiceChip(
            label: const Text('전체 보기'),
            selected: filter == BrokerFilter.all,
            onSelected: (_) => onChanged(BrokerFilter.all),
          ),
          const SizedBox(width: 8),
          ChoiceChip(
            avatar: const CircleAvatar(backgroundColor: Colors.purple, radius: 8),
            label: const Text('한국투자증권'),
            selected: filter == BrokerFilter.kis,
            onSelected: (_) => onChanged(BrokerFilter.kis),
          ),
          const SizedBox(width: 8),
          ChoiceChip(
            avatar: const CircleAvatar(backgroundColor: _tossColor, radius: 8),
            label: const Text('토스증권'),
            selected: filter == BrokerFilter.toss,
            onSelected: (_) => onChanged(BrokerFilter.toss),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Broker badge — colored label chip shown on each unified position row
// ---------------------------------------------------------------------------

class _BrokerBadge extends StatelessWidget {
  const _BrokerBadge({required this.broker});
  final BrokerType broker;

  @override
  Widget build(BuildContext context) {
    final isKis = broker == BrokerType.KIS;
    final color = isKis ? Colors.purple : _tossColor;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        broker.shortLabel,
        style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: color),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// KIS pane — existing tab-based view (모의 / 실전 / ISA)
// ---------------------------------------------------------------------------

class _KisPane extends ConsumerWidget {
  const _KisPane();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selected = ref.watch(selectedAccountProvider);
    final asyncDetail = ref.watch(accountDetailProvider);

    return Column(
      children: [
        _AccountBanner(account: selected),
        _AccountTabs(
          selected: selected,
          onSelect: (a) => ref.read(selectedAccountProvider.notifier).state = a,
        ),
        const Divider(height: 1),
        Expanded(
          child: asyncDetail.when(
            data: (d) => _DetailBody(detail: d),
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (e, st) => _ErrorBlock(
              error: e,
              stack: st,
              onRetry: () => ref.invalidate(accountDetailProvider),
            ),
          ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Unified pane — cross-broker view (토스 / 전체)
// ---------------------------------------------------------------------------

class _UnifiedPane extends ConsumerWidget {
  const _UnifiedPane();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncData = ref.watch(unifiedPortfolioProvider);
    return asyncData.when(
      data: (portfolio) => _UnifiedContent(portfolio: portfolio),
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, st) => _ErrorBlock(
        error: e,
        stack: st,
        onRetry: () => ref.invalidate(unifiedPortfolioProvider),
      ),
    );
  }
}

class _UnifiedContent extends StatelessWidget {
  const _UnifiedContent({required this.portfolio});
  final UnifiedPortfolio portfolio;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return RefreshIndicator(
      onRefresh: () async {},
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _UnifiedSummaryCard(portfolio: portfolio),
          const SizedBox(height: 16),
          if (portfolio.accounts.isNotEmpty) ...[
            Text('계좌별 요약',
                style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            ...portfolio.accounts.map((a) => Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: _AccountSummaryTile(account: a),
                )),
            const SizedBox(height: 8),
          ],
          Text('보유 종목',
              style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          if (portfolio.positions.isEmpty)
            _EmptyHoldings()
          else
            Card(
              child: ListView.separated(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                itemCount: portfolio.positions.length,
                separatorBuilder: (_, __) => const Divider(height: 1),
                itemBuilder: (_, i) =>
                    _UnifiedPositionRow(position: portfolio.positions[i]),
              ),
            ),
          if (portfolio.errors.isNotEmpty) ...[
            const SizedBox(height: 12),
            _ErrorsCard(errors: portfolio.errors),
          ],
        ],
      ),
    );
  }
}

class _UnifiedSummaryCard extends StatelessWidget {
  const _UnifiedSummaryCard({required this.portfolio});
  final UnifiedPortfolio portfolio;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isUp = portfolio.totalPl >= 0;
    final c = isUp ? Colors.redAccent : Colors.blueAccent;
    return Card(
      color: theme.colorScheme.surfaceContainerHighest,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('💰 통합 평가금액', style: theme.textTheme.titleSmall),
            const SizedBox(height: 4),
            Text(
              _krw.format(portfolio.totalValue),
              style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 4),
            Text('기준: ${_timeFmt.format(portfolio.asOf)}',
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.outline)),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: _MiniTile(
                    label: '평가손익',
                    value: '${isUp ? '+' : ''}${_krw.format(portfolio.totalPl)}',
                    valueColor: c,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _MiniTile(
                    label: '수익률',
                    value: '${_pct.format(portfolio.totalPlPct)}%',
                    valueColor: c,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _AccountSummaryTile extends StatelessWidget {
  const _AccountSummaryTile({required this.account});
  final UnifiedAccountSummary account;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isUp = account.totalPl >= 0;
    final c = isUp ? Colors.redAccent : Colors.blueAccent;
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        child: Row(
          children: [
            _BrokerBadge(broker: account.broker),
            if (account.accountType != null) ...[
              const SizedBox(width: 6),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: theme.colorScheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Text(account.accountType!.label,
                    style: theme.textTheme.labelSmall),
              ),
            ],
            const Spacer(),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(_krw.format(account.totalValue),
                    style: theme.textTheme.titleSmall
                        ?.copyWith(fontWeight: FontWeight.w700)),
                Text('${isUp ? '+' : ''}${_pct.format(account.totalPlPct)}%',
                    style: theme.textTheme.bodySmall?.copyWith(color: c)),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _UnifiedPositionRow extends ConsumerWidget {
  const _UnifiedPositionRow({required this.position});
  final UnifiedPosition position;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final p = position;

    final liveTick = ref.watch(quotesProvider.select((m) => m[p.stockCode]));
    final livePrice = liveTick?.price ?? p.currentPrice ?? p.avgBuyPrice;
    final costBasis = p.avgBuyPrice * p.quantity;
    final pl = livePrice * p.quantity - costBasis;
    final plPct = costBasis == 0 ? 0.0 : (pl / costBasis) * 100;
    final isUp = pl >= 0;
    final plColor = isUp ? Colors.redAccent : Colors.blueAccent;

    return InkWell(
      // Open the order sheet routed to *this position's* broker + account
      // so a Toss holding never gets sent through the KIS order path.
      onTap: () => showOrderSheet(
        context,
        ref,
        OrderSheetArgs(
          account: p.accountType ?? KisAccount.paper,
          broker: p.broker,
          accountId: p.accountId,
          stockCode: p.stockCode,
          stockName: p.stockName,
          initialSide: OrderDirection.buy,
          holdingQuantity: p.quantity,
          avgBuyPrice: p.avgBuyPrice,
          initialMarketPrice: liveTick?.price ?? p.currentPrice,
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          children: [
            Expanded(
              flex: 4,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      _BrokerBadge(broker: p.broker),
                      const SizedBox(width: 6),
                      Flexible(
                        child: Text(p.stockName,
                            style: theme.textTheme.titleSmall
                                ?.copyWith(fontWeight: FontWeight.w700)),
                      ),
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text('${p.stockCode}  ·  ${_qty.format(p.quantity)}주',
                      style: theme.textTheme.bodySmall),
                ],
              ),
            ),
            Expanded(
              flex: 3,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(_krw.format(livePrice),
                      style: theme.textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w600,
                        color: liveTick == null ? null : plColor,
                      )),
                  Text('평단 ${_krw.format(p.avgBuyPrice)}',
                      style: theme.textTheme.bodySmall),
                ],
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              flex: 3,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    '${isUp ? '+' : ''}${_krw.format(pl)}',
                    style: theme.textTheme.titleSmall?.copyWith(
                      color: plColor,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  Text('${_pct.format(plPct)}%',
                      style: theme.textTheme.bodySmall?.copyWith(color: plColor)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ErrorsCard extends StatelessWidget {
  const _ErrorsCard({required this.errors});
  final List<Map<String, dynamic>> errors;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      color: theme.colorScheme.errorContainer,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('⚠️ 일부 브로커 연결 오류',
                style: theme.textTheme.labelMedium?.copyWith(
                    color: theme.colorScheme.onErrorContainer,
                    fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            ...errors.map((e) => Text(
                  '• ${e['broker'] ?? '?'}: ${e['error'] ?? e['message'] ?? e.toString()}',
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.onErrorContainer),
                )),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Banner + Tabs (KIS-specific)
// ---------------------------------------------------------------------------

class _AccountBanner extends StatelessWidget {
  const _AccountBanner({required this.account});
  final KisAccount account;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AccountColors>()!;
    final c = switch (account) {
      KisAccount.real => colors.real,
      KisAccount.isa => colors.isa,
      KisAccount.paper => colors.paper,
    };
    return Container(
      width: double.infinity,
      color: c.withValues(alpha: 0.15),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: Row(
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: c, shape: BoxShape.circle),
          ),
          const SizedBox(width: 8),
          Text(
            '활성 계좌: ${account.label} (${account.wire})',
            style: TextStyle(color: c, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}

class _AccountTabs extends StatelessWidget {
  const _AccountTabs({required this.selected, required this.onSelect});
  final KisAccount selected;
  final ValueChanged<KisAccount> onSelect;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: SegmentedButton<KisAccount>(
        segments: const [
          ButtonSegment(value: KisAccount.paper, label: Text('모의 (PAPER)')),
          ButtonSegment(value: KisAccount.real, label: Text('실전 (REAL)')),
          ButtonSegment(value: KisAccount.isa, label: Text('ISA')),
        ],
        selected: {selected},
        onSelectionChanged: (s) => onSelect(s.first),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// KIS detail body
// ---------------------------------------------------------------------------

class _DetailBody extends StatelessWidget {
  const _DetailBody({required this.detail});
  final AccountDetail detail;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return RefreshIndicator(
      onRefresh: () async {},
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _SummaryCard(detail: detail),
          const SizedBox(height: 16),
          Text('보유 종목',
              style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          if (detail.positions.isEmpty)
            _EmptyHoldings()
          else
            _HoldingsTable(positions: detail.positions),
        ],
      ),
    );
  }
}

class _SummaryCard extends StatelessWidget {
  const _SummaryCard({required this.detail});
  final AccountDetail detail;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isUp = detail.totalPl >= 0;
    final c = isUp ? Colors.redAccent : Colors.blueAccent;
    return Card(
      color: theme.colorScheme.surfaceContainerHighest,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('💰 총 평가금액', style: theme.textTheme.titleSmall),
            const SizedBox(height: 4),
            Text(
              _krw.format(detail.totalValue),
              style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: _MiniTile(
                    label: '평가손익',
                    value: '${isUp ? '+' : ''}${_krw.format(detail.totalPl)}',
                    valueColor: c,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _MiniTile(
                    label: '수익률',
                    value: '${_pct.format(detail.totalPlPct)}%',
                    valueColor: c,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _MiniTile(
                    label: '예수금',
                    value: _krw.format(detail.cashBalance),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _MiniTile extends StatelessWidget {
  const _MiniTile({required this.label, required this.value, this.valueColor});
  final String label;
  final String value;
  final Color? valueColor;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: theme.colorScheme.surface,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: theme.textTheme.labelSmall),
          const SizedBox(height: 4),
          Text(value,
              style: theme.textTheme.bodyLarge?.copyWith(
                fontWeight: FontWeight.w700,
                color: valueColor,
              )),
        ],
      ),
    );
  }
}

class _EmptyHoldings extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return const EmptyState(
      icon: Icons.account_balance_wallet_outlined,
      title: '보유 종목이 없습니다',
      subtitle: '거래를 시작하면 여기에 표시됩니다.\n관심종목에서 종목을 골라 매수 주문을 넣어보세요.',
    );
  }
}

// ---------------------------------------------------------------------------
// Holdings table — per-row live price subscription + flash animation
// ---------------------------------------------------------------------------

class _HoldingsTable extends StatelessWidget {
  const _HoldingsTable({required this.positions});
  final List<Position> positions;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListView.separated(
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        itemCount: positions.length,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (_, i) => _HoldingRow(position: positions[i]),
      ),
    );
  }
}

class _HoldingRow extends ConsumerStatefulWidget {
  const _HoldingRow({required this.position});
  final Position position;

  @override
  ConsumerState<_HoldingRow> createState() => _HoldingRowState();
}

class _HoldingRowState extends ConsumerState<_HoldingRow>
    with SingleTickerProviderStateMixin {
  late AnimationController _flash;
  double? _prevPrice;

  @override
  void initState() {
    super.initState();
    _flash = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 350),
    );
  }

  @override
  void dispose() {
    _flash.dispose();
    super.dispose();
  }

  void _maybeFlash(double? newPrice) {
    if (!mounted) return;
    if (newPrice == null) return;
    if (_prevPrice != null && newPrice != _prevPrice) {
      _flash.forward(from: 0);
    }
    _prevPrice = newPrice;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final p = widget.position;

    final liveTick = ref.watch(quotesProvider.select((m) => m[p.stockCode]));
    final livePrice = liveTick?.price ?? p.currentPrice ?? p.avgBuyPrice;
    _maybeFlash(liveTick?.price);

    final marketValue = livePrice * p.quantity;
    final costBasis = p.avgBuyPrice * p.quantity;
    final pl = marketValue - costBasis;
    final plPct = costBasis == 0 ? 0.0 : (pl / costBasis) * 100;
    final isUp = pl >= 0;
    final plColor = isUp ? Colors.redAccent : Colors.blueAccent;

    return AnimatedBuilder(
      animation: _flash,
      builder: (context, child) {
        final flashColor = plColor.withValues(alpha: 0.18 * (1 - _flash.value));
        return Container(color: flashColor, child: child);
      },
      child: InkWell(
        onTap: () => showOrderSheet(
          context,
          ref,
          OrderSheetArgs(
            account: ref.read(selectedAccountProvider),
            stockCode: p.stockCode,
            stockName: p.stockName,
            initialSide: OrderDirection.buy,
            holdingQuantity: p.quantity,
            avgBuyPrice: p.avgBuyPrice,
            initialMarketPrice: liveTick?.price ?? p.currentPrice,
          ),
        ),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          child: Row(
            children: [
              Expanded(
                flex: 4,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(p.stockName,
                        style: theme.textTheme.titleSmall
                            ?.copyWith(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 2),
                    Text('${p.stockCode}  ·  ${_qty.format(p.quantity)}주',
                        style: theme.textTheme.bodySmall),
                  ],
                ),
              ),
              Expanded(
                flex: 3,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(_krw.format(livePrice),
                        style: theme.textTheme.titleSmall?.copyWith(
                          fontWeight: FontWeight.w600,
                          color: liveTick == null ? null : plColor,
                        )),
                    Text('평단 ${_krw.format(p.avgBuyPrice)}',
                        style: theme.textTheme.bodySmall),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                flex: 3,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      '${isUp ? '+' : ''}${_krw.format(pl)}',
                      style: theme.textTheme.titleSmall?.copyWith(
                        color: plColor,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    Text('${_pct.format(plPct)}%',
                        style: theme.textTheme.bodySmall?.copyWith(color: plColor)),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              PopupMenuButton<OrderDirection>(
                icon: const Icon(Icons.more_vert),
                tooltip: '주문',
                onSelected: (side) => showOrderSheet(
                  context,
                  ref,
                  OrderSheetArgs(
                    account: ref.read(selectedAccountProvider),
                    stockCode: p.stockCode,
                    stockName: p.stockName,
                    initialSide: side,
                    holdingQuantity: p.quantity,
                    avgBuyPrice: p.avgBuyPrice,
                    initialMarketPrice: liveTick?.price ?? p.currentPrice,
                  ),
                ),
                itemBuilder: (_) => const [
                  PopupMenuItem(value: OrderDirection.buy, child: Text('추가 매수')),
                  PopupMenuItem(value: OrderDirection.sell, child: Text('매도')),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Error block
// ---------------------------------------------------------------------------

class _ErrorBlock extends StatelessWidget {
  const _ErrorBlock({required this.error, required this.stack, required this.onRetry});
  final Object error;
  final StackTrace stack;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Icon(Icons.error_outline, size: 48),
          const SizedBox(height: 8),
          const Text('잔고를 불러오지 못했습니다.', textAlign: TextAlign.center),
          const SizedBox(height: 8),
          SelectableText('$error',
              textAlign: TextAlign.center,
              style: TextStyle(color: theme.colorScheme.error)),
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
