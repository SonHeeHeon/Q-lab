/// File: app/lib/presentation/quant/insights_tab/insights_controller.dart
///
/// Riverpod state for the Quant & AI — Insights tab.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../data/api/quant_api.dart';

/// User-selected analysis date. Null = backend chooses latest available.
final insightsDateProvider = StateProvider<DateTime?>((ref) => null);

final undervaluedReportProvider = FutureProvider<UndervaluedReport>((ref) {
  final date = ref.watch(insightsDateProvider);
  return ref.read(quantApiProvider).getUndervalued(date: date);
});

/// 슬리브별 저평가 top10 — 주간 배치(run_weekly_sleeve_insights)가 채운 최신
/// 스냅샷을 전략 이름으로 조회한다(날짜 선택과 무관하게 항상 최신).
final sleeveReportProvider =
    FutureProvider.family<UndervaluedReport, String>((ref, strategyName) {
  return ref.read(quantApiProvider).getUndervalued(strategyName: strategyName);
});
