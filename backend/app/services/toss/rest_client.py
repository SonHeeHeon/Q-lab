"""Async Toss Securities Open API REST client."""

from __future__ import annotations

import json
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

import aiohttp
import certifi

from backend.app.core.config import PROJECT_ROOT, Settings, settings
from backend.app.schemas.portfolio import (
    OrderRequest,
    OrderResponse,
    OrderType,
    PortfolioResponse,
    PortfolioSummary,
    PositionResponse,
)
from backend.app.services.brokers.base import BrokerAccountRef, BrokerQuote
from shared.domain.account import AccountType, BrokerType

TOKEN_PATH = "/oauth2/token"
ACCOUNTS_PATH = "/api/v1/accounts"
HOLDINGS_PATH = "/api/v1/holdings"
PRICES_PATH = "/api/v1/prices"
ORDERS_PATH = "/api/v1/orders"
EXCHANGE_RATE_PATH = "/api/v1/exchange-rate"
BUYING_POWER_PATH = "/api/v1/buying-power"


class TossRestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


@dataclass(frozen=True, slots=True)
class TossAccount:
    account_no: str
    account_seq: int
    account_type: str
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TossToken:
    access_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class TossExchangeRate:
    base_currency: str
    quote_currency: str
    rate: Decimal
    mid_rate: Decimal
    change_type: str
    valid_from: datetime
    valid_until: datetime | None
    raw: dict[str, Any]


