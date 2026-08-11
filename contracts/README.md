# Machine-readable data contracts

Each YAML file defines one critical table's logical grain, primary key, temporal
semantics, source, deduplication, retention, columns, assertions, producers and
consumers.

`schema_snapshot.json` is the repository-side expected schema used by CI. It is
**not** evidence of the live BigQuery schema. A live schema export must be
validated against the same contracts before any data snapshot can be published.

Validate the catalog and expected schema:

```bash
python -m packages.common.data_contracts \
  --contracts contracts \
  --schema-snapshot contracts/schema_snapshot.json
```

Build a deterministic snapshot row without writing BigQuery:

```bash
python tools/build_data_snapshot.py \
  --environment shadow \
  --data-contract-version audit-contracts-v1 \
  --contract-set-hash <sha256> \
  --schema-snapshot-hash <sha256> \
  --source-manifest source-manifest.json \
  --content-checksum <sha256> \
  --quality-gates quality-gates.json \
  --output snapshot-row.json
```

The builder emits `PUBLISHED` only if every quality gate is `PASS`, has evidence,
and every source has an immutable checksum and timezone-aware `as_of_utc`.
It performs no cloud mutation.

WP-03 and WP-04 extend this catalog with point-in-time financial, earnings,
price and corporate-action contracts. WP-02 does not reinterpret legacy data.
