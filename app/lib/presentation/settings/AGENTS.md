<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/lib/presentation/settings/ — App Settings

## Purpose
User-configurable settings — KIS account credentials (app_key/app_secret/account_no/account_type), Toss account config (accountSeq), notification preferences, mock/live mode toggle.

## Key Files

| File | Description |
|------|-------------|
| `settings_screen.dart` | `SettingsScreen` — form fields for KIS + Toss config, save/reset actions |
| `settings_controller.dart` | `appSettingsProvider` (`FutureProvider<AppSettings?>`), save action, `activeAccountProvider` sync |

## For AI Agents

### `appSettingsProvider` — Critical Global
This provider is read by `portfolio_screen.dart`, `stock_detail_screen.dart`, and `order_sheet.dart` to get `toss.accountSeq` for Toss order routing:
```dart
final tossAccountId = ref.read(appSettingsProvider).valueOrNull?.toss?.accountSeq?.toString();
```
Null means Toss is not configured → Toss orders will fail gracefully with an error message.

### Never Log Credentials
`app_key`, `app_secret`, and `accountSeq` must never appear in logs.

<!-- MANUAL: -->