class TossRestClient:
    """Small wrapper around Toss Securities Open API v1."""

    broker = BrokerType.TOSS

    def __init__(
        self,
        *,
        app_settings: Settings = settings,
        client_id: str | None = None,
        client_secret: str | None = None,
        account_seq: int | str | None = None,
        is_mock: bool | None = None,
        base_url: str | None = None,
    ) -> None:
        self._settings = app_settings
        self._client_id = client_id if client_id is not None else app_settings.TOSS_CLIENT_ID
        if client_secret is None:
            client_secret = app_settings.TOSS_CLIENT_SECRET.get_secret_value()
        self._client_secret = client_secret
        self._account_seq = _optional_int(
            account_seq if account_seq is not None else app_settings.TOSS_ACCOUNT_SEQ
        )
        self._is_mock = app_settings.TOSS_IS_MOCK if is_mock is None else is_mock
        self._base_url = (base_url or app_settings.TOSS_API_BASE_URL).rstrip("/")
        self._cached_token: TossToken | None = None

    @classmethod
    def from_settings_map(cls, rows: Mapping[str, str]) -> "TossRestClient":
        return cls(
            client_id=rows.get("toss_client_id") or settings.TOSS_CLIENT_ID,
            client_secret=(
                rows.get("toss_client_secret")
                or settings.TOSS_CLIENT_SECRET.get_secret_value()
            ),
            account_seq=rows.get("toss_account_seq") or settings.TOSS_ACCOUNT_SEQ,
            is_mock=_str_to_bool(rows.get("toss_is_mock"), settings.TOSS_IS_MOCK),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

    @property
    def is_mock(self) -> bool:
        return self._is_mock

    async def get_accounts(self) -> list[TossAccount]:
        payload = await self._request("GET", ACCOUNTS_PATH)
        return [
            TossAccount(
                account_no=str(row.get("accountNo") or ""),
                account_seq=int(row.get("accountSeq") or 0),
                account_type=str(row.get("accountType") or ""),
                raw=row,
            )
            for row in _as_list(payload.get("result"))
        ]

    async def resolve_account_seq(self, explicit: int | str | None = None) -> int:
        if explicit is not None and str(explicit).strip():
            return int(explicit)
        if self._account_seq is not None:
            return self._account_seq
        accounts = await self.get_accounts()
        brokerage_accounts = [
            account for account in accounts if account.account_type == "BROKERAGE"
        ]
        selected = brokerage_accounts[0] if brokerage_accounts else (accounts[0] if accounts else None)
        if selected is None:
            raise TossRestError("Toss account list is empty.")
        return selected.account_seq

    async def get_balance(self, account: BrokerAccountRef | None = None) -> PortfolioResponse:
        account_seq = await self.resolve_account_seq(account.account_id if account else None)
        payload = await self._request(
            "GET",
            HOLDINGS_PATH,
            headers={"X-Tossinvest-Account": str(account_seq)},
        )
        result = _as_dict(payload.get("result"))
        items = _as_list(result.get("items"))
        positions = [
            self._parse_position(item, account_seq=account_seq)
            for item in items
        ]
        summary = self._parse_summary(result, account_seq=account_seq)
        summary = await self._fill_missing_cash_from_buying_power(
            account_seq=account_seq,
            summary=summary,
        )
        return PortfolioResponse(
            broker=BrokerType.TOSS,
            account_type=None,
            account_id=str(account_seq),
            positions=positions,
            summary=summary,
            raw_output2=result,
        )

    async def get_buying_power(
        self,
        *,
        currency: str,
        account_seq: int | str | None = None,
    ) -> Decimal | None:
        resolved_account_seq = await self.resolve_account_seq(account_seq)
        payload = await self._request(
            "GET",
            BUYING_POWER_PATH,
            headers={"X-Tossinvest-Account": str(resolved_account_seq)},
            params={"currency": currency.upper()},
        )
        result = _as_dict(payload.get("result"))
        return _optional_decimal(result.get("cashBuyingPower"))

    async def get_current_prices(self, symbols: list[str]) -> list[BrokerQuote]:
        if not symbols:
            return []
        payload = await self._request(
            "GET",
            PRICES_PATH,
            params={"symbols": ",".join(symbols[:200])},
        )
        return [
            BrokerQuote(
                broker=BrokerType.TOSS,
                symbol=str(row.get("symbol") or ""),
                last_price=_decimal(row.get("lastPrice")),
                currency=str(row.get("currency") or ""),
                timestamp=str(row.get("timestamp")) if row.get("timestamp") else None,
                raw=row,
            )
            for row in _as_list(payload.get("result"))
        ]

    async def get_current_price(
        self,
        symbol: str,
        *,
        account: BrokerAccountRef | None = None,
    ) -> BrokerQuote:
        quotes = await self.get_current_prices([symbol])
        if not quotes:
            raise TossRestError(f"Toss price not found for symbol: {symbol}")
        return quotes[0]

    async def get_exchange_rate(
        self,
        *,
        base_currency: str = "USD",
        quote_currency: str = "KRW",
        date_time: datetime | None = None,
    ) -> TossExchangeRate:
        params: dict[str, str] = {
            "baseCurrency": base_currency.upper(),
            "quoteCurrency": quote_currency.upper(),
        }
        if date_time is not None:
            params["dateTime"] = date_time.isoformat()

        payload = await self._request("GET", EXCHANGE_RATE_PATH, params=params)
        result = _as_dict(payload.get("result"))
        if not result:
            raise TossRestError("Toss exchange-rate response did not include result.")

        rate = _optional_decimal(result.get("rate"))
        mid_rate = _optional_decimal(result.get("midRate"))
        valid_from = _parse_datetime(result.get("validFrom")) or datetime.now().astimezone()
        if rate is None or mid_rate is None:
            raise TossRestError("Toss exchange-rate response did not include rate/midRate.")

        return TossExchangeRate(
            base_currency=str(result.get("baseCurrency") or base_currency).upper(),
            quote_currency=str(result.get("quoteCurrency") or quote_currency).upper(),
            rate=rate,
            mid_rate=mid_rate,
            change_type=_normalize_change_type(result.get("rateChangeType"), rate, mid_rate),
            valid_from=valid_from,
            valid_until=_parse_datetime(result.get("validUntil")),
            raw=result,
        )

    async def place_order(self, request: OrderRequest) -> OrderResponse:
        account_seq = await self.resolve_account_seq(request.account_id)
        body = {
            "symbol": request.stock_code,
            "side": request.direction.value,
            "orderType": request.order_type.value,
            "quantity": str(request.quantity),
            "confirmHighValueOrder": False,
        }
        if request.order_type is OrderType.LIMIT:
            body["price"] = str(request.price)

        if self._is_mock:
            now = datetime.now().astimezone()
            mock_order_id = f"TOSS-MOCK-{now.strftime('%Y%m%d%H%M%S%f')}"
            return OrderResponse(
                broker=BrokerType.TOSS,
                account_type=None,
                account_id=str(account_seq),
                stock_code=request.stock_code,
                direction=request.direction,
                quantity=request.quantity,
                order_type=request.order_type,
                price=request.price,
                kis_order_no=None,
                broker_order_no=mock_order_id,
                accepted_at=now,
                raw={"mock": True, "request": body, "orderId": mock_order_id},
            )

        payload = await self._request(
            "POST",
            ORDERS_PATH,
            headers={"X-Tossinvest-Account": str(account_seq)},
            json_body=body,
        )
        result = _as_dict(payload.get("result"))
        order_id = str(result.get("orderId") or "")
        return OrderResponse(
            broker=BrokerType.TOSS,
            account_type=None,
            account_id=str(account_seq),
            stock_code=request.stock_code,
            direction=request.direction,
            quantity=request.quantity,
            order_type=request.order_type,
            price=request.price,
            kis_order_no=None,
            broker_order_no=order_id or None,
            accepted_at=datetime.now().astimezone(),
            raw=result or payload,
        )

    async def _access_token(self) -> str:
        if self._cached_token and self._cached_token.expires_at > datetime.now():
            return self._cached_token.access_token
        cache = self._read_token_cache()
        if cache and cache.expires_at > datetime.now():
            self._cached_token = cache
            return cache.access_token
        return await self._refresh_token()

    async def _refresh_token(self) -> str:
        if not self.is_configured:
            raise TossRestError("TOSS_CLIENT_ID and TOSS_CLIENT_SECRET are required.")
        timeout = aiohttp.ClientTimeout(total=self._settings.TOSS_HTTP_TIMEOUT_SECONDS)
        connector = aiohttp.TCPConnector(ssl=self._ssl_context())
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.post(
                f"{self._base_url}{TOKEN_PATH}",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={"content-type": "application/x-www-form-urlencoded"},
            ) as response:
                status = response.status
                text = await response.text()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TossRestError(
                f"Toss token response was not JSON. HTTP {status}: {text[:300]}",
                status_code=status,
            ) from exc
        if status >= 400:
            raise TossRestError(
                str(payload.get("error_description") or payload),
                status_code=status,
                payload=payload,
            )
        ttl = int(payload.get("expires_in") or 86400)
        token = TossToken(
            access_token=str(payload["access_token"]),
            expires_at=datetime.now() + timedelta(seconds=max(ttl - 300, 60)),
        )
        self._cached_token = token
        self._write_token_cache(token)
        return token.access_token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = await self._access_token()
        request_headers = {
            "authorization": f"Bearer {token}",
            "accept": "application/json",
        }
        if json_body is not None:
            request_headers["content-type"] = "application/json"
        if headers:
            request_headers.update(headers)
        timeout = aiohttp.ClientTimeout(total=self._settings.TOSS_HTTP_TIMEOUT_SECONDS)
        connector = aiohttp.TCPConnector(ssl=self._ssl_context())
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            try:
                async with session.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=request_headers,
                    params=params,
                    json=json_body,
                ) as response:
                    status = response.status
                    text = await response.text()
            except aiohttp.ClientConnectorCertificateError as exc:
                raise TossRestError(
                    "Toss TLS certificate verification failed. Set TOSS_CA_BUNDLE_PATH "
                    "if your network uses a custom root CA."
                ) from exc
            except aiohttp.ClientError as exc:
                raise TossRestError(f"Toss REST client error: {exc}") from exc
            except TimeoutError as exc:
                raise TossRestError(
                    f"Toss REST request timed out after "
                    f"{self._settings.TOSS_HTTP_TIMEOUT_SECONDS}s."
                ) from exc
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TossRestError(
                f"Toss REST response was not JSON. HTTP {status}: {text[:300]}",
                status_code=status,
            ) from exc
        if status >= 400 or payload.get("error"):
            message = str(_as_dict(payload.get("error")).get("message") or payload)
            raise TossRestError(message, status_code=status, payload=payload)
        return payload

    def _parse_position(self, row: dict[str, Any], *, account_seq: int) -> PositionResponse:
        market_value = _as_dict(row.get("marketValue"))
        profit_loss = _as_dict(row.get("profitLoss"))
        symbol = str(row.get("symbol") or "")
        currency = str(row.get("currency") or _infer_currency(symbol)).upper()
        market_country = str(row.get("marketCountry") or _infer_market_country(symbol)).upper()
        return PositionResponse(
            broker=BrokerType.TOSS,
            account_type=None,
            account_id=str(account_seq),
            stock_code=symbol,
            name=str(row.get("name") or "") or None,
            currency=currency,
            market_country=market_country,
            quantity=int(_decimal(row.get("quantity"))),
            avg_buy_price=_decimal(row.get("averagePurchasePrice")),
            current_price=_decimal(row.get("lastPrice")),
            purchase_amount=_money_in_currency(market_value.get("purchaseAmount"), currency),
            evaluation_amount=_money_in_currency(market_value.get("amount"), currency),
            unrealized_pl=_money_in_currency(profit_loss.get("amount"), currency),
            unrealized_pl_rate=_rate_to_percent(profit_loss.get("rate")),
        )

    def _parse_summary(self, result: dict[str, Any], *, account_seq: int) -> PortfolioSummary:
        market_value = _as_dict(result.get("marketValue"))
        profit_loss = _as_dict(result.get("profitLoss"))
        purchase = _as_dict(result.get("totalPurchaseAmount"))
        market_amount = _as_dict(market_value.get("amount"))
        profit_amount = _as_dict(profit_loss.get("amount"))
        cash_amount = _cash_money_dict(result)
        cash_krw = _optional_decimal(cash_amount.get("krw"))
        cash_usd = _optional_decimal(cash_amount.get("usd"))
        return PortfolioSummary(
            broker=BrokerType.TOSS,
            account_type=None,
            account_id=str(account_seq),
            currency="KRW",
            total_evaluation_amount=_optional_decimal(market_amount.get("krw")),
            stock_evaluation_amount=_optional_decimal(market_amount.get("krw")),
            purchase_amount=_optional_decimal(purchase.get("krw")),
            cash_amount=cash_krw,
            cash_krw=cash_krw,
            cash_usd=cash_usd,
            unrealized_pl=_optional_decimal(profit_amount.get("krw")),
            unrealized_pl_rate=_rate_to_percent(profit_loss.get("rate")),
        )

    async def _fill_missing_cash_from_buying_power(
        self,
        *,
        account_seq: int,
        summary: PortfolioSummary,
    ) -> PortfolioSummary:
        if summary.cash_krw is None:
            summary.cash_krw = await self._safe_buying_power("KRW", account_seq)
            summary.cash_amount = summary.cash_krw
        if summary.cash_usd is None:
            summary.cash_usd = await self._safe_buying_power("USD", account_seq)
        return summary

    async def _safe_buying_power(
        self,
        currency: str,
        account_seq: int,
    ) -> Decimal | None:
        try:
            return await self.get_buying_power(
                currency=currency,
                account_seq=account_seq,
            )
        except TossRestError:
            return None

    def _token_cache_path(self) -> Path:
        return self._settings.token_cache_dir / "toss.json"

    def _read_token_cache(self) -> TossToken | None:
        path = self._token_cache_path()
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return TossToken(
                access_token=str(payload["access_token"]),
                expires_at=datetime.fromisoformat(str(payload["expires_at"])),
            )
        except Exception:
            return None

    def _write_token_cache(self, token: TossToken) -> None:
        path = self._token_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "access_token": token.access_token,
                    "expires_at": token.expires_at.isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _ssl_context(self) -> ssl.SSLContext | bool:
        if not self._settings.TOSS_SSL_VERIFY:
            return False
        ca_bundle_path = self._settings.toss_ca_bundle_path
        if ca_bundle_path is not None:
            if not ca_bundle_path.exists() or not ca_bundle_path.is_file():
                raise TossRestError(f"TOSS_CA_BUNDLE_PATH is not a file: {ca_bundle_path}")
            return ssl.create_default_context(cafile=str(ca_bundle_path))
        return ssl.create_default_context(cafile=certifi.where())


