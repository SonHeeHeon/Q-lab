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
            // 창 높이가 낮으면 목적지 수만큼 rail 내부 Column이 넘쳐(RenderFlex
            // overflow) 노란 줄무늬가 뜬다. 스크롤 가능하게 감싸되 minHeight로
            // 평소(높이 충분할 때) 레이아웃은 그대로 유지한다.
            LayoutBuilder(
              builder: (context, constraints) => SingleChildScrollView(
                child: ConstrainedBox(
                  constraints:
                      BoxConstraints(minHeight: constraints.maxHeight),
                  child: IntrinsicHeight(
                    child: NavigationRail(
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
                  ),
                ),
              ),
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
        selectedIndex: idx >= 4 ? 4 : idx,
        onDestinationSelected: (i) => i == 4 ? _showMoreSheet(context) : onTap(i),
        destinations: [
          for (final d in navDestinations.take(4))
            NavigationDestination(icon: Icon(d.icon), label: d.label),
          const NavigationDestination(icon: Icon(Icons.more_horiz), label: '더보기'),
        ],
      ),
    );
  }

  /// Bottom sheet listing every destination beyond the first 4 tabs (built
  /// dynamically from [navDestinations] so new destinations show up here
  /// automatically without further edits).
  void _showMoreSheet(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            for (final d in navDestinations.skip(4))
              ListTile(
                leading: Icon(d.icon),
                title: Text(d.label),
                onTap: () {
                  Navigator.pop(sheetContext);
                  context.go(d.path);
                },
              ),
          ],
        ),
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
