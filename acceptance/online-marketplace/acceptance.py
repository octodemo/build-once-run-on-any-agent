#!/usr/bin/env python3
"""Acceptance tests for the online-marketplace demo.

Written by people, not by the agent, and kept outside the example project the
agent works in. They encode the business rules agreed for the 48-hour dispatch
promise (see story.json) and check that whatever pipelines exist in the metric
store produce exactly the numbers those rules imply.

How it works:
  1. Build a fresh warehouse in a temporary folder with the example's seed.py.
  2. Drop the seeded metric tables and recreate every table from the store's
     own Schema/*.sql files.
  3. Run every pipeline through the store's own runner for each snapshot date,
     in both regions.
  4. Compare every metric row with expected values computed here, in plain
     Python, straight from the source rows.

Until Dispatch metrics exist, only the existing Order metrics are checked.

    python acceptance/online-marketplace/acceptance.py            # last 30 days
    python acceptance/online-marketplace/acceptance.py --days 120 # whole window

Requires Python 3.9+ and the duckdb CLI on PATH. No other dependencies.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import datetime as dt
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_EXAMPLE = REPO / "demos" / "dataforge" / "examples" / "online-marketplace"
STORY = json.loads((HERE / "story.json").read_text())

SOURCE = "demo_gold_commerce"
TARGET = "demo_gold_marketplace_metric_store"
ZONES = ("east", "west")
CADENCES = ("Daily", "Cumulative")
PROMISE = dt.timedelta(hours=STORY["promise_hours"])

BUILT_ENTITY = "Order"
REQUESTED_ENTITY = "Dispatch"
ORDER_METRICS = ("total_order_place_count", "total_order_cancel_count")
DISPATCH_METRICS = ("total_dispatch_meet_count", "total_dispatch_miss_count")
METRIC_NAME = re.compile(r"^total_[a-z]+(_[a-z]+)*_count$")
TABLE_NAME = re.compile(
    r"^(?P<entity>[A-Za-z_]+)_(?P<grain>[A-Za-z]+)_Metrics_Snapshot_(?P<cadence>Daily|Cumulative)$"
)

# DuckDB 2 switches to an "agent mode" output when it detects an AI agent.
# Explicit output modes (-json) and this variable keep parsing predictable.
DUCKDB_ENV = dict(os.environ, DUCKDB_AGENT_MODE="0")


class Report:
    def __init__(self) -> None:
        self.checks = []

    def add(self, status: str, title: str, detail: str = "") -> None:
        self.checks.append({"status": status, "title": title, "detail": detail})
        mark = {"pass": "✓", "fail": "✗", "info": "•"}[status]
        print(f"  {mark} {title}")
        if detail:
            for line in detail.splitlines():
                print(f"      {line}")

    @property
    def passed(self) -> bool:
        return all(check["status"] != "fail" for check in self.checks)


def duckdb(db: pathlib.Path, sql: str, *args: str) -> str:
    result = subprocess.run(
        ["duckdb", *args, str(db)], input=sql, capture_output=True, text=True, env=DUCKDB_ENV
    )
    if result.returncode != 0:
        raise RuntimeError(f"duckdb failed on {db.name}: {result.stderr.strip()}")
    return result.stdout


def query(db: pathlib.Path, sql: str) -> list:
    out = duckdb(db, sql, "-json").strip()
    return json.loads(out) if out else []


def timestamp(value):
    return dt.datetime.fromisoformat(value) if value else None


def end_date(db: pathlib.Path) -> dt.date:
    """The last day of data: the seed's window ends yesterday."""
    row = query(db, f"SELECT CAST(MAX(placed_at) AS DATE) AS d FROM {SOURCE}.orders")[0]
    return dt.date.fromisoformat(row["d"])


# ---------------------------------------------------------------------------
# Expected values: the agreed business rules, in plain Python
# ---------------------------------------------------------------------------

