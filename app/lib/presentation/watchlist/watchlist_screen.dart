/// File: app/lib/presentation/watchlist/watchlist_screen.dart
///
/// Watchlist — see PROJECT_BLUEPRINT.md §9.3.
/// Category tabs (+ Add) · Entries per category with per-stock REASON ·
/// Add entry FAB · Delete via long-press / overflow menu.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../data/api/watchlist_api.dart';
import '../../shared/widgets/empty_state.dart';
import 'watchlist_controller.dart';

final _date = DateFormat('M/d');

class WatchlistScreen extends ConsumerWidget {
  const WatchlistScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncCats = ref.watch(categoriesProvider);
    final asyncEntries = ref.watch(entriesProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('관심종목'),
        actions: [
          IconButton(
            tooltip: '새로고침',
            icon: const Icon(Icons.refresh),
            onPressed: () {
              ref.invalidate(categoriesProvider);
              ref.invalidate(entriesProvider);
            },
          ),
        ],
      ),
      // FAB only when BOTH async streams have resolved AND categories
      // exist. Avoids the inconsistent state where categories errored
      // but entries succeeded (or vice versa), which previously left
      // the FAB enabled despite no usable destination category.
      floatingActionButton: () {
        final cats = asyncCats.valueOrNull;
        final entriesReady = asyncEntries.hasValue || asyncEntries.hasError;
        if (cats == null || !entriesReady || cats.isEmpty) return null;
        return FloatingActionButton.extended(
          onPressed: () => _showAddEntryDialog(context, ref, cats),
          icon: const Icon(Icons.add),
          label: const Text('종목 추가'),
        );
      }(),
      body: asyncCats.when(
        data: (cats) => Column(
          children: [
            _CategoryTabs(categories: cats),
            const Divider(height: 1),
            Expanded(
              child: asyncEntries.when(
                data: (entries) => entries.isEmpty
                    ? _EmptyState(hasCategories: cats.isNotEmpty)
                    : _EntriesList(entries: entries, categories: cats),
                loading: () => const Center(child: CircularProgressIndicator()),
                error: (e, _) => _ErrorBlock(error: e, onRetry: () => ref.invalidate(entriesProvider)),
              ),
            ),
          ],
        ),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => _ErrorBlock(error: e, onRetry: () => ref.invalidate(categoriesProvider)),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Category tabs
// ---------------------------------------------------------------------------

class _CategoryTabs extends ConsumerWidget {
  const _CategoryTabs({required this.categories});
  final List<WatchlistCategory> categories;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selected = ref.watch(selectedCategoryProvider);

    return SizedBox(
      height: 56,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        children: [
          _Chip(
            label: '전체',
            selected: selected == null,
            onTap: () => ref.read(selectedCategoryProvider.notifier).state = null,
          ),
          for (final c in categories)
            _Chip(
              label: c.name,
              color: _parseHex(c.color),
              selected: selected == c.id,
              onTap: () => ref.read(selectedCategoryProvider.notifier).state = c.id,
              onLongPress: () => _showCategoryEditDialog(context, ref, c),
            ),
          IconButton(
            tooltip: '카테고리 추가',
            icon: const Icon(Icons.add),
            onPressed: () => _showCategoryCreateDialog(context, ref),
          ),
        ],
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({
    required this.label,
    required this.selected,
    required this.onTap,
    this.onLongPress,
    this.color,
  });
  final String label;
  final bool selected;
  final VoidCallback onTap;
  final VoidCallback? onLongPress;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final base = color ?? theme.colorScheme.primary;
    return Padding(
      padding: const EdgeInsets.only(right: 6),
      child: GestureDetector(
        onLongPress: onLongPress,
        child: ChoiceChip(
          label: Text(label),
          selected: selected,
          onSelected: (_) => onTap(),
          selectedColor: base.withValues(alpha: 0.18),
          labelStyle: TextStyle(
            color: selected ? base : theme.colorScheme.onSurface,
            fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
          ),
          shape: StadiumBorder(
            side: BorderSide(color: selected ? base : theme.colorScheme.outlineVariant),
          ),
          showCheckmark: false,
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Entries list
// ---------------------------------------------------------------------------

class _EntriesList extends ConsumerWidget {
  const _EntriesList({required this.entries, required this.categories});
  final List<WatchlistEntry> entries;
  final List<WatchlistCategory> categories;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final byCat = {for (final c in categories) c.id: c};
    return ListView.separated(
      itemCount: entries.length,
      separatorBuilder: (_, __) => const Divider(height: 1),
      itemBuilder: (_, i) => _EntryRow(entry: entries[i], category: byCat[entries[i].categoryId]),
    );
  }
}

class _EntryRow extends ConsumerWidget {
  const _EntryRow({required this.entry, required this.category});
  final WatchlistEntry entry;
  final WatchlistCategory? category;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final catColor = category == null ? theme.colorScheme.outline : _parseHex(category!.color);
    return ListTile(
      leading: Container(
        width: 8,
        height: double.infinity,
        color: catColor,
        margin: const EdgeInsets.symmetric(vertical: 8),
      ),
      title: Row(
        children: [
          Text(entry.stockCode,
              style: theme.textTheme.titleSmall?.copyWith(
                fontFamily: 'monospace',
                fontWeight: FontWeight.w700,
              )),
          const SizedBox(width: 8),
          if (category != null)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                color: catColor.withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(category!.name,
                  style: theme.textTheme.labelSmall?.copyWith(color: catColor)),
            ),
          const Spacer(),
          Text('${_date.format(entry.addedAt.toLocal())} 추가',
              style: theme.textTheme.bodySmall),
        ],
      ),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Text('💬 ${entry.reason}', style: theme.textTheme.bodyMedium),
      ),
      trailing: PopupMenuButton<String>(
        onSelected: (v) async {
          if (v == 'edit') {
            await _showEditReasonDialog(context, ref, entry);
          } else if (v == 'delete') {
            await _confirmDelete(context, ref, entry);
          }
        },
        itemBuilder: (_) => const [
          PopupMenuItem(value: 'edit', child: Text('사유 수정')),
          PopupMenuItem(value: 'delete', child: Text('삭제')),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Dialogs
// ---------------------------------------------------------------------------

Future<void> _showCategoryCreateDialog(BuildContext context, WidgetRef ref) async {
  final nameCtrl = TextEditingController();
  String color = '#3B82F6';
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setState) => AlertDialog(
        title: const Text('카테고리 생성'),
        content: SizedBox(
          width: 360,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              TextField(controller: nameCtrl, decoration: const InputDecoration(labelText: '이름')),
              const SizedBox(height: 12),
              const Text('색상'),
              const SizedBox(height: 6),
              Wrap(
                spacing: 8,
                children: [
                  for (final hex in const ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#A855F7', '#06B6D4'])
                    GestureDetector(
                      onTap: () => setState(() => color = hex),
                      child: Container(
                        width: 32,
                        height: 32,
                        decoration: BoxDecoration(
                          color: _parseHex(hex),
                          shape: BoxShape.circle,
                          border: Border.all(
                            color: color == hex ? Colors.white : Colors.transparent,
                            width: 3,
                          ),
                        ),
                      ),
                    ),
                ],
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
  final name = nameCtrl.text.trim();
  if (name.isEmpty) return;

  try {
    await ref.read(watchlistApiProvider).createCategory(name: name, color: color);
    ref.invalidate(categoriesProvider);
  } catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('카테고리 생성 실패: $e'), backgroundColor: Colors.redAccent),
      );
    }
  }
}

Future<void> _showCategoryEditDialog(
  BuildContext context,
  WidgetRef ref,
  WatchlistCategory c,
) async {
  final nameCtrl = TextEditingController(text: c.name);
  final ok = await showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text('카테고리: ${c.name}'),
      content: TextField(
        controller: nameCtrl,
        decoration: const InputDecoration(labelText: '이름'),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(ctx, 'delete'),
          style: TextButton.styleFrom(foregroundColor: Colors.redAccent),
          child: const Text('삭제'),
        ),
        const Spacer(),
        TextButton(onPressed: () => Navigator.pop(ctx, null), child: const Text('취소')),
        FilledButton(onPressed: () => Navigator.pop(ctx, 'save'), child: const Text('저장')),
      ],
    ),
  );

  if (ok == 'save') {
    final newName = nameCtrl.text.trim();
    if (newName.isEmpty || newName == c.name) return;
    try {
      await ref.read(watchlistApiProvider).updateCategory(c.id, name: newName);
      ref.invalidate(categoriesProvider);
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('수정 실패: $e')));
      }
    }
  } else if (ok == 'delete') {
    try {
      await ref.read(watchlistApiProvider).deleteCategory(c.id);
      if (ref.read(selectedCategoryProvider) == c.id) {
        ref.read(selectedCategoryProvider.notifier).state = null;
      }
      ref.invalidate(categoriesProvider);
      ref.invalidate(entriesProvider);
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('삭제 실패: $e')));
      }
    }
  }
}

