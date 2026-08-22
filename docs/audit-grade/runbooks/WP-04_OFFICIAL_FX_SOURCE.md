# WP-04 - Official USD/CLP FX source

## Decision

WP-04 uses the Banco Central de Chile BDE observed-dollar series as the only
eligible USD/CLP source:

```text
provider = BCCH_BDE
series_id = F073.TCO.PRE.Z.D
source_policy_version = wp04-bcch-observed-dollar-v1
policy_version = wp04-bcch-vintage-availability-v2
source_version = bcch-bde-rest-v1
availability_policy = wp04-bcch-vintage-availability-v2
```

Yahoo `CLP=X` is `DIAGNOSTIC_ONLY`. It is not downloaded by the official
planner, is not inserted into `market_price_raw`, and cannot produce
`fx_rates_pit`.

## Rejected Yahoo series

The bounded diagnostic found 44 invalid Yahoo daily observations for `CLP=X`.
Forty-three had material OHLC inconsistencies; the remaining observation was
outside the canonical FX session. The inconsistencies were stable across
repeated downloads and did not disappear with provider repair diagnostics.
They are therefore treated as a provider-data defect, not as harmless numeric
rounding.

An independent date-normalization defect was also found: daily provider labels
were converted to UTC before preserving their provider-local calendar date.
That could shift a Monday BST label to Sunday UTC. The ingestion policy now
uses the provider-local date for daily observations and keeps intraday
timestamps unchanged. This correction does not make Yahoo `CLP=X` eligible.

The quality gates remain unchanged:

```text
MIN_VALID_ROW_RATIO = 0.995
MAX_INVALID_ROWS_PER_SERIES = 5
```

No OHLC value is repaired, clipped, swapped, interpolated, or replaced, and
`repair=True` is not used for final evidence.

## Authentication

The official API token is supplied only through the private
`BCCH_API_TOKEN` environment variable. The planner fails closed if the token is
missing or rejected. The token, authenticated URL, response body, cookies, and
headers must never appear in plans, logs, errors, status JSONL, commits, or
evidence. Secret Manager is outside this code remediation.

## Point-In-Time Availability

Each `rate_date` uses the prior successful banking-day observation as
`source_reference_date`. `source_published_at` retains the 17:30
`America/Santiago` economic/legal schedule, but it is not evidence that the
payload observed today existed historically. For the current snapshot API:

```text
source_reference_date < rate_date
source_published_at < TIMESTAMP(rate_date, source_timezone)
first_observed_at = ingested_at
available_at = first_observed_at
quality_status = CURRENT_SNAPSHOT_NO_VINTAGE
backtest_eligible = false
production_change_allowed = false
```

The first requested rate date fails closed if no prior successful observation
is available. The adapter queries a bounded 32-day lookback to establish this
lineage.

## Storage And Replay

`fx_rate_raw` is an append-only scalar table. It does not fabricate
`open/high/low/close` fields. `fx_rate_record_id` is stable for provider,
series, and rate date. `fx_rate_revision_id` additionally binds the payload
hash and publication timestamp. The executor uses insert-only `MERGE` keyed by
`fx_rate_revision_id`, so an exact replay inserts zero rows.

`fx_rates_pit` reads only `fx_rate_raw` and preserves every distinct observed
revision. A consumer must select the deterministic maximum revision satisfying
`available_at <= signal_timestamp`; selecting one global latest revision per
rate date is forbidden. It has no dependency on market OHLC,
`market_price_canonical`, Yahoo `CLP=X`, `adjusted_close`, or
`vars.usdClpTicker`.

The BDE API does not expose a complete historical revision ledger or archived
checksum/URI/timestamp for each payload. WP-04 preserves every revision
observed by FirstLayer after ingestion, but cannot reconstruct provider
revisions that were never observed. A future archive-backed row may become
eligible only under a separately reviewed policy with verifiable URI,
checksum, and timestamp evidence.

## Production Prohibitions

This remediation authorizes code, contracts, tests, and documentation only.
It does not authorize a BigQuery dataset or backfill, Dataform production,
Cloud Run deployment, Terraform apply, Scheduler/IAM/Secret Manager mutation,
Strategy Brain activation, Paper Champion activation, broker calls, merge, or
Issue #39 closure.
