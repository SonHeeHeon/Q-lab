/// File: app/lib/presentation/quant/builder/builder_screen.dart
///
/// Equation Builder — Phase 5 Step 7. Lets the user assemble a
/// StrategyDefinition (universe + rebalance + factor weights + filters
/// + top_n + date window) and submit to POST /api/backtest/run.
///
/// On success → cache the full result + navigate to the detail screen
/// which now renders the equity curve.
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../../data/api/api_client.dart';
import '../../../data/api/backtest_api.dart';
import 'builder_controller.dart';

final _date = DateFormat('yyyy-MM-dd');

class BuilderScreen extends ConsumerWidget {
  const BuilderScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(builderProvider);
    final notifier = ref.read(builderProvider.notifier);
    // What will actually be POSTed — the raw preset verbatim in grouped
    // mode, or the editable draft otherwise. Drives the JSON preview card.
    final previewJson =
        state.isGroupedPresetMode ? state.groupedPreset! : state.draft.toJson();

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/quant/backtest'),
        ),
        title: const Text('가치 방정식 빌더'),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: !state.isValid || state.busy
            ? null
            : () async {
                final result = await notifier.run();
                if (!context.mounted) return;
                if (result != null) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('백테스트 완료: ${result.runId}')),
                  );
                  context.go('/quant/backtest/runs/${result.runId}');
                } else if (ref.read(builderProvider).lastError != null) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text('실행 실패: ${ref.read(builderProvider).lastError}'),
                      backgroundColor: Colors.redAccent,
                    ),
                  );
                }
              },
        icon: state.busy
            ? const SizedBox(
                width: 16, height: 16,
                child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
              )
            : const Icon(Icons.play_arrow_rounded),
        label: Text(state.busy ? '실행 중...' : '백테스트 실행'),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
        children: [
          _PresetSection(state: state, notifier: notifier),
          const SizedBox(height: 20),
          if (state.isGroupedPresetMode) ...[
            _GroupedPresetSummaryCard(state: state),
            const SizedBox(height: 20),
          ] else ...[
            _MetaSection(state: state, notifier: notifier),
            const SizedBox(height: 20),
            _UniverseAndRebalanceSection(state: state, notifier: notifier),
            const SizedBox(height: 20),
            _FactorsSection(state: state, notifier: notifier),
            const SizedBox(height: 20),
            _FiltersSection(state: state, notifier: notifier),
            const SizedBox(height: 20),
          ],
          _TopNAndDatesSection(state: state, notifier: notifier),
          const SizedBox(height: 20),
          _JsonPreviewCard(json: previewJson),
          if (state.lastError != null) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.redAccent.withValues(alpha: 0.1),
                border: Border.all(color: Colors.redAccent.withValues(alpha: 0.5)),
                borderRadius: BorderRadius.circular(8),
              ),
              child: SelectableText('⚠️ ${state.lastError}',
                  style: const TextStyle(color: Colors.redAccent)),
            ),
          ],
        ],
      ),
    );
  }
}

// ===========================================================================
// Sections
// ===========================================================================

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({required this.title, this.subtitle, this.trailing});
  final String title;
  final String? subtitle;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title,
                    style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
                if (subtitle != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(subtitle!,
                        style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.outline)),
                  ),
              ],
            ),
          ),
          if (trailing != null) trailing!,
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Preset picker
// ---------------------------------------------------------------------------