def expected_events(db: pathlib.Path) -> list:
    """Every metric event as (merchant_id, metric_name, event_date)."""
    orders = query(
        db,
        f"SELECT order_id, merchant_id, placed_at, cancelled_at, is_deleted FROM {SOURCE}.orders",
    )
    attempts = query(
        db,
        f"SELECT order_id, attempted_at, outcome, is_deleted FROM {SOURCE}.dispatch_attempts",
    )

    first_dispatch = {}
    for attempt in attempts:
        if attempt["is_deleted"] or attempt["outcome"] != "dispatched":
            continue
        when = timestamp(attempt["attempted_at"])
        current = first_dispatch.get(attempt["order_id"])
        if current is None or when < current:
            first_dispatch[attempt["order_id"]] = when

    events = []
    for order in orders:
        if order["is_deleted"]:  # test orders are ignored by every metric
            continue
        merchant = order["merchant_id"]
        placed = timestamp(order["placed_at"])
        cancelled = timestamp(order["cancelled_at"])
        events.append((merchant, "total_order_place_count", placed.date()))
        if cancelled:
            events.append((merchant, "total_order_cancel_count", cancelled.date()))

        deadline = placed + PROMISE
        dispatched = first_dispatch.get(order["order_id"])  # one order, however many attempts
        if dispatched is not None and dispatched <= deadline:
            events.append((merchant, "total_dispatch_meet_count", dispatched.date()))
        elif cancelled is not None and cancelled < deadline:
            continue  # cancelled in time: neither met nor missed
        else:
            # Missed when the deadline passed, even if it shipped later or was
            # cancelled after the deadline. Deadlines after the last snapshot
            # date are simply never counted.
            events.append((merchant, "total_dispatch_miss_count", deadline.date()))
    return events


def expected_values(events: list, snapshots: list) -> dict:
    """{(cadence, metric): {(snapshot_date, merchant_id): value}}, zeros omitted."""
    by_key = collections.defaultdict(list)
    for merchant, metric, day in events:
        by_key[(metric, merchant)].append(day)

    values = collections.defaultdict(dict)
    for (metric, merchant), days in by_key.items():
        for snapshot in snapshots:
            daily = sum(1 for day in days if day == snapshot)
            cumulative = sum(1 for day in days if day <= snapshot)
            if daily:
                values[("Daily", metric)][(snapshot, merchant)] = daily
            if cumulative:
                values[("Cumulative", metric)][(snapshot, merchant)] = cumulative
    return values


# ---------------------------------------------------------------------------
# Actual values: the store's own DDL, pipelines, and runner
# ---------------------------------------------------------------------------

def entity_folders(store: pathlib.Path) -> list:
    return sorted({path.parent.parent.name for path in store.glob("*/*/Code/*.py")})


def schema_files(store: pathlib.Path) -> list:
    return sorted(store.glob("*/*/Schema/*_Metrics_Snapshot_*.sql"))


def pipelines(store: pathlib.Path) -> list:
    found = []
    for path in sorted(store.glob("*/*/Code/*.py")):
        if path.name.startswith("__"):
            continue
        if path.stem.endswith("_Daily"):
            found.append((path, "Daily"))
        elif path.stem.endswith("_Cumulative"):
            found.append((path, "Cumulative"))
    return found


def load_runner(store: pathlib.Path):
    sys.path.insert(0, str(store / "common"))
    import daily_runner  # noqa: E402  -- the store's own runner

    return daily_runner


def render(runner, path: pathlib.Path, zone: str, snapshot: dt.date, cadence: str) -> str:
    """What `SOURCE_ZONE=... SNAPSHOT_DATE=... python common/<cadence>_runner.py <file>` prints."""
    runner.INJECTED.update(SOURCE_ZONE=zone, SNAPSHOT_DATE=str(snapshot), CADENCE=cadence)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        runner.run(str(path))
    return buffer.getvalue()


def rebuild_targets(db: pathlib.Path, store: pathlib.Path) -> None:
    existing = query(
        db, f"SELECT table_name FROM information_schema.tables WHERE table_schema = '{TARGET}'"
    )
    statements = [f'DROP TABLE {TARGET}."{row["table_name"]}";' for row in existing]
    statements += [p.read_text().replace("{TARGET_CATALOG}", TARGET) for p in schema_files(store)]
    duckdb(db, "\n".join(statements))


