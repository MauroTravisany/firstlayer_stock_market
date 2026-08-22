# WP-04 - RETIRED USD/CLP reference design

This document name is retained only as a historical pointer. The design that
encoded a BCCh scalar reference rate in `market_price_raw` is retired.

The canonical policy is
[`WP-04_OFFICIAL_FX_SOURCE.md`](WP-04_OFFICIAL_FX_SOURCE.md): official rates
are stored append-only in `fx_rate_raw`, Yahoo `CLP=X` is diagnostic-only, and
`fx_rates_pit` derives exclusively from the Banco Central de Chile BDE series
`F073.TCO.PRE.Z.D`.
