# Acceptance tests

Human-owned checks for the demo. They live here, outside the example project
the agent works in, so the agent building the metrics is never pointed at them.

| Folder | Checks |
| --- | --- |
| [`online-marketplace/`](online-marketplace/) | The 48-hour dispatch promise metrics, against the rules in [`story.json`](online-marketplace/story.json) |

```bash
python acceptance/online-marketplace/acceptance.py
```

The test builds a fresh warehouse, runs every pipeline in the metric store
through the store's own runner, and compares every row with expected values it
computes in plain Python from the source data. The pipelines and the expected
values never share code, so a test can't pass just because both made the same
mistake.

Before the Dispatch metrics exist, only the existing Order metrics are checked.
GitHub Actions runs the same command on every pull request, and the result is
the required check for merging to `main`.
