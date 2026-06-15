"""Async KIS REST client for domestic stock balance and orders."""

from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import aiohttp
import certifi

from backend.app.core.config import Settings, settings
from backend.app.schemas.portfolio import (
    OrderRequest,
    OrderResponse,
    OrderType,
    PortfolioResponse,
    PortfolioSummary,
    PositionResponse,
)
from backend.app.services.kis.accounts import KISAccountRegistry
from backend.app.services.kis.auth import KISTokenManager
from shared.domain.account import AccountType, KISAccount
from shared.domain.trade import TradeDirection

BALANCE_PATH = "/uapi/domestic-stock/v1/trading/inquire-balance"
ORDER_CASH_PATH = "/uapi/domestic-stock/v1/trading/order-cash"
ORDER_EXECUTION_PATH = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
QUOTE_PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-price"

ORDER_STATUS_PENDING = "PENDING"
ORDER_STATUS_PARTIALLY_FILLED = "PARTIALLY_FILLED"
ORDER_STATUS_FILLED = "FILLED"
ORDER_STATUS_CANCELED = "CANCELED"
ORDER_STATUS_NOT_FOUND = "NOT_FOUND"


class KISRestError(RuntimeError):
    """Raised when a KIS REST request fails or returns rt_cd != 0."""

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
class KISAccountParts:
    cano: str
    acnt_prdt_cd: str


@dataclass(frozen=True, slots=True)
class KISOrderExecution:
    """Normalized KIS order/execution inquiry row."""

    account_type: AccountType
    order_no: str | None
    stock_code: str | None
    direction: TradeDirection | None
    order_quantity: int
    filled_quantity: int
    filled_price: Decimal | None
    order_price: Decimal | None
    fees: Decimal
    taxes: Decimal
    status: str
    filled_at: datetime | None
    raw: dict[str, Any]

    @property
    def is_terminal(self) -> bool:
        return self.status in {ORDER_STATUS_FILLED, ORDER_STATUS_CANCELED}


@dataclass(frozen=True, slots=True)
class KISCurrentPrice:
    """Normalized KIS domestic stock current-price row."""

    stock_code: str
    name: str | None
    current_price: Decimal
    previous_close: Decimal | None
    change_amount: Decimal | None
    change_pct: Decimal
    volume: int
    market_cap: Decimal | None
    raw: dict[str, Any]


