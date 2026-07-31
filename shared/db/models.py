"""SQLAlchemy ORM models for the service and research databases."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class ServiceBase(DeclarativeBase):
    """Declarative base for tables stored in service.db."""


class ResearchBase(DeclarativeBase):
    """Declarative base for tables stored in research.db."""


class Account(ServiceBase):
    __tablename__ = "accounts"

    type: Mapped[str] = mapped_column(Text, primary_key=True)
    app_key: Mapped[str] = mapped_column(Text, nullable=False)
    app_secret: Mapped[str] = mapped_column(Text, nullable=False)
    account_no: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("1")
    )

    trades: Mapped[list[Trade]] = relationship(back_populates="account")


class Trade(ServiceBase):
    __tablename__ = "trades"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_type: Mapped[str | None] = mapped_column(
        Text, ForeignKey("accounts.type"), nullable=True
    )
    broker: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'KIS'")
    )
    stock_code: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    kis_order_no: Mapped[str | None] = mapped_column(Text)
    client_order_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'PENDING'")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    filled_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    filled_price: Mapped[Decimal | None] = mapped_column(Numeric)
    fees: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, server_default=text("0")
    )
    taxes: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, server_default=text("0")
    )
    filled_at: Mapped[datetime | None] = mapped_column(DateTime)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    raw_order: Mapped[str | None] = mapped_column(Text)
    raw_execution: Mapped[str | None] = mapped_column(Text)

    account: Mapped[Account] = relationship(back_populates="trades")
    journal_entry: Mapped[TradeJournalEntry | None] = relationship(
        back_populates="trade", uselist=False
    )


class WatchlistCategory(ServiceBase):
    __tablename__ = "watchlist_categories"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    color: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'#888888'")
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

    entries: Mapped[list[WatchlistEntry]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )


class WatchlistEntry(ServiceBase):
    __tablename__ = "watchlist_entries"
    __table_args__ = (
        UniqueConstraint("stock_code", "category_id"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_code: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("watchlist_categories.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    category: Mapped[WatchlistCategory] = relationship(back_populates="entries")


class Alert(ServiceBase):
    __tablename__ = "alerts"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_code: Mapped[str] = mapped_column(Text, nullable=False)
    broker: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'KIS'")
    )
    market_country: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'KR'")
    )
    symbol: Mapped[str | None] = mapped_column(Text)
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    action: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'NOTIFY'")
    )
    order_quantity: Mapped[int | None] = mapped_column(Integer)
    account_type: Mapped[str | None] = mapped_column(Text)
    account_id: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("1")
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_price: Mapped[float | None] = mapped_column(Float)
    last_error: Mapped[str | None] = mapped_column(Text)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime)
    post_mortem: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class Principle(ServiceBase):
    __tablename__ = "principles"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    is_editable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("1")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    journal_entries: Mapped[list[TradeJournalEntry]] = relationship(
        secondary=lambda: trade_journal_principles,
        back_populates="applied_principles",
    )


trade_journal_principles = Table(
    "trade_journal_principles",
    ServiceBase.metadata,
    Column(
        "journal_id",
        Integer,
        ForeignKey("trade_journal.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "principle_id", Integer, ForeignKey("principles.id"), primary_key=True
    ),
)


class TradeJournalEntry(ServiceBase):
    __tablename__ = "trade_journal"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("trades.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    post_review: Mapped[str | None] = mapped_column(Text)
    llm_analysis_summary: Mapped[str | None] = mapped_column(Text)
    llm_violation_tags: Mapped[str | None] = mapped_column(Text)
    llm_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime)
    llm_analysis_model: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    trade: Mapped[Trade] = relationship(back_populates="journal_entry")
    applied_principles: Mapped[list[Principle]] = relationship(
        secondary=lambda: trade_journal_principles,
        back_populates="journal_entries",
    )


class BatchAnalysisResult(ServiceBase):
    __tablename__ = "batch_analysis_results"
    __table_args__ = (
        UniqueConstraint("analysis_date", "strategy_name", "stock_code"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_date: Mapped[date] = mapped_column(Date, nullable=False)
    strategy_name: Mapped[str] = mapped_column(Text, nullable=False)
    stock_code: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_commentary: Mapped[str | None] = mapped_column(Text)


class LLMCache(ServiceBase):
    __tablename__ = "llm_cache"

    cache_key: Mapped[str] = mapped_column(Text, primary_key=True)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)


class AccountProfile(ServiceBase):
    """계좌별 퀀트 프로파일 — 자격증명은 env, 메타만 DB (A안).

    account_key = "KIS:REAL" | "TOSS:MAIN" 형식. sleeves_json은
    [{"type":"strategy","name":...,"weight":...}|{"type":"hold","code":...,
    "weight":...}] 직렬화 문자열. quant_enabled 기본 false — 라이브 잠금
    (Setting live_quant_unlocked)이 풀리기 전엔 PAPER 외 계좌는 켤 수 없다.
    """

    __tablename__ = "account_profiles"

    account_key: Mapped[str] = mapped_column(Text, primary_key=True)
    broker: Mapped[str] = mapped_column(Text, nullable=False)
    account_type: Mapped[str | None] = mapped_column(Text)
    profile_type: Mapped[str] = mapped_column(Text, nullable=False)
    quant_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    sleeves_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )


class RebalanceTarget(ServiceBase):
    """리밸런스 주기(월) 목표 포트폴리오 — 미이행 이월(carryover) 재제안용.

    월초 full_rebalance 제안 생성 시 목표 수량 맵을 저장하고, 비월초에도
    실보유와의 잔여 diff가 남아 있으면 이월 제안을 만든다. period는 YYYY-MM.
    """

    __tablename__ = "rebalance_targets"
    __table_args__ = (
        UniqueConstraint("account_type", "strategy_name", "period"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_type: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_name: Mapped[str] = mapped_column(Text, nullable=False)
    period: Mapped[str] = mapped_column(Text, nullable=False)
    target_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )


class Setting(ServiceBase):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class OrderProposal(ServiceBase):
    """One proposed trade from the approval-based semi-auto pipeline.

    The daily generator diffs the strategy's target portfolio against current
    holdings and writes proposals; the user approves in-app. Approval mints a
    ``client_order_id`` (idempotency key) and routes through the same safety
    gateway as manual orders. Status flow:
    PROPOSED → APPROVED → SUBMITTED → FILLED | REJECTED | EXPIRED | FAILED.
    """

    __tablename__ = "order_proposals"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str] = mapped_column(Text, nullable=False)
    proposal_date: Mapped[date] = mapped_column(Date, nullable=False)
    account_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'PAPER'")
    )
    strategy_name: Mapped[str] = mapped_column(Text, nullable=False)
    config_hash: Mapped[str | None] = mapped_column(Text)
    stock_code: Mapped[str] = mapped_column(Text, nullable=False)
    market: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'KR'")
    )
    side: Mapped[str] = mapped_column(Text, nullable=False)  # BUY | SELL
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    order_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'LIMIT'")
    )
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric)
    last_price: Mapped[Decimal | None] = mapped_column(Numeric)
    estimated_notional: Mapped[Decimal | None] = mapped_column(Numeric)
    reason_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'PROPOSED'")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    client_order_id: Mapped[str | None] = mapped_column(Text)
    trade_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("trades.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class PortfolioSnapshot(ServiceBase):
    """Daily portfolio NAV per account for performance tracking.

    Populated by the NAV snapshot batch job (source='BROKER', the actual
    broker-reported NAV) so paper/real equity curves accumulate over time.
    When absent, the performance API reconstructs a curve from ``trades`` +
    historical prices instead.
    """

    __tablename__ = "portfolio_snapshots"

    account_type: Mapped[str] = mapped_column(Text, primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    nav: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    cash: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, server_default=text("0")
    )
    holdings_value: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, server_default=text("0")
    )
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'BROKER'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class StockRating(ServiceBase):
    """매수축 평가 결과 — 종목당 1행(최신 평가로 upsert되는 현재 상태 테이블).

    일일 평가 배치가 유니버스 전 종목을 스캔해 채점하고, 이 테이블을 종목당
    한 행으로 갱신한다. ``status``가 'OK'가 아니면(NO_DATA/UNSUPPORTED)
    ``buy_grade``/``score``/``percentile``은 비어 있을 수 있다.
    """

    __tablename__ = "stock_ratings"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    buy_grade: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Float)
    percentile: Mapped[float | None] = mapped_column(Float)
    weakest_group: Mapped[str | None] = mapped_column(Text)
    strategy_name: Mapped[str] = mapped_column(Text, nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class PositionRating(ServiceBase):
    """매도축 평가 결과 — 계좌×종목당 1행(보유 포지션의 현재 매도 신호).

    ``account_key``는 브로커별 계좌 식별자다: KIS는 ``account_type``
    값('PAPER'/'REAL'/'ISA'), Toss는 ``'TOSS:<seq>'`` 형식을 쓴다.
    """

    __tablename__ = "position_ratings"

    broker: Mapped[str] = mapped_column(Text, primary_key=True)
    account_key: Mapped[str] = mapped_column(Text, primary_key=True)
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    sell_grade: Mapped[str] = mapped_column(Text, nullable=False)
    reason_json: Mapped[str] = mapped_column(Text, nullable=False)
    pl_rate: Mapped[float | None] = mapped_column(Float)
    entry_price: Mapped[float | None] = mapped_column(Float)
    lane: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class RatingBatchRun(ServiceBase):
    """매수/매도축 평가 배치 갱신 이력(관측성용)."""

    __tablename__ = "rating_batch_runs"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lane: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    universe_size: Mapped[int | None] = mapped_column(Integer)
    stored_count: Mapped[int | None] = mapped_column(Integer)
    error_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    detail_json: Mapped[str | None] = mapped_column(Text)


class Stock(ResearchBase):
    __tablename__ = "stocks"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    market: Mapped[str] = mapped_column(Text, nullable=False)
    sector: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(Text)
    listed_at: Mapped[date] = mapped_column(Date, nullable=False)
    delisted_at: Mapped[date | None] = mapped_column(Date)
    is_delisted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )

    prices: Mapped[list[PriceDaily]] = relationship(back_populates="stock")
    financials: Mapped[list[Financial]] = relationship(back_populates="stock")
    factor_values: Mapped[list[FactorValue]] = relationship(back_populates="stock")


class PriceDaily(ResearchBase):
    __tablename__ = "prices_daily"

    stock_code: Mapped[str] = mapped_column(
        Text, ForeignKey("stocks.code"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)
    adj_close: Mapped[Decimal | None] = mapped_column(Numeric)

    stock: Mapped[Stock] = relationship(back_populates="prices")


class Financial(ResearchBase):
    __tablename__ = "financials"
    __table_args__ = (
        UniqueConstraint("stock_code", "fiscal_period"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_code: Mapped[str] = mapped_column(
        Text, ForeignKey("stocks.code"), nullable=False
    )
    fiscal_period: Mapped[date] = mapped_column(Date, nullable=False)
    disclosed_at: Mapped[date] = mapped_column(Date, nullable=False)
    revenue: Mapped[Decimal | None] = mapped_column(Numeric)
    operating_income: Mapped[Decimal | None] = mapped_column(Numeric)
    net_income: Mapped[Decimal | None] = mapped_column(Numeric)
    total_assets: Mapped[Decimal | None] = mapped_column(Numeric)
    total_equity: Mapped[Decimal | None] = mapped_column(Numeric)
    eps: Mapped[Decimal | None] = mapped_column(Numeric)
    bps: Mapped[Decimal | None] = mapped_column(Numeric)

    stock: Mapped[Stock] = relationship(back_populates="financials")


class FactorValue(ResearchBase):
    __tablename__ = "factor_values"

    stock_code: Mapped[str] = mapped_column(
        Text, ForeignKey("stocks.code"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    factor_name: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[float | None] = mapped_column(Float)

    stock: Mapped[Stock] = relationship(back_populates="factor_values")


class MarketIndex(ResearchBase):
    __tablename__ = "market_index"

    index_code: Mapped[str] = mapped_column(Text, primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[Decimal] = mapped_column(Numeric, nullable=False)


class InvestorFlowDaily(ResearchBase):
    """Daily net-purchase trading value by investor type (pykrx 투자자별 순매수).

    Values are KRW net purchase amounts (buy − sell); positive = net buying.
    Feeds the Flow factor group (e.g. FOREIGN_NET_20D) of the composite score.
    """

    __tablename__ = "investor_flows_daily"

    stock_code: Mapped[str] = mapped_column(Text, primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    foreign_net: Mapped[Decimal | None] = mapped_column(Numeric)
    inst_net: Mapped[Decimal | None] = mapped_column(Numeric)
    indiv_net: Mapped[Decimal | None] = mapped_column(Numeric)


class MarketCapDaily(ResearchBase):
    """True daily market capitalization (pykrx 시가총액/상장주식수).

    The backtest engine's MARKET_CAP factor/filter reads this table; without it
    MARKET_CAP is skipped with a warning (never silently proxied by turnover).
    """

    __tablename__ = "market_caps"

    stock_code: Mapped[str] = mapped_column(Text, primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    market_cap: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    shares_outstanding: Mapped[int | None] = mapped_column(Integer)


class StockUs(ResearchBase):
    """US universe (NASDAQ100-ish) mirrored into research.db.

    The table is created out-of-band by
    ``research/scripts/download_us_universe.py``; this ORM model mirrors that
    schema. ``korean_name``/``isin`` are backfilled from Toss (see
    ``backend.app.services.batch.us_names_sync``) so US tickers are searchable
    by their Korean display name in-app.
    """

    __tablename__ = "stocks_us"

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'NASDAQ'")
    )
    sector: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'USD'")
    )
    listed_at: Mapped[date | None] = mapped_column(Date)
    delisted_at: Mapped[date | None] = mapped_column(Date)
    is_delisted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    korean_name: Mapped[str | None] = mapped_column(Text)
    isin: Mapped[str | None] = mapped_column(Text)


Index("idx_trades_account_executed", Trade.account_type, Trade.executed_at.desc())
Index("idx_trades_stock", Trade.stock_code)
Index("idx_trades_order_no", Trade.kis_order_no)
Index("idx_trades_client_order_id", Trade.client_order_id, unique=True)
Index("idx_trades_status_checked", Trade.status, Trade.last_checked_at)
Index("idx_watchlist_stock", WatchlistEntry.stock_code)
Index("idx_alerts_triggered", Alert.triggered_at.desc())
Index("idx_journal_trade", TradeJournalEntry.trade_id)
Index(
    "idx_snapshots_account_date",
    PortfolioSnapshot.account_type,
    PortfolioSnapshot.date.desc(),
)
Index(
    "idx_proposals_status_date",
    OrderProposal.status,
    OrderProposal.proposal_date.desc(),
)
Index("idx_proposals_batch", OrderProposal.batch_id)
Index(
    "idx_proposals_client_order_id",
    OrderProposal.client_order_id,
    unique=True,
)
Index(
    "idx_batch_date",
    BatchAnalysisResult.analysis_date.desc(),
    BatchAnalysisResult.rank,
)
Index("idx_stocks_market", Stock.market)
Index("idx_stocks_delisted", Stock.is_delisted)
Index("idx_prices_date", PriceDaily.date)
Index("idx_market_caps_date", MarketCapDaily.date)
Index("idx_investor_flows_date", InvestorFlowDaily.date)
Index("idx_fin_stock_disclosed", Financial.stock_code, Financial.disclosed_at)
Index("idx_factor_date", FactorValue.date, FactorValue.factor_name)
