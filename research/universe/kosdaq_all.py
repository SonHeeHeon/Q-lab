"""
Module: research.universe.kosdaq_all

Role:
    All KOSDAQ-listed stocks AS OF `as_of` — survivorship-free.

API:
    def get_kosdaq_all(as_of: date) -> list[str]

Same selection rule as kospi_all.py with `market = 'KOSDAQ'`.
"""
