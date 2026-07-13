/// Test seed: Proposal.fromJson parses the backend envelope shape and the
/// status enum survives unknown wire values (backend may add statuses).
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/domain/entities/proposal.dart';

void main() {
  group('ProposalStatus.fromWire', () {
    test('round-trips known values (case-insensitive)', () {
      for (final s in ProposalStatus.values) {
        expect(ProposalStatus.fromWire(s.name.toUpperCase()), s);
        expect(ProposalStatus.fromWire(s.name), s);
      }
    });

    test('unknown wire falls back to proposed', () {
      expect(ProposalStatus.fromWire('CANCELLED_BY_BROKER'),
          ProposalStatus.proposed);
      expect(ProposalStatus.fromWire(''), ProposalStatus.proposed);
    });

    test('only PROPOSED is actionable', () {
      for (final s in ProposalStatus.values) {
        expect(s.isActionable, s == ProposalStatus.proposed);
      }
    });
  });

  group('Proposal.fromJson', () {
    final json = <String, dynamic>{
      'id': 42,
      'batch_id': 'batch-abc',
      'proposal_date': '2026-07-13',
      'account_type': 'PAPER',
      'strategy_name': 'qlab_alpha_v2',
      'stock_code': '005930',
      'market': 'KR',
      'side': 'SELL',
      'qty': 12,
      'order_type': 'LIMIT',
      'limit_price': 70210.0,
      'last_price': 70000.0,
      'estimated_notional': 842520.0,
      'reason': {'rule': 'BAND_TRIM', 'replaces': null},
      'status': 'PROPOSED',
      'expires_at': '2026-07-14T08:30:00',
      'approved_at': null,
      'trade_id': null,
      'created_at': '2026-07-13T18:40:05',
    };

    test('maps all fields', () {
      final p = Proposal.fromJson(json);
      expect(p.id, 42);
      expect(p.stockCode, '005930');
      expect(p.isBuy, isFalse);
      expect(p.qty, 12);
      expect(p.limitPrice, 70210.0);
      expect(p.status, ProposalStatus.proposed);
      expect(p.expiresAt, DateTime.parse('2026-07-14T08:30:00'));
      expect(p.tradeId, isNull);
    });

    test('ruleLabel maps rule codes to Korean labels', () {
      expect(Proposal.fromJson(json).ruleLabel, '비중 트림');
      final tp = Proposal.fromJson({...json, 'reason': {'rule': 'TAKE_PROFIT'}});
      expect(tp.ruleLabel, '익절');
      final unknown =
          Proposal.fromJson({...json, 'reason': {'rule': 'MYSTERY'}});
      expect(unknown.ruleLabel, 'MYSTERY');
    });

    test('tolerates missing optional numeric fields', () {
      final sparse = Proposal.fromJson({
        'id': 1,
        'batch_id': 'b',
        'proposal_date': '2026-07-13',
        'stock_code': '000660',
        'side': 'BUY',
        'qty': 3,
        'status': 'SUBMITTED',
        'created_at': '2026-07-13T18:40:05',
        'reason': {'rule': 'REBALANCE'},
      });
      expect(sparse.limitPrice, isNull);
      expect(sparse.estimatedNotional, isNull);
      expect(sparse.isBuy, isTrue);
      expect(sparse.status, ProposalStatus.submitted);
    });
  });
}
