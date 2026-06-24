/// File: app/lib/presentation/stocks/stock_detail_screen.dart
///
/// Stock detail screen — 종목 상세.
/// Shows price, 1-year chart, fundamentals, holding status, watchlist toggle.
/// Bottom bar: 매수 / 매도 order sheet, 알림 만들기 in AppBar.
library;

import 'dart:math' show min, max;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/config.dart';
import '../../data/api/portfolio_api.dart' show BrokerType, OrderDirection;
import '../../data/api/stocks_api.dart';
import '../../data/api/watchlist_api.dart';
import '../../domain/entities/account.dart';
import '../../shared/format/money.dart';
import '../alerts/alerts_screen.dart' show showCreateAlertDialog;
import '../portfolio/order_sheet.dart';
import '../settings/settings_controller.dart';
import 'stocks_controller.dart';

final _pct = NumberFormat('+0.00;-0.00');
final _date = DateFormat('yy.MM.dd');

class StockDetailScreen extends ConsumerWidget {
  const StockDetailScreen({super.key, required this.market, required this.code});

  final String market;
  final String code;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(stockDetailProvider((market, code)));
    return async.when(
      data: (detail) => _DetailBody(detail: detail),
      loading: () => const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      ),
      error: (e, _) => Scaffold(
        appBar: AppBar(),
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.error_outline, size: 48),
              const SizedBox(height: 8),
              Text('$e', textAlign: TextAlign.center),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: () => ref.invalidate(stockDetailProvider((market, code))),
                child: const Text('다시 시도'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Main detail body (ConsumerStatefulWidget for watchlist state)
// ---------------------------------------------------------------------------

class _DetailBody extends ConsumerStatefulWidget {
  const _DetailBody({required this.detail});
  final StockDetail detail;

  @override
  ConsumerState<_DetailBody> createState() => _DetailBodyState();
}

class _DetailBodyState extends ConsumerState<_DetailBody> {
  bool _watchlistLoading = false;

  StockDetail get d => widget.detail;

  // ── Watchlist add ──────────────────────────────────────────────────────────

  Future<void> _addToWatchlist() async {
    setState(() => _watchlistLoading = true);
    try {
      final api = ref.read(watchlistApiProvider);
      final cats = await api.listCategories();

      int categoryId;
      if (!mounted) return;

      if (cats.isEmpty) {
        final newCat = await api.createCategory(name: '기본 관심종목', color: '#888888');
        categoryId = newCat.id;
      } else if (cats.length == 1) {
        categoryId = cats.first.id;
      } else {
        final picked = await _pickCategory(cats);
        if (picked == null) return;
        categoryId = picked;
      }

      await api.addEntry(
        stockCode: d.symbol, // AAPL 그대로 — backend no longer transforms
        categoryId: categoryId,
        reason: '종목 상세에서 추가',
      );

      // Refresh detail to reflect new watchlist status.
      ref.invalidate(stockDetailProvider((d.marketCountry, d.isUs ? d.symbol : d.code)));
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('${d.name}을(를) 관심종목에 추가했습니다')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('관심종목 추가 실패: $e')));
      }
    } finally {
      if (mounted) setState(() => _watchlistLoading = false);
    }
  }

  Future<int?> _pickCategory(List<WatchlistCategory> cats) {
    return showModalBottomSheet<int>(
      context: context,
      showDragHandle: true,
      builder: (_) => Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Text('관심종목 카테고리 선택',
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w700,
                    )),
          ),
          const Divider(height: 1),
          for (final cat in cats)
            ListTile(
              leading: CircleAvatar(
                backgroundColor:
                    Color(int.tryParse(cat.color.replaceFirst('#', '0xFF')) ?? 0xFF888888)
                        .withValues(alpha: 0.2),
                child: const Icon(Icons.star_outline),
              ),
              title: Text(cat.name),
              onTap: () => Navigator.pop(context, cat.id),
            ),
          const SizedBox(height: 16),
        ],
      ),
    );
  }

  // ── Order sheet ────────────────────────────────────────────────────────────

  void _openOrder(OrderDirection side) {
    final isUs = d.isUs;
    final price = d.displayPrice;

    KisAccount kisAccount;
    if (isUs) {
      kisAccount = KisAccount.paper; // not used for Toss order
    } else {
      final activeType = ref.read(activeAccountProvider);
      kisAccount = KisAccount.fromWire(activeType.name.toUpperCase());
    }

    final tossAccountId =
        ref.read(appSettingsProvider).valueOrNull?.toss?.accountSeq?.toString();

    showOrderSheet(
      context,
      ref,
      OrderSheetArgs(
        account: kisAccount,
        broker: isUs ? BrokerType.TOSS : BrokerType.KIS,
        accountId: isUs ? tossAccountId : null,
        stockCode: isUs ? d.symbol : d.code,
        stockName: d.name,
        initialSide: side,
        holdingQuantity: d.holding?.isHolding == true ? d.holding?.quantity : null,
        avgBuyPrice: d.holding?.isHolding == true ? d.holding?.avgBuyPrice : null,
        initialMarketPrice: price,
      ),
    );
  }

  // ── Alert dialog ───────────────────────────────────────────────────────────

  void _openAlertDialog() {
    showCreateAlertDialog(
      context,
      ref,
      initialSymbol: d.isUs ? d.symbol : d.code,
      initialMarketCountry: d.marketCountry,
    );
  }

  // ── Build ──────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isUs = d.isUs;
    final price = d.displayPrice;
    final changePct = d.changePct;
    final changeAbs = d.changeAbs;
    final isUp = (changePct ?? 0) >= 0;
    final priceColor = changePct == null
        ? theme.colorScheme.onSurface
        : isUp
            ? Colors.redAccent
            : Colors.blueAccent;

    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(d.name,
                style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
            Text(
              isUs ? d.symbol : d.code,
              style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.outline),
            ),
          ],
        ),
        actions: [
          IconButton(
            tooltip: '알림 만들기',
            icon: const Icon(Icons.add_alert_outlined),
            onPressed: _openAlertDialog,
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: ListView(
              padding: EdgeInsets.zero,
              children: [
                // ── Price header ──────────────────────────────────────────
                _PriceHeader(
                  price: price,
                  changePct: changePct,
                  changeAbs: changeAbs,
                  currency: d.currency,
                  priceColor: priceColor,
                  marketCountry: d.marketCountry,
                  broker: d.broker,
                  market: d.market,
                ),
                // ── 1-year chart ──────────────────────────────────────────
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                  child: _PriceChart(history: d.priceHistory, currency: d.currency),
                ),
                // ── Sector / industry info ─────────────────────────────────
                if (d.sector != null || d.industry != null)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    child: Text(
                      [d.sector, d.industry].whereType<String>().join(' · '),
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: theme.colorScheme.outline),
                    ),
                  ),
                const SizedBox(height: 8),
                const Divider(height: 1),
                // ── Factor cards ──────────────────────────────────────────
                if (d.factors != null) _FactorSection(factor: d.factors!),
                const Divider(height: 1),
                // ── Holding ───────────────────────────────────────────────
                _HoldingTile(holding: d.holding, currency: d.currency),
                const Divider(height: 1),
                // ── Watchlist ─────────────────────────────────────────────
                _WatchlistTile(
                  watchlistInfo: d.watchlistInfo,
                  loading: _watchlistLoading,
                  onAdd: _addToWatchlist,
                ),
                const SizedBox(height: 80), // bottom bar clearance
              ],
            ),
          ),
          // ── Bottom order bar ──────────────────────────────────────────
          _OrderBar(onBuy: () => _openOrder(OrderDirection.buy), onSell: () => _openOrder(OrderDirection.sell)),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Price header
