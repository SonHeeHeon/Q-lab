"""Scheduled synchronization of broker-side KIS orders."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from backend.app.core.config import settings
from backend.app.services.kis.order_tracker import (
    ExternalOrderSyncResult,
    sync_external_orders_once,
)
from backend.app.services.kis.rest_client import KISRestClient, KISRestError
from shared.domain.account import AccountType

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BrokerOrderSyncError:
    account_type: AccountType
    start_date: date
    end_date: date
    error: str


BrokerOrderSyncJobItem = ExternalOrderSyncResult | BrokerOrderSyncError


async def run_broker_order_sync(
    *,
    lookback_days: int | None = None,
    accounts: list[AccountType] | None = None,
) -> list[BrokerOrderSyncJobItem]:
    """Synchronize app-external KIS orders for configured accounts."""

    sync_end = date.today()
    days = lookback_days if lookback_days is not None else settings.BROKER_ORDER_SYNC_LOOKBACK_DAYS
    sync_start = sync_end - timedelta(days=max(1, days))
    target_accounts = accounts if accounts is not None else settings.broker_order_sync_accounts
    kis_client = KISRestClient()
    results: list[BrokerOrderSyncJobItem] = []

    logger.info(
        "broker order sync started accounts=%s start=%s end=%s",
        [account.value for account in target_accounts],
        sync_start,
        sync_end,
    )
    for account_type in target_accounts:
        try:
            result = await sync_external_orders_once(
                account_type,
                kis_client=kis_client,
                start_date=sync_start,
                end_date=sync_end,
            )
            logger.info(
                "broker order sync account=%s seen=%s imported=%s updated=%s skipped=%s notes=%s",
                account_type.value,
                result.seen,
                result.imported,
                result.updated,
                result.skipped,
                result.notes,
            )
            results.append(result)
        except KISRestError as exc:
            logger.warning(
                "broker order sync failed account=%s error=%s",
                account_type.value,
                exc,
            )
            results.append(
                BrokerOrderSyncError(
                    account_type=account_type,
                    start_date=sync_start,
                    end_date=sync_end,
                    error=str(exc),
                )
            )
        except Exception as exc:
            logger.exception(
                "broker order sync unexpected failure account=%s",
                account_type.value,
            )
            results.append(
                BrokerOrderSyncError(
                    account_type=account_type,
                    start_date=sync_start,
                    end_date=sync_end,
                    error=str(exc),
                )
            )

    logger.info("broker order sync finished accounts=%s", len(results))
    return results
