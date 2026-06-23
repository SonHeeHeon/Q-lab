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
    account_type: Mapped[str] = mapped_column(
        Text, ForeignKey("accounts.type"), nullable=False
    )
    stock_code: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    kis_order_no: Mapped[str | None] = mapped_column(Text)
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


class Setting(ServiceBase):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


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


Index("idx_trades_account_executed", Trade.account_type, Trade.executed_at.desc())
Index("idx_trades_stock", Trade.stock_code)
Index("idx_trades_order_no", Trade.kis_order_no)
Index("idx_trades_status_checked", Trade.status, Trade.last_checked_at)
Index("idx_watchlist_stock", WatchlistEntry.stock_code)
Index("idx_alerts_triggered", Alert.triggered_at.desc())
Index("idx_journal_trade", TradeJournalEntry.trade_id)
Index(
    "idx_batch_date",
    BatchAnalysisResult.analysis_date.desc(),
    BatchAnalysisResult.rank,
)
Index("idx_stocks_market", Stock.market)
Index("idx_stocks_delisted", Stock.is_delisted)
Index("idx_prices_date", PriceDaily.date)
Index("idx_fin_stock_disclosed", Financial.stock_code, Financial.disclosed_at)
Index("idx_factor_date", FactorValue.date, FactorValue.factor_name)