// ---------------------------------------------------------------------------

class _PriceHeader extends StatelessWidget {
  const _PriceHeader({
    required this.price,
    required this.changePct,
    required this.changeAbs,
    required this.currency,
    required this.priceColor,
    required this.marketCountry,
    required this.broker,
    required this.market,
  });

  final double? price;
  final double? changePct;
  final double? changeAbs;
  final String currency;
  final Color priceColor;
  final String marketCountry;
  final String broker;
  final String? market;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isUs = marketCountry.toUpperCase() == 'US';
    final priceStr = price == null
        ? '--'
        : isUs
            ? usdFmt.format(price)
            : krwFmt.format(price);

    return Container(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
      color: theme.colorScheme.surfaceContainerLow,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Badges row
          Wrap(
            spacing: 6,
            children: [
              _Chip(
                label: isUs ? '🇺🇸 미국' : '🇰🇷 국내',
                color: isUs ? Colors.blueAccent : Colors.purple,
              ),
              _Chip(
                label: broker,
                color: broker.toUpperCase() == 'TOSS'
                    ? const Color(0xFF3182F6)
                    : Colors.purple,
              ),
              if (market != null) _Chip(label: market!, color: theme.colorScheme.tertiary),
            ],
          ),
          const SizedBox(height: 12),
          // Price
          Text(
            priceStr,
            style: theme.textTheme.headlineMedium?.copyWith(
              fontWeight: FontWeight.w800,
              color: priceColor,
              fontFamily: 'monospace',
            ),
          ),
          if (changePct != null) ...[
            const SizedBox(height: 4),
            Row(
              children: [
                Icon(
                  changePct! >= 0 ? Icons.arrow_drop_up : Icons.arrow_drop_down,
                  color: priceColor,
                ),
                Text(
                  '${_pct.format(changePct)}%',
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: priceColor,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                if (changeAbs != null) ...[
                  const SizedBox(width: 8),
                  Text(
                    isUs ? usdFmt.format(changeAbs) : krwFmt.format(changeAbs),
                    style: theme.textTheme.bodySmall?.copyWith(color: priceColor),
                  ),
                ],
              ],
            ),
          ],
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 1-year price chart
// ---------------------------------------------------------------------------

class _PriceChart extends StatelessWidget {
  const _PriceChart({required this.history, required this.currency});
  final List<PricePoint> history;
  final String currency;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (history.isEmpty) {
      return SizedBox(
        height: 140,
        child: Center(
          child: Text('차트 데이터 없음',
              style: TextStyle(color: theme.colorScheme.outline)),
        ),
      );
    }

    final closes = history.map((p) => p.close).toList();
    final minY = closes.reduce(min) * 0.99;
    final maxY = closes.reduce(max) * 1.01;
    final spots = history
        .asMap()
        .entries
        .map((e) => FlSpot(e.key.toDouble(), e.value.close))
        .toList();

    final isUp = closes.last >= closes.first;
    final lineColor = isUp ? Colors.redAccent : Colors.blueAccent;

    final firstDate = history.first.date;
    final lastDate = history.last.date;
    final startLabel = _date.format(firstDate);
    final endLabel = _date.format(lastDate);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SizedBox(
          height: 160,
          child: LineChart(
            LineChartData(
              minY: minY,
              maxY: maxY,
              clipData: const FlClipData.all(),
              gridData: const FlGridData(show: false),
              borderData: FlBorderData(show: false),
              titlesData: const FlTitlesData(show: false),
              lineBarsData: [
                LineChartBarData(
                  spots: spots,
                  isCurved: true,
                  curveSmoothness: 0.25,
                  color: lineColor,
                  barWidth: 2,
                  dotData: const FlDotData(show: false),
                  belowBarData: BarAreaData(
                    show: true,
                    color: lineColor.withValues(alpha: 0.08),
                  ),
                ),
              ],
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(startLabel,
                  style: TextStyle(fontSize: 10, color: theme.colorScheme.outline)),
              Text('1년 일봉',
                  style: TextStyle(
                      fontSize: 10,
                      color: theme.colorScheme.outline,
                      fontWeight: FontWeight.w600)),
              Text(endLabel,
                  style: TextStyle(fontSize: 10, color: theme.colorScheme.outline)),
            ],
          ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Factor cards section
// ---------------------------------------------------------------------------

class _FactorSection extends StatelessWidget {
  const _FactorSection({required this.factor});
  final StockFactor factor;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('펀더멘털',
              style: Theme.of(context)
                  .textTheme
                  .titleSmall
                  ?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 10),
          Row(
            children: [
              _FactorCard(label: 'PER', value: factor.per),
              const SizedBox(width: 8),
              _FactorCard(label: 'PBR', value: factor.pbr),
              const SizedBox(width: 8),
              _FactorCard(label: 'ROE', value: factor.roe, suffix: '%'),
              const SizedBox(width: 8),
              _FactorCard(label: 'ROA', value: factor.roa, suffix: '%'),
            ],
          ),
        ],
      ),
    );
  }
}

class _FactorCard extends StatelessWidget {
  const _FactorCard({required this.label, required this.value, this.suffix = 'x'});
  final String label;
  final double? value;
  final String suffix;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 8),
        decoration: BoxDecoration(
          color: theme.colorScheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(
          children: [
            Text(label,
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.outline)),
            const SizedBox(height: 4),
            Text(
              value == null ? '--' : '${value!.toStringAsFixed(1)}$suffix',
              style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Holding tile
// ---------------------------------------------------------------------------

class _HoldingTile extends StatelessWidget {
  const _HoldingTile({required this.holding, required this.currency});
  final StockHolding? holding;
  final String currency;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final h = holding;
    final isHolding = h?.isHolding ?? false;

    return ListTile(
      leading: Icon(
        isHolding ? Icons.account_balance_wallet : Icons.account_balance_wallet_outlined,
        color: isHolding ? theme.colorScheme.primary : theme.colorScheme.outline,
      ),
      title: Text(isHolding ? '보유 중' : '미보유',
          style: TextStyle(fontWeight: FontWeight.w600)),
      subtitle: isHolding && h != null
          ? Text(
              '${h.quantity ?? 0}주'
              '${h.avgBuyPrice != null ? '  ·  평단 ${formatNative(h.avgBuyPrice!, currency)}' : ''}',
            )
          : null,
    );
  }
}

// ---------------------------------------------------------------------------
// Watchlist tile
// ---------------------------------------------------------------------------

class _WatchlistTile extends StatelessWidget {
  const _WatchlistTile({
    required this.watchlistInfo,
    required this.loading,
    required this.onAdd,
  });
  final StockWatchlistInfo? watchlistInfo;
  final bool loading;
  final VoidCallback onAdd;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isWatchlisted = watchlistInfo?.isWatchlisted ?? false;

    return ListTile(
      leading: Icon(
        isWatchlisted ? Icons.star : Icons.star_border,
        color: isWatchlisted ? Colors.amber : theme.colorScheme.outline,
      ),
      title: Text(
        isWatchlisted ? '관심종목 등록됨' : '관심종목 추가',
        style: TextStyle(fontWeight: FontWeight.w600),
      ),
      trailing: isWatchlisted
          ? const Chip(label: Text('등록됨'))
          : loading
              ? const SizedBox(
                  width: 24,
                  height: 24,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : FilledButton.tonal(
                  onPressed: onAdd,
                  child: const Text('등록'),
                ),
    );
  }
}

// ---------------------------------------------------------------------------
// Bottom order bar
// ---------------------------------------------------------------------------

class _OrderBar extends StatelessWidget {
  const _OrderBar({required this.onBuy, required this.onSell});
  final VoidCallback onBuy;
  final VoidCallback onSell;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Container(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surface,
          border: Border(
              top: BorderSide(color: Theme.of(context).colorScheme.outlineVariant)),
        ),
        child: Row(
          children: [
            Expanded(
              child: FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: Colors.redAccent,
                  foregroundColor: Colors.white,
                ),
                onPressed: onBuy,
                child: const Text('매수', style: TextStyle(fontWeight: FontWeight.w700)),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: Colors.blueAccent,
                  foregroundColor: Colors.white,
                ),
                onPressed: onSell,
                child: const Text('매도', style: TextStyle(fontWeight: FontWeight.w700)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Shared chip widget
// ---------------------------------------------------------------------------

class _Chip extends StatelessWidget {
  const _Chip({required this.label, required this.color});
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      child: Text(
        label,
        style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w600),
      ),
    );
  }
}
