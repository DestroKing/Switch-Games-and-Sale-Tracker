"""Physical-game market tracker: availability, scarcity and out-of-print evidence.

A self-contained subsystem with its own database (market.db). The price
tracker never imports this package at module level; every integration point
is a lazy import behind ``settings.market_tracker``, so switching it off -- or
deleting this package -- leaves the price tracker exactly as it was.

Design and removal steps: docs/market-tracker-design.md.
"""
