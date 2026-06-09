"""Verify KIS access-token and WebSocket approval-key issuance."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import Settings
from backend.app.services.kis.auth import KISAuthError, KISTokenManager
from shared.domain.account import AccountType


def _mask(secret: str) -> str:
    if len(secret) <= 10:
        return "*" * len(secret)
    return f"{secret[:6]}...{secret[-4:]}"


def _parse_account(value: str) -> AccountType:
    try:
        return AccountType(value.upper())
    except ValueError as exc:
        choices = ", ".join(account_type.value for account_type in AccountType)
        raise argparse.ArgumentTypeError(f"Choose one of: {choices}") from exc


async def _verify_account(
    manager: KISTokenManager,
    account_type: AccountType,
    *,
    force_refresh: bool,
) -> bool:
    try:
        if force_refresh:
            access_token = await manager.refresh_access_token(account_type)
            approval_key = await manager.refresh_approval_key(account_type)
        else:
            access_token = await manager.get_access_token(account_type)
            approval_key = await manager.get_approval_key(account_type)
        status = manager.cache_status(account_type)
    except KISAuthError as exc:
        print(f"[FAIL] {account_type.value}: {exc}")
        return False

    print(f"[ OK ] {account_type.value}")
    print(f"       access_token: {_mask(access_token)}")
    print(f"       approval_key: {_mask(approval_key)}")
    print(f"       access_token_expires_at: {status.access_token_expires_at}")
    print(f"       approval_key_expires_at: {status.approval_key_expires_at}")
    print(f"       cache: {status.cache_path}")
    return True


async def async_main() -> int:
    parser = argparse.ArgumentParser(
        description="Issue and cache KIS REST access tokens and WS approval keys."
    )
    parser.add_argument(
        "--account",
        action="append",
        type=_parse_account,
        choices=list(AccountType),
        help="Account to verify. Repeatable. Defaults to PAPER, REAL, and ISA.",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore cached values and request fresh tokens from KIS.",
    )
    parser.add_argument(
        "--ca-bundle",
        type=Path,
        help="Path to a PEM CA bundle to trust for KIS HTTPS requests.",
    )
    parser.add_argument(
        "--insecure-skip-ssl-verify",
        action="store_true",
        help="Temporarily disable TLS verification for local diagnostics only.",
    )
    args = parser.parse_args()

    accounts = args.account or list(AccountType)
    settings_overrides = {}
    if args.ca_bundle is not None:
        settings_overrides["KIS_CA_BUNDLE_PATH"] = args.ca_bundle
    if args.insecure_skip_ssl_verify:
        settings_overrides["KIS_SSL_VERIFY"] = False

    manager = KISTokenManager(Settings(**settings_overrides))

    results = []
    for account_type in accounts:
        results.append(
            await _verify_account(
                manager,
                account_type,
                force_refresh=args.force_refresh,
            )
        )

    return 0 if all(results) else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
