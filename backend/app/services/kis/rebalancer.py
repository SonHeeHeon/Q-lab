"""Portfolio rebalancing planner and safe execution helper."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR

from backend.app.core.config import settings
from backend.app.schemas.portfolio import OrderRequest, OrderResponse, OrderType
from backend.app.services.automation.safety import assert_order_allowed
from backend.app.services.kis.rest_client import KISRestClient
from shared.domain.account import AccountType
from shared.domain.trade import TradeDirection

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RebalanceOrderPlan:
    stock_code: str
    direction: TradeDirection
    quantity: int
    reference_price: Decimal
    current_value: Decimal
    target_value: Decimal
    diff_value: Decimal

    @property
    def estimated_notional(self) -> Decimal:
        return self.reference_price * Decimal(self.quantity)


@dataclass(frozen=True, slots=True)
class RebalancePlan:
    account_type: AccountType
    target_weights: dict[str, Decimal]
    total_portfolio_value: Decimal
    investable_value: Decimal
    current_values: dict[str, Decimal]
    orders: list[RebalanceOrderPlan]
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class RebalanceExecutionResult:
    is_mock: bool
    attempted_orders: int
    submitted_orders: list[OrderResponse]
    plan: RebalancePlan


async def build_rebalance_plan(
    *,
    account_type: AccountType,
    target_weights: dict[str, Decimal | float | int],
    kis_client: KISRestClient | None = None,
    total_target_value: Decimal | None = None,
    min_trade_value: Decimal | None = None,
    cash_buffer_pct: Decimal | None = None,
    normalize_overallocated: bool = True,
) -> RebalancePlan:
    """Create market-order deltas from current KIS holdings and target weights."""

    client = kis_client or KISRestClient()
    portfolio = await client.get_balance(account_type)
    weights, warnings = _normalize_target_weights(
        target_weights,
        normalize_overallocated=normalize_overallocated,
    )
    current_values: dict[str, Decimal] = {}
    current_quantities: dict[str, int] = {}
    prices: dict[str, Decimal] = {}

    for position in portfolio.positions:
        code = position.stock_code.zfill(6)
        price = position.current_price or position.avg_buy_price
        value = position.evaluation_amount
        if value is None:
            value = price * Decimal(position.quantity)
        current_values[code] = value
        current_quantities[code] = position.quantity
        prices[code] = price

    await _fill_missing_target_prices(
        account_type=account_type,
        target_codes=set(weights) - set(prices),
        prices=prices,
        kis_client=client,
        warnings=warnings,
    )

    summary_value = portfolio.summary.total_evaluation_amount
    if summary_value is None:
        cash = portfolio.summary.cash_amount or Decimal("0")
        summary_value = sum(current_values.values(), Decimal("0")) + cash
    total_value = total_target_value or summary_value
    buffer_pct = cash_buffer_pct if cash_buffer_pct is not None else Decimal(str(settings.REBALANCER_CASH_BUFFER_PCT))
    investable_value = total_value * (Decimal("1") - buffer_pct)
    minimum = min_trade_value or Decimal(settings.REBALANCER_MIN_TRADE_VALUE)

    orders: list[RebalanceOrderPlan] = []
    for code in sorted(set(current_values) | set(weights)):
        current_value = current_values.get(code, Decimal("0"))
        target_value = investable_value * weights.get(code, Decimal("0"))
        diff = target_value - current_value
        price = prices.get(code)
        if price is None or price <= 0:
            if diff > 0:
                warnings.append(f"Skipped BUY {code}: no current KIS price available.")
            continue
        if abs(diff) < minimum:
            continue

        direction = TradeDirection.BUY if diff > 0 else TradeDirection.SELL
        quantity = _floor_quantity(abs(diff), price)
        if direction is TradeDirection.SELL:
            quantity = min(quantity, current_quantities.get(code, 0))
        if quantity <= 0:
            continue

        orders.append(
            RebalanceOrderPlan(
                stock_code=code,
                direction=direction,
                quantity=quantity,
                reference_price=price,
                current_value=current_value,
                target_value=target_value,
                diff_value=diff,
            )
        )

    orders.sort(key=lambda order: 0 if order.direction is TradeDirection.SELL else 1)
    return RebalancePlan(
        account_type=account_type,
        target_weights=weights,
        total_portfolio_value=total_value,
        investable_value=investable_value,
        current_values=current_values,
        orders=orders,
        warnings=warnings,
    )


async def execute_rebalance_plan(
    plan: RebalancePlan,
    *,
    kis_client: KISRestClient | None = None,
    is_mock: bool | None = None,
) -> RebalanceExecutionResult:
    """Submit planned market orders, or log them when running in mock mode."""

    mock_mode = settings.REBALANCER_IS_MOCK if is_mock is None else is_mock
    client = kis_client or KISRestClient()
    submitted: list[OrderResponse] = []

    for order in plan.orders:
        request = OrderRequest(
            account_type=plan.account_type,
            stock_code=order.stock_code,
            direction=order.direction,
            quantity=order.quantity,
            order_type=OrderType.MARKET,
            price=None,
        )
        if mock_mode:
            logger.info(
                "rebalance mock order account=%s side=%s code=%s qty=%s notional=%s",
                plan.account_type.value,
                order.direction.value,
                order.stock_code,
                order.quantity,
                order.estimated_notional,
            )
            continue
        assert_order_allowed(
            estimated_notional=order.estimated_notional,
            live_mode=True,
        )
        submitted.append(await client.place_order(request))

    return RebalanceExecutionResult(
        is_mock=mock_mode,
        attempted_orders=len(plan.orders),
        submitted_orders=submitted,
        plan=plan,
    )


async def rebalance_to_target_weights(
    *,
    account_type: AccountType,
    target_weights: dict[str, Decimal | float | int],
    kis_client: KISRestClient | None = None,
    is_mock: bool | None = None,
) -> RebalanceExecutionResult:
    """Convenience wrapper: build a plan and execute it safely."""

    client = kis_client or KISRestClient()
    plan = await build_rebalance_plan(
        account_type=account_type,
        target_weights=target_weights,
        kis_client=client,
    )
    return await execute_rebalance_plan(plan, kis_client=client, is_mock=is_mock)


def _normalize_target_weights(
    weights: dict[str, Decimal | float | int],
    *,
    normalize_overallocated: bool,
) -> tuple[dict[str, Decimal], list[str]]:
    normalized = {
        str(code).zfill(6): Decimal(str(weight))
        for code, weight in weights.items()
        if Decimal(str(weight)) > 0
    }
    warnings: list[str] = []
    total_weight = sum(normalized.values(), Decimal("0"))
    if total_weight <= 0:
        warnings.append("Target weights are empty; plan will liquidate existing positions.")
        return {}, warnings
    if total_weight > Decimal("1") and normalize_overallocated:
        normalized = {
            code: weight / total_weight for code, weight in normalized.items()
        }
        warnings.append(
            f"Target weights summed to {total_weight}; normalized to 1.0."
        )
    return normalized, warnings


def _floor_quantity(value: Decimal, price: Decimal) -> int:
    if price <= 0:
        return 0
    return int((value / price).to_integral_value(rounding=ROUND_FLOOR))


async def _fill_missing_target_prices(
    *,
    account_type: AccountType,
    target_codes: set[str],
    prices: dict[str, Decimal],
    kis_client: KISRestClient,
    warnings: list[str],
) -> None:
    if not target_codes:
        return
    if not hasattr(kis_client, "get_current_price"):
        warnings.append("Skipped target price lookup: KIS client has no quote method.")
        return

    for code in sorted(target_codes):
        try:
            quote = await kis_client.get_current_price(account_type, code)
        except Exception as exc:
            warnings.append(f"Skipped BUY {code}: current price lookup failed: {exc}")
            continue
        if quote.current_price > 0:
            prices[code] = quote.current_price
        else:
            warnings.append(f"Skipped BUY {code}: current price lookup returned zero.")
