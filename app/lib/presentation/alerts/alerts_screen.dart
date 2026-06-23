/// File: app/lib/presentation/alerts/alerts_screen.dart
///
/// Alert History — see PROJECT_BLUEPRINT.md §9.5.
/// Two views: flat list (filter chips) and calendar month grid.
/// Toggle in AppBar: list ↔ calendar.
/// WS alert_triggered → allAlertsProvider.invalidateSelf → live re-fetch (B8).
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
final _monthFmt = DateFormat('yyyy년 M월');

class AlertsScreen extends ConsumerWidget {
  const AlertsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final filter = ref.watch(alertFilterProvider);
    final async = ref.watch(allAlertsProvider);
    final filtered = ref.watch(filteredAlertsProvider);
    final isCalendar = ref.watch(alertCalendarViewProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('알림 이력'),
        actions: [
          IconButton(
            tooltip: isCalendar ? '목록 보기' : '캘린더 보기',
            icon: Icon(isCalendar ? Icons.list_outlined : Icons.calendar_month_outlined),
            onPressed: () =>
                ref.read(alertCalendarViewProvider.notifier).state = !isCalendar,
          ),
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
      body: async.when(
        data: (_) => isCalendar
            ? _AlertCalendarView(alerts: ref.watch(allAlertsProvider).valueOrNull ?? [])
            : Column(
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
                    child: filtered.isEmpty
                        ? const _EmptyState()
                        : ListView.separated(
                            itemCount: filtered.length,
                            separatorBuilder: (_, __) => const Divider(height: 1),
                            itemBuilder: (_, i) => _AlertRow(alert: filtered[i]),
                          ),
                  ),
                ],
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
    );
  }
}

// ---------------------------------------------------------------------------
// Calendar grid view (B7)
// ---------------------------------------------------------------------------

class _AlertCalendarView extends StatefulWidget {
  const _AlertCalendarView({required this.alerts});
  final List<Alert> alerts;

  @override
  State<_AlertCalendarView> createState() => _AlertCalendarViewState();
}

class _AlertCalendarViewState extends State<_AlertCalendarView> {
  DateTime _month = DateTime(DateTime.now().year, DateTime.now().month);

  Map<String, List<Alert>> get _byDate {
    final map = <String, List<Alert>>{};
    for (final a in widget.alerts) {
      final ts = (a.triggeredAt ?? a.createdAt).toLocal();
      final key = '${ts.year}-${ts.month.toString().padLeft(2, '0')}-'
          '${ts.day.toString().padLeft(2, '0')}';
      map.putIfAbsent(key, () => []).add(a);
    }
    return map;
  }

  String _key(int year, int month, int day) =>
      '$year-${month.toString().padLeft(2, '0')}-${day.toString().padLeft(2, '0')}';

  void _prevMonth() => setState(() {
        _month = DateTime(_month.year, _month.month - 1);
      });

  void _nextMonth() => setState(() {
        _month = DateTime(_month.year, _month.month + 1);
      });

  void _onDayTap(BuildContext context, List<Alert> dayAlerts) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (_) => _DayAlertsSheet(alerts: dayAlerts),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final byDate = _byDate;

    // Build day list for the month grid.
    // We use Monday as the first column (Korean / ISO convention).
    final firstDay = DateTime(_month.year, _month.month, 1);
    final daysInMonth = DateTime(_month.year, _month.month + 1, 0).day;
    // weekday: 1=Mon, 7=Sun → offset from Monday column
    final startOffset = firstDay.weekday - 1; // 0=Mon, 6=Sun

    final totalCells = startOffset + daysInMonth;
    final rows = (totalCells / 7).ceil();

