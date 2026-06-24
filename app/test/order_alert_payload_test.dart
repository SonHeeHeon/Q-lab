// Locks in the broker-routing + auto-order contracts:
//   - Toss holdings must serialize broker="TOSS" (+ account_id) so a Toss
//     order never flows through the KIS path.
//   - KIS holdings keep broker="KIS" and omit account_id.
//   - AlertAction maps NOTIFY/BUY/SELL and flags order actions.
import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/data/api/portfolio_api.dart';
import 'package:qlab/domain/entities/account.dart';
import 'package:qlab/domain/entities/alert.dart';

void main() {
  group('PlaceOrderRequest.toJson — broker routing', () {
    test('Toss order carries broker=TOSS + account_id + ticker', () {
      final json = PlaceOrderRequest(
        broker: BrokerType.TOSS,
        accountType: KisAccount.paper,
        accountId: '7',
        stockCode: 'AAPL',
        direction: OrderDirection.buy,
        quantity: 3,
      ).toJson();

      expect(json['broker'], 'TOSS');
      expect(json['account_id'], '7');
      expect(json['stock_code'], 'AAPL');
      expect(json['direction'], 'BUY');
      expect(json['quantity'], 3);
      expect(json['order_type'], 'MARKET');
    });

    test('KIS order defaults to broker=KIS and omits account_id', () {
      final json = PlaceOrderRequest(
        accountType: KisAccount.real,
        stockCode: '005930',
        direction: OrderDirection.sell,
        quantity: 10,
        price: 75500,
      ).toJson();

      expect(json['broker'], 'KIS');
      expect(json.containsKey('account_id'), isFalse);
      expect(json['direction'], 'SELL');
      expect(json['order_type'], 'LIMIT');
      expect(json['price'], 75500);
    });
  });

  group('AlertAction', () {
    test('fromWire maps NOTIFY/BUY/SELL, unknown → notify', () {
      expect(AlertAction.fromWire('NOTIFY'), AlertAction.notify);
      expect(AlertAction.fromWire('buy'), AlertAction.buy);
      expect(AlertAction.fromWire('SELL'), AlertAction.sell);
      expect(AlertAction.fromWire('???'), AlertAction.notify);
    });

    test('isOrder true only for BUY/SELL', () {
      expect(AlertAction.notify.isOrder, isFalse);
      expect(AlertAction.buy.isOrder, isTrue);
      expect(AlertAction.sell.isOrder, isTrue);
    });
  });
}
