/// File: app/lib/presentation/settings/settings_screen.dart
///
/// Settings screen — see PROJECT_BLUEPRINT.md §9.9.
/// V1 wires:
///   - KIS accounts: Active badge + [Test] + [Edit] (creds modal)
///   - Telegram chat_id + token (masked) + [Test]
///   - LLM provider/model/key (masked) — read-only until Phase 5 step ≥ 6
///   - Appearance: theme mode
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/config.dart';
import '../../core/preferences.dart';
import '../../data/api/portfolio_api.dart';
import '../../data/api/settings_api.dart';
import '../../domain/entities/account.dart';
import '../portfolio/portfolio_controller.dart';
import 'settings_controller.dart';

// Toss brand teal — matches Toss Securities identity
const _tossColor = Color(0xFF3182F6);

class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncSettings = ref.watch(appSettingsProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('설정'),
        actions: [
          IconButton(
            tooltip: '새로고침',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(appSettingsProvider),
          ),
        ],
      ),
      body: asyncSettings.when(
        data: (s) => _SettingsBody(settings: s),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => _BackendMissingBlock(error: e, ref: ref),
      ),
    );
  }
}

/// Backend `/api/settings` is not yet implemented (Codex Phase 5
/// backend follow-up). Local controls (theme + active account default)
/// still work and are shown here.
class _BackendMissingBlock extends ConsumerWidget {
  const _BackendMissingBlock({required this.error, required this.ref});
  final Object error;
  final WidgetRef ref;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          color: theme.colorScheme.errorContainer,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '⚠️  /api/settings 백엔드 엔드포인트가 아직 없습니다.',
                  style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 6),
                SelectableText(
                  '$error',
                  style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onErrorContainer),
                ),
                const SizedBox(height: 8),
                const Text(
                  'KIS 키 / Telegram / LLM 항목은 현재 백엔드 .env 에서 직접 관리됩니다.\n'
                  '아래 로컬 설정(테마, 활성 계좌 기본값)은 정상 동작합니다.',
                  style: TextStyle(fontSize: 12),
                ),
                const SizedBox(height: 8),
                FilledButton.tonal(
                  onPressed: () => ref.invalidate(appSettingsProvider),
                  child: const Text('다시 시도'),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 24),
        const _SectionHeader('📈 유니버스'),
        const _UniverseBlock(),
        const SizedBox(height: 24),
        const _SectionHeader('🔄 거래 내역 동기화'),
        const _BrokerSyncBlock(),
        const SizedBox(height: 24),
        const _SectionHeader('🎨 화면'),
        _ThemeBlock(),
        const SizedBox(height: 24),
        const _SectionHeader('🔧 활성 계좌 (UI 기본값)'),
        _ActiveAccountBlock(),
      ],
    );
  }
}

class _SettingsBody extends ConsumerWidget {
  const _SettingsBody({required this.settings});
  final AppSettings settings;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _SectionHeader('🔐 한국투자증권 (KIS) 계좌'),
        _KisAccountList(settings: settings),
        const SizedBox(height: 24),

        _SectionHeader('🟦 토스증권 (Toss) 연동'),
        _TossBlock(settings: settings),
        const SizedBox(height: 24),

        _SectionHeader('🔔 알림 (Telegram)'),
        _TelegramBlock(settings: settings),
        const SizedBox(height: 24),

        _SectionHeader('🤖 LLM'),
        _LlmReadOnlyBlock(settings: settings),
        const SizedBox(height: 24),

        _SectionHeader('📈 유니버스'),
        const _UniverseBlock(),
        const SizedBox(height: 24),

        _SectionHeader('🔄 거래 내역 동기화'),
        const _BrokerSyncBlock(),
        const SizedBox(height: 24),

        _SectionHeader('🎨 화면'),
        _ThemeBlock(),
        const SizedBox(height: 24),

