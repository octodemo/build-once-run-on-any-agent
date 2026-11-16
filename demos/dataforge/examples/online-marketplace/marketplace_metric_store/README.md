# marketplace_metric_store

The metric store for the online-marketplace example. `forge-init` scans this
tree to discover the domain taxonomy, the entity folder structure, and the
naming conventions — none of it is declared in the manifest.

## Layout

```
marketplace_metric_store/
  common/                      # runners and shared config (not a domain)
  fulfilment/                  # domain
    Order/                     # entity
      Code/                    # pipelines, one file per cadence
      Schema/                  # table DDL, one file per grain and cadence
      Schema/Alter/            # column additions to existing tables
      README.md                # metric inventory and development history
    Dispatch/                  # 48-hour promise outcomes, joined from orders and attempts
      Code/                    # Daily, Cumulative, and source reconciliation SQL
      Schema/                  # merchant-grain DDL for both cadences
      test_dispatch.py         # boundary cases and isolated two-region validation
      README.md                # approved policy and run instructions
```

## Key numbers

| | |
| --- | --- |
| Domains | 1 (`fulfilment`) |
| Entities implemented | 2 (`Order`, `Dispatch`) |
| Metrics | 4 (2 Order lifecycle, 2 Dispatch promise outcomes) |
| Grains | 1 (`merchant_id`) |
| Cadences | 2 (Daily, Cumulative) |
| Tables per entity | 2 |
| Table definitions | 4 |
| Zones | 2 (`east`, `west`) |

`seed.py` preloads Order only. Dispatch was deployed to east, then west, with
30 snapshot dates (2026-10-16 through 2026-11-14) after schema approval.
See [Dispatch](fulfilment/Dispatch/README.md) for approved business rules,
deployment details, run commands, and isolated validation.

## Conventions

Metric columns are `total_{entity}_{verb}_count`. System columns
(`SNAPSHOT_DATE`, `LOAD_TIMESTAMP`, `SOURCE_ZONE`) are uppercase; everything
else is `lowercase_snake_case`. Table names are
`{Entity}_{Grain}_Metrics_Snapshot_{Cadence}`.

`forge-lint` enforces all of the above. The rules live in the skill, the
vocabulary they are applied to comes from the resolved manifest.
