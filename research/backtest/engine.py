"""Custom point-in-time backtest engine."""

from __future__ import annotations

import sqlite3
import re
from collections.abc import Callable
from datetime import date as Date
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel

from research.backtest.metrics import Metrics, compute_metrics
from research.backtest.simulator import (
    CostModel,
    SimulatedTrade,
    default_cost_model_for_universe,
    rebalance,
)
from research.factors.momentum import (
    calculate_named_idio_momentum,
    calculate_named_momentum,
)
from research.factors.common import (
    normalize_code,
    normalize_codes,
    split_korean_and_global,
    table_exists,
)
from research.factors.flows import (
    calculate_foreign_net_20d,
    calculate_indiv_net_20d,
    calculate_inst_net_20d,
)
from research.factors.quality import calculate_op_margin, calculate_roa, calculate_roe
from research.factors.value import calculate_pbr, calculate_per, calculate_psr
from research.factors.volume import calculate_trading_days_30d, calculate_volume_spike
from research.universe.kosdaq150 import KOSDAQ150_CODES_FILE
from research.universe.kospi200 import DEFAULT_CODES_FILE
from shared.db.session import research_db_path
from research.backtest.composite import (
    GroupFactorSpec,
    GroupSpec,
    composite_score,
)
from research.backtest.macro_data import load_regime_series
from research.backtest.regime import compute_regime
from shared.domain.strategy import (
    FactorGroup,
    FactorWeight,
    FilterRule,
    StrategyDefinition,
)

INITIAL_NAV = 100_000_000.0
INVESTABLE_NAV_RATIO = 0.995


class EquityPoint(BaseModel):
    date: Date
    nav: float


class RunResult(BaseModel):
    strategy_name: str
    start_date: Date
    end_date: Date
    initial_nav: float
    final_nav: float
    equity_curve: list[EquityPoint]
    trades: list[SimulatedTrade]
    metrics: Metrics
    warnings: list[str]


