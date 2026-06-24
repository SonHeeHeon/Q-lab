/// File: app/lib/presentation/stocks/stock_search_screen.dart
///
/// Stock search screen — 종목 검색.
/// Debounce 300ms on TextField. Results route to StockDetailScreen.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../data/api/stocks_api.dart';
import 'stocks_controller.dart';

class StockSearchScreen extends ConsumerStatefulWidget {
  const StockSearchScreen({super.key});

  @override
  ConsumerState<StockSearchScreen> createState() => _StockSearchScreenState();
}

class _StockSearchScreenState extends ConsumerState<StockSearchScreen> {
  final _ctrl = TextEditingController();
  Timer? _debounce;
  String _query = '';

  @override
  void dispose() {
    _ctrl.dispose();
    _debounce?.cancel();
    super.dispose();
  }

  void _onChanged(String v) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () {
      if (mounted) setState(() => _query = v.trim());
    });
  }

  void _clearSearch() {
    _ctrl.clear();
    setState(() => _query = '');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 0,
        title: TextField(
          controller: _ctrl,
          autofocus: true,
          textInputAction: TextInputAction.search,
          decoration: InputDecoration(
            hintText: '종목명 · 코드 · 티커 검색',
            border: InputBorder.none,
            contentPadding: const EdgeInsets.symmetric(horizontal: 4),
            suffixIcon: _query.isNotEmpty
                ? IconButton(
                    icon: const Icon(Icons.clear),
                    onPressed: _clearSearch,
                  )
                : null,
          ),
          onChanged: _onChanged,
        ),
      ),
      body: _query.isEmpty
          ? const _SearchHint()
          : Consumer(
              builder: (ctx, ref, _) {
                final async = ref.watch(stockSearchProvider(_query));
                return async.when(
                  data: (results) => results.isEmpty
                      ? const _EmptyResults()
                      : ListView.separated(
                          itemCount: results.length,
                          separatorBuilder: (_, __) => const Divider(height: 1),
                          itemBuilder: (_, i) => _SearchTile(result: results[i]),
                        ),
                  loading: () => const Center(child: CircularProgressIndicator()),
                  error: (e, _) => Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.error_outline, size: 48),
                        const SizedBox(height: 8),
                        Text('검색 오류: $e', textAlign: TextAlign.center),
                        const SizedBox(height: 12),
                        FilledButton(
                          onPressed: () => ref.invalidate(stockSearchProvider(_query)),
                          child: const Text('다시 시도'),
                        ),
                      ],
                    ),
                  ),
                );
              },
            ),
    );
  }
}

// ---------------------------------------------------------------------------
// Search tile
// ---------------------------------------------------------------------------

class _SearchTile extends StatelessWidget {
  const _SearchTile({required this.result});
  final StockSearchResult result;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ListTile(
      onTap: () => context.push(
        '/stocks/${result.marketCountry.toUpperCase()}/${Uri.encodeComponent(result.displayCode)}',
      ),
      leading: CircleAvatar(
        backgroundColor: result.isUs
            ? Colors.blueAccent.withValues(alpha: 0.12)
            : Colors.purple.withValues(alpha: 0.12),
        child: Text(
          result.isUs ? '🇺🇸' : '🇰🇷',
          style: const TextStyle(fontSize: 18),
        ),
      ),
      title: Row(
        children: [
          Expanded(
            child: Text(
              result.name,
              style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          const SizedBox(width: 8),
          _Badge(
            label: result.displayCode,
            color: theme.colorScheme.outline,
          ),
        ],
      ),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Wrap(
          spacing: 6,
          children: [
            _Badge(
              label: result.isUs ? '🇺🇸 미국' : '🇰🇷 국내',
              color: result.isUs ? Colors.blueAccent : Colors.purple,
            ),
            _Badge(
              label: result.broker,
              color: result.broker.toUpperCase() == 'TOSS'
                  ? const Color(0xFF3182F6)
                  : Colors.purple,
            ),
            if (result.market != null)
              _Badge(label: result.market!, color: theme.colorScheme.tertiary),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Shared badge chip
// ---------------------------------------------------------------------------

class _Badge extends StatelessWidget {
  const _Badge({required this.label, required this.color});
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      child: Text(
        label,
        style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w600),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Empty states
// ---------------------------------------------------------------------------

class _SearchHint extends StatelessWidget {
  const _SearchHint();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.search, size: 64, color: theme.colorScheme.outline),
          const SizedBox(height: 16),
          Text(
            '종목명, 코드, 티커를 입력하세요',
            style: theme.textTheme.titleMedium?.copyWith(
              color: theme.colorScheme.outline,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            '예) 삼성전자  ·  005930  ·  AAPL',
            style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.outline),
          ),
        ],
      ),
    );
  }
}

class _EmptyResults extends StatelessWidget {
  const _EmptyResults();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.search_off, size: 48, color: theme.colorScheme.outline),
          const SizedBox(height: 12),
          Text('검색 결과가 없습니다',
              style: theme.textTheme.bodyLarge
                  ?.copyWith(color: theme.colorScheme.outline)),
        ],
      ),
    );
  }
}
