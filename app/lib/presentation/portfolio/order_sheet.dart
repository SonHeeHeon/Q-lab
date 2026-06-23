/// File: app/lib/presentation/portfolio/order_sheet.dart
///
/// Modal bottom sheet for placing a BUY/SELL order. Replaces the older
/// AlertDialog-style ordering. Reads live price from `quotesProvider`,
/// validates inputs, sends `POST /api/portfolio/orders`.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../data/api/portfolio_api.dart';
import '../../data/ws/quotes_ws_client.dart';
import '../../domain/entities/account.dart';
import '../../shared/widgets/sparkline.dart';
import '../trade_journal/post_order_journal_dialog.dart';
import 'portfolio_controller.dart';

final _krw = NumberFormat('#,##0');

enum _OrderType { market, limit }

class _OrderResult {
  _OrderResult({required this.receipt, required this.side, required this.qty});
  final TradeReceipt receipt;
  final OrderDirection side;
  final int qty;
}

class _SparklinePreview extends StatelessWidget {
  const _SparklinePreview({required this.stockCode});
  final String stockCode;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final values = Sparkline.fromCodeDummy(stockCode);
    final isUp = values.last >= values.first;
    final pctish = ((values.last - values.first) / values.first) * 100;
    final color = isUp ? Colors.redAccent : Colors.blueAccent;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          Expanded(
            child: SizedBox(
              height: 56,
              child: Sparkline(values: values),
            ),
          ),
          const SizedBox(width: 12),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text('최근 추세',
                  style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline)),
              Text('${pctish >= 0 ? '+' : ''}${pctish.toStringAsFixed(2)}%',
                  style: theme.textTheme.titleSmall?.copyWith(
                    color: color,
                    fontWeight: FontWeight.w800,
                    fontFamily: 'monospace',
                  )),
              const SizedBox(height: 2),
              Text('(미리보기 — 실데이터 API 대기 중)',
                  style: theme.textTheme.labelSmall
                      ?.copyWith(color: theme.colorScheme.outline, fontSize: 9)),
            ],
          ),
        ],
      ),
    );
  }
}

class OrderSheetArgs {
  OrderSheetArgs({
    required this.account,
    required this.stockCode,
    required this.stockName,
    required this.initialSide,
    this.holdingQuantity,
    this.avgBuyPrice,
    this.initialMarketPrice,
    this.broker = BrokerType.KIS,
  });

  final KisAccount account;
  final String stockCode;
  final String stockName;
  final OrderDirection initialSide;
  final int? holdingQuantity;
  final double? avgBuyPrice;

  /// Best-known *market* price at open time (live tick or last close).
  /// Never the average buy price — that would mislead the order estimate.
  /// Used only until a fresh WS tick/snapshot arrives.
  final double? initialMarketPrice;
  final BrokerType broker;
}

Future<void> showOrderSheet(BuildContext context, WidgetRef ref, OrderSheetArgs args) async {
  // Make sure WS is subscribed so the live price ticks while the sheet
  // is open. Track whether this code was already subscribed by the
  // owning screen (Portfolio holdings auto-subscribe) — if so, we
  // leave it; otherwise we own the subscription and must release it.
  final quotes = ref.read(quotesProvider.notifier);
  final alreadySubscribed = quotes.isSubscribed(args.stockCode);
  if (!alreadySubscribed) {
    quotes.subscribe([args.stockCode]);
  }
  // Always pull a fresh snapshot on open — a steady subscription only
  // pushes ticks on change, so an already-subscribed code may have a
  // stale (or no) price in the cache.
  quotes.requestSnapshot([args.stockCode], broker: args.broker.wire);

  _OrderResult? result;
  try {
    result = await showModalBottomSheet<_OrderResult?>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (ctx) => Padding(
        padding: EdgeInsets.only(
          bottom: MediaQuery.of(ctx).viewInsets.bottom,
        ),
        child: _OrderSheet(args: args),
      ),
    );
  } finally {
    if (!alreadySubscribed) {
      quotes.unsubscribe([args.stockCode]);
    }
  }

  if (result == null || !context.mounted) return;

  final snackMsg = '✅ 주문 전송: ${args.stockName} '
      '${result.side == OrderDirection.buy ? '매수' : '매도'} ${result.qty}주'
      '${result.receipt.tradeId != null ? ' (trade #${result.receipt.tradeId})' : ''}';
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(snackMsg)));

  if (result.receipt.tradeId != null) {
    await showPostOrderJournalDialog(
      context, ref,
      stockCode: args.stockCode,
      stockName: args.stockName,
      side: result.side,
      qty: result.qty,
      tradeId: result.receipt.tradeId!,
    );
  }
}

