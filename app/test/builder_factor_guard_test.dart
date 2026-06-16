/// Test seed: validates that the equation builder doesn't silently
/// duplicate factors once the catalog is exhausted (was HIGH bug A5).
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/presentation/quant/builder/builder_controller.dart';

void main() {
  test('addFactor stops adding once catalog is exhausted', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);

    final notifier = container.read(builderProvider.notifier);

    // Default state has 1 factor. Top up to the catalog size.
    while (notifier.state.draft.factors.length < kFactorCatalog.length) {
      final before = notifier.state.draft.factors.length;
      notifier.addFactor();
      final after = notifier.state.draft.factors.length;
      expect(after, before + 1,
          reason: 'addFactor must add exactly one until catalog exhausted');
    }

    expect(notifier.catalogExhausted, isTrue);

    // Further calls must be no-ops, NOT silent duplicates.
    final exhaustedSize = notifier.state.draft.factors.length;
    notifier.addFactor();
    notifier.addFactor();
    expect(notifier.state.draft.factors.length, exhaustedSize,
        reason: 'addFactor must not insert duplicates after catalog exhausted');

    // All factor codes must be distinct.
    final codes = notifier.state.draft.factors.map((f) => f.factor).toSet();
    expect(codes.length, notifier.state.draft.factors.length,
        reason: 'every factor in the draft must have a unique code');
  });
}
