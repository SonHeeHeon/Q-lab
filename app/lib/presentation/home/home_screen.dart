/// File: app/lib/presentation/home/home_screen.dart
///
/// Home Dashboard — the first screen the user sees every morning.
/// Cards (top → bottom):
///   1. Today's P&L (sum across 3 KIS accounts)
///   2. Market status (KOSPI + KOSDAQ)
///   3. Pending alerts (preview)
///   4. Today's triggered alerts
///   5. Top movers in portfolio
///
/// See PROJECT_BLUEPRINT.md §9.1 for the ASCII wireframe.
library;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../core/env.dart';
import '../../data/api/portfolio_api.dart';
import '../../domain/entities/account.dart';
import '../../domain/entities/alert.dart';
import '../../domain/entities/position.dart';
import 'home_controller.dart';

// intl 의 explicit locale 인자는 web 빌드에서 ko_KR locale 데이터가 번들에
// 포함되지 않아 내부적으로 null cast 를 던지는 사례가 있다. 안전하게 default
// locale(en_US) + 통화 심볼만 override 하는 방식으로 우회.
final _krw = NumberFormat.currency(symbol: '₩', decimalDigits: 0);
final _pct = NumberFormat('+0.00;-0.00');
final _hhmm = DateFormat('HH:mm');

String _dateKo(DateTime d) => '${d.month}월 ${d.day}일';

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final snapshot = ref.watch(homeSnapshotProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Q-Lab'),
        actions: [
          if (Env.useMock)
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 8),
              child: Chip(
                label: Text('MOCK', style: TextStyle(fontSize: 11)),
                visualDensity: VisualDensity.compact,
              ),
            ),
          IconButton(
            tooltip: '알림',
            icon: const Icon(Icons.notifications_outlined),
            onPressed: () => context.go('/alerts'),
          ),
          IconButton(
            tooltip: '설정',
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => context.go('/settings'),
          ),
          IconButton(
            tooltip: '새로고침',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(homeSnapshotProvider),
          ),
        ],
      ),
      body: snapshot.when(
        data: (s) => RefreshIndicator(
          onRefresh: () async => ref.invalidate(homeSnapshotProvider),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              _PnlCard(balance: s.balance),
              const SizedBox(height: 12),
              _PendingAlertsCard(alerts: s.pendingAlerts),
              const SizedBox(height: 12),
              _TriggeredTodayCard(alerts: s.triggeredToday),
              const SizedBox(height: 12),
              if (!s.alertsAvailable) const _AlertsUnavailableCard(),
              const SizedBox(height: 12),
              _TopMoversCard(positions: s.topMovers),
              const SizedBox(height: 24),
            ],
          ),
        ),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, st) {
          // Diagnostic: full stack trace in browser console (F12 → Console).
          debugPrint('Home snapshot error: $e\n$st');
          return _ErrorView(
            error: e,
            stack: st,
            onRetry: () => ref.invalidate(homeSnapshotProvider),
          );
        },
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Cards
// ---------------------------------------------------------------------------

class _SectionCard extends StatelessWidget {
  const _SectionCard({required this.title, required this.child, this.onTap, this.trailing});
  final String title;
  final Widget child;
  final Widget? trailing;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      color: theme.colorScheme.surfaceContainerHighest,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(title, style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                  ),
                  if (trailing != null) trailing!,
                ],
              ),
              const SizedBox(height: 12),
              child,
            ],
          ),
        ),
      ),
    );
  }
}

class _PnlCard extends StatelessWidget {
  const _PnlCard({required this.balance});
  final UnifiedBalance balance;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isUp = balance.totalPl >= 0;
    final plColor = isUp ? Colors.redAccent : Colors.blueAccent;

    return _SectionCard(
      title: '📊 오늘의 평가손익',
      trailing: Text(
        _dateKo(balance.asOf),
        style: theme.textTheme.bodySmall,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Text(
                '${isUp ? '+' : ''}${_krw.format(balance.totalPl)}',
                style: theme.textTheme.headlineMedium?.copyWith(
                  color: plColor,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(width: 12),
              Text(
                '${_pct.format(balance.totalPlPct)}%',
                style: theme.textTheme.titleMedium?.copyWith(color: plColor),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            '총 평가금액  ${_krw.format(balance.totalValue)}',
            style: theme.textTheme.bodyMedium,
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              for (final a in balance.accounts) ...[
                Expanded(child: _AccountPill(account: a)),
                if (a != balance.accounts.last) const SizedBox(width: 8),
              ],
            ],
          ),
        ],
      ),
    );
  }
}

class _AccountPill extends StatelessWidget {
  const _AccountPill({required this.account});
  final AccountSummary account;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isUp = account.totalPl >= 0;
    final plColor = isUp ? Colors.redAccent : Colors.blueAccent;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: theme.colorScheme.surface,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(account.accountType.wire, style: theme.textTheme.labelSmall),
          const SizedBox(height: 2),
          Text(_krw.format(account.totalValue),
              style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
          Text('${_pct.format(account.totalPlPct)}%',
              style: theme.textTheme.bodySmall?.copyWith(color: plColor)),
        ],
      ),
    );
  }
}

