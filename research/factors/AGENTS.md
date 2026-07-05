<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# research/factors/ — Factor Model

## Purpose
Computes quantitative factor scores for each stock in the universe. Factors are cross-sectionally normalised (z-score or rank-percentile) before being combined into a composite score.

## Key Files

| File | Description |
|------|-------------|
| `common.py` | Base factor utilities — cross-sectional z-score, winsorization, factor combination |
| `value.py` | Value factors — PER, PBR, EV/EBITDA inverse |
| `quality.py` | Quality factors — ROE, ROA, GP/A, accruals |
| `momentum.py` | Momentum factors — 12-1 price momentum, earnings revision |
| `volume.py` | Volume/liquidity factors — ADTV, turnover, short interest |

## For AI Agents

### Factor Catalog Exhaustion Guard
`builder_factor_guard_test.dart` (Flutter) verifies that the factor catalog enum in `shared/domain/factor.py` is exhaustively handled. When adding a new factor type, update the Python enum AND the Flutter domain enum together.

### Cross-Sectional Normalisation
All factor values must be normalised at the same calendar date before combination. Using raw absolute values across dates is a look-ahead violation.

### Adding a New Factor
1. Add function to the appropriate `<type>.py` file
2. Register it in `common.py` factor catalog dict
3. Update `shared/domain/factor.py` enum
4. Run `research/tests/test_us_factors.py` and `research/tests/test_backtest_engine_smoke.py`

<!-- MANUAL: -->
