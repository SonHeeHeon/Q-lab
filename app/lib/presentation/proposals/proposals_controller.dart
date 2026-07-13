/// File: app/lib/presentation/proposals/proposals_controller.dart
///
/// Riverpod state for the "오늘의 제안" (order proposals) screen.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/proposals_api.dart';
import '../../domain/entities/proposal.dart';

/// Filter tabs: 대기(PROPOSED) is the actionable default.
enum ProposalFilter { pending, all, history }

final proposalFilterProvider =
    StateProvider<ProposalFilter>((ref) => ProposalFilter.pending);

final allProposalsProvider = FutureProvider<List<Proposal>>((ref) async {
  final list = await ref.read(proposalsApiProvider).list();
  list.sort((a, b) {
    // Actionable (PROPOSED) first, then most-recent.
    final r = (a.status.isActionable ? 0 : 1)
        .compareTo(b.status.isActionable ? 0 : 1);
    if (r != 0) return r;
    return b.createdAt.compareTo(a.createdAt);
  });
  return list;
});

final filteredProposalsProvider = Provider<List<Proposal>>((ref) {
  final all = ref.watch(allProposalsProvider).valueOrNull ?? const <Proposal>[];
  final filter = ref.watch(proposalFilterProvider);
  return switch (filter) {
    ProposalFilter.all => all,
    ProposalFilter.pending =>
      all.where((p) => p.status == ProposalStatus.proposed).toList(),
    ProposalFilter.history =>
      all.where((p) => !p.status.isActionable).toList(),
  };
});

/// Count of actionable proposals — drives the nav badge / home card.
final pendingProposalCountProvider = Provider<int>((ref) {
  final all = ref.watch(allProposalsProvider).valueOrNull ?? const <Proposal>[];
  return all.where((p) => p.status == ProposalStatus.proposed).length;
});
