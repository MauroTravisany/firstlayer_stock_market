# WP-04 - Canonical price shadow validation

This runbook is the only operational authority for WP-04 live shadow work.
It requires separate authorization; the code remediation that introduced it
does not authorize GCP writes.

## Safety precheck

Before any write, verify the exact PR SHA and successful CI, draft/no-merge
state, disabled deploy workflow, paused Strategy Brain, `BACKTEST_ONLY`,
`SHADOW_ONLY`, Alpaca Paper, and unchanged Dataform production. Stop on any
discrepancy.

Use only new isolated datasets in `us-east1`:

```text
acciones_dataset_shadow_wp04_schema_<UTC>
  environment=shadow
  work_package=wp04
  purpose=compiled_sql_validation

acciones_dataset_shadow_wp04_<UTC>
  environment=shadow
  work_package=wp04
  purpose=canonical_price_validation
```

Never write to `acciones_dataset`, move `dataform-production`, update a
production release/workflow config, deploy, apply Terraform, mutate Scheduler,
IAM or Secret Manager, or call a broker.

## Dataform snapshot and schema graph

Create a fresh candidate branch whose root is exactly `$FINAL_SHA:dataform`.
Compile with:

```text
defaultDatabase = stocks-437902
defaultSchema = acciones_dataset
defaultLocation = us-east1
assertionSchema = <SCHEMA_DATASET>

vars.auditDataset = <SCHEMA_DATASET>
vars.operationalDataset = acciones_dataset
vars.environment = shadow
vars.useCanonicalPrices = "true"
vars.minimumIntradayCoverage = "0.95"
vars.requireSecondaryPriceSource = "false"
vars.priceCloseToleranceBps = "10"
vars.priceVolumeToleranceRatio = "0.10"
vars.priceSourceStaleSeconds = "86400"
vars.priceModelVersion = "wp04-canonical-prices-v1"
```

The required graph is exactly:

```text
11 required actions
4 operations
6 relations
1 assertion

market_price_raw                              operations
corporate_actions_pit                         operations
market_session_calendar                       operations
fx_rate_raw                                   operations
price_source_reconciliation                   relation
market_price_canonical                        relation
fx_rates_pit                                  relation
trading_price_features_canonical_shadow       relation
trading_price_features_wp04_shadow            relation
wp04_legacy_vs_canonical_shadow                relation
audit_canonical_prices                        assertion
```

Export every paginated compilation action and run
`tools/wp04_compiled_sql_schema_check.py` in plan and acknowledged execution
mode. Continue only on:

```text
status = ALL_COMPILED_ACTIONS_SCHEMA_GRAPH_PASS
required_action_count = 11
operations = 4
relations = 6
assertions = 1
failed_action_count = 0
failed_assertion_count = 0
validation_dataset_only = true
production_change_allowed = false
```

Create the real-shadow compilation from the same source snapshot by changing
only `vars.auditDataset` and `assertionSchema` to the real shadow dataset.

## Empty raw tables

Materialize individually, with no transitive dependencies:

```text
market_price_raw
corporate_actions_pit
market_session_calendar
fx_rate_raw
```

All four tables must be empty, schema-exact, and located only in the new real
shadow dataset.

## Official moving-window plan

`BCCH_API_TOKEN` must exist only in the private process environment. Never
print, persist, log, or commit it. Stooq remains optional unless separately
authorized.

The only authorized planner command is:

```bash
python tools/wp04_shadow_backfill_windowed_official_fx.py \
  --expected-git-sha "$FINAL_SHA" \
  --asset-set config/wp04_shadow_assets.v1.json \
  --daily-start-date 2024-01-01 \
  --end-lag-days 2 \
  --intraday-lookback-days 45 \
  --hourly-lookback-days 365 \
  --max-rows 100000 \
  --work-dir /tmp/wp04-shadow-evidence/backfill \
  --window-output /tmp/wp04-shadow-evidence/wp04_provider_window.json \
  --output /tmp/wp04-shadow-evidence/wp04_shadow_backfill_plan.json
```

Do not use fixed effective intraday/hourly dates. The command must produce one
checksum-bound moving-window document and one plan from the same anchor.

Review all file hashes and identities, plus:

```text
official_fx_source_policy.policy_version = wp04-bcch-vintage-availability-v2
official_fx_source_policy.provider = BCCH_BDE
official_fx_source_policy.series_id = F073.TCO.PRE.Z.D
official_fx_source_policy.yahoo_fx_role = DIAGNOSTIC_ONLY
official_fx_source_status.required = true
official_fx_source_status.authentication_mode = API_KEY
fx_rate_raw quality_status = CURRENT_SNAPSHOT_NO_VINTAGE
fx_rate_raw first_observed_at = available_at = ingested_at
fx_rate_raw backtest_eligible = false
production_change_allowed = false
```

Yahoo `CLP=X` must not occur in `market_price_raw` or the mandatory Yahoo
series list. The current BDE snapshot is not historical-vintage evidence.

## Append-only execution and replay

The only authorized execution command is:

```bash
python tools/wp04_shadow_backfill_official_fx.py \
  --expected-git-sha "$FINAL_SHA" \
  --execute \
  --plan-file /tmp/wp04-shadow-evidence/wp04_shadow_backfill_plan.json \
  --expected-plan-checksum "$WP04_PLAN_CHECKSUM" \
  --acknowledge-shadow-write WP04_SHADOW_WRITE \
  --project-id stocks-437902 \
  --dataset-id "$REAL_SHADOW_DATASET" \
  --location us-east1 \
  --environment shadow \
  --output /tmp/wp04-shadow-evidence/wp04_shadow_backfill_execution.json
```

The executor must validate every row and `official_fx_source_status` before
creating a BigQuery client or staging table. It writes exactly four tables via
insert-only `MERGE`:

```text
market_price_raw -> raw_revision_id
corporate_actions_pit -> action_id
market_session_calendar -> session_id
fx_rate_raw -> fx_rate_revision_id
```

Repeat the same official executor command with the same plan, files, hashes,
SHA and dataset. The replay must insert zero rows into all four tables.

## Ordered materialization and evidence

Run individually with `transitiveDependenciesIncluded=false`:

```text
price_source_reconciliation
market_price_canonical
fx_rates_pit
trading_price_features_canonical_shadow
trading_price_features_wp04_shadow
wp04_legacy_vs_canonical_shadow
audit_canonical_prices
```

`fx_rates_pit` preserves all observed revisions. Any consumer must select
deterministically as-of with `available_at <= signal_timestamp`; a global
latest revision per rate date is forbidden.

Capture final read-only evidence with `tools/wp04_shadow_evidence.py`. Require
zero audit violations and hard gates, including no retroactive FX revision,
missing `first_observed_at`, snapshot-as-vintage claim, duplicate revision,
invalid source/rate/policy, or production-change flag.

Repeat sanitized before/after inventories and prove all writes were confined
to the two new shadow datasets. Keep PR #70 draft and Issue #39 open.