Future<void> _showAddEntryDialog(
  BuildContext context,
  WidgetRef ref,
  List<WatchlistCategory> cats,
) async {
  final codeCtrl = TextEditingController();
  final reasonCtrl = TextEditingController();
  int catId = ref.read(selectedCategoryProvider) ?? cats.first.id;

  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setState) => AlertDialog(
        title: const Text('관심종목 추가'),
        content: SizedBox(
          width: 420,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: codeCtrl,
                decoration: const InputDecoration(labelText: '종목 코드 (예: 005930)'),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<int>(
                initialValue: catId,
                decoration: const InputDecoration(labelText: '카테고리'),
                items: [
                  for (final c in cats)
                    DropdownMenuItem(value: c.id, child: Text(c.name)),
                ],
                onChanged: (v) => setState(() => catId = v ?? catId),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: reasonCtrl,
                decoration: const InputDecoration(labelText: '등록 사유 (필수)'),
                maxLines: 3,
                minLines: 2,
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('취소')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('추가')),
        ],
      ),
    ),
  );
  if (ok != true) return;

  final code = codeCtrl.text.trim();
  final reason = reasonCtrl.text.trim();
  if (code.isEmpty || reason.isEmpty) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('종목 코드와 등록 사유는 필수입니다.')),
      );
    }
    return;
  }

  try {
    await ref.read(watchlistApiProvider).addEntry(
      stockCode: code,
      categoryId: catId,
      reason: reason,
    );
    ref.invalidate(entriesProvider);
  } catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('추가 실패: $e'), backgroundColor: Colors.redAccent),
      );
    }
  }
}

