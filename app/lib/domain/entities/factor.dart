/// File: app/lib/domain/entities/factor.dart
///
/// Role:
///   Dart mirror of `shared.domain.factor.FactorValue` + helper types
///   for the Quant & AI Tab 1 factor-decomposition view and the
///   Backtest Lab factor list.
///
/// Helper types:
///   - FactorDecomposition: list of (factor, contribution_pct, value)
///   - FactorDescriptor: { name, description, transformOptions }
///
/// Connected modules:
///   - data/api/quant_api.dart, backtest_api.dart
///   - presentation/quant/insights_tab/ (decomposition bar chart)
///   - presentation/quant/backtest_lab/ (factor weight sliders)
