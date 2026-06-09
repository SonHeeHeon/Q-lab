/// File: app/lib/domain/entities/account.dart
///
/// KIS account types — paper / real / isa.
/// Wire encoding mirrors backend's `AccountType` enum (uppercase strings).
library;

enum KisAccount {
  paper('PAPER'),
  real('REAL'),
  isa('ISA');

  const KisAccount(this.wire);
  final String wire;

  static KisAccount fromWire(String s) =>
      KisAccount.values.firstWhere((e) => e.wire == s.toUpperCase());

  String get label => switch (this) {
        KisAccount.paper => '모의',
        KisAccount.real => '실전',
        KisAccount.isa => 'ISA',
      };
}

class AccountSummary {
  AccountSummary({
    required this.accountType,
    required this.totalValue,
    required this.cashBalance,
    required this.totalPl,
    required this.totalPlPct,
  });

  final KisAccount accountType;
  final double totalValue;
  final double cashBalance;
  final double totalPl;
  final double totalPlPct;

  factory AccountSummary.fromJson(Map<String, dynamic> json) => AccountSummary(
        accountType: KisAccount.fromWire(json['account_type'] as String),
        totalValue: (json['total_value'] as num).toDouble(),
        cashBalance: (json['cash_balance'] as num).toDouble(),
        totalPl: (json['total_pl'] as num).toDouble(),
        totalPlPct: (json['total_pl_pct'] as num).toDouble(),
      );
}
