/// File: app/lib/presentation/principles/principles_screen.dart
///
/// Principles & Notes — see PROJECT_BLUEPRINT.md §9.8.
/// Three sections grouped by category:
///   - 🚫 절대 원칙 (ABSOLUTE) — read-only when is_editable=false
///   - 🎯 판단 기준 (CRITERIA)
///   - 📝 자유 노트 (FREE_NOTE) — long-form markdown
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../data/api/principles_api.dart';
import '../../shared/widgets/empty_state.dart';
import 'principles_controller.dart';

final _fmt = DateFormat('yyyy-MM-dd');

class PrinciplesScreen extends ConsumerWidget {
  const PrinciplesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(principlesProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('투자 원칙 & 노트'),
        actions: [
          IconButton(
            tooltip: '새로고침',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(principlesProvider),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.add),
        label: const Text('원칙 추가'),
        onPressed: () => _showCreateDialog(context, ref),
      ),
      body: async.when(
        data: (_) => _Body(),
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
                  onPressed: () => ref.invalidate(principlesProvider),
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

class _Body extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final grouped = ref.watch(principlesByCategoryProvider);
    if (grouped.isEmpty) {
      return EmptyState(
        icon: Icons.lightbulb_outline,
        title: '아직 등록된 투자 원칙이 없습니다',
        subtitle: '나만의 매매 원칙을 정의하면 AI 매매일지 복기 시 위반 여부를 분석해 알려드려요.',
        action: FilledButton.icon(
          icon: const Icon(Icons.add),
          label: const Text('첫 원칙 추가'),
          onPressed: () => _showCreateDialog(context, ref),
        ),
      );
    }
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _CategorySection(
          title: '🚫 절대 원칙',
          subtitle: '어떤 상황에서도 어기지 않는 규칙. 변경/삭제가 제한될 수 있습니다.',
          items: grouped.absolute,
          color: Colors.redAccent,
        ),
        const SizedBox(height: 24),
        _CategorySection(
          title: '🎯 판단 기준',
          subtitle: '매매 시 적용할 평가 기준 (지표, 임계값 등).',
          items: grouped.criteria,
          color: Colors.orange,
        ),
        const SizedBox(height: 24),
        _CategorySection(
          title: '📝 자유 노트',
          subtitle: '학습 메모, 관찰, 아이디어를 자유롭게.',
          items: grouped.freeNotes,
          color: Colors.blueAccent,
        ),
        const SizedBox(height: 80),
      ],
    );
  }
}

class _CategorySection extends ConsumerWidget {
  const _CategorySection({
    required this.title,
    required this.subtitle,
    required this.items,
    required this.color,
  });
  final String title;
  final String subtitle;
  final List<Principle> items;
  final Color color;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(title,
            style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800, color: color)),
        const SizedBox(height: 2),
        Text(subtitle, style: theme.textTheme.bodySmall),
        const SizedBox(height: 8),
        if (items.isEmpty)
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: theme.colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: theme.colorScheme.outlineVariant),
            ),
            child: Row(
              children: [
                Icon(Icons.add_circle_outline, color: theme.colorScheme.outline),
                const SizedBox(width: 8),
                Text('이 카테고리에 항목이 없습니다.',
                    style: theme.textTheme.bodySmall),
              ],
            ),
          )
        else
          for (final p in items) ...[
            _PrincipleCard(principle: p, accent: color),
            const SizedBox(height: 8),
          ],
      ],
    );
  }
}