class KISRestClient:
    """Small async wrapper around the KIS domestic stock REST endpoints."""

    _semaphores = {account_type: asyncio.Semaphore(20) for account_type in AccountType}

    def __init__(
        self,
        *,
        app_settings: Settings = settings,
        registry: KISAccountRegistry | None = None,
        token_manager: KISTokenManager | None = None,
    ) -> None:
        self._settings = app_settings
        self._registry = registry or KISAccountRegistry(app_settings)
        self._token_manager = token_manager or KISTokenManager(app_settings)

    async def get_balance(self, account_type: AccountType) -> PortfolioResponse:
        account_config = self._registry.get(account_type)
        account = account_config.account
        account_parts = self._split_account_no(account)
        tr_id = "VTTC8434R" if account_type is AccountType.PAPER else "TTTC8434R"

        output1: list[dict[str, Any]] = []
        output2: dict[str, Any] | None = None
        fk100 = ""
        nk100 = ""
        tr_cont = ""

        for _ in range(10):
            params = {
                "CANO": account_parts.cano,
                "ACNT_PRDT_CD": account_parts.acnt_prdt_cd,
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "00",
                "CTX_AREA_FK100": fk100,
                "CTX_AREA_NK100": nk100,
            }
            payload, headers = await self._request(
                "GET",
                account_type,
                BALANCE_PATH,
                tr_id=tr_id,
                params=params,
                tr_cont=tr_cont,
            )
            output1.extend(self._as_list(payload.get("output1")))
            latest_output2 = self._as_dict(payload.get("output2"))
            if latest_output2:
                output2 = latest_output2

            next_tr_cont = str(headers.get("tr_cont", "") or "")
            fk100 = str(payload.get("ctx_area_fk100", "") or "")
            nk100 = str(payload.get("ctx_area_nk100", "") or "")
            if next_tr_cont not in {"M", "F"}:
                break
            tr_cont = "N"
            await asyncio.sleep(0.1)

        return PortfolioResponse(
            account_type=account_type,
            positions=[self._parse_position(row) for row in output1],
            summary=self._parse_summary(account_type, output2 or {}),
            raw_output2=output2,
        )

    async def place_order(self, request: OrderRequest) -> OrderResponse:
        account_config = self._registry.get(request.account_type)
        account = account_config.account
        account_parts = self._split_account_no(account)
        tr_id = self._order_tr_id(request.account_type, request.direction)
        order_dvsn = self._order_dvsn(request.order_type)
        order_price = "0" if request.order_type is OrderType.MARKET else str(request.price)

        body = {
            "CANO": account_parts.cano,
            "ACNT_PRDT_CD": account_parts.acnt_prdt_cd,
            "PDNO": request.stock_code,
            "ORD_DVSN": order_dvsn,
            "ORD_QTY": str(request.quantity),
            "ORD_UNPR": order_price,
            "EXCG_ID_DVSN_CD": request.exchange_id,
            "SLL_TYPE": "01" if request.direction is TradeDirection.SELL else "",
            "CNDT_PRIC": "",
        }
        payload, _headers = await self._request(
            "POST",
            request.account_type,
            ORDER_CASH_PATH,
            tr_id=tr_id,
            json_body=body,
        )
        output = self._as_dict(payload.get("output"))

        return OrderResponse(
            account_type=request.account_type,
            stock_code=request.stock_code,
            direction=request.direction,
            quantity=request.quantity,
            order_type=request.order_type,
            price=request.price,
            kis_order_no=self._first_present(output, "ODNO", "odno", "ord_no"),
            kis_order_time=self._first_present(output, "ORD_TMD", "ord_tmd"),
            accepted_at=datetime.now().astimezone(),
            raw=output or payload,
        )

    async def get_current_price(
        self,
        account_type: AccountType,
        stock_code: str,
    ) -> KISCurrentPrice:
        """Fetch one domestic stock's current price snapshot from KIS."""

        normalized_code = str(stock_code).zfill(6)
        payload, _headers = await self._request(
            "GET",
            account_type,
            QUOTE_PRICE_PATH,
            tr_id="FHKST01010100",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": normalized_code,
            },
        )
        output = self._as_dict(payload.get("output"))
        return self._parse_current_price(normalized_code, output or payload)

    async def get_order_execution(
        self,
        account_type: AccountType,
        order_no: str,
        *,
        stock_code: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> KISOrderExecution:
        """Fetch one domestic stock order's latest execution state from KIS."""

        executions = await self.list_order_executions(
            account_type,
            stock_code=stock_code,
            order_no=order_no,
            start_date=start_date,
            end_date=end_date,
        )
        for execution in executions:
            if execution.order_no == order_no:
                return execution
        if len(executions) == 1:
            return executions[0]
        return KISOrderExecution(
            account_type=account_type,
            order_no=order_no,
            stock_code=stock_code,
            direction=None,
            order_quantity=0,
            filled_quantity=0,
            filled_price=None,
            order_price=None,
            fees=Decimal("0"),
            taxes=Decimal("0"),
            status=ORDER_STATUS_NOT_FOUND,
            filled_at=None,
            raw={"output1": []},
        )

    async def list_order_executions(
        self,
        account_type: AccountType,
        *,
        stock_code: str | None = None,
        order_no: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        max_pages: int = 20,
    ) -> list[KISOrderExecution]:
        """Fetch recent domestic stock order/execution rows from KIS."""

        account_config = self._registry.get(account_type)
        account_parts = self._split_account_no(account_config.account)
        today = date.today()
        query_start = start_date or today - timedelta(days=7)
        query_end = end_date or today

        fk100 = ""
        nk100 = ""
        tr_cont = ""
        executions: list[KISOrderExecution] = []
        for _ in range(max_pages):
            params = {
                "CANO": account_parts.cano,
                "ACNT_PRDT_CD": account_parts.acnt_prdt_cd,
                "INQR_STRT_DT": query_start.strftime("%Y%m%d"),
                "INQR_END_DT": query_end.strftime("%Y%m%d"),
                "SLL_BUY_DVSN_CD": "00",
                "INQR_DVSN": "00",
                "PDNO": stock_code or "",
                "CCLD_DVSN": "00",
                "ORD_GNO_BRNO": "",
                "ODNO": order_no or "",
                "INQR_DVSN_3": "00",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": fk100,
                "CTX_AREA_NK100": nk100,
                "EXCG_ID_DVSN_CD": "KRX",
            }
            payload, headers = await self._request(
                "GET",
                account_type,
                ORDER_EXECUTION_PATH,
                tr_id=self._execution_inquiry_tr_id(account_type),
                params=params,
                tr_cont=tr_cont,
            )
            rows = self._as_list(payload.get("output1"))
            executions.extend(
                self._parse_order_execution(account_type, row, payload=payload)
                for row in rows
            )

            next_tr_cont = str(headers.get("tr_cont", "") or "")
            fk100 = str(
                payload.get("ctx_area_fk100")
                or payload.get("CTX_AREA_FK100")
                or ""
            )
            nk100 = str(
                payload.get("ctx_area_nk100")
                or payload.get("CTX_AREA_NK100")
                or ""
            )
            if next_tr_cont not in {"M", "F"}:
                break
            tr_cont = "N"
            await asyncio.sleep(0.1)

        return executions

    async def _request(
        self,
        method: str,
        account_type: AccountType,
        path: str,
        *,
        tr_id: str,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        tr_cont: str = "",
    ) -> tuple[dict[str, Any], Mapping[str, str]]:
        account_config = self._registry.get(account_type)
        account = account_config.account
        access_token = await self._token_manager.get_access_token(account_type)
        url = f"{account_config.endpoints.rest_base_url}{path}"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {access_token}",
            "appkey": account.app_key.get_secret_value(),
            "appsecret": account.app_secret.get_secret_value(),
            "tr_id": tr_id,
            "tr_cont": tr_cont,
            "custtype": "P",
        }

        timeout = aiohttp.ClientTimeout(total=self._settings.KIS_HTTP_TIMEOUT_SECONDS)
        connector = aiohttp.TCPConnector(ssl=self._ssl_context())

        async with self._semaphores[account_type]:
            try:
                async with aiohttp.ClientSession(
                    timeout=timeout,
                    connector=connector,
                ) as session:
                    async with session.request(
                        method,
                        url,
                        headers=headers,
                        params=params,
                        json=json_body,
                    ) as response:
                        status = response.status
                        response_headers = response.headers
                        response_text = await response.text()
            except aiohttp.ClientConnectorCertificateError as exc:
                raise KISRestError(
                    "KIS TLS certificate verification failed. Set KIS_CA_BUNDLE_PATH "
                    "if your network uses a custom root CA."
                ) from exc
            except aiohttp.ClientError as exc:
                raise KISRestError(f"KIS REST client error: {exc}") from exc
            except TimeoutError as exc:
                raise KISRestError(
                    f"KIS REST request timed out after "
                    f"{self._settings.KIS_HTTP_TIMEOUT_SECONDS}s."
                ) from exc

        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise KISRestError(
                f"KIS REST response was not JSON. HTTP {status}: "
                f"{response_text[:300]}",
                status_code=status,
            ) from exc

        if status >= 400:
            raise KISRestError(
                f"KIS REST request failed. HTTP {status}",
                status_code=status,
                payload=payload,
            )

        if payload.get("rt_cd") not in (None, "0"):
            message = str(payload.get("msg1") or payload.get("msg_cd") or payload)
            raise KISRestError(message, status_code=status, payload=payload)

        return payload, response_headers

    def _split_account_no(self, account: KISAccount) -> KISAccountParts:
        normalized = account.account_no.replace("-", "").strip()
        if len(normalized) == 8:
            return KISAccountParts(cano=normalized, acnt_prdt_cd="01")
        if len(normalized) < 10:
            raise KISRestError(
                f"Invalid account number for {account.type.value}: "
                "expected 8-2 format such as 12345678-01, or an 8-digit "
                "domestic stock account number that defaults to product code 01."
            )
        return KISAccountParts(cano=normalized[:8], acnt_prdt_cd=normalized[8:10])

    def _order_tr_id(
        self,
        account_type: AccountType,
        direction: TradeDirection,
    ) -> str:
        if account_type is AccountType.PAPER:
            return "VTTC0012U" if direction is TradeDirection.BUY else "VTTC0011U"
        return "TTTC0012U" if direction is TradeDirection.BUY else "TTTC0011U"

    def _order_dvsn(self, order_type: OrderType) -> str:
        if order_type is OrderType.MARKET:
            return "01"
        if order_type is OrderType.LIMIT:
            return "00"
        raise KISRestError(f"Unsupported order type: {order_type}")

    def _execution_inquiry_tr_id(self, account_type: AccountType) -> str:
        return "VTTC8001R" if account_type is AccountType.PAPER else "TTTC8001R"

    def _match_order_row(
        self,
        rows: list[dict[str, Any]],
        order_no: str,
    ) -> dict[str, Any] | None:
        normalized_order_no = str(order_no).strip()
        for row in rows:
            row_order_no = self._first_present(
                row,
                "odno",
                "ODNO",
                "ord_no",
                "ORD_NO",
                "order_no",
            )
            if row_order_no == normalized_order_no:
                return row
        return rows[0] if len(rows) == 1 else None

    def _parse_order_execution(
        self,
        account_type: AccountType,
        row: dict[str, Any],
        *,
        payload: dict[str, Any],
    ) -> KISOrderExecution:
        order_no = self._first_present(row, "odno", "ODNO", "ord_no", "ORD_NO")
        stock_code = self._first_present(row, "pdno", "PDNO", "stock_code")
        order_quantity = self._first_int(
            row,
            "ord_qty",
            "ORD_QTY",
            "order_qty",
            "tot_ord_qty",
        )
        filled_quantity = self._first_int(
            row,
            "tot_ccld_qty",
            "TOT_CCLD_QTY",
            "ccld_qty",
            "CCLD_QTY",
            "filled_qty",
        )
        order_price = self._first_decimal(row, "ord_unpr", "ORD_UNPR", "order_price")
        filled_price = self._first_decimal(
            row,
            "avg_prvs",
            "AVG_PRVS",
            "avg_ccld_pric",
            "AVG_CCLD_PRIC",
            "ccld_unpr",
            "CCLD_UNPR",
            "filled_price",
        )
        if filled_price is None and filled_quantity > 0:
            filled_amount = self._first_decimal(
                row,
                "tot_ccld_amt",
                "TOT_CCLD_AMT",
                "ccld_amt",
                "CCLD_AMT",
            )
            if filled_amount is not None:
                filled_price = filled_amount / Decimal(filled_quantity)

        direction = self._parse_direction(row)
        fees = self._first_decimal(
            row,
            "ord_fee",
            "ORD_FEE",
            "ccld_cmsn",
            "CCLD_CMSN",
            "cmsn_amt",
            "fee",
        ) or Decimal("0")
        taxes = self._first_decimal(
            row,
            "tr_tax",
            "TR_TAX",
            "stex",
            "STEX",
            "tax",
            "tax_amt",
        ) or Decimal("0")
        status = self._parse_order_status(row, order_quantity, filled_quantity)
        raw = {"row": row, "payload": payload}
        return KISOrderExecution(
            account_type=account_type,
            order_no=order_no,
            stock_code=stock_code.zfill(6) if stock_code else None,
            direction=direction,
            order_quantity=order_quantity,
            filled_quantity=filled_quantity,
            filled_price=filled_price,
            order_price=order_price,
            fees=fees,
            taxes=taxes,
            status=status,
            filled_at=self._parse_execution_time(row),
            raw=raw,
        )

    def _parse_direction(self, row: dict[str, Any]) -> TradeDirection | None:
        value = str(
            self._first_present(
                row,
                "sll_buy_dvsn_cd",
                "SLL_BUY_DVSN_CD",
                "sll_buy_dvsn_name",
                "trad_dvsn_name",
                "buy_sell_name",
            )
            or ""
        ).strip()
        if value in {"01", "1", "SELL", "매도"} or "매도" in value:
            return TradeDirection.SELL
        if value in {"02", "2", "BUY", "매수"} or "매수" in value:
            return TradeDirection.BUY
        return None

    def _parse_order_status(
        self,
        row: dict[str, Any],
        order_quantity: int,
        filled_quantity: int,
    ) -> str:
        text_values = " ".join(str(value) for value in row.values() if value is not None)
        cancel_flag = str(
            self._first_present(row, "cncl_yn", "CNCL_YN", "cancel_yn") or ""
        ).upper()
        if cancel_flag == "Y" or "취소" in text_values or "CANCEL" in text_values.upper():
            return ORDER_STATUS_CANCELED
        if order_quantity > 0 and filled_quantity >= order_quantity:
            return ORDER_STATUS_FILLED
        if filled_quantity > 0:
            return ORDER_STATUS_PARTIALLY_FILLED
        return ORDER_STATUS_PENDING

    def _parse_execution_time(self, row: dict[str, Any]) -> datetime | None:
        date_value = self._first_present(
            row,
            "ccld_dt",
            "CCLD_DT",
            "ord_dt",
            "ORD_DT",
            "order_dt",
        )
        time_value = self._first_present(
            row,
            "ccld_tmd",
            "CCLD_TMD",
            "ord_tmd",
            "ORD_TMD",
            "order_tmd",
        )
        if not date_value:
            return None
        cleaned_date = "".join(ch for ch in str(date_value) if ch.isdigit())
        cleaned_time = "".join(ch for ch in str(time_value or "000000") if ch.isdigit())
        if len(cleaned_date) != 8:
            return None
        cleaned_time = cleaned_time.ljust(6, "0")[:6]
        try:
            return datetime.strptime(f"{cleaned_date}{cleaned_time}", "%Y%m%d%H%M%S")
        except ValueError:
            return None

    def _parse_position(self, row: dict[str, Any]) -> PositionResponse:
        quantity = self._to_int(row.get("hldg_qty"))
        avg_buy_price = self._to_decimal(row.get("pchs_avg_pric"))
        current_price = self._to_decimal(row.get("prpr"))
        unrealized_pl = self._to_decimal(row.get("evlu_pfls_amt"))

        return PositionResponse(
            stock_code=str(row.get("pdno") or row.get("PDNO") or ""),
            name=self._optional_str(row.get("prdt_name") or row.get("PRDT_NAME")),
            quantity=quantity,
            avg_buy_price=avg_buy_price,
            current_price=current_price,
            purchase_amount=self._to_optional_decimal(row.get("pchs_amt")),
            evaluation_amount=self._to_optional_decimal(row.get("evlu_amt")),
            unrealized_pl=unrealized_pl,
            unrealized_pl_rate=self._to_optional_decimal(row.get("evlu_pfls_rt")),
        )

    def _parse_summary(
        self,
        account_type: AccountType,
        row: dict[str, Any],
    ) -> PortfolioSummary:
        return PortfolioSummary(
            account_type=account_type,
            total_evaluation_amount=self._to_optional_decimal(row.get("tot_evlu_amt")),
            stock_evaluation_amount=self._to_optional_decimal(row.get("scts_evlu_amt")),
            purchase_amount=self._to_optional_decimal(row.get("pchs_amt_smtl_amt")),
            cash_amount=self._to_optional_decimal(
                row.get("dnca_tot_amt") or row.get("prvs_rcdl_excc_amt")
            ),
            unrealized_pl=self._to_optional_decimal(row.get("evlu_pfls_smtl_amt")),
            unrealized_pl_rate=self._to_optional_decimal(
                row.get("asst_icdc_erng_rt") or row.get("evlu_pfls_rt")
            ),
        )

    def _parse_current_price(
        self,
        stock_code: str,
        row: dict[str, Any],
    ) -> KISCurrentPrice:
        current_price = self._to_decimal(
            row.get("stck_prpr")
            or row.get("STCK_PRPR")
            or row.get("current_price")
        )
        previous_close = self._to_optional_decimal(
            row.get("stck_sdpr")
            or row.get("STCK_SDPR")
            or row.get("prdy_clpr")
            or row.get("PRDY_CLPR")
        )
        change_amount = self._to_optional_decimal(
            row.get("prdy_vrss")
            or row.get("PRDY_VRSS")
            or row.get("change_amount")
        )
        change_pct = self._to_decimal(
            row.get("prdy_ctrt")
            or row.get("PRDY_CTRT")
            or row.get("change_pct")
        )
        market_cap = self._market_cap_to_krw(
            self._to_optional_decimal(
                row.get("hts_avls")
                or row.get("HTS_AVLS")
                or row.get("market_cap")
            )
        )
        return KISCurrentPrice(
            stock_code=stock_code,
            name=self._optional_str(
                row.get("hts_kor_isnm")
                or row.get("HTS_KOR_ISNM")
                or row.get("prdt_name")
            ),
            current_price=current_price,
            previous_close=previous_close,
            change_amount=change_amount,
            change_pct=change_pct,
            volume=self._to_int(
                row.get("acml_vol")
                or row.get("ACML_VOL")
                or row.get("volume")
            ),
            market_cap=market_cap,
            raw=row,
        )

    def _market_cap_to_krw(self, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        if value <= 0:
            return None
        if value < Decimal("1000000000"):
            return value * Decimal("100000000")
        return value

    def _ssl_context(self) -> ssl.SSLContext | bool:
        if not self._settings.KIS_SSL_VERIFY:
            return False
        ca_bundle_path = self._settings.kis_ca_bundle_path
        if ca_bundle_path is not None:
            if not ca_bundle_path.exists() or not ca_bundle_path.is_file():
                raise KISRestError(f"KIS_CA_BUNDLE_PATH is not a file: {ca_bundle_path}")
            return ssl.create_default_context(cafile=str(ca_bundle_path))
        return ssl.create_default_context(cafile=certifi.where())

    def _as_list(self, value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [value]
        return []

    def _as_dict(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value[0]
        return {}

    def _first_present(self, row: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = row.get(key)
            if value:
                return str(value)
        return None

    def _optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        value_str = str(value).strip()
        return value_str or None

    def _first_int(self, row: dict[str, Any], *keys: str) -> int:
        for key in keys:
            if key in row and row[key] not in (None, ""):
                return self._to_int(row[key])
        return 0

    def _first_decimal(self, row: dict[str, Any], *keys: str) -> Decimal | None:
        for key in keys:
            if key in row and row[key] not in (None, ""):
                return self._to_optional_decimal(row[key])
        return None

    def _to_int(self, value: Any) -> int:
        if value in (None, ""):
            return 0
        try:
            return int(Decimal(str(value).replace(",", "")))
        except (InvalidOperation, ValueError):
            return 0

    def _to_decimal(self, value: Any) -> Decimal:
        return self._to_optional_decimal(value) or Decimal("0")

    def _to_optional_decimal(self, value: Any) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value).replace(",", ""))
        except (InvalidOperation, ValueError):
            return None