def actual_values(db: pathlib.Path):
    """Return (values, duplicates, tables, problems) for every metric table."""
    tables = [
        row["table_name"]
        for row in query(
            db,
            f"SELECT table_name FROM information_schema.tables WHERE table_schema = '{TARGET}' "
            "ORDER BY 1",
        )
    ]
    values = collections.defaultdict(dict)
    duplicates, problems, parsed = [], [], {}
    for table in tables:
        match = TABLE_NAME.match(table)
        if not match:
            problems.append(f"{table}: name does not follow {{Entity}}_{{Grain}}_Metrics_Snapshot_{{Cadence}}")
            continue
        parsed[table] = match.groupdict()
        if match["grain"] != "Merchant":
            problems.append(f"{table}: grain {match['grain']} was not requested")
            continue
        rows = query(
            db,
            f'SELECT CAST(SNAPSHOT_DATE AS VARCHAR) AS snapshot_date, merchant_id, metric_name, '
            f'metric_value, SOURCE_ZONE AS zone FROM {TARGET}."{table}"',
        )
        for row in rows:
            key = (dt.date.fromisoformat(row["snapshot_date"]), row["merchant_id"])
            bucket = values[(match["cadence"], row["metric_name"])]
            if key in bucket:
                duplicates.append(f"{table}: {row['metric_name']} {key[0]} merchant {key[1]}")
            bucket[key] = bucket.get(key, 0) + row["metric_value"]
            if not METRIC_NAME.match(row["metric_name"]):
                problems.append(f"{table}: metric name {row['metric_name']} breaks total_{{entity}}_{{verb}}_count")
    return values, duplicates, parsed, problems


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def compare(expected: dict, actual: dict, merchants: dict, limit: int = 3) -> list:
    keys = sorted(set(expected) | set(actual))
    differences = []
    for key in keys:
        want, got = expected.get(key, 0), actual.get(key, 0)
        if want != got:
            differences.append((key, want, got))
    lines = [
        f"{day} {merchants.get(merchant, merchant)}: expected {want}, got {got}"
        for (day, merchant), want, got in differences[:limit]
    ]
    if len(differences) > limit:
        lines.append(f"... and {len(differences) - limit} more")
    return lines if differences else []


def check_story(report: Report, events: list, last_day: dt.date) -> None:
    story = STORY["merchant"]
    mine = [(metric, day) for merchant, metric, day in events if merchant == story["merchant_id"]]
    day_of = lambda day: 7 - (last_day - day).days  # noqa: E731
    problems = []
    for metric, by_day in STORY["expected"]["daily"].items():
        got = collections.Counter(str(day_of(day)) for m, day in mine if m == metric and day <= last_day)
        if dict(got) != by_day:
            problems.append(f"{metric} by day: expected {by_day}, rules give {dict(got)}")
    for metric, total in STORY["expected"]["cumulative_on_day_7"].items():
        got = sum(1 for m, day in mine if m == metric and day <= last_day)
        if got != total:
            problems.append(f"{metric} by day 7: expected {total}, rules give {got}")
    title = (
        f"Story orders: the agreed rules give {STORY['expected']['cumulative_on_day_7']['total_dispatch_meet_count']} met and "
        f"{STORY['expected']['cumulative_on_day_7']['total_dispatch_miss_count']} missed for {story['name']}"
    )
    report.add("fail" if problems else "pass", title, "\n".join(problems))


