"""
Module: research.strategies.multi_factor

Role:
    Composite-factor scoring helpers. Used by `engine.score_stocks`
    when the strategy combines multiple factors with weights and
    transforms (ZSCORE, RANK, RAW).

Planned helpers:
    - apply_transform(series: Series, transform: str) -> Series
    - composite_score(df: DataFrame, factors: list[FactorWeight]) -> Series
    - apply_filter_rules(df: DataFrame, rules: list[FilterRule]) -> DataFrame

Why a dedicated module:
    The transform-then-weight-then-aggregate pipeline is the most
    error-prone spot for subtle bugs. Centralizing keeps a single
    well-tested implementation.

Connected modules:
    - shared.domain.strategy.{FactorWeight, FilterRule}
    - research.backtest.engine.score_stocks
"""
