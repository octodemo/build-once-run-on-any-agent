# Dispatch

Dispatch promise metrics for the fulfilment domain, combining orders with
dispatch attempts at merchant grain.

## Metrics

| Metric | Grains | Cadences | Source |
| :--- | :--- | :--- | :--- |
| `total_dispatch_meet_count` | merchant | Daily, Cumulative | `orders.placed_at`, `dispatch_attempts.attempted_at` |
| `total_dispatch_miss_count` | merchant | Daily, Cumulative | `orders.placed_at`, `dispatch_attempts.attempted_at` |

A promise is met when the first non-deleted successful dispatch occurs within
48 hours of placement, including exactly at the deadline. Count it on the
dispatch date. An order dispatched late or still undispatched at its deadline
is a miss counted on the deadline date. Exclude cancellations before the
deadline, retain cancellations at or after it, and exclude soft-deleted orders
and attempts. Multiple attempts still represent one order and one promise.

## Development history

| Date | Change | Issue |
| :--- | :--- | :--- |
| 2026-11-15 | Initial build: 48-hour dispatch promise meets and misses at merchant grain | #5 |
