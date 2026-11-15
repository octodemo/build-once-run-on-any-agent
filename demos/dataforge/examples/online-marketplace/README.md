# online-marketplace

A complete, runnable Dataforge project backed by local DuckDB files, built for
the Sydney delivery of *Build once, run on any agent*. A fictional Australian
online marketplace wants to know whether it keeps its promise to dispatch every
order within 48 hours. Everything here is synthetic and generated from a fixed
seed.

```bash
brew install duckdb
python seed.py
```

That builds `warehouse/east.duckdb` and `warehouse/west.duckdb`, each holding a
source schema of raw marketplace data and a target schema with the Order metric
tables already built. No account, no cluster, no credentials.

[DEMO.md](DEMO.md) is the scripted walkthrough: a GitHub issue in, a reviewed
pull request out, with Dataforge running in the GitHub Copilot app.

## What is here

| Path | What it is |
| --- | --- |
| `dataforge.manifest.yaml` | The seed manifest. A few lines of config; everything else is discovered. |
| `seed.py` | Builds the warehouse. `--check` verifies an existing one. |
| `marketplace_metric_store/` | The metric store `forge-init` scans to learn the house style. `Order` is preloaded. `Dispatch` includes pipelines, schema, tests, and approved policy documentation. |
| `issues/` | The issue body used as intake for the demo. |
| `warehouse/` | Generated DuckDB files. Not committed. |

## The data

Two regions, each with its own database file, so that deploying to more than
one region is a real sequence rather than a duplicated command.

| | east | west |
| --- | --- | --- |
| Fulfilment centre | Sydney | Perth |
| Merchants | 12 | 6 |
| Source tables | `merchants`, `orders`, `dispatch_attempts` | same |
| Deployed entities | `Order`, `Dispatch` | `Order`, `Dispatch` |

The seed preloads only Order. The [Dispatch implementation](marketplace_metric_store/fulfilment/Dispatch/README.md)
adds met/missed promise outcomes for both regions and cadences. Following
schema approval, Dispatch was deployed to east, then west, with 30 snapshot
dates from 2026-10-16 through 2026-11-14. Re-running the seed resets the warehouse
to Order only.

- `merchants`: the businesses that sell on the marketplace.
- `orders`: one row per order — who sold it, when it was placed, when (if ever)
  it was cancelled, and whether it is a soft-deleted test order.
- `dispatch_attempts`: one row each time a fulfilment centre tries to send an
  order. Some attempts fail before one succeeds, so one order can have several
  rows.

The window is the 120 days ending yesterday, and every timestamp is Sydney
time. One merchant, Harbour Homewares (east), joined last week and has only
seven hand-made "story" orders, so every number the demo produces for it can be
checked by hand.

The human-owned acceptance tests live outside this folder, in
[`acceptance/online-marketplace/`](../../../../acceptance/online-marketplace/),
so the agent building the metrics is never pointed at the answers.

## Why DuckDB

`forge-dbx` treats the platform as one swappable primitive. Under
`engine: duckdb` a region is a file and a query is a subprocess. The tradeoff is
visible: DuckDB has no job scheduler, so `forge-init` marks orchestration
engine-unsupported rather than inventing one.
