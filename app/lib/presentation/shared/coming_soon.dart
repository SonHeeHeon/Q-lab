/// File: app/lib/presentation/shared/coming_soon.dart
///
/// Reusable placeholder widget used by screens whose full implementation
/// is still pending (Phase 5 step ≥ 3). Keeps go_router routes resolvable
/// and shows users the screen's planned purpose.
library;

import 'package:flutter/material.dart';

class ComingSoon extends StatelessWidget {
  const ComingSoon({
    super.key,
    required this.title,
    required this.subtitle,
    this.icon = Icons.construction_outlined,
  });

  final String title;
  final String subtitle;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 64, color: theme.colorScheme.primary),
              const SizedBox(height: 16),
              Text(title, style: theme.textTheme.headlineSmall),
              const SizedBox(height: 8),
              Text(
                subtitle,
                style: theme.textTheme.bodyMedium,
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 16),
              Chip(label: Text('🚧 Coming soon — Phase 5 step ≥ 3')),
            ],
          ),
        ),
      ),
    );
  }
}