def run(example: pathlib.Path, days: int, report: Report) -> None:
    store = example / "marketplace_metric_store"
    entities = entity_folders(store)
    new_entities = [e for e in entities if e != BUILT_ENTITY]
    if BUILT_ENTITY not in entities:
        report.add("fail", f"The existing {BUILT_ENTITY} entity is missing from {store}")
        return
    if new_entities and new_entities != [REQUESTED_ENTITY]:
        report.add(
            "fail",
            f"Unexpected entity folders: {', '.join(new_entities)}",
            f"The request asked for {REQUESTED_ENTITY} metrics next to {BUILT_ENTITY}.",
        )
    dispatch_built = REQUESTED_ENTITY in new_entities

    runner = load_runner(store)
    with tempfile.TemporaryDirectory(prefix="acceptance-") as tmp:
        warehouse = pathlib.Path(tmp)
        seeded = subprocess.run(
            [sys.executable, str(example / "seed.py"), "--warehouse", str(warehouse)],
            capture_output=True, text=True, env=DUCKDB_ENV,
        )
        if seeded.returncode != 0:
            report.add("fail", "seed.py could not build a fresh warehouse", seeded.stderr.strip())
            return

        first_zone = True
        for zone in ZONES:
            db = warehouse / f"{zone}.duckdb"
            last_day = end_date(db)
            snapshots = [last_day - dt.timedelta(days=offset) for offset in range(days - 1, -1, -1)]
            merchants = {
                row["merchant_id"]: row["merchant_name"]
                for row in query(db, f"SELECT merchant_id, merchant_name FROM {SOURCE}.merchants")
            }
            events = expected_events(db)
            if first_zone:
                check_story(report, events, last_day)
                first_zone = False
            expected = expected_values(events, snapshots)

            try:
                rebuild_targets(db, store)
                sql = [
                    render(runner, path, zone, snapshot, cadence)
                    for snapshot in snapshots
                    for path, cadence in pipelines(store)
                ]
                duckdb(db, "\n".join(sql))
            except (RuntimeError, SystemExit, Exception) as error:  # noqa: BLE001
                report.add("fail", f"{zone}: the store's DDL or pipelines failed to run", str(error))
                continue

            actual, duplicates, tables, problems = actual_values(db)
            if problems:
                report.add("fail", f"{zone}: naming problems", "\n".join(problems[:5]))
            if duplicates:
                report.add(
                    "fail",
                    f"{zone}: {len(duplicates)} duplicate metric rows",
                    "\n".join(duplicates[:3]),
                )
            wrong_zone = query(
                db,
                " UNION ALL ".join(
                    f'SELECT \'{t}\' AS t, COUNT(*) AS n FROM {TARGET}."{t}" WHERE SOURCE_ZONE <> \'{zone}\''
                    for t in tables
                ) or "SELECT 1 AS t, 0 AS n",
            )
            bad_zone = [row["t"] for row in wrong_zone if row["n"]]
            if bad_zone:
                report.add("fail", f"{zone}: rows labelled with the wrong SOURCE_ZONE", ", ".join(bad_zone))

            checked = [(ORDER_METRICS, BUILT_ENTITY)]
            if dispatch_built:
                checked.append((DISPATCH_METRICS, REQUESTED_ENTITY))
                found = sorted(
                    metric for (cadence, metric) in actual if metric.startswith("total_dispatch_")
                )
                extra = sorted(set(found) - set(DISPATCH_METRICS))
                if extra:
                    report.add("fail", f"{zone}: unexpected Dispatch metrics", ", ".join(extra))
            for metrics, entity in checked:
                for metric in metrics:
                    for cadence in CADENCES:
                        if not actual.get((cadence, metric)) and expected.get((cadence, metric)):
                            report.add("fail", f"{zone}: {metric} ({cadence}) is missing")
                            continue
                        lines = compare(expected.get((cadence, metric), {}), actual.get((cadence, metric), {}), merchants)
                        if lines:
                            report.add("fail", f"{zone}: {metric} ({cadence}) does not match the agreed rules", "\n".join(lines))
                rows = sum(len(actual.get((c, m), {})) for m in metrics for c in CADENCES)
                if all(
                    not compare(expected.get((c, m), {}), actual.get((c, m), {}), merchants)
                    for m in metrics for c in CADENCES
                ):
                    report.add(
                        "pass",
                        f"{zone}: {entity} metrics match the agreed rules ({rows} rows, {days} days, daily and cumulative)",
                    )

    if not dispatch_built:
        report.add("info", f"{REQUESTED_ENTITY} metrics are not built yet, so only {BUILT_ENTITY} metrics were checked")


def write_summary(report: Report, days: int) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    icon = {"pass": "✅", "fail": "❌", "info": "ℹ️"}
    lines = [
        "## Dispatch promise acceptance tests",
        "",
        f"Human-owned checks over the last {days} days in both regions. "
        "Expected values come from the agreed rules, computed independently of the pipelines.",
        "",
        "| | Check |",
        "| --- | --- |",
    ]
    for check in report.checks:
        detail = f"<br>{check['detail'].replace(chr(10), '<br>')}" if check["detail"] else ""
        lines.append(f"| {icon[check['status']]} | {check['title']}{detail} |")
    lines += ["", f"**Result: {'PASS' if report.passed else 'FAIL'}**"]
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=30, help="snapshot dates to check, ending yesterday")
    parser.add_argument("--example", type=pathlib.Path, default=DEFAULT_EXAMPLE, help="example project to test")
    parser.add_argument("--report", type=pathlib.Path, help="also write the results as JSON")
    options = parser.parse_args()

    print(f"Acceptance tests: online-marketplace, last {options.days} days, regions {', '.join(ZONES)}")
    report = Report()
    run(options.example.resolve(), options.days, report)
    print(f"Result: {'PASS' if report.passed else 'FAIL'}")
    write_summary(report, options.days)
    if options.report:
        options.report.parent.mkdir(parents=True, exist_ok=True)
        options.report.write_text(
            json.dumps(
                {
                    "result": "pass" if report.passed else "fail",
                    "days": options.days,
                    "checks": report.checks,
                    "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
                },
                indent=2,
            )
        )
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
