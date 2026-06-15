"""Custom point-in-time backtest engine."""

from __future__ import annotations

import sqlite3
import re
from datetime import date as Date
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel

from research.backtest.metrics import Metrics, compute_metrics
from research.backtest.simulator import CostModel, SimulatedTrade, rebalance
from research.factors.momentum import calculate_named_momentum
from research.factors.common import (
    normalize_code,
    normalize_codes,
    split_korean_and_global,
    table_exists,
)
from research.factors.quality import calculate_roa, calculate_roe
from research.factors.value import calculate_pbr, calculate_per
from research.factors.volume import calculate_trading_days_30d, calculate_volume_spike
from research.universe.kosdaq150 import KOSDAQ150_CODES_FILE
from research.universe.kospi200 import DEFAULT_CODES_FILE
from shared.db.session import research_db_path
from shared.domain.strategy import FactorWeight, FilterRule, StrategyDefinition

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

    for current_day in trading_days:
        last_prices.update(daily_prices.get(current_day, {}))
        nav = _mark_to_market(cash, positions, last_prices)

        if _is_rebalance_day(
            current_day,
            last_rebalance_day,
            strategy.rebalance_freq,
        ):
            universe = get_universe(strategy.universe, as_of=current_day, db_path=path)
            scored = score_stocks(
                universe,
                strategy.factors,
                as_of=current_day,
                db_path=path,
                warnings=warnings,
            )
            scored = apply_filters(
                scored,
                strategy.filters,
                as_of=current_day,
                db_path=path,
                warnings=warnings,
            )
            selected = list(scored.head(strategy.top_n).index)
            target = _allocate_equal_weight(
                selected,
                nav=nav,
                prices=last_prices,
            )
            rebalance_trades = rebalance(
                current=positions,
                target=target,
                prices=last_prices,
                trade_date=current_day,
                cost_model=cost_model,
            )
            executed_trades, cash = _apply_trades(
                cash,
                positions,
                rebalance_trades,
                warnings=warnings,
            )
            trades.extend(executed_trades)
            last_rebalance_day = current_day
            nav = _mark_to_market(cash, positions, last_prices)

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
) -> pd.DataFrame:
    """Score stocks with point-in-time factor values."""

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
        if factor_name == "ROE":
            return calculate_roe(codes, as_of=as_of, db_path=db_path)
        if factor_name == "ROA":
            return calculate_roa(codes, as_of=as_of, db_path=db_path)
        if factor_name.startswith("MOMENTUM_"):
            return calculate_named_momentum(
                factor_name,
                codes,
                as_of=as_of,
                db_path=db_path,
            )
        if factor_name == "TRADING_DAYS_30D":
            return calculate_trading_days_30d(codes, as_of=as_of, db_path=db_path)
        if factor_name == "VOLUME_SPIKE":
            return calculate_volume_spike(codes, as_of=as_of, db_path=db_path)
        if factor_name == "MARKET_CAP":
            _warn(
                warnings,
                "MARKET_CAP currently uses a liquidity proxy unless true "
                "historical market-cap data is present; prefer TURNOVER_PROXY.",
            )
            return _market_cap_proxy(codes, as_of=as_of, db_path=db_path)
        if factor_name in {"TURNOVER", "TURNOVER_PROXY", "LIQUIDITY"}:
            return _market_cap_proxy(codes, as_of=as_of, db_path=db_path)
    except Exception as exc:
        _warn(warnings, f"Failed to compute {factor_name} on {as_of}: {exc}")
        return pd.Series(dtype="float64")

    _warn(warnings, f"Unsupported factor: {factor_name}")
    return pd.Series(dtype="float64")


def _market_cap_proxy(
    codes: list[str],
    *,
    as_of: Date,
    db_path: Path | None,
) -> pd.Series:
    """Local size proxy used when true historical market cap is unavailable."""

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
        if normalized_universe != "NASDAQ100" and table_exists(conn, "prices_daily"):
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
        if normalized_universe in {"NASDAQ100", "CUSTOM"} and table_exists(conn, "prices_daily_us"):
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
) -> dict[str, int]:
    if not selected_codes or nav <= 0:
        return {}

    budget_per_stock = (nav * INVESTABLE_NAV_RATIO) / len(selected_codes)
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