Future<void> _showEditReasonDialog(BuildContext context, WidgetRef ref, WatchlistEntry e) async {
  final ctrl = TextEditingController(text: e.reason);
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text('${e.stockCode} 사유 수정'),
      content: TextField(
        controller: ctrl,
        decoration: const InputDecoration(labelText: '등록 사유'),
        maxLines: 4,
        minLines: 2,
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('취소')),
        FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('저장')),
      ],
    ),
  );
  if (ok != true) return;
  final newReason = ctrl.text.trim();
  if (newReason.isEmpty) return;
  try {
    await ref.read(watchlistApiProvider).updateEntryReason(e.id, newReason);
    ref.invalidate(entriesProvider);
  } catch (err) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('수정 실패: $err')));
    }
  }
}

Future<void> _confirmDelete(BuildContext context, WidgetRef ref, WatchlistEntry e) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: const Text('삭제'),
      content: Text('${e.stockCode} 을(를) 관심종목에서 삭제할까요?'),
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
    await ref.read(watchlistApiProvider).deleteEntry(e.id);
    ref.invalidate(entriesProvider);
  } catch (err) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('삭제 실패: $err')));
    }
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

Color _parseHex(String hex) {
  final clean = hex.replaceAll('#', '');
  final n = int.tryParse(clean, radix: 16) ?? 0x888888;
  return Color(0xFF000000 | n);
}

class _EmptyState extends ConsumerWidget {
  const _EmptyState({required this.hasCategories});
  final bool hasCategories;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (!hasCategories) {
      return EmptyState(
        icon: Icons.folder_open_outlined,
        title: '카테고리를 먼저 만들어보세요',
        subtitle: '예: 배당주 / 성장주 / 추세전환 ... 종목을 분류해서 사유와 함께 등록할 수 있어요.',
        action: FilledButton.icon(
          icon: const Icon(Icons.add),
          label: const Text('카테고리 만들기'),
          onPressed: () => _showCategoryCreateDialog(context, ref),
        ),
      );
    }
    return EmptyState(
      icon: Icons.star_border,
      title: '이 카테고리에 등록된 종목이 없습니다',
      subtitle: '우측 하단 [종목 추가] 버튼으로 종목과 등록 사유를 입력하세요.',
      action: FilledButton.icon(
        icon: const Icon(Icons.add),
        label: const Text('종목 추가'),
        onPressed: () async {
          final cats = ref.read(categoriesProvider).valueOrNull ?? const [];
          if (cats.isEmpty) return;
          await _showAddEntryDialog(context, ref, cats);
        },
      ),
    );
  }
}

class _ErrorBlock extends StatelessWidget {
  const _ErrorBlock({required this.error, required this.onRetry});
  final Object error;
  final VoidCallback onRetry;
  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, size: 48),
            const SizedBox(height: 8),
            SelectableText('$error', textAlign: TextAlign.center),
            const SizedBox(height: 12),
            FilledButton(onPressed: onRetry, child: const Text('다시 시도')),
          ],
        ),
      ),
    );
  }
}