class _PrincipleCard extends ConsumerWidget {
  const _PrincipleCard({required this.principle, required this.accent});
  final Principle principle;
  final Color accent;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(width: 4, height: 18, color: accent),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(principle.title,
                      style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
                ),
                if (!principle.isEditable)
                  Tooltip(
                    message: '변경 불가 (시스템/시드 원칙)',
                    child: Icon(Icons.lock_outline, size: 16, color: theme.colorScheme.outline),
                  ),
                PopupMenuButton<String>(
                  enabled: principle.isEditable,
                  icon: Icon(
                    Icons.more_vert,
                    color: principle.isEditable
                        ? theme.colorScheme.onSurface
                        : theme.colorScheme.outline.withValues(alpha: 0.3),
                  ),
                  onSelected: (v) async {
                    if (v == 'edit') {
                      await _showEditDialog(context, ref, principle);
                    } else if (v == 'delete') {
                      await _confirmDelete(context, ref, principle);
                    }
                  },
                  itemBuilder: (_) => const [
                    PopupMenuItem(value: 'edit', child: Text('편집')),
                    PopupMenuItem(value: 'delete', child: Text('삭제')),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(principle.body, style: theme.textTheme.bodyMedium),
            const SizedBox(height: 6),
            Text('업데이트 ${_fmt.format(principle.updatedAt.toLocal())}',
                style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline)),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Dialogs
// ---------------------------------------------------------------------------

Future<void> _showCreateDialog(BuildContext context, WidgetRef ref) async {
  final title = TextEditingController();
  final body = TextEditingController();
  PrincipleCategory cat = PrincipleCategory.criteria;
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setState) => AlertDialog(
        title: const Text('원칙 추가'),
        content: SizedBox(
          width: 480,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              DropdownButtonFormField<PrincipleCategory>(
                initialValue: cat,
                decoration: const InputDecoration(labelText: '카테고리'),
                items: [
                  for (final c in PrincipleCategory.values)
                    DropdownMenuItem(value: c, child: Text(c.label)),
                ],
                onChanged: (v) => setState(() => cat = v ?? cat),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: title,
                decoration: const InputDecoration(labelText: '제목'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: body,
                maxLines: 5,
                minLines: 3,
                decoration: const InputDecoration(
                  labelText: '본문',
                  hintText: '예: 손절선을 -5% 로 사전 설정한 종목만 진입한다.',
                  border: OutlineInputBorder(),
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('취소')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('저장')),
        ],
      ),
    ),
  );
  if (ok != true) return;
  final t = title.text.trim();
  final b = body.text.trim();
  if (t.isEmpty || b.isEmpty) return;
  try {
    await ref.read(principlesApiProvider).create(title: t, body: b, category: cat);
    ref.invalidate(principlesProvider);
  } catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('저장 실패: $e'), backgroundColor: Colors.redAccent),
      );
    }
  }
}

Future<void> _showEditDialog(BuildContext context, WidgetRef ref, Principle p) async {
  final title = TextEditingController(text: p.title);
  final body = TextEditingController(text: p.body);
  PrincipleCategory cat = p.category;
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setState) => AlertDialog(
        title: Text('원칙 편집 — ${p.title}'),
        content: SizedBox(
          width: 480,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              DropdownButtonFormField<PrincipleCategory>(
                initialValue: cat,
                decoration: const InputDecoration(labelText: '카테고리'),
                items: [
                  for (final c in PrincipleCategory.values)
                    DropdownMenuItem(value: c, child: Text(c.label)),
                ],
                onChanged: (v) => setState(() => cat = v ?? cat),
              ),
              const SizedBox(height: 12),
              TextField(controller: title, decoration: const InputDecoration(labelText: '제목')),
              const SizedBox(height: 12),
              TextField(
                controller: body,
                maxLines: 6,
                minLines: 3,
                decoration: const InputDecoration(labelText: '본문', border: OutlineInputBorder()),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('취소')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('저장')),
        ],
      ),
    ),
  );
  if (ok != true) return;
  final t = title.text.trim();
  final b = body.text.trim();
  if (t.isEmpty || b.isEmpty) return;
  try {
    await ref.read(principlesApiProvider).patch(
      p.id,
      title: t == p.title ? null : t,
      body: b == p.body ? null : b,
      category: cat == p.category ? null : cat,
    );
    ref.invalidate(principlesProvider);
  } catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('저장 실패: $e')));
    }
  }
}

Future<void> _confirmDelete(BuildContext context, WidgetRef ref, Principle p) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: const Text('삭제'),
      content: Text('"${p.title}" 원칙을 삭제할까요?'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('취소')),
        FilledButton(
          style: FilledButton.styleFrom(backgroundColor: Colors.redAccent),
          onPressed: () => Navigator.pop(ctx, true),
          child: const Text('삭제'),
        ),
      ],
    ),
  );
  if (ok != true) return;
  try {
    await ref.read(principlesApiProvider).delete(p.id);
    ref.invalidate(principlesProvider);
  } catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('삭제 실패: $e')));
    }
  }
}
