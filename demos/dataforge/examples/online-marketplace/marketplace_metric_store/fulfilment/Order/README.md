# Order

Order lifecycle metrics for the fulfilment domain.

## Metrics

| Metric | Grains | Cadences | Source |
| --- | --- | --- | --- |
| `total_order_place_count` | merchant | Daily, Cumulative | `orders.placed_at` |
| `total_order_cancel_count` | merchant | Daily, Cumulative | `orders.cancelled_at` |

Soft-deleted rows (`is_deleted = true`), such as test orders, are excluded
from every metric.

## Development history

| Date | Change | Issue |
| --- | --- | --- |
| 2026-06-02 | Initial build: place and cancel counts at merchant grain | — |