/// Preset dropdown — "직접 만들기" (scratch) or one of
/// `GET /api/backtest/strategies`. Flat presets load into the editable
/// draft; grouped presets (qlab_alpha_v2 등) switch the screen into the
/// read-only "이 공식 그대로 사용" mode via [_GroupedPresetSummaryCard].
class _PresetSection extends ConsumerWidget {
  const _PresetSection({required this.state, required this.notifier});
  final BuilderState state;
  final BuilderNotifier notifier;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final presetsAsync = ref.watch(strategyPresetsProvider);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const _SectionHeader(
              title: '📚 프리셋',
              subtitle: '미리 만든 전략을 그대로 쓰거나 초안으로 불러와 편집하세요.',
            ),
            presetsAsync.when(
              data: (presets) {
                final names = presets.map((p) => p.name).toSet();
                return DropdownButtonFormField<String?>(
                  initialValue: state.selectedPresetName,
                  isDense: true,
                  decoration: const InputDecoration(labelText: '전략 프리셋', isDense: true),
                  items: [
                    const DropdownMenuItem<String?>(value: null, child: Text('✏️ 직접 만들기')),
                    for (final p in presets)
                      DropdownMenuItem<String?>(
                        value: p.name,
                        child: Text(
                          '${p.isGrouped ? '📐' : '🧮'} ${p.name}${p.isPrivate ? ' 🔒' : ''}',
                          style: const TextStyle(fontSize: 13),
                        ),
                      ),
                    // 방어: 선택된 프리셋이 목록에서 사라진 경우(새로고침 등)에도
                    // Dropdown의 "값이 항목과 정확히 하나 일치해야 함" 단언이
                    // 터지지 않도록 항목을 보강한다.
                    if (state.selectedPresetName != null &&
                        !names.contains(state.selectedPresetName))
                      DropdownMenuItem<String?>(
                        value: state.selectedPresetName,
                        child: Text('${state.selectedPresetName} (목록에 없음)'),
                      ),
                  ],
                  onChanged: state.busy
                      ? null
                      : (v) {
                          if (v == null) {
                            notifier.clearPreset();
                          } else {
                            notifier.loadPreset(v);
                          }
                        },
                );
              },
              loading: () => const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: LinearProgressIndicator(),
              ),
              error: (e, _) => Text(
                '프리셋 목록을 불러오지 못했습니다: $e',
                style: theme.textTheme.bodySmall?.copyWith(color: Colors.redAccent),
              ),
            ),
            if (state.selectedPresetName != null) ...[
              const SizedBox(height: 8),
              Text(
                state.isGroupedPresetMode
                    ? '📐 그룹형 전략 — 방정식은 편집할 수 없고 그대로 실행됩니다 (Top N·기간만 조정 가능).'
                    : '🧮 평탄(factors) 전략 — 초안으로 불러왔습니다. 자유롭게 편집할 수 있습니다.',
                style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Read-only "이 공식 그대로 사용" summary for a grouped preset — universe,
/// rebalance, top_n, group weights + factors, filters, band_trim. The flat
/// factor/filter editors are hidden while this is shown; `run()` submits
/// the raw JSON verbatim (see `BuilderNotifier.run`).
class _GroupedPresetSummaryCard extends StatelessWidget {
  const _GroupedPresetSummaryCard({required this.state});
  final BuilderState state;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final preset = state.groupedPreset!;
    final groups = ((preset['groups'] as List?) ?? const []).map(asJsonMap).toList();
    final filters = ((preset['filters'] as List?) ?? const []).map(asJsonMap).toList();
    final bandTrim = preset['band_trim_threshold'];

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _SectionHeader(
              title: '📐 ${preset['name'] ?? ''}',
              subtitle: (preset['description'] as String?) ?? '',
            ),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                Chip(label: Text(_universeLabel(preset['universe'] as String?))),
                Chip(label: Text('${_rebalanceLabel(preset['rebalance_freq'] as String?)} 리밸런싱')),
                Chip(label: Text('Top ${state.draft.topN}')),
                if (bandTrim != null) Chip(label: Text('밴드트림 ×$bandTrim')),
              ],
            ),
            const SizedBox(height: 14),
            Text('그룹 가중치', style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800)),
            const SizedBox(height: 6),
            for (final g in groups)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SizedBox(
                      width: 92,
                      child: Text('${g['name']}', style: const TextStyle(fontWeight: FontWeight.w700)),
                    ),
                    SizedBox(
                      width: 48,
                      child: Text(
                        '${(((g['weight'] as num?)?.toDouble() ?? 0) * 100).toStringAsFixed(0)}%',
                        style: const TextStyle(fontFamily: 'monospace', fontWeight: FontWeight.w700),
                      ),
                    ),
                    Expanded(
                      child: Wrap(
                        spacing: 4,
                        runSpacing: 4,
                        children: [
                          for (final f in ((g['factors'] as List?) ?? const []))
                            _factorChip(asJsonMap(f)),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            if (filters.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text('필터', style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800)),
              const SizedBox(height: 4),
              for (final f in filters)
                Text(
                  '${(f['field'] as String?)?.toUpperCase()} ${f['op']} ${f['value']}',
                  style: theme.textTheme.bodySmall?.copyWith(fontFamily: 'monospace'),
                ),
            ],
          ],
        ),
      ),
    );
  }
}

