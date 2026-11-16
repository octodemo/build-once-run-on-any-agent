# Dispatch

48-hour dispatch promise metrics for the fulfilment domain, at merchant grain.

| Metric | Event date | Rule |
| :--- | :--- | :--- |
| `total_dispatch_meet_count` | First successful dispatch date | Dispatch at or before `placed_at + INTERVAL '48 hours'` |
| `total_dispatch_miss_count` | Deadline date | No successful dispatch at or before the deadline, even if shipped later |

One order is one promise. Failed attempts never count as a dispatch. Deleted
orders and attempts are excluded before deriving the first success. Orders
cancelled strictly before their deadline are excluded entirely. Cancellation
at or after the deadline does not exclude a promise.

Both Daily and Cumulative tables store `SNAPSHOT_DATE`, `merchant_id`,
`metric_name`, `metric_value`, `LOAD_TIMESTAMP`, and `SOURCE_ZONE`, matching
Order's long-format contract. Each merchant with an eligible order placed by
the snapshot has both metric rows, including zero counts.

## Running

The existing shared runners compile SQL using injected source/target schemas,
snapshot date, and region. From the project root:

```bash
SOURCE_ZONE=east SNAPSHOT_DATE=2026-11-15 python3 \
  marketplace_metric_store/common/daily_runner.py \
  marketplace_metric_store/fulfilment/Dispatch/Code/Dispatch_Metrics_Snapshot_Daily.py
```

Use `common/cumulative_runner.py` and the Cumulative pipeline for running
totals. The runners print SQL rather than execute it. After schema approval,
execute that SQL through `forge-dbx` against the matching zone. Every load
atomically replaces only its snapshot using a transaction, leaving other
dates intact. Stop on any SQL error.

Snapshots represent complete Sydney calendar days. Source timestamps already
use Sydney time, so no UTC conversion is applied. Daily counts events on the
snapshot date, and Cumulative counts all events through it. Neither cadence
uses an earlier target snapshot as its input.

## Validation

```bash
python3 -m unittest discover \
  -s marketplace_metric_store/fulfilment/Dispatch/Code -p 'test_*.py' -v
```

Tests cover deadline equality, midnight boundaries, cancellation before/at/after
the deadline, failed attempts, repeated successes, deleted orders/attempts,
pending deadlines, idempotent reruns, and transaction rollback. Full-history
reconciliation runs on disposable east/west database copies, leaving the
deployed warehouse untouched.

`Code/__dispatch_test.sql` independently derives promise events with `EXISTS`
and `NOT EXISTS`, rather than the pipeline's `MIN` aggregation. Substitute
`SOURCE_CATALOG`, `TARGET_CATALOG`, `SOURCE_ZONE`, and `SNAPSHOT_DATE` before
executing through `forge-dbx`. It returns aggregate failure counts for exact
source/target agreement, row counts, grain uniqueness, nulls and negative
values, source-zone attribution, date coverage, and Daily/Cumulative agreement.
Every failure count must be zero.

## Development history

| Date | Change | Issue |
| :--- | :--- | :--- |
| 2026-11-16 | Add meet/miss metrics, merchant Daily/Cumulative pipelines, and validation | #10 |