def run_backtest(
    strategy: StrategyDefinition,
    *,
    db_path: Path | None = None,
    initial_nav: float = INITIAL_NAV,
    cost_model: CostModel | None = None,
) -> RunResult:
    """Run a single-period backtest and return all in-memory artifacts."""

    path = db_path or research_db_path
    warnings: list[str] = []
    if cost_model is None:
        cost_model = default_cost_model_for_universe(strategy.universe)
    price_rows = _load_price_rows(strategy.start_date, strategy.end_date, path, strategy.universe)

    if price_rows.empty:
        warnings.append("No price rows found for requested backtest window.")
        metrics = compute_metrics([], [])
        return RunResult(
            strategy_name=strategy.name,
            start_date=strategy.start_date,
            end_date=strategy.end_date,
            initial_nav=initial_nav,
            final_nav=initial_nav,
            equity_curve=[],
            trades=[],
            metrics=metrics,
            warnings=warnings,
        )

    trading_days = sorted(price_rows["date"].unique())
    daily_prices = _daily_price_maps(price_rows)
    last_prices: dict[str, float] = {}
    positions: dict[str, int] = {}
    cash = initial_nav
    trades: list[SimulatedTrade] = []
    equity_curve: list[EquityPoint] = []
    last_rebalance_day: Date | None = None

    pending_orders: tuple[list[str], float, Callable] | None = None
    pending_execute_index = -1
    applied_exposure = 1.0
    last_selected: list[str] = []
    entry_prices: dict[str, float] = {}
    regime_series: dict = {}
    if strategy.use_regime:
        window_days = (trading_days[-1] - trading_days[0]).days + 500
        regime_series = load_regime_series(
            trading_days[-1], db_path=path, lookback_days=window_days
        )

    for day_index, current_day in enumerate(trading_days):
        last_prices.update(daily_prices.get(current_day, {}))
        nav = _mark_to_market(cash, positions, last_prices)

        def _apply_and_track(
            planned_trades: list[SimulatedTrade],
            reason_for: "Callable[[SimulatedTrade], dict | None] | None" = None,
        ) -> None:
            """Single choke point for executing trades: applies them, stamps a
            logic-based reason on each, keeps volume-weighted entry prices
            current, and re-marks NAV."""
            nonlocal cash, nav
            positions_before = dict(positions)
            executed_trades, cash = _apply_trades(
                cash, positions, planned_trades, warnings=warnings
            )
            if reason_for is not None:
                for executed in executed_trades:
                    tagged = reason_for(executed)
                    if tagged is not None:
                        executed.reason = tagged
            _track_entry_prices(entry_prices, executed_trades, positions_before)
            trades.extend(executed_trades)
            nav = _mark_to_market(cash, positions, last_prices)

        def _execute(
            selected: list[str],
            exposure: float,
            day: Date,
            reason_for: "Callable[[SimulatedTrade], dict | None] | None" = None,
        ) -> None:
            target = _allocate_equal_weight(
                selected,
                nav=nav,
                prices=last_prices,
                exposure=exposure,
            )
            _apply_and_track(
                rebalance(
                    current=positions,
                    target=target,
                    prices=last_prices,
                    trade_date=day,
                    cost_model=cost_model,
                ),
                reason_for=reason_for,
            )

        # Daily per-position exits vs volume-weighted entry (stop / take-profit).
        if (
            strategy.stop_loss_pct is not None
            or strategy.take_profit_pct is not None
        ) and positions:
            exit_rules: list[tuple[str, str, float]] = []
            for code in list(positions):
                entry = entry_prices.get(code)
                price = last_prices.get(code)
                if not entry or not price or entry <= 0:
                    continue
                position_return = price / entry - 1.0
                if (
                    strategy.stop_loss_pct is not None
                    and position_return <= strategy.stop_loss_pct
                ):
                    exit_rules.append((code, "STOP_LOSS", position_return))
                elif (
                    strategy.take_profit_pct is not None
                    and position_return >= strategy.take_profit_pct
                ):
                    exit_rules.append((code, "TAKE_PROFIT", position_return))
            if exit_rules:
                exit_codes = {code for code, _, _ in exit_rules}
                exit_reason = {
                    code: {"rule": rule, "return": round(position_return, 4)}
                    for code, rule, position_return in exit_rules
                }
                for code, rule, position_return in exit_rules:
                    _warn(
                        warnings,
                        f"{current_day} rule={rule} {code} ret={position_return:+.1%}",
                    )
                target = {
                    code: qty
                    for code, qty in positions.items()
                    if code not in exit_codes
                }
                _apply_and_track(
                    rebalance(
                        current=positions,
                        target=target,
                        prices=last_prices,
                        trade_date=current_day,
                        cost_model=cost_model,
                    ),
                    reason_for=lambda t: exit_reason.get(t.code),
                )

        if pending_orders is not None and day_index >= pending_execute_index:
            lagged_selected, lagged_exposure, lagged_reason = pending_orders
            pending_orders = None
            _execute(
                lagged_selected, lagged_exposure, current_day,
                reason_for=lagged_reason,
            )
            applied_exposure = lagged_exposure

        is_rebalance = _is_rebalance_day(
            current_day,
            last_rebalance_day,
            strategy.rebalance_freq,
        )
        is_month_start = (
            day_index > 0 and current_day.month != trading_days[day_index - 1].month
        )

        if (
            strategy.use_regime
            and strategy.regime_check == "MONTHLY"
            and not is_rebalance
            and is_month_start
        ):
            confirmed = _confirmed_regime_exposure(
                day_index, trading_days, regime_series
            )
            if confirmed is not None and confirmed[0] != applied_exposure:
                new_exposure, label = confirmed
                _warn(
                    warnings,
                    f"{current_day} regime-adjust {applied_exposure:.0%}"
                    f"→{new_exposure:.0%} ({label})",
                )
                regime_from, regime_to = applied_exposure, new_exposure
                if new_exposure < applied_exposure and applied_exposure > 0:
                    # De-risk in place: shrink every holding proportionally.
                    ratio = new_exposure / applied_exposure
                    target = {
                        code: int(qty * ratio) for code, qty in positions.items()
                    }
                    target = {c: q for c, q in target.items() if q > 0}
                    _apply_and_track(
                        rebalance(
                            current=positions,
                            target=target,
                            prices=last_prices,
                            trade_date=current_day,
                            cost_model=cost_model,
                        ),
                        reason_for=lambda t: {
                            "rule": "REGIME_DERISK",
                            "from_exposure": round(regime_from, 2),
                            "to_exposure": round(regime_to, 2),
                            "label": label,
                        },
                    )
                elif last_selected:
                    # Re-risk: rebuild toward the last selection at the new
                    # exposure (also handles recovery from 0%).
                    _execute(
                        last_selected, new_exposure, current_day,
                        reason_for=lambda t: {
                            "rule": "REGIME_RERISK",
                            "to_exposure": round(regime_to, 2),
                            "label": label,
                        },
                    )
                applied_exposure = new_exposure

        # Monthly band trim: sell drifted winners back to their base weight.
        if (
            strategy.band_trim_threshold is not None
            and not is_rebalance
            and is_month_start
            and positions
        ):
            trim_target = _band_trim_target(
                positions,
                last_prices,
                nav=nav,
                exposure=applied_exposure,
                threshold=strategy.band_trim_threshold,
            )
            if trim_target is not None:
                trimmed = {
                    code
                    for code, qty in trim_target.items()
                    if qty < positions.get(code, 0)
                }
                _warn(
                    warnings,
                    f"{current_day} rule=BAND_TRIM {sorted(trimmed)}",
                )
                _apply_and_track(
                    rebalance(
                        current=positions,
                        target=trim_target,
                        prices=last_prices,
                        trade_date=current_day,
                        cost_model=cost_model,
                    ),
                    reason_for=lambda t: {
                        "rule": "BAND_TRIM",
                        "threshold": strategy.band_trim_threshold,
                    },
                )

        # Monthly score-exit swap: replace holdings whose composite-score
        # percentile fell below the threshold with the best non-held names.
        if (
            strategy.replace_if_rank_below is not None
            and not is_rebalance
            and is_month_start
            and positions
        ):
            universe = get_universe(strategy.universe, as_of=current_day, db_path=path)
            scored = score_stocks(
                universe,
                strategy.factors,
                as_of=current_day,
                db_path=path,
                warnings=warnings,
                groups=strategy.groups,
                min_groups=strategy.min_groups,
                winsor_pct=strategy.winsor_pct,
                clip_z=strategy.clip_z,
            )
            scored = apply_filters(
                scored, strategy.filters,
                as_of=current_day, db_path=path, warnings=warnings,
            )
            swaps = _score_exit_swaps(
                list(scored.index), set(positions), strategy.replace_if_rank_below
            )
            if swaps:
                swap_target = dict(positions)
                swap_reason: dict[str, dict] = {}
                for exit_code, replacement in swaps:
                    exit_qty = swap_target.pop(exit_code, 0)
                    exit_price = last_prices.get(exit_code)
                    swap_reason[exit_code] = {
                        "rule": "SCORE_EXIT",
                        "replaced_by": replacement,
                    }
                    _warn(
                        warnings,
                        f"{current_day} rule=SCORE_EXIT {exit_code}→{replacement}",
                    )
                    if replacement is None or not exit_price:
                        continue
                    replacement_price = last_prices.get(replacement)
                    if not replacement_price or replacement_price <= 0:
                        continue
                    # Haircut the sale proceeds for round-trip costs
                    # (slippage+commission+tax) so the replacement BUY never
                    # dies on an insufficient-cash skip.
                    budget = exit_qty * exit_price * 0.99
                    qty = int(budget // replacement_price)
                    if qty > 0:
                        swap_target[replacement] = (
                            swap_target.get(replacement, 0) + qty
                        )
                        swap_reason[replacement] = {
                            "rule": "SCORE_EXIT_REPLACE",
                            "replaces": exit_code,
                        }
                _apply_and_track(
                    rebalance(
                        current=positions,
                        target=swap_target,
                        prices=last_prices,
                        trade_date=current_day,
                        cost_model=cost_model,
                    ),
                    reason_for=lambda t: swap_reason.get(t.code),
                )

        if is_rebalance:
            universe = get_universe(strategy.universe, as_of=current_day, db_path=path)
            scored = score_stocks(
                universe,
                strategy.factors,
                as_of=current_day,
                db_path=path,
                warnings=warnings,
                groups=strategy.groups,
                min_groups=strategy.min_groups,
                winsor_pct=strategy.winsor_pct,
                clip_z=strategy.clip_z,
            )
            scored = apply_filters(
                scored,
                strategy.filters,
                as_of=current_day,
                db_path=path,
                warnings=warnings,
            )
            selected = list(scored.head(strategy.top_n).index)
            exposure = 1.0
            regime_label = None
            if strategy.use_regime:
                regime = compute_regime(current_day, **regime_series)
                exposure = regime.exposure
                if strategy.regime_check == "MONTHLY":
                    confirmed = _confirmed_regime_exposure(
                        day_index, trading_days, regime_series
                    )
                    if confirmed is not None:
                        exposure = confirmed[0]
                regime_label = regime.label
                _warn(
                    warnings,
                    f"{current_day} regime={regime.label} "
                    f"exposure={exposure:.0%} R={regime.r_score:.2f}",
                )
            last_selected = selected
            # Logic-based reason per trade: entered top-N (with rank/score) vs
            # dropped out of top-N. Rank map is bound per rebalance so a lagged
            # fill keeps the signal-day ranking.
            has_score = "score" in scored.columns
            rank_by_code = {
                code: (i + 1, float(scored.loc[code, "score"]) if has_score else None)
                for i, code in enumerate(selected)
                if code in scored.index
            }

            def _rebalance_reason(trade, ranks=rank_by_code, label=regime_label):
                if trade.side == "BUY":
                    entry = ranks.get(trade.code)
                    reason: dict = {"rule": "REBALANCE_IN"}
                    if entry is not None:
                        reason["rank"] = entry[0]
                        if entry[1] is not None:
                            reason["score"] = round(entry[1], 4)
                    if label is not None:
                        reason["regime"] = label
                    return reason
                return {"rule": "REBALANCE_OUT"}

            if strategy.execution_lag_days > 0:
                # Signal today, fill at a later close — removes the
                # same-close fill assumption (look-ahead robustness).
                pending_orders = (selected, exposure, _rebalance_reason)
                pending_execute_index = day_index + strategy.execution_lag_days
            else:
                _execute(selected, exposure, current_day, reason_for=_rebalance_reason)
                applied_exposure = exposure
            last_rebalance_day = current_day

        equity_curve.append(EquityPoint(date=current_day, nav=nav))

    equity_pairs = [(point.date, point.nav) for point in equity_curve]
    metrics = compute_metrics(equity_pairs, trades)
    final_nav = equity_curve[-1].nav if equity_curve else initial_nav
    return RunResult(
        strategy_name=strategy.name,
        start_date=trading_days[0],
        end_date=trading_days[-1],
        initial_nav=initial_nav,
        final_nav=final_nav,
        equity_curve=equity_curve,
        trades=trades,
        metrics=metrics,
        warnings=warnings,
    )


def get_universe(
    universe: str,
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> list[str]:
    """Return survivorship-free stock codes valid on ``as_of``."""

    path = db_path or research_db_path
    market_clause = ""
    params: list[str] = [as_of.isoformat(), as_of.isoformat()]

    normalized = universe.upper()
    if normalized == "KOSPI200":
        codes = _index_membership_universe(
            "KOSPI200",
            as_of=as_of,
            db_path=path,
            fallback_file=DEFAULT_CODES_FILE,
        )
        if codes:
            return codes
        market_clause = "AND market = ?"
        params.append("KOSPI")
    elif normalized == "KOSDAQ150":
        codes = _index_membership_universe(
            "KOSDAQ150",
            as_of=as_of,
            db_path=path,
            fallback_file=KOSDAQ150_CODES_FILE,
        )
        if codes:
            return codes
        market_clause = "AND market = ?"
        params.append("KOSDAQ")
    elif normalized == "NASDAQ100":
        return _us_universe(as_of=as_of, db_path=path, exchange="NASDAQ")
    elif normalized == "ETF_US":
        return _us_universe(as_of=as_of, db_path=path, exchange="ETF")
    elif normalized == "ETF_KR":
        market_clause = "AND market = ?"
        params.append("ETF")
    elif normalized == "KOSPI_TOP100":
        return _kospi_top_n_universe(as_of=as_of, db_path=path, top_n=100)
    elif normalized == "KOSPI_ALL":
        market_clause = "AND market = ?"
        params.append("KOSPI")
    elif normalized == "KOSDAQ_ALL":
        market_clause = "AND market = ?"
        params.append("KOSDAQ")
    elif normalized != "CUSTOM":
        raise ValueError(f"Unsupported universe: {universe}")

    sql = f"""
        SELECT code
        FROM stocks
        WHERE listed_at <= ?
          AND (delisted_at IS NULL OR delisted_at > ?)
          {market_clause}
        ORDER BY code
    """
    with sqlite3.connect(path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return normalize_codes(row[0] for row in rows)


def score_stocks(
    codes: list[str],
    factors: list[FactorWeight],
    *,
    as_of: Date,
    db_path: Path | None = None,
    warnings: list[str] | None = None,
    groups: list[FactorGroup] | None = None,
    min_groups: int = 5,
    winsor_pct: float = 0.01,
    clip_z: float = 3.0,
) -> pd.DataFrame:
    """Score stocks with point-in-time factor values.

    When ``groups`` is given, the qlab_alpha_v2 grouped composite (robust
    preprocessing + coverage penalty) is used; otherwise the flat weighted-sum
    scorer runs exactly as before.
    """

    if groups:
        return _score_stocks_grouped(
            codes,
            groups,
            as_of=as_of,
            db_path=db_path,
            warnings=warnings,
            min_groups=min_groups,
            winsor_pct=winsor_pct,
            clip_z=clip_z,
        )

    normalized_codes = normalize_codes(codes)
    frame = pd.DataFrame(index=pd.Index(normalized_codes, name="code"))
    score_columns: list[str] = []

    for spec in factors:
        factor_name = spec.factor.upper()
        raw = _factor_series(
            factor_name,
            normalized_codes,
            as_of=as_of,
            db_path=db_path,
            warnings=warnings,
        )
        if raw.empty:
            _warn(warnings, f"{factor_name} returned no values on {as_of}.")
            continue

        frame[factor_name] = raw.reindex(frame.index)
        transformed = _transform(frame[factor_name], spec.transform)
        score_column = f"{factor_name}__weighted"
        frame[score_column] = transformed * spec.weight
        score_columns.append(score_column)

    if not score_columns:
        frame["score"] = pd.NA
    else:
        frame["score"] = frame[score_columns].sum(axis=1, min_count=1)

    frame = frame.dropna(subset=["score"])
    return frame.sort_values("score", ascending=False)


def _score_stocks_grouped(
    codes: list[str],
    groups: list[FactorGroup],
    *,
    as_of: Date,
    db_path: Path | None,
    warnings: list[str] | None,
    min_groups: int,
    winsor_pct: float,
    clip_z: float,
) -> pd.DataFrame:
    """qlab_alpha_v2 composite: fetch every group factor once, then combine."""

    normalized_codes = normalize_codes(codes)
    frame = pd.DataFrame(index=pd.Index(normalized_codes, name="code"))

    seen: set[str] = set()
    for group in groups:
        for member in group.factors:
            factor_name = member.factor.upper()
            if factor_name in seen:
                continue
            seen.add(factor_name)
            raw = _factor_series(
                factor_name,
                normalized_codes,
                as_of=as_of,
                db_path=db_path,
                warnings=warnings,
            )
            if raw.empty:
                _warn(warnings, f"{factor_name} returned no values on {as_of}.")
                continue
            frame[factor_name] = raw.reindex(frame.index)

    group_specs = tuple(
        GroupSpec(
            name=group.name,
            weight=group.weight,
            factors=tuple(
                GroupFactorSpec(member.factor.upper(), member.higher_is_better)
                for member in group.factors
            ),
        )
        for group in groups
    )
    frame["score"] = composite_score(
        frame,
        group_specs,
        min_groups=min_groups,
        winsor_pct=winsor_pct,
        clip_z=clip_z,
    )
    frame = frame.dropna(subset=["score"])
    return frame.sort_values("score", ascending=False)


def apply_filters(
    scored: pd.DataFrame,
    filters: list[FilterRule],
    *,
    as_of: Date,
    db_path: Path | None = None,
    warnings: list[str] | None = None,
) -> pd.DataFrame:
    """Apply strategy filters to a scored stock frame."""

    if scored.empty or not filters:
        return scored

    result = scored.copy()
    for rule in filters:
        field = rule.field.upper()
        if field not in result.columns:
            values = _factor_series(
                field,
                list(result.index),
                as_of=as_of,
                db_path=db_path,
                warnings=warnings,
            )
            if values.empty:
                _warn(warnings, f"Skipped unsupported or empty filter field: {rule.field}")
                continue
            result[field] = values.reindex(result.index)

        mask = _filter_mask(result[field], rule)
        result = result[mask.fillna(False)]
    return result


def _factor_series(
    factor_name: str,
    codes: list[str],
    *,
    as_of: Date,
    db_path: Path | None,
    warnings: list[str] | None,
) -> pd.Series:
    try:
        if factor_name == "PER":
            return calculate_per(codes, as_of=as_of, db_path=db_path)
        if factor_name == "PBR":
            return calculate_pbr(codes, as_of=as_of, db_path=db_path)
        if factor_name == "PSR":
            return calculate_psr(codes, as_of=as_of, db_path=db_path)
        if factor_name == "ROE":
            return calculate_roe(codes, as_of=as_of, db_path=db_path)
        if factor_name == "ROA":
            return calculate_roa(codes, as_of=as_of, db_path=db_path)
        if factor_name == "OP_MARGIN":
            return calculate_op_margin(codes, as_of=as_of, db_path=db_path)
        if factor_name.startswith("IDIO_MOM_"):
            return calculate_named_idio_momentum(
                factor_name,
                codes,
                as_of=as_of,
                db_path=db_path,
            )
        if factor_name.startswith("MOMENTUM_"):
            return calculate_named_momentum(
                factor_name,
                codes,
                as_of=as_of,
                db_path=db_path,
            )
        if factor_name == "TRADING_DAYS_30D":
            return calculate_trading_days_30d(codes, as_of=as_of, db_path=db_path)
        if factor_name == "FOREIGN_NET_20D":
            return calculate_foreign_net_20d(codes, as_of=as_of, db_path=db_path)
        if factor_name == "INST_NET_20D":
            return calculate_inst_net_20d(codes, as_of=as_of, db_path=db_path)
        if factor_name == "INDIV_NET_20D":
            return calculate_indiv_net_20d(codes, as_of=as_of, db_path=db_path)
        if factor_name == "VOLUME_SPIKE":
            return calculate_volume_spike(codes, as_of=as_of, db_path=db_path)
        if factor_name == "MARKET_CAP":
            caps = _true_market_cap(codes, as_of=as_of, db_path=db_path)
            if caps.empty:
                # Never substitute the turnover proxy here: with a
                # "market cap >= 100B" filter the proxy silently keeps only
                # the ~dozen highest-turnover names of the day (12/193 on
                # KOSPI200, measured) — a completely different strategy.
                # Empty series → apply_filters skips the rule with a warning.
                _warn(
                    warnings,
                    "MARKET_CAP data unavailable (market_caps table absent/empty "
                    "as of this date) — factor empty, filters on it skipped. "
                    "Ingest via pykrx_loader.update_market_caps; for liquidity "
                    "filtering use TURNOVER_PROXY.",
                )
            return caps
        if factor_name in {"TURNOVER", "TURNOVER_PROXY", "LIQUIDITY"}:
            return _turnover_proxy(codes, as_of=as_of, db_path=db_path)
    except Exception as exc:
        _warn(warnings, f"Failed to compute {factor_name} on {as_of}: {exc}")
        return pd.Series(dtype="float64")

    _warn(warnings, f"Unsupported factor: {factor_name}")
    return pd.Series(dtype="float64")


def _true_market_cap(
    codes: list[str],
    *,
    as_of: Date,
    db_path: Path | None,
) -> pd.Series:
    """Point-in-time market cap from the market_caps table (empty if absent)."""

    normalized_codes = normalize_codes(codes)
    if not normalized_codes:
        return pd.Series(dtype="float64")
    path = db_path or research_db_path
    with sqlite3.connect(path) as conn:
        if not table_exists(conn, "market_caps"):
            return pd.Series(dtype="float64")
        placeholders = ",".join("?" for _ in normalized_codes)
        sql = f"""
            SELECT stock_code, market_cap
            FROM (
                SELECT
                    stock_code,
                    market_cap,
                    ROW_NUMBER() OVER (
                        PARTITION BY stock_code
                        ORDER BY date DESC
                    ) AS rn
                FROM market_caps
                WHERE stock_code IN ({placeholders})
                  AND date <= ?
            )
            WHERE rn = 1
        """
        rows = pd.read_sql_query(
            sql, conn, params=[*normalized_codes, as_of.isoformat()]
        )
    if rows.empty:
        return pd.Series(dtype="float64")
    return rows.set_index("stock_code")["market_cap"].astype(float)


def _turnover_proxy(
    codes: list[str],
    *,
    as_of: Date,
    db_path: Path | None,
) -> pd.Series:
    """Latest-day close×volume turnover (a liquidity measure, NOT market cap)."""

    normalized_codes = normalize_codes(codes)
    if not normalized_codes:
        return pd.Series(dtype="float64")
    path = db_path or research_db_path
    with sqlite3.connect(path) as conn:
        frames = []
        korean_codes, global_codes = split_korean_and_global(normalized_codes)
        if korean_codes and table_exists(conn, "prices_daily"):
            frames.append(
                _turnover_proxy_from_table(
                    conn,
                    table_name="prices_daily",
                    code_column="stock_code",
                    codes=korean_codes,
                    as_of=as_of,
                )
            )
        if global_codes and table_exists(conn, "prices_daily_us"):
            frames.append(
                _turnover_proxy_from_table(
                    conn,
                    table_name="prices_daily_us",
                    code_column="ticker",
                    codes=global_codes,
                    as_of=as_of,
                )
            )
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.Series(dtype="float64")
    rows = pd.concat(frames, ignore_index=True)
    rows["market_cap_proxy"] = rows["close"].astype(float) * rows["volume"].astype(float)
    return rows.set_index("stock_code")["market_cap_proxy"]


def _index_membership_universe(
    index_code: str,
    *,
    as_of: Date,
    db_path: Path,
    fallback_file: Path,
) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        if table_exists(conn, "index_memberships"):
            rows = conn.execute(
                """
                SELECT stock_code
                FROM index_memberships
                WHERE index_code = ?
                  AND valid_from <= ?
                  AND (valid_to IS NULL OR valid_to > ?)
                ORDER BY stock_code
                """,
                [index_code, as_of.isoformat(), as_of.isoformat()],
            ).fetchall()
            if rows:
                return normalize_codes(row[0] for row in rows)

    file_codes = _read_codes_file(fallback_file)
    if file_codes:
        return file_codes
    return []


def _track_entry_prices(
    entry_prices: dict[str, float],
    executed_trades: list[SimulatedTrade],
    positions_before: dict[str, int],
) -> None:
    """Maintain volume-weighted entry prices across fills.

    BUY blends the fill into the running average; a SELL that empties the
    position clears its entry (a partial sell keeps the average — the basis
    for stop/take-profit stays the original cost).
    """
    remaining = dict(positions_before)
    for trade in executed_trades:
        code = trade.code
        prev_qty = remaining.get(code, 0)
        if trade.side == "BUY":
            prev_entry = entry_prices.get(code, trade.price)
            total = prev_qty + trade.qty
            if total > 0:
                entry_prices[code] = (
                    prev_qty * prev_entry + trade.qty * trade.price
                ) / total
            remaining[code] = total
        else:
            remaining[code] = prev_qty - trade.qty
            if remaining[code] <= 0:
                entry_prices.pop(code, None)


def _band_trim_target(
    positions: dict[str, int],
    prices: dict[str, float],
    *,
    nav: float,
    exposure: float,
    threshold: float,
) -> dict[str, int] | None:
    """Target that trims holdings drifted above base_weight × threshold.

    Base weight = the equal-weight share each current holding would get at the
    applied exposure. Only trims (never tops up); returns None when nothing
    breaches the band.
    """
    if not positions or nav <= 0 or threshold <= 1.0:
        return None
    effective_exposure = exposure if exposure > 0 else 1.0
    base_weight = effective_exposure * INVESTABLE_NAV_RATIO / len(positions)
    target = dict(positions)
    trimmed = False
    for code, qty in positions.items():
        price = prices.get(code)
        if not price or price <= 0:
            continue
        weight = qty * price / nav
        if weight > base_weight * threshold:
            target[code] = int(base_weight * nav / price)
            trimmed = True
    return target if trimmed else None


def _score_exit_swaps(
    ranked_codes: list[str],
    held: set[str],
    rank_below: float,
) -> list[tuple[str, str | None]]:
    """(exit, replacement) pairs for held names whose score percentile
    (1.0 = best) fell below ``rank_below``.

    Held names absent from the ranking (no data that day) are left alone —
    a data gap must not force a sale. Replacements are the best-ranked
    non-held names, one per exit, None when the bench runs dry.
    """
    n = len(ranked_codes)
    if n < 2 or not held:
        return []
    percentile = {
        code: 1.0 - index / (n - 1) for index, code in enumerate(ranked_codes)
    }
    exits = [
        code for code in ranked_codes
        if code in held and percentile[code] < rank_below
    ]
    bench = [code for code in ranked_codes if code not in held]
    return [
        (exit_code, bench[i] if i < len(bench) else None)
        for i, exit_code in enumerate(exits)
    ]


def _confirmed_regime_exposure(
    day_index: int,
    trading_days: list[Date],
    regime_series: dict,
    *,
    persistence: int = 5,
) -> tuple[float, str] | None:
    """Regime exposure confirmed by ``persistence`` consecutive same-label days.

    Whipsaw guard for intra-rebalance adjustments: a single panicky day must
    not flip the book. Returns None while unconfirmed (caller keeps the
    currently applied exposure).
    """
    if day_index + 1 < persistence:
        return None
    states = [
        compute_regime(day, **regime_series)
        for day in trading_days[day_index - persistence + 1 : day_index + 1]
    ]
    label = states[-1].label
    if all(state.label == label for state in states):
        return states[-1].exposure, label
    return None


def _kospi_top_n_universe(
    *,
    as_of: Date,
    db_path: Path,
    top_n: int,
) -> list[str]:
    """Top-N KOSPI stocks by point-in-time market cap (market_caps table).

    Empty when market_caps has no coverage on/before ``as_of`` — never falls
    back to a turnover ranking.
    """
    with sqlite3.connect(db_path) as conn:
        if not table_exists(conn, "market_caps"):
            return []
        rows = conn.execute(
            """
            SELECT s.code
            FROM stocks s
            JOIN (
                SELECT stock_code, market_cap,
                       ROW_NUMBER() OVER (
                           PARTITION BY stock_code ORDER BY date DESC
                       ) AS rn
                FROM market_caps
                WHERE date <= ?
            ) mc ON mc.stock_code = s.code AND mc.rn = 1
            WHERE s.market = 'KOSPI'
              AND s.listed_at <= ?
              AND (s.delisted_at IS NULL OR s.delisted_at > ?)
            ORDER BY CAST(mc.market_cap AS REAL) DESC
            LIMIT ?
            """,
            [as_of.isoformat(), as_of.isoformat(), as_of.isoformat(), top_n],
        ).fetchall()
    return normalize_codes(row[0] for row in rows)


def _us_universe(
    *,
    as_of: Date,
    db_path: Path,
    exchange: str,
) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        if not table_exists(conn, "stocks_us"):
            return []
        rows = conn.execute(
            """
            SELECT ticker
            FROM stocks_us
            WHERE exchange = ?
              AND (listed_at IS NULL OR listed_at <= ?)
              AND (delisted_at IS NULL OR delisted_at > ?)
              AND is_delisted = 0
            ORDER BY ticker
            """,
            [exchange, as_of.isoformat(), as_of.isoformat()],
        ).fetchall()
    return normalize_codes(row[0] for row in rows)


def _read_codes_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    return normalize_codes(re.findall(r"(?<!\d)\d{6}(?!\d)", text))


def _turnover_proxy_from_table(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    code_column: str,
    codes: list[str],
    as_of: Date,
) -> pd.DataFrame:
    placeholders = ",".join("?" for _ in codes)
    sql = f"""
        SELECT stock_code, close, volume
        FROM (
            SELECT
                {code_column} AS stock_code,
                COALESCE(adj_close, close) AS close,
                volume,
                ROW_NUMBER() OVER (
                    PARTITION BY {code_column}
                    ORDER BY date DESC
                ) AS rn
            FROM {table_name}
            WHERE {code_column} IN ({placeholders})
              AND date <= ?
        )
        WHERE rn = 1
    """
    return pd.read_sql_query(sql, conn, params=[*codes, as_of.isoformat()])


def _transform(
    values: pd.Series,
    transform: Literal["RAW", "ZSCORE", "RANK"],
) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if transform == "RAW":
        return numeric
    if transform == "RANK":
        return numeric.rank(pct=True)
    if transform == "ZSCORE":
        std = numeric.std(ddof=0)
        if std == 0 or pd.isna(std):
            return numeric.where(numeric.isna(), 0.0)
        return (numeric - numeric.mean()) / std
    raise ValueError(f"Unsupported transform: {transform}")


def _filter_mask(series: pd.Series, rule: FilterRule) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    op = rule.op
    value = rule.value

    if op == "GT":
        return numeric > float(value)
    if op == "GTE":
        return numeric >= float(value)
    if op == "LT":
        return numeric < float(value)
    if op == "LTE":
        return numeric <= float(value)
    if op == "BETWEEN":
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError("BETWEEN filter requires a two-item value list.")
        return (numeric >= float(value[0])) & (numeric <= float(value[1]))
    raise ValueError(f"Unsupported filter op: {op}")


def _load_price_rows(start: Date, end: Date, db_path: Path, universe: str) -> pd.DataFrame:
    normalized_universe = universe.upper()
    with sqlite3.connect(db_path) as conn:
        frames: list[pd.DataFrame] = []
        if normalized_universe not in {"NASDAQ100", "ETF_US"} and table_exists(
            conn, "prices_daily"
        ):
            frames.append(
                pd.read_sql_query(
                    """
                    SELECT stock_code, date, COALESCE(adj_close, close) AS close
                    FROM prices_daily
                    WHERE date BETWEEN ? AND ?
                    ORDER BY date, stock_code
                    """,
                    conn,
                    params=[start.isoformat(), end.isoformat()],
                )
            )
        if normalized_universe in {"NASDAQ100", "ETF_US", "CUSTOM"} and table_exists(
            conn, "prices_daily_us"
        ):
            frames.append(
                pd.read_sql_query(
                    """
                    SELECT ticker AS stock_code, date, COALESCE(adj_close, close) AS close
                    FROM prices_daily_us
                    WHERE date BETWEEN ? AND ?
                    ORDER BY date, ticker
                    """,
                    conn,
                    params=[start.isoformat(), end.isoformat()],
                )
            )
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=["stock_code", "date", "close"])
    rows = pd.concat(frames, ignore_index=True)
    rows["date"] = pd.to_datetime(rows["date"]).dt.date
    rows["close"] = rows["close"].astype(float)
    rows["stock_code"] = rows["stock_code"].map(normalize_code)
    return rows


def _daily_price_maps(price_rows: pd.DataFrame) -> dict[Date, dict[str, float]]:
    maps: dict[Date, dict[str, float]] = {}
    for day, group in price_rows.groupby("date"):
        maps[day] = dict(zip(group["stock_code"], group["close"], strict=False))
    return maps


def _is_rebalance_day(
    current_day: Date,
    last_rebalance_day: Date | None,
    frequency: Literal["MONTHLY", "QUARTERLY", "YEARLY"],
) -> bool:
    if last_rebalance_day is None:
        return True
    if frequency == "MONTHLY":
        return (current_day.year, current_day.month) != (
            last_rebalance_day.year,
            last_rebalance_day.month,
        )
    if frequency == "QUARTERLY":
        return (current_day.year, _quarter(current_day)) != (
            last_rebalance_day.year,
            _quarter(last_rebalance_day),
        )
    if frequency == "YEARLY":
        return current_day.year != last_rebalance_day.year
    raise ValueError(f"Unsupported rebalance frequency: {frequency}")


def _quarter(value: Date) -> int:
    return (value.month - 1) // 3 + 1


def _allocate_equal_weight(
    selected_codes: list[str],
    *,
    nav: float,
    prices: dict[str, float],
    exposure: float = 1.0,
) -> dict[str, int]:
    invested = max(0.0, min(1.0, exposure))
    if not selected_codes or nav <= 0 or invested <= 0:
        return {}

    budget_per_stock = (nav * INVESTABLE_NAV_RATIO * invested) / len(selected_codes)
    target: dict[str, int] = {}
    for code in selected_codes:
        price = prices.get(code)
        if price is None or price <= 0:
            continue
        qty = int(budget_per_stock // price)
        if qty > 0:
            target[code] = qty
    return target


def _apply_trades(
    cash: float,
    positions: dict[str, int],
    trades: list[SimulatedTrade],
    *,
    warnings: list[str],
) -> tuple[list[SimulatedTrade], float]:
    executed: list[SimulatedTrade] = []
    for trade in trades:
        if trade.side == "BUY" and cash + trade.cash_flow < 0:
            _warn(
                warnings,
                f"Skipped BUY {trade.code} on {trade.date}: insufficient cash.",
            )
            continue

        cash += trade.cash_flow
        if trade.side == "BUY":
            positions[trade.code] = positions.get(trade.code, 0) + trade.qty
        else:
            positions[trade.code] = positions.get(trade.code, 0) - trade.qty
            if positions[trade.code] <= 0:
                positions.pop(trade.code, None)
        executed.append(trade)
    return executed, cash


def _mark_to_market(
    cash: float,
    positions: dict[str, int],
    prices: dict[str, float],
) -> float:
    position_value = sum(qty * prices.get(code, 0.0) for code, qty in positions.items())
    return float(cash + position_value)


def _warn(warnings: list[str] | None, message: str) -> None:
    if warnings is not None and message not in warnings:
        warnings.append(message)