    return Column(
      children: [
        // Month navigation
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              IconButton(
                icon: const Icon(Icons.chevron_left),
                onPressed: _prevMonth,
              ),
              Text(
                _monthFmt.format(_month),
                style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
              ),
              IconButton(
                icon: const Icon(Icons.chevron_right),
                onPressed: _nextMonth,
              ),
            ],
          ),
        ),
        // Weekday header
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8),
          child: Row(
            children: [
              for (final d in ['월', '화', '수', '목', '금', '토', '일'])
                Expanded(
                  child: Center(
                    child: Text(
                      d,
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: d == '일'
                            ? Colors.redAccent
                            : d == '토'
                                ? Colors.blueAccent
                                : theme.colorScheme.onSurface,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
        const Divider(height: 8),
        // Calendar grid
        Expanded(
          child: GridView.builder(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 7,
              mainAxisSpacing: 4,
              crossAxisSpacing: 2,
              childAspectRatio: 0.8,
            ),
            itemCount: rows * 7,
            itemBuilder: (ctx, idx) {
              final dayNum = idx - startOffset + 1;
              if (dayNum < 1 || dayNum > daysInMonth) return const SizedBox.shrink();
              final key = _key(_month.year, _month.month, dayNum);
              final dayAlerts = byDate[key] ?? [];
              final today = DateTime.now();
              final isToday = today.year == _month.year &&
                  today.month == _month.month &&
                  today.day == dayNum;
              return _DayCell(
                day: dayNum,
                alerts: dayAlerts,
                isToday: isToday,
                isSunday: (idx % 7) == 6,
                isSaturday: (idx % 7) == 5,
                onTap: dayAlerts.isEmpty ? null : () => _onDayTap(ctx, dayAlerts),
              );
            },
          ),
        ),
      ],
    );
  }
}

class _DayCell extends StatelessWidget {
  const _DayCell({
    required this.day,
    required this.alerts,
    required this.isToday,
    required this.isSunday,
    required this.isSaturday,
    required this.onTap,
  });

  final int day;
  final List<Alert> alerts;
  final bool isToday;
  final bool isSunday;
  final bool isSaturday;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final hasTrigger = alerts.any((a) => a.status == AlertStatus.triggered);
    final hasPending = alerts.any((a) => a.status == AlertStatus.pending);

    Color dayColor;
    if (isSunday) {
      dayColor = Colors.redAccent;
    } else if (isSaturday) {
      dayColor = Colors.blueAccent;
    } else {
      dayColor = theme.colorScheme.onSurface;
    }

    return GestureDetector(
      onTap: onTap,
      child: Container(
        decoration: BoxDecoration(
          color: isToday
              ? theme.colorScheme.primaryContainer.withValues(alpha: 0.4)
              : alerts.isNotEmpty
                  ? theme.colorScheme.surfaceContainerHighest
                  : null,
          borderRadius: BorderRadius.circular(8),
          border: isToday
              ? Border.all(color: theme.colorScheme.primary, width: 1.5)
              : null,
        ),
        padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 2),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.start,
          children: [
            Text(
              '$day',
              style: theme.textTheme.bodySmall?.copyWith(
                color: dayColor,
                fontWeight: isToday ? FontWeight.w800 : FontWeight.normal,
              ),
            ),
            if (alerts.isNotEmpty) ...[
              const SizedBox(height: 2),
              Wrap(
                alignment: WrapAlignment.center,
                spacing: 2,
                runSpacing: 2,
                children: [
                  if (hasTrigger)
                    Container(
                      width: 7,
                      height: 7,
                      decoration: const BoxDecoration(
                        color: Colors.amber,
                        shape: BoxShape.circle,
                      ),
                    ),
                  if (hasPending)
                    Container(
                      width: 7,
                      height: 7,
                      decoration: BoxDecoration(
                        color: theme.colorScheme.primary,
                        shape: BoxShape.circle,
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 2),
              Text(
                '${alerts.length}건',
                style: const TextStyle(fontSize: 9, color: Colors.amber),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _DayAlertsSheet extends StatelessWidget {
  const _DayAlertsSheet({required this.alerts});
  final List<Alert> alerts;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('알림 ${alerts.length}건',
              style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          for (final a in alerts) ...[
            _DayAlertItem(alert: a),
            const Divider(height: 1),
          ],
        ],
      ),
    );
  }
}

class _DayAlertItem extends StatelessWidget {
  const _DayAlertItem({required this.alert});
  final Alert alert;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = switch (alert.status) {
      AlertStatus.triggered => Colors.amber,
      AlertStatus.pending => theme.colorScheme.primary,
      AlertStatus.cancelled => theme.colorScheme.outline,
    };
    final label = switch (alert.status) {
      AlertStatus.triggered => '발동',
      AlertStatus.pending => '대기',
      AlertStatus.cancelled => '취소',
    };
    final ts = (alert.triggeredAt ?? alert.createdAt).toLocal();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text('${alert.stockName}  ${alert.condition.label}',
                style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
          ),
          Text(DateFormat('HH:mm').format(ts),
              style: theme.textTheme.bodySmall),
          const SizedBox(width: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Text(label, style: TextStyle(color: color, fontSize: 11)),
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
