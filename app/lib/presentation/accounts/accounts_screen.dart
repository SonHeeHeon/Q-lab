/// File: app/lib/presentation/accounts/accounts_screen.dart
///
/// 계좌 관리 화면 — 7계좌(KIS 6 + Toss) 카드 목록.
/// 카드마다: 브로커·타입 배지, 연결 상태, 프로파일 타입 마킹, 퀀트 ON/OFF
/// 스위치(라이브 잠금 중 실계좌 ON은 백엔드 403 → 스낵바), 확장 시 슬리브
/// 비중 편집(저장 → 다음 리밸런싱부터 반영).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/accounts_api.dart';
import '../../data/api/api_client.dart';

const _profileTypes = ['PERSONAL', 'ISA', 'DC', 'IRP', 'PENSION', 'US'];

const _profileLabels = {
  'PERSONAL': '개인',
  'ISA': 'ISA',
  'DC': '퇴직연금DC',
  'IRP': 'IRP',
  'PENSION': '연금저축',
  'US': '미국(Toss)',
};

class AccountsScreen extends ConsumerWidget {
  const AccountsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final accounts = ref.watch(accountsProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('계좌 관리')),
      body: accounts.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('계좌 목록을 불러오지 못했습니다\n$e')),
        data: (rows) => RefreshIndicator(
          onRefresh: () async => ref.refresh(accountsProvider.future),
          child: ListView(
            padding: const EdgeInsets.all(12),
            children: [
              const _LiveLockBanner(),
              for (final account in rows) _AccountCard(account: account),
            ],
          ),
        ),
      ),
    );
  }
}

class _LiveLockBanner extends StatelessWidget {
  const _LiveLockBanner();

  @override
  Widget build(BuildContext context) {
    return Card(
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      child: const Padding(
        padding: EdgeInsets.all(12),
        child: Row(
          children: [
            Icon(Icons.lock_outline, size: 18),
            SizedBox(width: 8),
            Expanded(
              child: Text(
                '실계좌 퀀트는 잠금 상태입니다 — 실전 운용 사전작업(도커 상시 서버, '
                '모의계좌 E2E, 모바일 검증 등) 완료 후 해제됩니다. '
                '지금은 모의(PAPER) 계좌만 켤 수 있어요.',
                style: TextStyle(fontSize: 12),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AccountCard extends ConsumerStatefulWidget {
  const _AccountCard({required this.account});
  final AccountProfileInfo account;

  @override
  ConsumerState<_AccountCard> createState() => _AccountCardState();
}

class _AccountCardState extends ConsumerState<_AccountCard> {
  late List<SleeveConfig> _draftSleeves = widget.account.sleeves;
  bool _saving = false;

  AccountProfileInfo get account => widget.account;

  double get _weightSum =>
      _draftSleeves.fold<double>(0, (a, s) => a + s.weight);

  Future<void> _patch({
    String? profileType,
    bool? quantEnabled,
    List<SleeveConfig>? sleeves,
  }) async {
    setState(() => _saving = true);
    try {
      await ref.read(accountsApiProvider).patch(
            account.accountKey,
            profileType: profileType,
            quantEnabled: quantEnabled,
            sleeves: sleeves,
          );
      ref.invalidate(accountsProvider);
      if (mounted && sleeves != null) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('저장됨 — 다음 리밸런싱부터 이 비중이 적용됩니다'),
          ),
        );
      }
    } on ApiError catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e.message)),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('저장 실패: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final locked = account.accountKey != 'KIS:PAPER';
    return Card(
      margin: const EdgeInsets.only(top: 8),
      child: ExpansionTile(
        title: Row(
          children: [
            Text(
              account.accountKey,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            const SizedBox(width: 8),
            if (!account.connected)
              const Chip(
                label: Text('미연결', style: TextStyle(fontSize: 11)),
                visualDensity: VisualDensity.compact,
              ),
          ],
        ),
        subtitle: Text(
          '${_profileLabels[account.profileType] ?? account.profileType}'
          ' · 슬리브 ${account.sleeves.length}개',
          style: const TextStyle(fontSize: 12),
        ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (locked && !account.quantEnabled)
              const Icon(Icons.lock_outline, size: 16),
            Switch(
              value: account.quantEnabled,
              onChanged: _saving
                  ? null
                  : (on) => _patch(quantEnabled: on),
            ),
          ],
        ),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
        children: [
          Row(
            children: [
              const Text('계좌 타입', style: TextStyle(fontSize: 13)),
              const SizedBox(width: 12),
              DropdownButton<String>(
                value: _profileTypes.contains(account.profileType)
                    ? account.profileType
                    : null,
                items: [
                  for (final t in _profileTypes)
                    DropdownMenuItem(
                      value: t,
                      child: Text(_profileLabels[t] ?? t),
                    ),
                ],
                onChanged: _saving
                    ? null
                    : (t) {
                        if (t != null) _patch(profileType: t);
                      },
              ),
            ],
          ),
          const Divider(),
          Align(
            alignment: Alignment.centerLeft,
            child: Text(
              '슬리브 비중 (합 ${(100 * _weightSum).toStringAsFixed(0)}%)',
              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
            ),
          ),
          for (var i = 0; i < _draftSleeves.length; i++)
            Row(
              children: [
                SizedBox(
                  width: 140,
                  child: Text(
                    _draftSleeves[i].label,
                    style: const TextStyle(fontSize: 12),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                Expanded(
                  child: Slider(
                    value: _draftSleeves[i].weight.clamp(0.0, 1.0),
                    divisions: 100,
                    label:
                        '${(100 * _draftSleeves[i].weight).toStringAsFixed(0)}%',
                    onChanged: (v) => setState(() {
                      _draftSleeves = [
                        for (var j = 0; j < _draftSleeves.length; j++)
                          j == i
                              ? _draftSleeves[j].copyWith(weight: v)
                              : _draftSleeves[j],
                      ];
                    }),
                  ),
                ),
                SizedBox(
                  width: 42,
                  child: Text(
                    '${(100 * _draftSleeves[i].weight).toStringAsFixed(0)}%',
                    style: const TextStyle(fontSize: 12),
                    textAlign: TextAlign.end,
                  ),
                ),
              ],
            ),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              TextButton(
                onPressed: _saving
                    ? null
                    : () =>
                        setState(() => _draftSleeves = account.sleeves),
                child: const Text('되돌리기'),
              ),
              const SizedBox(width: 8),
              FilledButton(
                // 합이 100%±1%p 이내일 때만 저장 가능(백엔드도 재검증)
                onPressed: _saving || (_weightSum - 1.0).abs() > 0.01
                    ? null
                    : () => _patch(sleeves: _draftSleeves),
                child: const Text('비중 저장'),
              ),
            ],
          ),
          const Align(
            alignment: Alignment.centerLeft,
            child: Text(
              '비중 변경은 즉시 주문을 내지 않고 다음 리밸런싱부터 반영됩니다.',
              style: TextStyle(fontSize: 11, color: Colors.grey),
            ),
          ),
        ],
      ),
    );
  }
}
