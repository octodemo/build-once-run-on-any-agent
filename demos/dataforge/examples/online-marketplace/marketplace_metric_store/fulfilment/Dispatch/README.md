# Dispatch

Dispatch promise metrics for the fulfilment domain.

## Metrics

| Metric | Grain | Cadences | Definition |
| --- | --- | --- | --- |
| `total_dispatch_meet_count` | merchant | Daily, Cumulative | Orders first dispatched within 48 hours, counted on the first successful dispatch date |
| `total_dispatch_miss_count` | merchant | Daily, Cumulative | Orders not dispatched by the 48-hour deadline, counted on the deadline date |

Orders cancelled before their deadline and soft-deleted orders or attempts are
excluded. Dispatch attempts are reduced to the first successful attempt per
order before aggregation.

## Development history

| Date | Change | Issue |
| --- | --- | --- |
| 2026-11-17 | Initial build: dispatch promise metrics at merchant grain | #14 |
