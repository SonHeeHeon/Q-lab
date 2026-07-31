import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/data/api/accounts_api.dart';

void main() {
  test('AccountProfileInfo parses sleeves and defaults', () {
    final info = AccountProfileInfo.fromJson({
      'account_key': 'KIS:DC',
      'broker': 'KIS',
      'account_type': 'DC',
      'profile_type': 'DC',
      'quant_enabled': false,
      'connected': false,
      'sleeves': [
        {'type': 'strategy', 'name': 'dc_risk_rotation_kr', 'weight': 0.68},
        {'type': 'hold', 'code': '153130', 'weight': 0.32},
      ],
    });
    expect(info.accountKey, 'KIS:DC');
    expect(info.quantEnabled, isFalse);
    expect(info.sleeves.length, 2);
    expect(
      info.sleeves.fold<double>(0, (a, s) => a + s.weight),
      closeTo(1.0, 1e-9),
    );
    expect(info.sleeves[1].label, '고정보유 153130');
  });

  test('SleeveConfig round-trips toJson', () {
    final sleeve = SleeveConfig(
      type: 'strategy',
      name: 'etf_rotation_kr',
      weight: 0.3,
    );
    expect(sleeve.toJson(), {
      'type': 'strategy',
      'name': 'etf_rotation_kr',
      'weight': 0.3,
    });
    expect(sleeve.copyWith(weight: 0.5).weight, 0.5);
  });
}