class _OrderSheet extends ConsumerStatefulWidget {
  const _OrderSheet({required this.args});
  final OrderSheetArgs args;

  @override
  ConsumerState<_OrderSheet> createState() => _OrderSheetState();
}

class _OrderSheetState extends ConsumerState<_OrderSheet> {
  late OrderDirection _side = widget.args.initialSide;
  _OrderType _type = _OrderType.market;
  final _qtyCtrl = TextEditingController(text: '1');
  final _priceCtrl = TextEditingController();
  bool _busy = false;
  String? _error;

  int get _qty => int.tryParse(_qtyCtrl.text.trim()) ?? 0;
  double? get _price => double.tryParse(_priceCtrl.text.trim().replaceAll(',', ''));

  @override
  void dispose() {
    _qtyCtrl.dispose();
    _priceCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_busy) return;
    final qty = _qty;
    if (qty <= 0) {
      setState(() => _error = '수량은 1 이상이어야 합니다.');
      return;
    }
    if (_type == _OrderType.limit && (_price == null || _price! <= 0)) {
      setState(() => _error = '지정가는 0보다 커야 합니다.');
      return;
    }

    setState(() {
      _busy = true;
      _error = null;
    });

    try {
      final receipt = await ref.read(portfolioApiProvider).placeOrder(
            PlaceOrderRequest(
              broker: widget.args.broker,
              accountType: widget.args.account,
              stockCode: widget.args.stockCode,
              direction: _side,
              quantity: qty,
              price: _type == _OrderType.market ? null : _price,
            ),
          );
      if (!mounted) return;
      ref.invalidate(accountDetailProvider);
      Navigator.of(context).pop(_OrderResult(receipt: receipt, side: _side, qty: qty));
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final tick = ref.watch(quotesProvider.select((m) => m[widget.args.stockCode]));
    // Market price only — never the average buy price. Falls back to the
    // open-time market price until a fresh tick/snapshot arrives.
    final livePrice = tick?.price ?? widget.args.initialMarketPrice;
    final est = _type == _OrderType.market
        ? (livePrice == null ? null : livePrice * _qty)
        : (_price == null ? null : _price! * _qty);

    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Header
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: theme.colorScheme.primaryContainer,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(widget.args.account.wire,
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: theme.colorScheme.onPrimaryContainer,
                      fontWeight: FontWeight.w700,
                    )),
              ),
              if (widget.args.broker == BrokerType.TOSS) ...[
                const SizedBox(width: 6),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: const Color(0xFF3182F6).withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text('토스증권',
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: const Color(0xFF3182F6),
                        fontWeight: FontWeight.w700,
                      )),
                ),
              ],
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '${widget.args.stockName}  ·  ${widget.args.stockCode}',
                  style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Row(
            children: [
              Text(
                livePrice != null
                    ? '현재가  ₩${_krw.format(livePrice)}'
                    : '현재가 확인 중…',
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: livePrice == null ? theme.colorScheme.outline : null,
                ),
              ),
              const SizedBox(width: 12),
              if (widget.args.holdingQuantity != null)
                Text('보유 ${widget.args.holdingQuantity}주',
                    style: theme.textTheme.bodySmall),
            ],
          ),
          const SizedBox(height: 12),

          // Sparkline preview (dummy data — replaced when backend ships
          // a price-history endpoint).
          _SparklinePreview(stockCode: widget.args.stockCode),
          const SizedBox(height: 16),

          // BUY / SELL toggle
          SegmentedButton<OrderDirection>(
            segments: const [
              ButtonSegment(
                value: OrderDirection.buy,
                label: Text('매수'),
                icon: Icon(Icons.arrow_upward),
              ),
              ButtonSegment(
                value: OrderDirection.sell,
                label: Text('매도'),
                icon: Icon(Icons.arrow_downward),
              ),
            ],
            selected: {_side},
            onSelectionChanged: (s) => setState(() => _side = s.first),
            style: SegmentedButton.styleFrom(
              selectedBackgroundColor: _side == OrderDirection.buy
                  ? Colors.redAccent.withValues(alpha: 0.18)
                  : Colors.blueAccent.withValues(alpha: 0.18),
              selectedForegroundColor:
                  _side == OrderDirection.buy ? Colors.redAccent : Colors.blueAccent,
            ),
          ),
          const SizedBox(height: 16),

          // MARKET / LIMIT toggle
          SegmentedButton<_OrderType>(
            segments: const [
              ButtonSegment(value: _OrderType.market, label: Text('시장가')),
              ButtonSegment(value: _OrderType.limit, label: Text('지정가')),
            ],
            selected: {_type},
            onSelectionChanged: (s) {
              setState(() {
                _type = s.first;
                if (_type == _OrderType.limit && _priceCtrl.text.isEmpty && livePrice != null) {
                  _priceCtrl.text = livePrice.toStringAsFixed(0);
                }
              });
            },
          ),
          const SizedBox(height: 16),

          // Quantity row
          Row(
            children: [
              IconButton(
                onPressed: () {
                  final q = (_qty - 1).clamp(1, 1 << 30);
                  _qtyCtrl.text = '$q';
                  setState(() {});
                },
                icon: const Icon(Icons.remove_circle_outline),
              ),
              Expanded(
                child: TextField(
                  controller: _qtyCtrl,
                  keyboardType: TextInputType.number,
                  textAlign: TextAlign.center,
                  inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                  decoration: const InputDecoration(labelText: '수량 (주)'),
                  onChanged: (_) => setState(() {}),
                ),
              ),
              IconButton(
                onPressed: () {
                  _qtyCtrl.text = '${_qty + 1}';
                  setState(() {});
                },
                icon: const Icon(Icons.add_circle_outline),
              ),
            ],
          ),
          const SizedBox(height: 8),

          // Price (only for LIMIT)
          if (_type == _OrderType.limit)
            TextField(
              controller: _priceCtrl,
              keyboardType: const TextInputType.numberWithOptions(decimal: false),
              decoration: const InputDecoration(
                labelText: '지정가 (₩)',
                hintText: '예: 75500',
              ),
              onChanged: (_) => setState(() {}),
            )
          else
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              decoration: BoxDecoration(
                color: theme.colorScheme.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  const Icon(Icons.bolt, size: 16),
                  const SizedBox(width: 6),
                  Text(
                    '시장가 — 체결 즉시 현재 호가로 처리',
                    style: theme.textTheme.bodySmall,
                  ),
                ],
              ),
            ),

          const SizedBox(height: 16),

          // Estimated total
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              border: Border.all(color: theme.colorScheme.outlineVariant),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              children: [
                Text('예상 체결대금', style: theme.textTheme.bodyMedium),
                const Spacer(),
                Text(
                  est == null ? '--' : '₩${_krw.format(est)}',
                  style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                ),
              ],
            ),
          ),

          if (_error != null) ...[
            const SizedBox(height: 12),
            Text('⚠️ $_error',
                style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.error)),
          ],

          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: _busy ? null : () => Navigator.of(context).pop(),
                  child: const Text('취소'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                flex: 2,
                child: FilledButton(
                  onPressed: _busy ? null : _submit,
                  style: FilledButton.styleFrom(
                    backgroundColor:
                        _side == OrderDirection.buy ? Colors.redAccent : Colors.blueAccent,
                  ),
                  child: _busy
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : Text(_side == OrderDirection.buy ? '매수 주문' : '매도 주문'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