Widget _factorChip(Map<String, dynamic> f) {
  final higherIsBetter = (f['higher_is_better'] as bool?) ?? true;
  return Chip(
    visualDensity: VisualDensity.compact,
    label: Text('${higherIsBetter ? '▲' : '▼'} ${f['factor']}'),
  );
}

String _universeLabel(String? wire) {
  for (final u in BacktestUniverse.values) {
    if (u.wire == wire) return u.label;
  }
  return wire ?? '-';
}

String _rebalanceLabel(String? wire) {
  for (final r in BacktestRebalanceFreq.values) {
    if (r.wire == wire) return r.label;
  }
  return wire ?? '-';
}

class _MetaSection extends StatelessWidget {
  const _MetaSection({required this.state, required this.notifier});
  final BuilderState state;
  final BuilderNotifier notifier;
  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const _SectionHeader(title: '🪪 전략 메타', subtitle: '이름은 영문/숫자 권장 (run_id 에 사용)'),
            TextFormField(
              initialValue: state.draft.name,
              decoration: const InputDecoration(labelText: '전략 이름'),
              onChanged: notifier.setName,
            ),
            const SizedBox(height: 10),
            TextFormField(
              initialValue: state.draft.description,
              decoration: const InputDecoration(labelText: '설명'),
              onChanged: notifier.setDescription,
            ),
          ],
        ),
      ),
    );
  }
}

