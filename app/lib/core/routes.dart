/// File: app/lib/core/routes.dart
///
/// go_router configuration for the 9 service screens + the shell scaffold
/// (NavigationRail on wide screens, NavigationBar on phones).
///
/// Routes:
///   /                   → Home Dashboard
///   /portfolio          → Portfolio
///   /watchlist          → Watchlist
///   /trade-journal      → Trade Journal
///   /alerts             → Alert History
///   /heatmap            → Market Heatmap
///   /quant              → Quant & AI (Insights tab default)
///   /quant/backtest     → Quant & AI > Backtest Lab tab
///   /principles         → Principles & Notes
///   /settings           → Settings
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../presentation/alerts/alerts_screen.dart';
import '../presentation/heatmap/heatmap_screen.dart';
import '../presentation/home/home_screen.dart';
import '../presentation/portfolio/portfolio_screen.dart';
import '../presentation/principles/principles_screen.dart';
import '../presentation/quant/backtest_lab/backtest_lab_screen.dart';
import '../presentation/quant/backtest_lab/backtest_run_detail_screen.dart';
import '../presentation/quant/builder/builder_screen.dart';
import '../presentation/quant/insights_tab/insights_screen.dart';
import '../presentation/settings/settings_screen.dart';
import '../presentation/shell/app_shell.dart';
import '../presentation/stocks/stock_detail_screen.dart';
import '../presentation/stocks/stock_search_screen.dart';
import '../presentation/trade_journal/trade_journal_screen.dart';
import '../presentation/watchlist/watchlist_screen.dart';

class NavDestination {
  const NavDestination({required this.path, required this.label, required this.icon});
  final String path;
  final String label;
  final IconData icon;
}

const navDestinations = <NavDestination>[
  NavDestination(path: '/', label: '홈', icon: Icons.home_outlined),
  NavDestination(path: '/portfolio', label: '포트폴리오', icon: Icons.account_balance_wallet_outlined),
  NavDestination(path: '/stocks', label: '종목', icon: Icons.search_outlined),
  NavDestination(path: '/watchlist', label: '관심종목', icon: Icons.star_border),
  NavDestination(path: '/trade-journal', label: '매매일지', icon: Icons.menu_book_outlined),
  NavDestination(path: '/alerts', label: '알림·자동매매', icon: Icons.notifications_active_outlined),
  NavDestination(path: '/heatmap', label: '히트맵', icon: Icons.grid_view_outlined),
  NavDestination(path: '/quant', label: '퀀트', icon: Icons.analytics_outlined),
  NavDestination(path: '/principles', label: '투자원칙', icon: Icons.lightbulb_outline),
  NavDestination(path: '/settings', label: '설정', icon: Icons.settings_outlined),
];

final routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: '/',
    routes: [
      ShellRoute(
        builder: (context, state, child) => AppShell(location: state.matchedLocation, child: child),
        routes: [
          GoRoute(path: '/', builder: (_, __) => const HomeScreen()),
          GoRoute(path: '/portfolio', builder: (_, __) => const PortfolioScreen()),
          GoRoute(
            path: '/stocks',
            builder: (_, __) => const StockSearchScreen(),
            routes: [
              GoRoute(
                path: ':market/:code',
                builder: (_, state) => StockDetailScreen(
                  market: state.pathParameters['market']!,
                  code: Uri.decodeComponent(state.pathParameters['code']!),
                ),
              ),
            ],
          ),
          GoRoute(path: '/watchlist', builder: (_, __) => const WatchlistScreen()),
          GoRoute(path: '/trade-journal', builder: (_, __) => const TradeJournalScreen()),
          GoRoute(path: '/alerts', builder: (_, __) => const AlertsScreen()),
          GoRoute(path: '/heatmap', builder: (_, __) => const HeatmapScreen()),
          GoRoute(
            path: '/quant',
            builder: (_, __) => const InsightsScreen(),
            routes: [
              GoRoute(
                path: 'backtest',
                builder: (_, __) => const BacktestLabScreen(),
                routes: [
                  GoRoute(
                    path: 'runs/:run_id',
                    builder: (_, state) =>
                        BacktestRunDetailScreen(runId: state.pathParameters['run_id']!),
                  ),
                ],
              ),
              GoRoute(path: 'builder', builder: (_, __) => const BuilderScreen()),
            ],
          ),
          GoRoute(path: '/principles', builder: (_, __) => const PrinciplesScreen()),
          GoRoute(path: '/settings', builder: (_, __) => const SettingsScreen()),
        ],
      ),
    ],
  );
});
