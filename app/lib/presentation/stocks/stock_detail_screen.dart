/// File: app/lib/presentation/stocks/stock_detail_screen.dart
///
/// Stock detail screen — 종목 상세.
/// Shows price, 1-year chart, fundamentals, holding status, watchlist toggle.
/// Bottom bar: 매수 / 매도 order sheet, 알림 만들기 in AppBar.
library;

import 'dart:math' show min, max;

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
                // ── Timeframe candlestick chart ────────────────────────────
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                  child: _CandleChart(
                    market: d.marketCountry,
                    symbol: d.isUs ? d.symbol : d.code,
                    currency: d.currency,
                  ),
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
// Candlestick chart — timeframe selector (일/주/월/연) + horizontal pan
//
// fl_chart 0.69.x has no CandlestickChart type (checked: only bar/line/pie/
// radar/scatter chart dirs exist in the package), so candles are rendered
// with a compact CustomPainter instead of a workaround line/bar hack.
// ---------------------------------------------------------------------------

enum _Interval { day, week, month, year }

extension on _Interval {
  String get wire => switch (this) {
        _Interval.day => 'day',
        _Interval.week => 'week',
        _Interval.month => 'month',
        _Interval.year => 'year',
      };

  String get label => switch (this) {
        _Interval.day => '일봉',
        _Interval.week => '주봉',
        _Interval.month => '월봉',
        _Interval.year => '연봉',
      };

  /// Default page size — also the x-axis width shown right after a switch.
  int get defaultCount => switch (this) {
        _Interval.day => 120,
        _Interval.week => 104,
        _Interval.month => 60,
        _Interval.year => 20,
      };
}

class _CandleChart extends ConsumerStatefulWidget {
  const _CandleChart({required this.market, required this.symbol, required this.currency});
  final String market;
  final String symbol;
  final String currency;

  @override
  ConsumerState<_CandleChart> createState() => _CandleChartState();
}

class _CandleChartState extends ConsumerState<_CandleChart> {
  /// Hard ceiling on in-memory bars per interval — pan pages back until hit.
  static const _maxBars = 600;
  static const _slotWidth = 8.0;
  static const _chartHeight = 220.0;

  _Interval _interval = _Interval.day;
  final Map<_Interval, List<Candle>> _cache = {};
  final Map<_Interval, bool> _reachedStart = {};
  bool _loading = true;
  bool _loadingMore = false;
  Object? _error;
  late final ScrollController _scrollController;

  List<Candle> get _candles => _cache[_interval] ?? const [];

  @override
  void initState() {
    super.initState();
    _scrollController = ScrollController()..addListener(_onScroll);
    _load(_interval);
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  // ── Scroll → pan paging ─────────────────────────────────────────────────

  void _onScroll() {
    if (_loading || _loadingMore) return;
    if (_reachedStart[_interval] == true) return;
    if (_candles.length >= _maxBars) return;
    if (!_scrollController.hasClients) return;
    final pos = _scrollController.position;
    // Dragging toward the left edge (oldest loaded bars) → fetch further back.
    if (pos.pixels <= pos.minScrollExtent + _slotWidth * 10) {
      _loadOlderPage();
    }
  }

  Future<void> _load(_Interval interval) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final candles = await ref.read(stocksApiProvider).history(
            market: widget.market,
            symbol: widget.symbol,
            interval: interval.wire,
            count: interval.defaultCount,
          );
      if (!mounted) return;
      setState(() {
        _cache[interval] = candles;
        _reachedStart[interval] = candles.length < interval.defaultCount;
        _loading = false;
      });
      _jumpToLatest();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  Future<void> _loadOlderPage() async {
    final before = _candles;
    if (before.isEmpty) return;
    setState(() => _loadingMore = true);
    final interval = _interval;
    try {
      final oldest = before.first.date;
      final older = await ref.read(stocksApiProvider).history(
            market: widget.market,
            symbol: widget.symbol,
            interval: interval.wire,
            count: interval.defaultCount,
            before: oldest,
          );
      if (!mounted) return;
      final merged = mergeOlderCandles(before, older);
      final addedBars = merged.length - before.length;
      setState(() {
        _cache[interval] = merged;
        _reachedStart[interval] = addedBars == 0;
        _loadingMore = false;
      });
      if (addedBars > 0) {
        final addedWidth = addedBars * _slotWidth;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (!mounted || !_scrollController.hasClients) return;
          // Keep the on-screen bars visually anchored after the prepend.
          _scrollController.jumpTo(_scrollController.offset + addedWidth);
        });
      }
    } catch (_) {
      // Paging failure is non-fatal — keep whatever is already on screen.
      if (!mounted) return;
      setState(() => _loadingMore = false);
    }
  }

  void _jumpToLatest() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_scrollController.hasClients) return;
      _scrollController.jumpTo(_scrollController.position.maxScrollExtent);
    });
  }

  void _onSelectInterval(_Interval next) {
    if (next == _interval) return;
    setState(() => _interval = next);
    if (_cache.containsKey(next)) {
      _jumpToLatest();
    } else {
      _load(next);
    }
  }

  // ── Build ────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final candles = _candles;
    final totalWidth = max(candles.length * _slotWidth, 1.0);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _IntervalSelector(current: _interval, onSelect: _onSelectInterval),
        const SizedBox(height: 10),
        SizedBox(
          height: _chartHeight,
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _error != null
                  ? _ChartError(onRetry: () => _load(_interval))
                  : candles.isEmpty
                      ? Center(
                          child: Text('가격 데이터가 없습니다',
                              style: TextStyle(color: theme.colorScheme.outline)),
                        )
                      : Stack(
                          children: [
                            ClipRect(
                              child: SingleChildScrollView(
                                controller: _scrollController,
                                scrollDirection: Axis.horizontal,
                                child: RepaintBoundary(
                                  child: CustomPaint(
                                    size: Size(totalWidth, _chartHeight),
                                    painter: _CandlestickPainter(
                                      candles: candles,
                                      slotWidth: _slotWidth,
                                      upColor: Colors.redAccent,
                                      downColor: Colors.blueAccent,
                                      gridColor: theme.colorScheme.outlineVariant
                                          .withValues(alpha: 0.4),
                                    ),
                                  ),
                                ),
                              ),
                            ),
                            if (_loadingMore)
                              Positioned(
                                top: 6,
                                left: 0,
                                right: 0,
                                child: Center(child: _LoadingMorePill(theme: theme)),
                              ),
                          ],
                        ),
        ),
        if (candles.isNotEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(_date.format(candles.first.date),
                    style: TextStyle(fontSize: 10, color: theme.colorScheme.outline)),
                Text(_interval.label,
                    style: TextStyle(
                        fontSize: 10,
                        color: theme.colorScheme.outline,
                        fontWeight: FontWeight.w600)),
                Text(_date.format(candles.last.date),
                    style: TextStyle(fontSize: 10, color: theme.colorScheme.outline)),
              ],
            ),
          ),
      ],
    );
  }
}

