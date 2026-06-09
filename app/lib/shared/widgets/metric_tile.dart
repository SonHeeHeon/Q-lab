/// File: app/lib/shared/widgets/metric_tile.dart
///
/// Role:
///   Reusable tile displaying a single labeled metric (label + value
///   + optional secondary text). Used in Home cards, Portfolio
///   summary row, and Backtest Lab result panel.
///
/// Props (planned):
///   - label: String                 // e.g. "CAGR", "MDD", "Sharpe", "Today P&L"
///   - value: String                 // formatted (incl. units)
///   - tone: MetricTone              // positive | negative | neutral (color)
///   - subtitle?: String
///   - onTap?: VoidCallback
///
/// Connected modules:
///   - presentation/home/, portfolio/, quant/backtest_lab/
