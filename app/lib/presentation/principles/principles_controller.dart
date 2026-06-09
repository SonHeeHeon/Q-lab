/// File: app/lib/presentation/principles/principles_controller.dart
///
/// Riverpod state for the Principles & Notes screen.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/principles_api.dart';

final principlesProvider = FutureProvider<List<Principle>>((ref) {
  return ref.read(principlesApiProvider).list();
});

class PrinciplesByCategory {
  PrinciplesByCategory({required this.absolute, required this.criteria, required this.freeNotes});
  final List<Principle> absolute;
  final List<Principle> criteria;
  final List<Principle> freeNotes;
  bool get isEmpty => absolute.isEmpty && criteria.isEmpty && freeNotes.isEmpty;
}

final principlesByCategoryProvider = Provider<PrinciplesByCategory>((ref) {
  final list = ref.watch(principlesProvider).valueOrNull ?? const <Principle>[];
  return PrinciplesByCategory(
    absolute: list.where((p) => p.category == PrincipleCategory.absolute).toList(),
    criteria: list.where((p) => p.category == PrincipleCategory.criteria).toList(),
    freeNotes: list.where((p) => p.category == PrincipleCategory.freeNote).toList(),
  );
});
