/// File: app/lib/presentation/shell/app_shell.dart
///
/// Adaptive shell: NavigationRail on width ≥ 720, NavigationBar otherwise.
/// Wraps every screen behind the go_router ShellRoute (see core/routes.dart).
library;

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/routes.dart';
import '../../core/theme.dart';
import '../../core/config.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.location, required this.child});

  final String location;
  final Widget child;

  int _selectedIndex() {
    // longest-prefix match
    var bestIdx = 0;
    var bestLen = -1;
    for (var i = 0; i < navDestinations.length; i++) {
      final p = navDestinations[i].path;
      final isMatch = p == '/' ? location == '/' : location.startsWith(p);
      if (isMatch && p.length > bestLen) {
        bestIdx = i;
        bestLen = p.length;
      }
    }
    return bestIdx;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final width = MediaQuery.sizeOf(context).width;
    final isWide = width >= 720;
    final idx = _selectedIndex();

    void onTap(int i) => context.go(navDestinations[i].path);

    if (isWide) {
      return Scaffold(
        body: Row(
          children: [
            NavigationRail(
              selectedIndex: idx,
              onDestinationSelected: onTap,
              labelType: width >= 960
                  ? NavigationRailLabelType.all
                  : NavigationRailLabelType.selected,
              leading: const _AccountBadge(),
              destinations: [
                for (final d in navDestinations)
                  NavigationRailDestination(
                    icon: Icon(d.icon),
                    label: Text(d.label),
                  ),
              ],
            ),
            const VerticalDivider(width: 1),
            Expanded(child: child),
          ],
        ),
      );
    }

    return Scaffold(
      body: child,
      bottomNavigationBar: NavigationBar(
        selectedIndex: idx.clamp(0, 4),
        onDestinationSelected: onTap,
        destinations: [
          for (final d in navDestinations.take(5))
            NavigationDestination(icon: Icon(d.icon), label: d.label),
        ],
      ),
    );
  }
}

class _AccountBadge extends ConsumerWidget {
  const _AccountBadge();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final account = ref.watch(activeAccountProvider);
    final colors = Theme.of(context).extension<AccountColors>()!;
    final color = switch (account) {
      KisAccountType.real => colors.real,
      KisAccountType.isa => colors.isa,
      KisAccountType.paper => colors.paper,
    };
    final label = switch (account) {
      KisAccountType.real => '실전',
      KisAccountType.isa => 'ISA',
      KisAccountType.paper => '모의',
    };
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Tooltip(
        message: '활성 계좌: $label',
        child: Container(
          width: 40,
          height: 40,
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.15),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: color, width: 2),
          ),
          alignment: Alignment.center,
          child: Text(label,
              style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 12)),
        ),
      ),
    );
  }
}