        _SectionHeader('🔧 활성 계좌 (UI 기본값)'),
        _ActiveAccountBlock(),
      ],
    );
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 8, 4, 8),
        child: Text(text,
            style: Theme.of(context)
                .textTheme
                .titleSmall
                ?.copyWith(fontWeight: FontWeight.w700)),
      );
}

// ---------------------------------------------------------------------------
// KIS accounts
// ---------------------------------------------------------------------------

class _KisAccountList extends ConsumerWidget {
  const _KisAccountList({required this.settings});
  final AppSettings settings;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final byType = {for (final a in settings.accounts) a.type: a};
    return Card(
      child: Column(
        children: [
          for (final t in KisAccount.values) ...[
            _KisAccountRow(status: byType[t] ?? KisAccountStatus(
              type: t, hasCredentials: false, tokenValid: false,
            )),
            if (t != KisAccount.values.last) const Divider(height: 1),
          ],
        ],
      ),
    );
  }
}

class _KisAccountRow extends ConsumerWidget {
  const _KisAccountRow({required this.status});
  final KisAccountStatus status;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final tests = ref.watch(testResultsProvider);
    final test = tests[kisTestKey(status.type)];

    final (badge, badgeColor) = switch ((status.hasCredentials, status.tokenValid)) {
      (false, _) => ('미설정', theme.colorScheme.outline),
      (true, false) => ('토큰 만료', Colors.amber),
      (true, true) => ('활성', Colors.green),
    };

    return ListTile(
      title: Row(
        children: [
          Text(status.type.wire,
              style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(width: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
            decoration: BoxDecoration(
              color: badgeColor.withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Text(badge, style: TextStyle(color: badgeColor, fontSize: 11)),
          ),
        ],
      ),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (status.accountNoMasked != null) Text('계좌번호: ${status.accountNoMasked}'),
          if (status.lastError != null)
            Text('마지막 오류: ${status.lastError}',
                style: TextStyle(color: theme.colorScheme.error, fontSize: 12)),
          if (test != null)
            Text(
              test.ok ? '✅ ${test.message ?? '연결 성공'}' : '❌ ${test.message ?? '실패'}',
              style: TextStyle(
                color: test.ok ? Colors.green : theme.colorScheme.error,
                fontSize: 12,
              ),
            ),
        ],
      ),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextButton(
            onPressed: () => _runTest(context, ref, status.type),
            child: const Text('Test'),
          ),
          TextButton(
            onPressed: () => _showEdit(context, ref, status.type),
            child: const Text('Edit'),
          ),
        ],
      ),
    );
  }

  Future<void> _runTest(BuildContext context, WidgetRef ref, KisAccount t) async {
    ref.setTestResult(kisTestKey(t), TestResult(ok: false, message: '테스트 중...'));
    final api = ref.read(settingsApiProvider);
    final r = await api.testAccount(t);
    ref.setTestResult(kisTestKey(t), r);
    ref.invalidate(appSettingsProvider);
  }

  Future<void> _showEdit(BuildContext context, WidgetRef ref, KisAccount t) async {
    final appKey = TextEditingController();
    final appSecret = TextEditingController();
    final accountNo = TextEditingController();

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('${t.wire} 계좌 인증 정보'),
        content: SizedBox(
          width: 420,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(controller: appKey, decoration: const InputDecoration(labelText: 'APP KEY')),
              TextField(
                controller: appSecret,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'APP SECRET'),
              ),
              TextField(
                controller: accountNo,
                decoration: const InputDecoration(labelText: '계좌번호 (8-2 형식)'),
              ),
              const SizedBox(height: 8),
              const Text(
                '⚠️ 시크릿은 입력 후 백엔드로 전송되며, 이후 GET 시에는 ••••• 로 마스킹됩니다.',
                style: TextStyle(fontSize: 11),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('취소')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('저장')),
        ],
      ),
    );

    if (ok != true) return;

    final api = ref.read(settingsApiProvider);
    try {
      await api.updateAccount(
        t,
        KisAccountCreds(
          appKey: appKey.text.trim(),
          appSecret: appSecret.text.trim(),
          accountNo: accountNo.text.trim(),
        ),
      );
      ref.invalidate(appSettingsProvider);
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('${t.wire} 인증 정보 저장 완료')));
      }
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('저장 실패: $e'), backgroundColor: Colors.redAccent),
        );
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Toss Securities
// ---------------------------------------------------------------------------