class _UniverseAndRebalanceSection extends StatelessWidget {
  const _UniverseAndRebalanceSection({required this.state, required this.notifier});
  final BuilderState state;
  final BuilderNotifier notifier;
  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const _SectionHeader(title: '🌐 유니버스 & 리밸런싱'),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final u in BacktestUniverse.values)
                  ChoiceChip(
                    label: Text(u.label),
                    selected: state.draft.universe == u,
                    onSelected: (_) => notifier.setUniverse(u),
                  ),
              ],
            ),
            const SizedBox(height: 14),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final r in BacktestRebalanceFreq.values)
                  ChoiceChip(
                    label: Text('${r.label} 리밸런싱'),
                    selected: state.draft.rebalanceFreq == r,
                    onSelected: (_) => notifier.setRebalance(r),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Factors
// ---------------------------------------------------------------------------

class _FactorsSection extends StatelessWidget {
  const _FactorsSection({required this.state, required this.notifier});
  final BuilderState state;
  final BuilderNotifier notifier;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final sum = state.weightSum;
    final sumGood = (sum - 1.0).abs() < 0.01;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _SectionHeader(
              title: '🧮 팩터 + 가중치',
              subtitle: '합계가 1.0 이 되도록 조절하세요. [정규화] 로 자동 조정 가능.',
              trailing: Row(
                children: [
                  Text(
                    '합계: ${sum.toStringAsFixed(2)}',
                    style: theme.textTheme.labelMedium?.copyWith(
                      color: sumGood ? Colors.green : Colors.amber.shade800,
                      fontWeight: FontWeight.w800,
                      fontFamily: 'monospace',
                    ),
                  ),
                  IconButton(
                    tooltip: '정규화 (합계=1)',
                    icon: const Icon(Icons.balance),
                    onPressed: state.draft.factors.isEmpty ? null : notifier.normalizeWeights,
                  ),
                ],
              ),
            ),
            if (state.draft.factors.isEmpty)
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: theme.colorScheme.surfaceContainerHigh,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text('팩터를 1개 이상 추가해야 백테스트 실행이 가능합니다.',
                    style: theme.textTheme.bodySmall),
              )
            else
              for (var i = 0; i < state.draft.factors.length; i++)
                _FactorRow(
                  index: i,
                  factor: state.draft.factors[i],
                  state: state,
                  notifier: notifier,
                ),
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                icon: const Icon(Icons.add),
                label: Text(notifier.catalogExhausted
                    ? '모든 팩터 사용 중'
                    : '팩터 추가'),
                onPressed: notifier.catalogExhausted ? null : notifier.addFactor,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _FactorRow extends StatelessWidget {
  const _FactorRow({
    required this.index,
    required this.factor,
    required this.state,
    required this.notifier,
  });
  final int index;
  final FactorWeightDraft factor;
  final BuilderState state;
  final BuilderNotifier notifier;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final used = state.draft.factors.map((f) => f.factor).toSet();
    final meta = kFactorCatalog.firstWhere(
      (m) => m.code == factor.factor,
      orElse: () => kFactorCatalog.first,
    );
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                flex: 5,
                child: DropdownButtonFormField<String>(
                  initialValue: factor.factor,
                  isDense: true,
                  decoration: const InputDecoration(labelText: '팩터', isDense: true),
                  items: [
                    for (final m in kFactorCatalog)
                      DropdownMenuItem(
                        value: m.code,
                        enabled: m.code == factor.factor || !used.contains(m.code),
                        child: Text('${m.label}  ·  ${m.code}',
                            style: const TextStyle(fontSize: 13)),
                      ),
                    // 방어: 프리셋에서 불러온 팩터가 kFactorCatalog 밖의 코드일 때
                    // Dropdown의 "값이 항목과 정확히 하나 일치해야 함" 단언을 피한다.
                    if (!kFactorCatalog.any((m) => m.code == factor.factor))
                      DropdownMenuItem(
                        value: factor.factor,
                        child: Text('${factor.factor} (커스텀)',
                            style: const TextStyle(fontSize: 13)),
                      ),
                  ],
                  onChanged: (v) {
                    if (v == null) return;
                    notifier.updateFactor(
                      index,
                      FactorWeightDraft(
                        factor: v,
                        weight: factor.weight,
                        transform: factor.transform,
                      ),
                    );
                  },
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                flex: 3,
                child: DropdownButtonFormField<BacktestTransform>(
                  initialValue: factor.transform,
                  isDense: true,
                  decoration: const InputDecoration(labelText: '변환', isDense: true),
                  items: const [
                    DropdownMenuItem(value: BacktestTransform.raw, child: Text('RAW')),
                    DropdownMenuItem(value: BacktestTransform.zscore, child: Text('ZSCORE')),
                    DropdownMenuItem(value: BacktestTransform.rank, child: Text('RANK')),
                  ],
                  onChanged: (v) {
                    if (v == null) return;
                    notifier.updateFactor(
                      index,
                      FactorWeightDraft(
                        factor: factor.factor,
                        weight: factor.weight,
                        transform: v,
                      ),
                    );
                  },
                ),
              ),
              IconButton(
                tooltip: '삭제',
                icon: const Icon(Icons.remove_circle_outline),
                color: Colors.redAccent,
                onPressed: () => notifier.removeFactor(index),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(meta.hint,
              style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline)),
          Row(
            children: [
              SizedBox(
                width: 52,
                child: Text('${(factor.weight * 100).toStringAsFixed(0)}%',
                    style: theme.textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                      fontFamily: 'monospace',
                    )),
              ),
              Expanded(
                child: Slider(
                  value: factor.weight.clamp(0.0, 1.0),
                  onChanged: (v) => notifier.updateFactor(
                    index,
                    FactorWeightDraft(
                      factor: factor.factor,
                      weight: v,
                      transform: factor.transform,
                    ),
                  ),
                  divisions: 20,
                  label: factor.weight.toStringAsFixed(2),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Filters
// ---------------------------------------------------------------------------

class _FiltersSection extends StatelessWidget {
  const _FiltersSection({required this.state, required this.notifier});
  final BuilderState state;
  final BuilderNotifier notifier;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const _SectionHeader(
                title: '🚧 필터 규칙', subtitle: '선택사항 — 유동성/거래일수 등 사전 필터.'),
            DropdownButtonFormField<String>(
              initialValue: state.filterPresetKey,
              isDense: true,
              decoration: const InputDecoration(labelText: '필터 프리셋', isDense: true),
              items: [
                for (final p in kFilterPresets)
                  DropdownMenuItem(
                      value: p.key, child: Text(p.label, style: const TextStyle(fontSize: 13))),
              ],
              onChanged: (v) {
                if (v != null) notifier.applyFilterPreset(v);
              },
            ),
            const SizedBox(height: 10),
            if (state.draft.filters.isEmpty)
              Text('필터 없음', style: theme.textTheme.bodySmall),
            for (var i = 0; i < state.draft.filters.length; i++)
              _FilterRow(index: i, filter: state.draft.filters[i], notifier: notifier),
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                icon: const Icon(Icons.add),
                label: const Text('필터 추가'),
                onPressed: notifier.addFilter,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _FilterRow extends StatelessWidget {
  const _FilterRow({required this.index, required this.filter, required this.notifier});
  final int index;
  final FilterRuleDraft filter;
  final BuilderNotifier notifier;
  @override
  Widget build(BuildContext context) {
    final valueText = filter.value is num ? '${filter.value}' : '';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(
            flex: 4,
            child: DropdownButtonFormField<String>(
              initialValue: filter.field,
              isDense: true,
              decoration: const InputDecoration(labelText: '필드', isDense: true),
              items: [
                for (final f in kFilterFields)
                  DropdownMenuItem(value: f, child: Text(f, style: const TextStyle(fontSize: 13))),
                // 방어: 프리셋에서 불러온 필터 필드가 kFilterFields 밖일 때
                // Dropdown의 "값이 항목과 정확히 하나 일치해야 함" 단언을 피한다.
                if (!kFilterFields.contains(filter.field))
                  DropdownMenuItem(
                    value: filter.field,
                    child: Text('${filter.field} (커스텀)', style: const TextStyle(fontSize: 13)),
                  ),
              ],
              onChanged: (v) {
                if (v == null) return;
                notifier.updateFilter(
                  index,
                  FilterRuleDraft(field: v, op: filter.op, value: filter.value),
                );
              },
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            flex: 2,
            child: DropdownButtonFormField<BacktestFilterOp>(
              initialValue: filter.op,
              isDense: true,
              decoration: const InputDecoration(labelText: '연산', isDense: true),
              items: const [
                DropdownMenuItem(value: BacktestFilterOp.gt, child: Text('>')),
                DropdownMenuItem(value: BacktestFilterOp.gte, child: Text('≥')),
                DropdownMenuItem(value: BacktestFilterOp.lt, child: Text('<')),
                DropdownMenuItem(value: BacktestFilterOp.lte, child: Text('≤')),
              ],
              onChanged: (v) {
                if (v == null) return;
                notifier.updateFilter(
                  index,
                  FilterRuleDraft(field: filter.field, op: v, value: filter.value),
                );
              },
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            flex: 3,
            child: TextFormField(
              initialValue: valueText,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9.\-]'))],
              decoration: const InputDecoration(labelText: '값', isDense: true),
              onChanged: (v) {
                final parsed = double.tryParse(v);
                if (parsed == null) return;
                notifier.updateFilter(
                  index,
                  FilterRuleDraft(field: filter.field, op: filter.op, value: parsed),
                );
              },
            ),
          ),
          IconButton(
            tooltip: '삭제',
            icon: const Icon(Icons.remove_circle_outline),
            color: Colors.redAccent,
            onPressed: () => notifier.removeFilter(index),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Top N + dates
// ---------------------------------------------------------------------------

class _TopNAndDatesSection extends StatelessWidget {
  const _TopNAndDatesSection({required this.state, required this.notifier});
  final BuilderState state;
  final BuilderNotifier notifier;
  @override
  Widget build(BuildContext context) {
    // 방어: 프리셋의 top_n(예: etf_rotation_kr/us = 3)이 kTopNOptions 밖일 때
    // Dropdown의 "값이 항목과 정확히 하나 일치해야 함" 단언을 피한다.
    final topNItems = <int>{...kTopNOptions, state.draft.topN}.toList()..sort();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const _SectionHeader(title: '🎯 종목수 & 기간'),
            Row(
              children: [
                Expanded(
                  child: DropdownButtonFormField<int>(
                    initialValue: state.draft.topN,
                    isDense: true,
                    decoration: const InputDecoration(labelText: 'Top N', isDense: true),
                    items: [
                      for (final n in topNItems)
                        DropdownMenuItem(value: n, child: Text('$n 종목')),
                    ],
                    onChanged: (v) {
                      if (v != null) notifier.setTopN(v);
                    },
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: DropdownButtonFormField<String>(
                    initialValue: state.periodPresetKey,
                    isDense: true,
                    decoration: const InputDecoration(labelText: '기간', isDense: true),
                    items: [
                      for (final p in kPeriodPresets)
                        DropdownMenuItem(value: p.key, child: Text(p.label)),
                    ],
                    onChanged: (v) {
                      if (v != null) notifier.applyPeriodPreset(v);
                    },
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: _DatePickerField(
                    label: '시작',
                    value: state.draft.startDate,
                    onChanged: notifier.setStartDate,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _DatePickerField(
                    label: '종료',
                    value: state.draft.endDate,
                    onChanged: notifier.setEndDate,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _DatePickerField extends StatelessWidget {
  const _DatePickerField({required this.label, required this.value, required this.onChanged});
  final String label;
  final DateTime value;
  final ValueChanged<DateTime> onChanged;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: () async {
        final picked = await showDatePicker(
          context: context,
          initialDate: value,
          firstDate: DateTime(2010),
          lastDate: DateTime.now().add(const Duration(days: 1)),
        );
        if (picked != null) onChanged(picked);
      },
      child: InputDecorator(
        decoration: InputDecoration(labelText: label),
        child: Text(_date.format(value)),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// JSON preview
// ---------------------------------------------------------------------------

class _JsonPreviewCard extends StatelessWidget {
  const _JsonPreviewCard({required this.json});

  /// What will actually be POSTed — the raw grouped-preset JSON verbatim,
  /// or `draft.toJson()` in flat/scratch mode. See [BuilderScreen.build].
  final Map<String, dynamic> json;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final body = const JsonEncoder.withIndent('  ').convert(json);
    return Card(
      color: theme.colorScheme.surfaceContainerHigh,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Text('🔎 전송될 JSON',
                    style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800)),
                const Spacer(),
                Text('POST /api/backtest/run',
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: theme.colorScheme.outline,
                      fontFamily: 'monospace',
                    )),
              ],
            ),
            const SizedBox(height: 8),
            SelectableText(
              body,
              style: theme.textTheme.bodySmall?.copyWith(fontFamily: 'monospace', fontSize: 11),
            ),
          ],
        ),
      ),
    );
  }
}
