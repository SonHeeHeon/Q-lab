/// File: app/lib/presentation/alerts/alerts_screen.dart
///
/// Alert History — see PROJECT_BLUEPRINT.md §9.5. List view (Phase 5);
/// calendar grid will land in Phase 6 alongside the WS auto-refresh.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../data/api/alerts_api.dart';
import '../../domain/entities/alert.dart';
import '../../shared/widgets/empty_state.dart';
import 'alerts_controller.dart';

final _dateTime = DateFormat('MM-dd HH:mm');
final _krw = NumberFormat('#,##0');

class AlertsScreen extends ConsumerWidget {
  const AlertsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final filter = ref.watch(alertFilterProvider);
    final async = ref.watch(allAlertsProvider);
    final filtered = ref.watch(filteredAlertsProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('알림 이력'),
        actions: [
          IconButton(
            tooltip: '새로고침',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(allAlertsProvider),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.add_alert_outlined),
        label: const Text('알림 추가'),
        onPressed: () => _showCreateDialog(context, ref),
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: SegmentedButton<AlertFilter>(
              segments: const [
                ButtonSegment(value: AlertFilter.all, label: Text('전체')),
                ButtonSegment(value: AlertFilter.pending, label: Text('대기')),
                ButtonSegment(value: AlertFilter.triggered, label: Text('발동')),
                ButtonSegment(value: AlertFilter.cancelled, label: Text('취소')),
              ],
              selected: {filter},
              onSelectionChanged: (s) =>
                  ref.read(alertFilterProvider.notifier).state = s.first,
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: async.when(
              data: (_) => filtered.isEmpty
                  ? const _EmptyState()
                  : ListView.separated(
                      itemCount: filtered.length,
                      separatorBuilder: (_, __) => const Divider(height: 1),
                      itemBuilder: (_, i) => _AlertRow(alert: filtered[i]),
                    ),
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.error_outline, size: 48),
                      const SizedBox(height: 8),
                      SelectableText('$e', textAlign: TextAlign.center),
                      const SizedBox(height: 12),
                      FilledButton(
                        onPressed: () => ref.invalidate(allAlertsProvider),
                        child: const Text('다시 시도'),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _AlertRow extends ConsumerWidget {
  const _AlertRow({required this.alert});
  final Alert alert;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final (icon, color, label) = switch (alert.status) {
      AlertStatus.pending => (Icons.notifications_active_outlined, theme.colorScheme.primary, '대기'),
      AlertStatus.triggered => (Icons.bolt, Colors.amber, '발동'),
      AlertStatus.cancelled => (Icons.cancel_outlined, theme.colorScheme.outline, '취소'),
    };
    final ts = alert.triggeredAt ?? alert.createdAt;

    return ListTile(
      isThreeLine: alert.postMortem != null,
      leading: CircleAvatar(
        backgroundColor: color.withValues(alpha: 0.15),
        child: Icon(icon, color: color),
      ),
      title: Row(
        children: [
          Text('${alert.stockName}  ·  ${alert.stockCode}',
              style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(width: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Text(label, style: TextStyle(color: color, fontSize: 11)),
          ),
        ],
      ),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${alert.condition.label}  ${_formatThreshold(alert)}  ·  '
              '${_dateTime.format(ts.toLocal())}',
              style: theme.textTheme.bodySmall,
            ),
            if (alert.postMortem != null && alert.postMortem!.trim().isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text('📝 ${alert.postMortem}',
                    style: theme.textTheme.bodySmall),
              ),
          ],
        ),
      ),
      trailing: PopupMenuButton<String>(
        onSelected: (v) async {
          if (v == 'cancel') {
            await _cancel(context, ref, alert);
          } else if (v == 'post') {
            await _editPostMortemDialog(context, ref, alert);
          }
        },
        itemBuilder: (_) => [
          if (alert.status == AlertStatus.pending)
            const PopupMenuItem(value: 'cancel', child: Text('알림 취소')),
          if (alert.status == AlertStatus.triggered)
            const PopupMenuItem(value: 'post', child: Text('사후 코멘트')),
        ],
      ),
    );
  }
}

String _formatThreshold(Alert a) {
  switch (a.condition) {
    case AlertCondition.priceAbove:
    case AlertCondition.priceBelow:
      return '₩${_krw.format(a.threshold)}';
    case AlertCondition.pctChange:
      return '${a.threshold.toStringAsFixed(2)}%';
    case AlertCondition.volumeSpike:
      return '${a.threshold.toStringAsFixed(0)}x';
  }
}

Future<void> _cancel(BuildContext context, WidgetRef ref, Alert a) async {
  try {
    await ref.read(alertsApiProvider).cancel(a.id);
    ref.invalidate(allAlertsProvider);
  } catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('취소 실패: $e')));
    }
  }
}

Future<void> _editPostMortemDialog(BuildContext context, WidgetRef ref, Alert a) async {
  final ctrl = TextEditingController(text: a.postMortem ?? '');
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text('${a.stockName} 사후 코멘트'),
      content: TextField(
        controller: ctrl,
        maxLines: 5,
        minLines: 3,
        decoration: const InputDecoration(
          labelText: '코멘트 (대응 결과, 배운점 등)',
          border: OutlineInputBorder(),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('취소')),
        FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('저장')),
      ],
    ),
  );
  if (ok != true) return;
  try {
    await ref.read(alertsApiProvider).updatePostMortem(a.id, ctrl.text.trim());
    ref.invalidate(allAlertsProvider);
  } catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('저장 실패: $e')));
    }
  }
}

Future<void> _showCreateDialog(BuildContext context, WidgetRef ref) async {
  final codeCtrl = TextEditingController();
  final thresholdCtrl = TextEditingController();
  AlertCondition cond = AlertCondition.priceAbove;

  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setState) => AlertDialog(
        title: const Text('알림 추가'),
        content: SizedBox(
          width: 360,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: codeCtrl,
                decoration: const InputDecoration(labelText: '종목 코드'),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<AlertCondition>(
                initialValue: cond,
                decoration: const InputDecoration(labelText: '조건'),
                items: [
                  for (final c in AlertCondition.values)
                    DropdownMenuItem(value: c, child: Text(c.label)),
                ],
                onChanged: (v) => setState(() => cond = v ?? cond),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: thresholdCtrl,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(labelText: '임계값'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('취소')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('생성')),
        ],
      ),
    ),
  );
  if (ok != true) return;
  final code = codeCtrl.text.trim();
  final threshold = double.tryParse(thresholdCtrl.text.trim());
  if (code.isEmpty || threshold == null) return;
  try {
    await ref.read(alertsApiProvider).create(
      stockCode: code,
      condition: cond,
      threshold: threshold,
    );
    ref.invalidate(allAlertsProvider);
  } catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('생성 실패: $e')));
    }
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();
  @override
  Widget build(BuildContext context) {
    return const EmptyState(
      icon: Icons.notifications_off_outlined,
      title: '등록된 알림이 없습니다',
      subtitle: '가격/변동률/거래량 등 트리거를 걸어두면 발동 시 텔레그램으로도 도착합니다.\n우측 하단 [알림 추가] 버튼으로 시작하세요.',
    );
  }
}