class _TossBlock extends ConsumerStatefulWidget {
  const _TossBlock({required this.settings});
  final AppSettings settings;

  @override
  ConsumerState<_TossBlock> createState() => _TossBlockState();
}

class _TossBlockState extends ConsumerState<_TossBlock> {
  final _clientId = TextEditingController();
  final _clientSecret = TextEditingController();
  final _accountSeq = TextEditingController();
  bool _isMock = true;
  bool _saving = false;

  @override
  void dispose() {
    _clientId.dispose();
    _clientSecret.dispose();
    _accountSeq.dispose();
    super.dispose();
  }

  TossSettings? get _toss => widget.settings.toss;

  Future<void> _save() async {
    final id = _clientId.text.trim();
    final secret = _clientSecret.text.trim();
    if (id.isEmpty || secret.isEmpty) return;

    setState(() => _saving = true);
    try {
      await ref.read(settingsApiProvider).saveTossSettings(
            TossSettingsCreds(
              clientId: id,
              clientSecret: secret,
              accountSeq: int.tryParse(_accountSeq.text.trim()),
              isMock: _isMock,
            ),
          );
      _clientId.clear();
      _clientSecret.clear();
      _accountSeq.clear();
      ref.invalidate(appSettingsProvider);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('토스증권 인증 정보 저장 완료')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('저장 실패: $e'), backgroundColor: Colors.redAccent),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _test() async {
    ref.setTestResult(tossTestKey, TestResult(ok: false, message: '연결 테스트 중...'));
    final r = await ref.read(settingsApiProvider).testToss();
    ref.setTestResult(tossTestKey, r);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final toss = _toss;
    final test = ref.watch(testResultsProvider)[tossTestKey];

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Status banner
            Row(
              children: [
                Container(
                  width: 10,
                  height: 10,
                  decoration: BoxDecoration(
                    color: (toss?.hasCredentials ?? false) ? Colors.green : theme.colorScheme.outline,
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 8),
                Text(
                  (toss?.hasCredentials ?? false)
                      ? '연동됨  ·  Client ID: ${toss!.clientIdMasked.isEmpty ? '(설정됨)' : toss.clientIdMasked}'
                      : '미연동 — Open API 키를 입력하세요',
                  style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
                ),
                if (toss?.hasCredentials ?? false) ...[
                  const SizedBox(width: 8),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                    decoration: BoxDecoration(
                      color: (toss?.isMock ?? true)
                          ? Colors.amber.withValues(alpha: 0.15)
                          : Colors.green.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      (toss?.isMock ?? true) ? '모의(Mock)' : '실전',
                      style: TextStyle(
                        color: (toss?.isMock ?? true) ? Colors.amber.shade800 : Colors.green,
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  if (toss?.accountSeq != null) ...[
                    const SizedBox(width: 8),
                    Text('계좌 #${toss!.accountSeq}',
                        style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.outline)),
                  ],
                ],
              ],
            ),
            const SizedBox(height: 4),
            Text(
              'Toss Open API v${toss?.specVersion ?? '1.1.1'}  ·  WebSocket: ${(toss?.websocketSupported ?? false) ? '지원' : '미지원 (REST-only)'}',
              style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.outline),
            ),
            const Divider(height: 24),

            // Credentials form
            TextField(
              controller: _clientId,
              decoration: const InputDecoration(
                labelText: 'Client ID',
                hintText: '토스증권 Open API Client ID',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _clientSecret,
              obscureText: true,
              decoration: const InputDecoration(
                labelText: 'Client Secret',
                hintText: '입력 후 ••••• 로 마스킹됩니다',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _accountSeq,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: '계좌 번호 (account_seq, 선택)',
                hintText: '예: 1',
              ),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Switch(
                  value: _isMock,
                  onChanged: (v) => setState(() => _isMock = v),
                  activeColor: _tossColor,
                ),
                const SizedBox(width: 8),
                Text(
                  _isMock ? '모의(Mock) 모드' : '실전 모드',
                  style: theme.textTheme.bodyMedium,
                ),
                const Spacer(),
                if (_isMock)
                  Text('⚠️ 실전 거래 아님', style: theme.textTheme.labelSmall?.copyWith(color: Colors.amber.shade800)),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                FilledButton.icon(
                  onPressed: _saving ? null : _save,
                  icon: _saving
                      ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                      : const Icon(Icons.link, size: 18),
                  label: Text(_saving ? '저장 중...' : '연동하기'),
                  style: FilledButton.styleFrom(backgroundColor: _tossColor),
                ),
                const SizedBox(width: 8),
                OutlinedButton.icon(
                  onPressed: (toss?.hasCredentials ?? false) ? _test : null,
                  icon: const Icon(Icons.network_check, size: 18),
                  label: const Text('연결 테스트'),
                ),
              ],
            ),
            if (test != null) ...[
              const SizedBox(height: 10),
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: (test.ok ? Colors.green : theme.colorScheme.error).withValues(alpha: 0.08),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(
                    color: (test.ok ? Colors.green : theme.colorScheme.error).withValues(alpha: 0.3),
                  ),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      test.ok ? '✅ ${test.message ?? "연결 성공"}' : '❌ ${test.message ?? "연결 실패"}',
                      style: TextStyle(
                        color: test.ok ? Colors.green : theme.colorScheme.error,
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    if (test.ok && test.details != null) ...[
                      const SizedBox(height: 6),
                      for (final acct in (test.details!['accounts'] as List? ?? []))
                        Padding(
                          padding: const EdgeInsets.only(top: 2),
                          child: Text(
                            '계좌 #${(acct as Map)['account_seq']}  ·  ${acct['account_type']}  ·  ${acct['account_no_masked'] ?? ''}',
                            style: theme.textTheme.bodySmall,
                          ),
                        ),
                    ],
                  ],
                ),
              ),
            ],
            const SizedBox(height: 8),
            Text(
              '토스증권 Open API 콘솔(openapi.toss.im)에서 발급받은 Client ID/Secret을 입력하세요.',
              style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.outline),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Telegram
// ---------------------------------------------------------------------------

class _TelegramBlock extends ConsumerStatefulWidget {
  const _TelegramBlock({required this.settings});
  final AppSettings settings;

  @override
  ConsumerState<_TelegramBlock> createState() => _TelegramBlockState();
}

class _TelegramBlockState extends ConsumerState<_TelegramBlock> {
  late final TextEditingController _chatId =
      TextEditingController(text: widget.settings.telegramChatId ?? '');
  final _newToken = TextEditingController();
  bool _saving = false;

  @override
  void dispose() {
    _chatId.dispose();
    _newToken.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      await ref.read(settingsApiProvider).patch({
        'telegram_chat_id': _chatId.text.trim(),
        if (_newToken.text.trim().isNotEmpty) 'telegram_bot_token': _newToken.text.trim(),
      });
      _newToken.clear();
      ref.invalidate(appSettingsProvider);
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('Telegram 설정 저장 완료')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('저장 실패: $e'), backgroundColor: Colors.redAccent),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final test = ref.watch(testResultsProvider)[telegramTestKey];
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: _chatId,
              decoration: const InputDecoration(labelText: 'Telegram chat_id'),
            ),
            const SizedBox(height: 12),
            Text('현재 봇 토큰: ${widget.settings.telegramTokenMasked.isEmpty ? "(미설정)" : widget.settings.telegramTokenMasked}',
                style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 4),
            TextField(
              controller: _newToken,
              obscureText: true,
              decoration: const InputDecoration(labelText: '새 봇 토큰 (변경 시에만 입력)'),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                FilledButton(
                  onPressed: _saving ? null : _save,
                  child: Text(_saving ? '저장 중...' : '저장'),
                ),
                const SizedBox(width: 8),
                OutlinedButton(
                  onPressed: () async {
                    ref.setTestResult(telegramTestKey, TestResult(ok: false, message: '테스트 중...'));
                    try {
                      await ref.read(settingsApiProvider).patch({'__test_telegram': true});
                      ref.setTestResult(telegramTestKey, TestResult(ok: true, message: 'ping 전송 완료'));
                    } catch (e) {
                      ref.setTestResult(telegramTestKey, TestResult(ok: false, message: '$e'));
                    }
                  },
                  child: const Text('Test Telegram'),
                ),
              ],
            ),
            if (test != null) ...[
              const SizedBox(height: 8),
              Text(
                test.ok ? '✅ ${test.message ?? "OK"}' : '❌ ${test.message ?? "실패"}',
                style: TextStyle(
                  color: test.ok ? Colors.green : Theme.of(context).colorScheme.error,
                  fontSize: 12,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// LLM (read-only for V1)
// ---------------------------------------------------------------------------

class _LlmReadOnlyBlock extends StatelessWidget {
  const _LlmReadOnlyBlock({required this.settings});
  final AppSettings settings;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Provider: ${settings.llmProvider}', style: theme.textTheme.bodyMedium),
            Text('Model: ${settings.llmModel}', style: theme.textTheme.bodyMedium),
            Text('API key: ${settings.llmApiKeyMasked.isEmpty ? "(미설정)" : settings.llmApiKeyMasked}',
                style: theme.textTheme.bodyMedium),
            Text('Cache TTL: ${settings.llmCacheTtlHours}시간', style: theme.textTheme.bodyMedium),
            const SizedBox(height: 8),
            Text(
              '⚠️ V1 에서는 LLM 키 편집은 백엔드 .env 에서만 가능합니다. UI 편집은 Phase 5 step ≥ 6에서 활성화됩니다.',
              style: theme.textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Universe (KOSPI200) — manual re-sync from KRX/Wikipedia
// ---------------------------------------------------------------------------

class _UniverseBlock extends ConsumerStatefulWidget {
  const _UniverseBlock();
  @override
  ConsumerState<_UniverseBlock> createState() => _UniverseBlockState();
}

class _UniverseBlockState extends ConsumerState<_UniverseBlock> {
  bool _busy = false;
  UniverseRefreshOutcome? _lastOutcome;
  String? _lastError;

  Future<void> _refresh() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _lastError = null;
    });

    try {
      final outcome = await ref.read(settingsApiProvider).refreshKospi200Universe();
      if (!mounted) return;
      setState(() => _lastOutcome = outcome);
      _showResultSnackbar(outcome);
    } catch (e) {
      if (!mounted) return;
      setState(() => _lastError = '$e');
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('동기화 실패: $e'),
          backgroundColor: Colors.redAccent,
          duration: const Duration(seconds: 6),
        ),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _showResultSnackbar(UniverseRefreshOutcome o) {
    final theme = Theme.of(context);
    String text;
    Color bg;
    if (o.isOfficial) {
      text = 'KOSPI 200 유니버스가 최신 데이터로 동기화되었습니다.'
          '${o.currentCount != null ? ' (총 ${o.currentCount}종목)' : ''}';
      bg = Colors.green.shade700;
    } else if (o.isWikipediaFallback) {
      text = 'KRX 공식 소스에서 데이터를 받아오지 못해, '
          'Wikipedia 대체 소스로 동기화되었습니다.'
          '${o.currentCount != null ? ' (총 ${o.currentCount}종목)' : ''}';
      bg = Colors.amber.shade800;
    } else if (o.isApproximateFallback) {
      text = '근사/캐시 fallback 소스로 동기화되었습니다 (HTTP 206).';
      bg = Colors.orange.shade800;
    } else {
      text = '동기화 완료 (HTTP ${o.statusCode}).';
      bg = theme.colorScheme.surfaceContainerHigh;
    }
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(text),
        backgroundColor: bg,
        duration: const Duration(seconds: 6),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final o = _lastOutcome;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('KOSPI 200 종목 리스트',
                style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            Text(
              '백테스트와 인사이트 화면이 참조하는 KOSPI 200 종목 마스터를 KRX에서 다시 받아옵니다.\n'
              '소요 시간: 보통 3~10초. KRX 응답 실패 시 Wikipedia 로 대체합니다.',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                ElevatedButton.icon(
                  onPressed: _busy ? null : _refresh,
                  icon: _busy
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.sync),
                  label: Text(_busy ? '동기화 중...' : '종목 리스트 최신화'),
                ),
                const SizedBox(width: 12),
                if (_busy)
                  Text('KRX 호출 중 (최대 60초)',
                      style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.outline)),
              ],
            ),
            if (o != null) ...[
              const SizedBox(height: 12),
              _OutcomeSummary(outcome: o),
            ],
            if (_lastError != null) ...[
              const SizedBox(height: 12),
              SelectableText(
                '⚠️ 마지막 시도: $_lastError',
                style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.error),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _OutcomeSummary extends StatelessWidget {
  const _OutcomeSummary({required this.outcome});
  final UniverseRefreshOutcome outcome;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final (label, color) = switch (outcome.statusCode) {
      200 => ('공식 KRX', Colors.green),
      203 => ('Wikipedia fallback', Colors.amber),
      206 => ('근사/캐시 fallback', Colors.orange),
      _ => ('HTTP ${outcome.statusCode}', theme.colorScheme.outline),
    };
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        border: Border.all(color: color.withValues(alpha: 0.3)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(8)),
                child: Text(label,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                    )),
              ),
              const SizedBox(width: 8),
              if (outcome.source != null)
                Text('source: ${outcome.source}', style: theme.textTheme.bodySmall),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            '${outcome.previousCount ?? '-'} → ${outcome.currentCount ?? '-'} 종목 '
            '(추가 ${outcome.added.length} · 삭제 ${outcome.removed.length})',
            style: theme.textTheme.bodyMedium,
          ),
          if (outcome.added.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text('+ ${outcome.added.join(', ')}',
                style: theme.textTheme.bodySmall?.copyWith(color: Colors.green.shade700)),
          ],
          if (outcome.removed.isNotEmpty) ...[
            const SizedBox(height: 2),
            Text('- ${outcome.removed.join(', ')}',
                style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.error)),
          ],
          if (outcome.message != null) ...[
            const SizedBox(height: 6),
            Text(outcome.message!, style: theme.textTheme.bodySmall),
          ],
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Broker order sync (KIS app / HTS imports)
// ---------------------------------------------------------------------------

class _BrokerSyncBlock extends ConsumerStatefulWidget {
  const _BrokerSyncBlock();
  @override
  ConsumerState<_BrokerSyncBlock> createState() => _BrokerSyncBlockState();
}

class _BrokerSyncBlockState extends ConsumerState<_BrokerSyncBlock> {
  bool _busy = false;
  BrokerSyncOutcome? _last;
  String? _error;

  Future<void> _sync() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final outcome = await ref.read(portfolioApiProvider).syncBrokerOrders();
      if (!mounted) return;
      setState(() => _last = outcome);
      // Refresh anything that depends on trades
      ref.invalidate(accountDetailProvider);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '한투앱 거래 내역이 성공적으로 동기화되었습니다.'
            '${outcome.totalImported > 0 ? ' (신규 ${outcome.totalImported}건)' : ''}',
          ),
          backgroundColor: Colors.green.shade700,
          duration: const Duration(seconds: 5),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = '$e');
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('동기화 실패: $e'),
          backgroundColor: Colors.redAccent,
          duration: const Duration(seconds: 6),
        ),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('한투앱 거래 내역 동기화',
                style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            Text(
              '앱 외부(한투 공식 MTS/HTS)에서 체결된 주문 내역을 가져와 매매일지 미작성 목록에 반영합니다.\n'
              '자동: 매일 1회 백그라운드 데몬이 실행됩니다.\n'
              '수동: 아래 버튼으로 즉시 동기화 (최대 60초).',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                ElevatedButton.icon(
                  onPressed: _busy ? null : _sync,
                  icon: _busy
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.cloud_sync_outlined),
                  label: Text(_busy ? '동기화 중...' : '한투앱 거래 내역 동기화'),
                ),
                const SizedBox(width: 12),
                if (_busy)
                  Text('KIS REST 호출 중',
                      style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.outline)),
              ],
            ),
            if (_last != null) ...[
              const SizedBox(height: 12),
              _SyncOutcomeCard(outcome: _last!),
            ],
            if (_error != null) ...[
              const SizedBox(height: 8),
              SelectableText('⚠️ 마지막 시도: $_error',
                  style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.error)),
            ],
          ],
        ),
      ),
    );
  }
}