def spec_path() -> Path:
    return PROJECT_ROOT / "docs" / "toss_openapi.json"


def _as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _optional_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return _decimal(value)


def _money_in_currency(value: Any, currency: str) -> Decimal | None:
    if isinstance(value, dict):
        for key in (currency.lower(), currency.upper()):
            if key in value and value[key] not in (None, ""):
                return _optional_decimal(value[key])
        return None
    return _optional_decimal(value)


def _cash_money_dict(result: dict[str, Any]) -> dict[str, Any]:
    for key in (
        "depositAmount",
        "availableAmount",
        "freeDeposit",
        "freeDepositAmount",
        "cashBalance",
        "cashBuyingPower",
        "buyingPower",
        "cashAmount",
        "cash",
        "deposit",
        "availableCash",
        "availableCashAmount",
        "withdrawableAmount",
        "withdrawableCash",
        "withdrawableCashAmount",
        "amount",
    ):
        value = result.get(key)
        if isinstance(value, dict):
            if _looks_like_money_dict(value):
                return value
            amount = value.get("amount")
            if isinstance(amount, dict) and _looks_like_money_dict(amount):
                return amount
    return {}


def _looks_like_money_dict(value: dict[str, Any]) -> bool:
    return any(key in value for key in ("krw", "KRW", "usd", "USD"))


def _rate_to_percent(value: Any) -> Decimal | None:
    parsed = _optional_decimal(value)
    return parsed * Decimal("100") if parsed is not None else None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_change_type(value: Any, rate: Decimal, mid_rate: Decimal) -> str:
    text = str(value or "").upper()
    if text in {"UP", "EQUAL", "DOWN"}:
        return text
    if text in {"RISE", "RISING"}:
        return "UP"
    if text in {"FALL", "FALLING"}:
        return "DOWN"
    if rate > mid_rate:
        return "UP"
    if rate < mid_rate:
        return "DOWN"
    return "EQUAL"


def _infer_currency(symbol: str) -> str:
    return "KRW" if symbol.isdigit() else "USD"


def _infer_market_country(symbol: str) -> str:
    return "KR" if symbol.isdigit() else "US"


def _optional_int(value: int | str | None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(value)


def _str_to_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