class _AlertsUnavailableCard extends StatelessWidget {
  const _AlertsUnavailableCard();
  @override
  Widget build(BuildContext context) {
    return _SectionCard(
      title: '🔔 알림',
      child: Text(
        '백엔드의 /api/alerts 엔드포인트가 아직 구현되지 않았습니다.\n(Codex Phase 5 백엔드 후속 작업)',
        style: Theme.of(context).textTheme.bodyMedium,
      ),
    );
  }
}

// (Market Status card removed — backend exposes no equivalent endpoint
// in Phase 4. Will return when `/api/quant/market-status` or similar
// ships in a later phase.)

class _PendingAlertsCard extends StatelessWidget {
  const _PendingAlertsCard({required this.alerts});
  final List<Alert> alerts;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return _SectionCard(
      title: '🔔 대기 중인 알림 (${alerts.length})',
      onTap: () => context.go('/alerts'),
      child: alerts.isEmpty
          ? Text('등록된 알림이 없습니다.', style: theme.textTheme.bodyMedium)
          : Column(
              children: [
                for (final a in alerts.take(3))
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.notifications_active_outlined),
                    title: Text('${a.stockName} (${a.stockCode})'),
                    subtitle: Text('${a.condition.label}  ${_formatThreshold(a)}'),
                  ),
              ],
            ),
    );
  }
}

class _TriggeredTodayCard extends StatelessWidget {
  const _TriggeredTodayCard({required this.alerts});
  final List<Alert> alerts;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return _SectionCard(
      title: '🚨 오늘 발동된 알림 (${alerts.length})',
      onTap: () => context.go('/alerts'),
      child: alerts.isEmpty
          ? Text('오늘 발동된 알림이 없습니다.', style: theme.textTheme.bodyMedium)
          : Column(
              children: [
                for (final a in alerts)
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.bolt, color: Colors.amber),
                    title: Text('${a.stockName} (${a.stockCode})'),
                    subtitle: Text(
                      '${_hhmm.format(a.triggeredAt!.toLocal())}  ${a.condition.label}  ${_formatThreshold(a)}',
                    ),
                  ),
              ],
            ),
    );
  }
}

class _TopMoversCard extends StatelessWidget {
  const _TopMoversCard({required this.positions});
  final List<Position> positions;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return _SectionCard(
      title: '📈 포트폴리오 Top Movers',
      onTap: () => context.go('/portfolio'),
      child: positions.isEmpty
          ? Text('보유 종목이 없습니다.', style: theme.textTheme.bodyMedium)
          : Column(
              children: [
                for (var i = 0; i < positions.length; i++)
                  _MoverRow(rank: i + 1, position: positions[i]),
              ],
            ),
    );
  }
}

class _MoverRow extends StatelessWidget {
  const _MoverRow({required this.rank, required this.position});
  final int rank;
  final Position position;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isUp = position.unrealizedPlPct >= 0;
    final color = isUp ? Colors.redAccent : Colors.blueAccent;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          SizedBox(width: 24, child: Text('$rank.', style: theme.textTheme.bodyMedium)),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(position.stockName,
                    style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
                Text('${position.stockCode}  ·  ${position.quantity}주',
                    style: theme.textTheme.bodySmall),
              ],
            ),
          ),
          Text(
            '${_pct.format(position.unrealizedPlPct)}%',
            style: theme.textTheme.titleMedium?.copyWith(color: color, fontWeight: FontWeight.w700),
          ),
        ],
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.error, required this.stack, required this.onRetry});
  final Object error;
  final StackTrace stack;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 720),
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Icon(Icons.error_outline, size: 48),
              const SizedBox(height: 8),
              const Text('데이터를 불러오지 못했습니다.', textAlign: TextAlign.center),
              const SizedBox(height: 12),
              SelectableText(
                '$error',
                style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.error),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 12),
              ExpansionTile(
                title: const Text('Stack trace'),
                childrenPadding: const EdgeInsets.all(12),
                children: [
                  SelectableText(
                    stack.toString(),
                    style: const TextStyle(fontFamily: 'monospace', fontSize: 11),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              FilledButton(onPressed: onRetry, child: const Text('다시 시도')),
            ],
          ),
        ),
      ),
    );
  }
}

String _formatThreshold(Alert a) {
  switch (a.condition) {
    case AlertCondition.priceAbove:
    case AlertCondition.priceBelow:
      return _krw.format(a.threshold);
    case AlertCondition.pctChange:
      return '${_pct.format(a.threshold)}%';
    case AlertCondition.volumeSpike:
      return '${a.threshold.toStringAsFixed(0)}x';
  }
}