class _SyncOutcomeCard extends StatelessWidget {
  const _SyncOutcomeCard({required this.outcome});
  final BrokerSyncOutcome outcome;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final hasErrors = outcome.hasErrors;
    final color = hasErrors
        ? Colors.amber.shade700
        : (outcome.totalImported > 0 ? Colors.green : theme.colorScheme.outline);
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        border: Border.all(color: color.withValues(alpha: 0.3)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(8)),
                child: Text(
                  hasErrors ? '일부 오류' : '성공',
                  style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w700),
                ),
              ),
              const SizedBox(width: 8),
              Text('${outcome.elapsed.inMilliseconds}ms', style: theme.textTheme.bodySmall),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            '총 ${outcome.totalSeen}건 조회 · '
            '신규 ${outcome.totalImported}건 · '
            '업데이트 ${outcome.totalUpdated}건',
            style: theme.textTheme.bodyMedium,
          ),
          const SizedBox(height: 6),
          for (final r in outcome.results)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                    decoration: BoxDecoration(
                      color: theme.colorScheme.surface,
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(r.accountType.wire,
                        style: theme.textTheme.labelSmall?.copyWith(fontFamily: 'monospace')),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      r.error != null
                          ? '⚠ ${r.error}'
                          : '조회 ${r.seen} · 신규 ${r.imported} · 업데이트 ${r.updated} · 스킵 ${r.skipped}',
                      style: theme.textTheme.bodySmall,
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Appearance + active-account-default (local-only providers)
// ---------------------------------------------------------------------------

class _ThemeBlock extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(themeModeProvider);
    return Card(
      child: Column(
        children: [
          for (final m in ThemeMode.values)
            RadioListTile<ThemeMode>(
              value: m,
              groupValue: mode,
              onChanged: (v) {
                if (v != null) {
                  ref.read(persistedThemeModeProvider.notifier).set(v);
                }
              },
              title: Text(switch (m) {
                ThemeMode.system => '시스템 설정 따름',
                ThemeMode.light => '라이트 모드',
                ThemeMode.dark => '다크 모드',
              }),
            ),
        ],
      ),
    );
  }
}

class _ActiveAccountBlock extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final account = ref.watch(activeAccountProvider);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SegmentedButton<KisAccountType>(
              segments: const [
                ButtonSegment(value: KisAccountType.paper, label: Text('모의')),
                ButtonSegment(value: KisAccountType.real, label: Text('실전')),
                ButtonSegment(value: KisAccountType.isa, label: Text('ISA')),
              ],
              selected: {account},
              onSelectionChanged: (s) => ref
                  .read(persistedActiveAccountProvider.notifier)
                  .set(s.first),
            ),
            const SizedBox(height: 8),
            const Text(
              '좌측 NavigationRail 의 계좌 배지 색이 함께 바뀝니다. 안전 기본값 = PAPER.',
              style: TextStyle(fontSize: 12),
            ),
          ],
        ),
      ),
    );
  }
}

