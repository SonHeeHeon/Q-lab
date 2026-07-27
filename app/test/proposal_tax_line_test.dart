/// Test seed: taxLineFor renders the compact "예상 세금" line for a SELL
/// proposal's `reason` (backend batch/proposal_generator.py stamps
/// tax_type/est_sell_tax/est_gains_tax/tax_note post-build), and stays
/// silent for BUY-shaped / older / exempt reasons.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/presentation/proposals/proposals_screen.dart';

void main() {
  group('taxLineFor', () {
    test('renders 거래세 for a plain stock sell', () {
      final line = taxLineFor({
        'rule': 'STOP_LOSS',
        'tax_type': 'stock',
        'est_sell_tax': 750,
        'est_gains_tax': 0,
        'tax_note': '국내 상장주식(소액주주): 매도 시 증권거래세만 부과, 매매차익 비과세',
      });
      expect(line, '예상 세금 ~₩750 (거래세)');
    });

    test('renders 배당소득세 15.4% for a taxable ETF gain', () {
      final line = taxLineFor({
        'rule': 'REBALANCE',
        'tax_type': 'etf_taxable',
        'est_sell_tax': 0,
        'est_gains_tax': 7700,
        'tax_note': '기타/해외/채권/파생 ETF: ...',
      });
      expect(line, '예상 세금 ~₩7,700 (배당소득세 15.4%)');
    });

    test('sums est_sell_tax and est_gains_tax when both are nonzero', () {
      final line = taxLineFor({
        'tax_type': 'stock',
        'est_sell_tax': 1000,
        'est_gains_tax': 500,
      });
      expect(line, '예상 세금 ~₩1,500 (거래세)');
    });

    test('omits the line for a tax-free domestic-equity ETF (total is 0)', () {
      final line = taxLineFor({
        'tax_type': 'etf_domestic_equity',
        'est_sell_tax': 0,
        'est_gains_tax': 0,
        'tax_note': '국내주식형 ETF: 증권거래세 없음, 매매차익 비과세',
      });
      expect(line, isNull);
    });

    test('omits the line when tax_type is unknown', () {
      final line = taxLineFor({
        'tax_type': 'unknown',
        'est_sell_tax': 0,
        'est_gains_tax': 0,
        'tax_note': '과세 분류 미등록',
      });
      expect(line, isNull);
    });

    test('omits the line for a BUY-shaped reason with no tax keys at all', () {
      expect(taxLineFor({'rule': 'REBALANCE'}), isNull);
    });

    test('omits the line for an older persisted reason predating this contract', () {
      expect(taxLineFor({'rule': 'BAND_TRIM', 'threshold': 0.15}), isNull);
    });
  });
}