class _LoadingMorePill extends StatelessWidget {
  const _LoadingMorePill({required this.theme});
  final ThemeData theme;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: theme.colorScheme.surface.withValues(alpha: 0.92),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: theme.colorScheme.outlineVariant),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          SizedBox(
            width: 11,
            height: 11,
            child: CircularProgressIndicator(
              strokeWidth: 1.6,
              color: theme.colorScheme.outline,
            ),
          ),
          const SizedBox(width: 6),
          Text('더 불러오는 중',
              style: TextStyle(fontSize: 10, color: theme.colorScheme.outline)),
        ],
      ),
    );
  }
}

class _ChartError extends StatelessWidget {
  const _ChartError({required this.onRetry});
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.error_outline, size: 28, color: theme.colorScheme.outline),
          const SizedBox(height: 6),
          Text('차트 데이터를 불러오지 못했습니다',
              style: TextStyle(color: theme.colorScheme.outline, fontSize: 12)),
          const SizedBox(height: 6),
          TextButton(onPressed: onRetry, child: const Text('다시 시도')),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Timeframe selector — 일봉/주봉/월봉/연봉 + disabled 시간봉 (no intraday data yet)
// ---------------------------------------------------------------------------

class _IntervalSelector extends StatelessWidget {
  const _IntervalSelector({required this.current, required this.onSelect});
  final _Interval current;
  final ValueChanged<_Interval> onSelect;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          for (final interval in _Interval.values) ...[
            ChoiceChip(
              label: Text(interval.label),
              selected: current == interval,
              visualDensity: VisualDensity.compact,
              onSelected: (_) => onSelect(interval),
            ),
            const SizedBox(width: 6),
          ],
          Tooltip(
            message: '시간봉(분/시간 단위) 데이터는 아직 준비 중입니다',
            child: ChoiceChip(
              label: const Text('시간봉'),
              avatar: Icon(Icons.hourglass_empty, size: 14, color: theme.colorScheme.outline),
              selected: false,
              visualDensity: VisualDensity.compact,
              onSelected: null, // disabled — backend has no intraday endpoint yet
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Candlestick painter — up=red / down=blue (Korean market convention, see
// portfolio_screen.dart's redAccent/blueAccent usage)
// ---------------------------------------------------------------------------

class _CandlestickPainter extends CustomPainter {
  _CandlestickPainter({
    required this.candles,
    required this.slotWidth,
    required this.upColor,
    required this.downColor,
    required this.gridColor,
  });

  final List<Candle> candles;
  final double slotWidth;
  final Color upColor;
  final Color downColor;
  final Color gridColor;

  @override
  void paint(Canvas canvas, Size size) {
    if (candles.isEmpty) return;

    final maxHigh = candles.map((c) => c.high).reduce(max);
    final minLow = candles.map((c) => c.low).reduce(min);
    final span = maxHigh - minLow;
    final padding = span == 0 ? (maxHigh == 0 ? 1.0 : maxHigh * 0.02) : span * 0.08;
    final top = maxHigh + padding;
    final bottom = minLow - padding;
    final valueRange = (top - bottom) == 0 ? 1.0 : (top - bottom);

    double yFor(double v) => size.height - ((v - bottom) / valueRange) * size.height;

    final gridPaint = Paint()
      ..color = gridColor
      ..strokeWidth = 0.5;
    for (final frac in const [0.0, 0.25, 0.5, 0.75, 1.0]) {
      final y = size.height * frac;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), gridPaint);
    }

    for (var i = 0; i < candles.length; i++) {
      final c = candles[i];
      final cx = i * slotWidth + slotWidth / 2;
      final color = c.isUp ? upColor : downColor;

      canvas.drawLine(
        Offset(cx, yFor(c.high)),
        Offset(cx, yFor(c.low)),
        Paint()
          ..color = color
          ..strokeWidth = 1,
      );

      final bodyTop = yFor(max(c.open, c.close));
      final bodyBottomRaw = yFor(min(c.open, c.close));
      final bodyBottom = bodyBottomRaw <= bodyTop ? bodyTop + 1 : bodyBottomRaw;
      final bodyWidth = slotWidth * 0.62;
      canvas.drawRect(
        Rect.fromLTRB(cx - bodyWidth / 2, bodyTop, cx + bodyWidth / 2, bodyBottom),
        Paint()..color = color,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _CandlestickPainter oldDelegate) {
    return !identical(oldDelegate.candles, candles) || oldDelegate.slotWidth != slotWidth;
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
