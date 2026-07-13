"""Point-in-time quality factor calculations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import date as Date
from pathlib import Path

import pandas as pd

from research.factors.common import normalize_codes, split_korean_and_global, table_exists
from shared.db.session import research_db_path


def calculate_roe(
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.Series:
    """ROE = latest disclosed net_income / total_equity."""

    frame = calculate_quality_factors(codes, as_of=as_of, db_path=db_path)
    return frame["ROE"] if "ROE" in frame else pd.Series(dtype="float64")


def calculate_roa(
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.Series:
    """ROA = latest disclosed net_income / total_assets."""

    frame = calculate_quality_factors(codes, as_of=as_of, db_path=db_path)
    return frame["ROA"] if "ROA" in frame else pd.Series(dtype="float64")


def calculate_quality_factors(
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.DataFrame:
    """Return quality factors using financials disclosed by ``as_of`` only."""

    normalized_codes = normalize_codes(codes)
    if not normalized_codes:
        return pd.DataFrame(columns=["ROE", "ROA"])

    path = db_path or research_db_path
    with sqlite3.connect(path) as conn:
        financials = _ttm_financials(conn, normalized_codes, as_of)

    frame = pd.DataFrame(index=normalized_codes)
    frame.index.name = "code"
    frame = frame.join(financials)
    frame["ROE"] = _safe_divide(frame["net_income_ttm"], frame["total_equity"])
    frame["ROA"] = _safe_divide(frame["net_income_ttm"], frame["total_assets"])
    # OP_MARGIN = 영업이익(TTM) / 매출(TTM) — 순수 비율, price/shares 불필요.
    frame["OP_MARGIN"] = _safe_divide(
        frame["operating_income_ttm"], frame["revenue_ttm"]
    )
    frame.loc[frame["total_equity"] <= 0, "ROE"] = pd.NA
    frame.loc[frame["total_assets"] <= 0, "ROA"] = pd.NA
    frame.loc[(frame["revenue_ttm"] <= 0).fillna(False), "OP_MARGIN"] = pd.NA
    return frame[["ROE", "ROA", "OP_MARGIN"]]


def calculate_op_margin(
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.Series:
    """OP_MARGIN = operating_income(TTM) / revenue(TTM)."""

    frame = calculate_quality_factors(codes, as_of=as_of, db_path=db_path)
    return frame["OP_MARGIN"] if "OP_MARGIN" in frame else pd.Series(dtype="float64")


def _ttm_financials(
    conn: sqlite3.Connection,
    codes: list[str],
    as_of: Date,
) -> pd.DataFrame:
    korean_codes, global_codes = split_korean_and_global(codes)
    frames: list[pd.DataFrame] = []
    if korean_codes and table_exists(conn, "financials"):
        # KR/DART rows mix 12-month annual reports with their own 3-month
        # interims — quarters must be reconstructed (mixed_annual=True).
        frames.append(
            _ttm_financials_from_table(
                conn, "financials", "stock_code", korean_codes, as_of,
                mixed_annual=True,
            )
        )
    if global_codes and table_exists(conn, "financials_us"):
        # US/yfinance rows are uniform quarterly flows — the plain last-4 sum
        # is already a correct TTM there.
        frames.append(
            _ttm_financials_from_table(
                conn, "financials_us", "ticker", global_codes, as_of,
                mixed_annual=False,
            )
        )
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame(
            index=pd.Index([], name="stock_code"),
            columns=[
                "net_income_ttm", "total_equity", "total_assets",
                "revenue_ttm", "operating_income_ttm",
            ],
        )
    return pd.concat(frames).sort_index()


def _ttm_financials_from_table(
    conn: sqlite3.Connection,
    table_name: str,
    code_column: str,
    codes: list[str],
    as_of: Date,
    *,
    mixed_annual: bool,
) -> pd.DataFrame:
    placeholders = ",".join("?" for _ in codes)
    sql = f"""
        SELECT stock_code, net_income, total_equity, total_assets
        FROM (
            SELECT
                {code_column} AS stock_code,
                net_income,
                total_equity,
                total_assets,
                ROW_NUMBER() OVER (
                    PARTITION BY {code_column}
                    ORDER BY disclosed_at DESC, fiscal_period DESC, id DESC
                ) AS rn
            FROM {table_name}
            WHERE {code_column} IN ({placeholders})
              AND disclosed_at <= ?
        )
        WHERE rn = 1
    """
    latest = pd.read_sql_query(sql, conn, params=[*codes, as_of.isoformat()])
    if latest.empty:
        return pd.DataFrame(
            index=pd.Index([], name="stock_code"),
            columns=[
                "net_income_ttm", "total_equity", "total_assets",
                "revenue_ttm", "operating_income_ttm",
            ],
        )
    latest_frame = latest.set_index("stock_code")

    ttm = net_income_ttm_series(
        conn, table_name, code_column, codes, as_of, mixed_annual=mixed_annual
    )
    latest_frame["net_income_ttm"] = ttm.reindex(latest_frame.index)
    latest_frame["net_income_ttm"] = latest_frame["net_income_ttm"].fillna(
        latest_frame["net_income"]
    )
    # 매출·영업이익도 같은 TTM 로직으로 합산(OP_MARGIN·PSR 소스). 결측은 그대로 NaN.
    for column, out in (("revenue", "revenue_ttm"),
                        ("operating_income", "operating_income_ttm")):
        series = flow_ttm_series(
            conn, table_name, code_column, codes, as_of,
            column=column, mixed_annual=mixed_annual,
        )
        latest_frame[out] = series.reindex(latest_frame.index)
    return latest_frame[[
        "net_income_ttm", "total_equity", "total_assets",
        "revenue_ttm", "operating_income_ttm",
    ]].astype(float)


def net_income_ttm_series(
    conn: sqlite3.Connection,
    table_name: str,
    code_column: str,
    codes: list[str],
    as_of: Date,
    *,
    mixed_annual: bool,
) -> pd.Series:
    """Trailing-12-month net income per stock (thin wrapper over flow_ttm_series)."""
    return flow_ttm_series(
        conn, table_name, code_column, codes, as_of,
        column="net_income", mixed_annual=mixed_annual,
    )


def flow_ttm_series(
    conn: sqlite3.Connection,
    table_name: str,
    code_column: str,
    codes: list[str],
    as_of: Date,
    *,
    column: str,
    mixed_annual: bool,
) -> pd.Series:
    """Trailing-12-month sum of a flow line item (net_income/revenue/operating_income).

    mixed_annual=True (KR/DART): rows mix 12-month annual reports with 3-month
    interim reports of the same fiscal year, so summing the last 4 disclosures
    double-counts up to ~2x (annual + its own constituent quarters). Quarters
    are reconstructed instead — Q4 = annual − (Q1+Q2+Q3) — and TTM is the sum
    of the last 4 reconstructed quarterly flows, falling back to the latest
    annual (a correct, if stale, 12-month basis) when quarters are incomplete.

    mixed_annual=False (US/yfinance): rows are uniform quarterly flows; TTM is
    simply the sum of the last ≤4 rows.

    Returns an empty Series if ``column`` is absent from the table (the US
    financials table is created ad-hoc; older/test schemas may lack revenue or
    operating_income — same tolerance as the ``NULL AS col`` value-factor guard).
    """
    if column not in _table_columns(conn, table_name):
        return pd.Series(dtype="float64")
    placeholders = ",".join("?" for _ in codes)
    sql = f"""
        SELECT stock_code, fiscal_period, {column} AS flow
        FROM (
            SELECT
                {code_column} AS stock_code,
                fiscal_period,
                {column},
                ROW_NUMBER() OVER (
                    PARTITION BY {code_column}
                    ORDER BY disclosed_at DESC, fiscal_period DESC, id DESC
                ) AS rn
            FROM {table_name}
            WHERE {code_column} IN ({placeholders})
              AND disclosed_at <= ?
              AND {column} IS NOT NULL
        )
        WHERE rn <= 12
    """
    rows = pd.read_sql_query(sql, conn, params=[*codes, as_of.isoformat()])
    if rows.empty:
        return pd.Series(dtype="float64")

    if not mixed_annual:
        recent = rows.groupby("stock_code").head(4)
        return recent.groupby("stock_code")["flow"].sum().astype(float)

    values: dict[str, float] = {}
    for code, group in rows.groupby("stock_code"):
        ttm = _reconstruct_ttm(group)
        if ttm is not None:
            values[code] = ttm
    return pd.Series(values, dtype="float64")


def _reconstruct_ttm(group: pd.DataFrame) -> float | None:
    """TTM from one stock's disclosure rows (KR mixed annual/interim shape)."""
    quarters: dict[tuple[int, int], float] = {}
    annuals: dict[int, float] = {}
    for _, row in group.iterrows():
        period = pd.Timestamp(row["fiscal_period"])
        value = float(row["flow"])
        if period.month == 12:
            annuals[period.year] = value
        elif period.month in (3, 6, 9):
            quarters[(period.year, period.month // 3)] = value

    # Derive Q4 flows where the year's annual and all three interims exist.
    flows = dict(quarters)
    for year, annual_value in annuals.items():
        q123 = [quarters.get((year, q)) for q in (1, 2, 3)]
        if all(v is not None for v in q123):
            flows[(year, 4)] = annual_value - sum(q123)  # type: ignore[arg-type]

    ordered = sorted(flows.items(), key=lambda item: item[0], reverse=True)
    latest_annual_year = max(annuals) if annuals else None

    if len(ordered) >= 4:
        newest_flow_end = ordered[0][0]
        # Prefer the annual when it is more recent than any derivable flow
        # (e.g. only annual reports were ever loaded for recent years).
        if latest_annual_year is None or newest_flow_end >= (latest_annual_year, 4):
            return float(sum(value for _, value in ordered[:4]))
    if latest_annual_year is not None:
        # Correct 12-month basis, possibly a few months stale — never mixes
        # the annual with its own constituent quarters.
        return float(annuals[latest_annual_year])
    if ordered:
        # Young listing: only interim flows exist; sum what there is (≤4).
        return float(sum(value for _, value in ordered[:4]))
    return None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    safe_numerator = pd.to_numeric(numerator, errors="coerce")
    safe_denominator = pd.to_numeric(denominator, errors="coerce").replace(0, pd.NA)
    result = safe_numerator / safe_denominator
    return result.replace([float("inf"), float("-inf")], pd.NA)
