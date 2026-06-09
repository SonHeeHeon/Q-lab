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
