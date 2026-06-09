/// File: app/lib/presentation/quant/quant_screen.dart
///
/// Role:
///   Quant & AI screen container. Hosts a 2-tab TabBar:
///     - Tab 1: insights_tab/insights_screen.dart
///              (today's undervalued list + LLM commentary)
///     - Tab 2: backtest_lab/backtest_lab_screen.dart
///              (in-app equation builder + backtest runner)
///
/// Tab persistence:
///   The selected tab is preserved across navigations within a session
///   via Riverpod state. Deep-link `/quant/backtest` jumps directly to Tab 2.
///
/// Connected modules:
///   - presentation/quant/insights_tab/
///   - presentation/quant/backtest_lab/
///   - core/routes.dart (deep links)
