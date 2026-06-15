/// File: app/lib/presentation/heatmap/session_badge.dart
///
/// "🕒 HH:mm 기준 (정규장)" badge shown alongside the heatmap. Includes
/// a compact refresh button and an ℹ️ icon (with tooltip) that explains
/// extended-hours liquidity risk when the session is PRE_MARKET or
/// AFTER_HOURS.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../data/api/heatmap_api.dart';
import 'heatmap_controller.dart';

final _hhmm = DateFormat('HH:mm');

class SessionBadge extends ConsumerWidget {
  const SessionBadge({
    super.key,
    required this.response,
    this.compact = false,
  });

  final HeatmapResponse response;

  /// When true, omits the relative-time suffix and uses smaller padding.
  /// Used by the embedded mini-heatmap on Insights.
  final bool compact;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final session = response.session;
    final updatedAt = response.updatedAt?.toLocal();
    final lastClient = ref.watch(lastClientRefreshProvider);

    final color = _sessionColor(session);
    final label = updatedAt == null
        ? '🕒 시각 미상 (${session.label})'
        : '🕒 ${_hhmm.format(updatedAt)} 기준 (${session.label})';

    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 8 : 12,
        vertical: compact ? 4 : 6,
      ),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        border: Border.all(color: color.withValues(alpha: 0.4)),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              color: color,
              shape: BoxShape.circle,
              boxShadow: session == MarketSession.regular
                  ? [
                      BoxShadow(
                        color: color.withValues(alpha: 0.6),
                        blurRadius: 6,
                      ),
                    ]
                  : null,
            ),
          ),
          const SizedBox(width: 8),
          Text(
            label,
            style: (compact ? theme.textTheme.labelMedium : theme.textTheme.bodyMedium)?.copyWith(
              color: color,
              fontWeight: FontWeight.w700,
            ),
          ),
          if (session.isExtended) ...[
            const SizedBox(width: 4),
            Tooltip(
              message: '시간외 거래는 유동성 부족으로 가격 변동성이 클 수 있습니다.\n'
                  '(${session.label}: '
                  '${session == MarketSession.preMarket ? '08:00–09:00 ATS' : '15:40–20:00 ATS'})',
              triggerMode: TooltipTriggerMode.tap,
              showDuration: const Duration(seconds: 6),
              child: Icon(
                Icons.info_outline,
                size: compact ? 14 : 16,
                color: color,
              ),
            ),
          ],
          if (!compact && lastClient != null) ...[
            const SizedBox(width: 8),
            Text(
              _relativeTime(lastClient),
              style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline),
            ),
          ],
          const SizedBox(width: 4),
          InkWell(
            borderRadius: BorderRadius.circular(12),
            onTap: () => ref.read(heatmapDataProvider.notifier).refresh(),
            child: Padding(
              padding: const EdgeInsets.all(2),
              child: Icon(Icons.refresh, size: compact ? 14 : 16, color: color),
            ),
          ),
        ],
      ),
    );
  }

  Color _sessionColor(MarketSession s) {
    switch (s) {
      case MarketSession.regular:
        return Colors.green;
      case MarketSession.preMarket:
        return Colors.blueAccent;
      case MarketSession.afterHours:
        return Colors.orange;
      case MarketSession.closed:
        return Colors.grey;
    }
  }

  String _relativeTime(DateTime t) {
    final diff = DateTime.now().difference(t);
    if (diff.inSeconds < 30) return '방금 갱신';
    if (diff.inMinutes < 1) return '${diff.inSeconds}초 전';
    if (diff.inMinutes < 60) return '${diff.inMinutes}분 전';
    return '${diff.inHours}시간 전';
  }
}
