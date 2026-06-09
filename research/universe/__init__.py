"""
Package: research.universe

Universe (stock-list) builders. The single most important property of
every universe function:

    get_universe(name: str, as_of: date) -> list[str]   # codes

…MUST be survivorship-free. It returns ALL stocks that were members
of `name` on `as_of`, including those that have since been delisted.

Files:
  - kospi200.py     → historical KOSPI200 constituents at as_of
  - kospi_all.py    → all KOSPI-listed stocks at as_of
  - kosdaq_all.py   → all KOSDAQ-listed stocks at as_of
"""
