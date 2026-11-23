# Dispatch

48-hour dispatch promise outcomes at merchant grain, alongside Order.
Both metrics use the existing long-format columns (`metric_name`,
`metric_value`) and have Daily and Cumulative tables.

| Metric | Outcome | Counted on |
| :--- | :--- | :--- |
| `total_dispatch_meet_count` | First valid successful dispatch is within 48 hours, inclusive | First successful dispatch date |
| `total_dispatch_miss_count` | No valid successful dispatch by the deadline | Placement timestamp + 48 hours, cast to date |

## Approved business rules

Operations confirmed these rules and approved both table definitions on
2026-11-15 for issue #3:

- The promise uses 48 elapsed hours, not business days. Source timestamps are
  already Sydney-local, so no region-dependent timezone conversion is applied.
- Only `outcome = 'dispatched'` is success. Failed attempts do not satisfy the
  promise. Reduce successful attempts to the earliest timestamp per order
  before joining to orders, so retries and repeated successes cannot multiply
  an order.
- Cancellation at or before the deadline, before any valid successful
  dispatch, exempts an order. Cancellation after a successful dispatch does
  not erase a met promise. If cancellation and success coincide, success wins.
- Late dispatch and cancellation after the deadline never erase a miss.
  An order receives at most one outcome, and a late dispatch never becomes met.
- Unresolved orders whose deadlines fall after the snapshot day are pending,
  not missed. Snapshots represent the end of their Sydney calendar day.
- Exclude soft-deleted orders and soft-deleted attempts independently.

Daily counts outcomes on that day. Cumulative recomputes all outcomes through
that day directly from source, without reading previous output. Future attempts
are excluded when rebuilding historical snapshots. Both metrics emit explicit
`metric_value = 0` records for merchants with non-deleted orders
placed by that snapshot, even if all their orders are pending or exempt.
No rows are emitted for merchants without such orders.

Current source soft-delete flags and corrected event timestamps govern reruns.
The source has no change history, so historical snapshots cannot reconstruct
what a deleted or corrected source row looked like before its correction.

## Running

Run commands from the `online-marketplace` project directory. `seed.py`
preloads only Order, not Dispatch. **Review and approve the two files in
`Schema/` before applying them to either region.** There are no ALTER scripts
or scheduler jobs for this new DuckDB entity.

Initial deployment completed on 2026-11-15, east before west. Both cadences
contain the 30 snapshot dates from 2026-10-16 through 2026-11-14 inclusive.
Cumulative values include all available source history through each snapshot,
not just events in the backfill window. Source reconciliation returned zero
mismatches in both regions, and existing source and Order data were unchanged.

| Region | Daily rows | Cumulative rows | Snapshot dates |
| :--- | :--- | :--- | :--- |
| east | 674 | 674 | 30 |
| west | 360 | 360 | 30 |

Database backups were retained outside the repository before schema execution.
For the first 48 hours after deployment, check for missing dates, NULL grain
keys, an all-zero metric, an empty region, or row counts deviating more than
20% from the source-based expectation. These are manual monitoring checks,
not a configured scheduler or alert service.

After schema approval, apply each schema and render each pipeline through the
existing runner, one region at a time (`east`, then `west`):

```bash
set -euo pipefail
export ENGINE=duckdb SOURCE_ZONE=east
export SNAPSHOT_DATE=2026-11-14  # replace with the snapshot date to build
entity=marketplace_metric_store/fulfilment/Dispatch

for cadence in Daily Cumulative; do
  sed 's/{TARGET_CATALOG}/demo_gold_marketplace_metric_store/g' \
    "$entity/Schema/Dispatch_Merchant_Metrics_Snapshot_${cadence}.sql" |
    duckdb "warehouse/$SOURCE_ZONE.duckdb" -bail -json
done

python3 marketplace_metric_store/common/daily_runner.py \
  "$entity/Code/Dispatch_Metrics_Snapshot_Daily.py" |
  duckdb "warehouse/$SOURCE_ZONE.duckdb" -bail -json
python3 marketplace_metric_store/common/cumulative_runner.py \
  "$entity/Code/Dispatch_Metrics_Snapshot_Cumulative.py" |
  duckdb "warehouse/$SOURCE_ZONE.duckdb" -bail -json
```

For backfills, run the two pipeline commands for each desired `SNAPSHOT_DATE`.
Each pipeline transactionally replaces only its selected date, so reruns are
idempotent and a failed insert rolls back the deletion. Older snapshots are
unaffected. Use `-bail` so execution stops on the first SQL failure. DuckDB has
no table history, so retain a database backup before applying schema changes.

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s marketplace_metric_store/fulfilment/Dispatch -v
```

Tests cover exact deadlines, a one-second miss, midnight boundaries, retry
deduplication, early and late cancellations, deleted orders and attempts,
pending orders, reverse-order backfills, reruns, and failed-load rollback.
They also load the full source window in **temporary copies** of both region
files and reconcile both metrics with `Code/__dispatch_test.sql`, including
snapshot coverage and merchant completeness. They do not deploy to the demo
warehouse or read the human-owned acceptance checks.

The reconciliation SQL uses `{SOURCE_CATALOG}`, `{TARGET_CATALOG}`,
`{START_DATE}`, and `{END_DATE}` placeholders. It returns a mismatch count
(expected zero), not source rows.

## Development history

| Date | Contributor | Change | Issue |
| :--- | :--- | :--- | :--- |
| 2026-11-15 | Copilot | Add approved merchant-grain met/missed counts and deploy 30 snapshot dates to east, then west | #3 |
