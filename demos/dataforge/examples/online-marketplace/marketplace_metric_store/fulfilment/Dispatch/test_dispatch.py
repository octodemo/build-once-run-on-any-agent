"""Run with python3 -m unittest discover -s marketplace_metric_store/fulfilment/Dispatch.

Uses only the standard library and DuckDB CLI. Warehouse validation operates on
temporary copies, never the demo's region files.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
CADENCES = ("Daily", "Cumulative")
METRICS = ("total_dispatch_meet_count", "total_dispatch_miss_count")
SOURCE = "demo_gold_commerce"
TARGET = "demo_gold_marketplace_metric_store"


def query(database: Path, sql: str) -> list[dict]:
    result = subprocess.run(
        ["duckdb", str(database), "-bail", "-json"],
        input=sql, text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else []


def schemas() -> str:
    return f"CREATE SCHEMA IF NOT EXISTS {TARGET};\n" + "\n".join(
        (HERE / f"Schema/Dispatch_Merchant_Metrics_Snapshot_{cadence}.sql")
        .read_text().format(TARGET_CATALOG=TARGET)
        for cadence in CADENCES
    )


def pipeline(day: str, cadence: str, zone: str) -> str:
    namespace = runpy.run_path(
        str(HERE / f"Code/Dispatch_Metrics_Snapshot_{cadence}.py"),
        init_globals={
            "SOURCE_CATALOG": SOURCE, "TARGET_CATALOG": TARGET,
            "SNAPSHOT_DATE": day, "SOURCE_ZONE": zone,
        },
    )
    return ";\n".join(namespace["STATEMENTS"]) + ";\n"


class DispatchTests(unittest.TestCase):
    def test_outcomes_boundaries_and_historical_snapshots(self):
        setup = [
            f"CREATE SCHEMA {SOURCE}",
            f"CREATE TABLE {SOURCE}.orders (order_id BIGINT, merchant_id BIGINT, "
            "placed_at TIMESTAMP, cancelled_at TIMESTAMP, is_deleted BOOLEAN)",
            f"CREATE TABLE {SOURCE}.dispatch_attempts (order_id BIGINT, "
            "attempted_at TIMESTAMP, outcome VARCHAR, is_deleted BOOLEAN)",
        ]

        def literal(value):
            return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"

        def order(number, attempts=(), cancelled=None, deleted=False,
                  placed="2026-01-01 10:00:00", merchant=1):
            setup.append(
                f"INSERT INTO {SOURCE}.orders VALUES ({number}, {merchant}, "
                f"{literal(placed)}, {literal(cancelled)}, {str(deleted).lower()})"
            )
            for when, outcome, removed in attempts:
                setup.append(
                    f"INSERT INTO {SOURCE}.dispatch_attempts VALUES ({number}, "
                    f"{literal(when)}, {literal(outcome)}, {str(removed).lower()})"
                )

        order(1, [("2026-01-01 12:00", "failed", False),
                  ("2026-01-02 09:00", "dispatched", False)])  # retry then success
        order(2, [("2026-01-03 10:00", "dispatched", False)])  # exactly 48 hours
        order(3, [("2026-01-03 10:00:01", "dispatched", False)])  # one second late
        order(4, placed="2026-01-06 22:00:00")  # not overdue in the test window
        order(5, cancelled="2026-01-01 11:00:00")
        order(6, cancelled="2026-01-04 10:00:00")  # late cancellation keeps miss
        order(7, [("2026-01-02 09:00", "dispatched", False)], deleted=True)
        order(8, [("2026-01-02 09:00", "dispatched", True),
                  ("2026-01-04 10:00", "dispatched", False)])  # deleted success
        order(9, [("2026-01-02 11:00", "dispatched", False),
                  ("2026-01-03 11:00", "dispatched", False)])  # first success only
        order(10, [("2026-01-02 09:00", "dispatched", False)],
              cancelled="2026-01-01 11:00:00")  # cancelled before dispatch
        order(11, [("2026-01-02 09:00", "dispatched", False)],
              cancelled="2026-01-02 10:00:00")  # cancellation after success
        order(12, cancelled="2026-01-03 10:00:00")  # cancel exactly at deadline
        order(13, [("2026-01-02 09:00", "failed", False)])  # failure is not success
        order(14, [("2026-01-02 09:00", "dispatched", True)])
        order(15, [("2026-01-02 09:00", "dispatched", False)],
              cancelled="2026-01-02 09:00:00")  # success wins a tie
        order(20, [("2026-01-03 23:59", "dispatched", False)],
              placed="2026-01-01 23:59:00", merchant=2)
        order(21, [("2026-01-04 00:00", "dispatched", False)],
              placed="2026-01-01 23:59:00", merchant=2)
        # Hand-labelled outcomes, deliberately independent of the SQL implementation.
        events = [
            ("2026-01-02", 1, METRICS[0]),
            ("2026-01-03", 1, METRICS[0]),
            ("2026-01-02", 1, METRICS[0]),
            ("2026-01-02", 1, METRICS[0]),
            ("2026-01-02", 1, METRICS[0]),
            *([("2026-01-03", 1, METRICS[1])] * 5),
            ("2026-01-03", 2, METRICS[0]),
            ("2026-01-03", 2, METRICS[1]),
        ]
        days = [f"2026-01-{day:02d}" for day in range(1, 7)]
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "fixture.duckdb"
            query(database, ";\n".join(setup) + ";\n" + schemas())
            for day in reversed(days):
                for cadence in CADENCES:
                    query(database, pipeline(day, cadence, "fixture"))
                    rows = query(database, f"""
                        SELECT merchant_id, metric_name, metric_value
                        FROM {TARGET}.Dispatch_Merchant_Metrics_Snapshot_{cadence}
                        WHERE SNAPSHOT_DATE = DATE '{day}'
                    """)
                    self.assertEqual(len(rows), 4)
                    for row in rows:
                        expected = sum(
                            merchant == row["merchant_id"] and metric == row["metric_name"]
                            and (event_day == day if cadence == "Daily" else event_day <= day)
                            for event_day, merchant, metric in events
                        )
                        self.assertEqual(row["metric_value"], expected, (day, cadence, row))
            before = query(database, f"SELECT SUM(metric_value) AS total FROM {TARGET}."
                           "Dispatch_Merchant_Metrics_Snapshot_Daily")
            for _ in range(2):
                query(database, pipeline(days[2], "Daily", "fixture"))
            self.assertEqual(before, query(database, f"SELECT SUM(metric_value) AS total FROM "
                                           f"{TARGET}.Dispatch_Merchant_Metrics_Snapshot_Daily"))
            # A failed reload must roll back the deletion, preserving the old partition.
            bad_sql = pipeline(days[2], "Daily", "fixture").replace(
                f"FROM {SOURCE}.orders", f"FROM {SOURCE}.missing_orders"
            )
            with self.assertRaises(subprocess.CalledProcessError):
                query(database, bad_sql)
            self.assertEqual(before, query(database, f"SELECT SUM(metric_value) AS total FROM "
                                           f"{TARGET}.Dispatch_Merchant_Metrics_Snapshot_Daily"))

    def test_both_regions_reconcile_and_rerun_through_shared_runners(self):
        for zone in ("east", "west"):
            source = PROJECT / f"warehouse/{zone}.duckdb"
            with self.subTest(zone=zone), tempfile.TemporaryDirectory() as temp:
                database = Path(temp) / f"{zone}.duckdb"
                shutil.copyfile(source, database)
                bounds = query(database, f"""
                    SELECT MIN(CAST(placed_at AS DATE)) AS first_day,
                           MAX(CAST(placed_at AS DATE)) AS last_day FROM {SOURCE}.orders
                """)[0]
                start = dt.date.fromisoformat(bounds["first_day"])
                end = dt.date.fromisoformat(bounds["last_day"])
                sql = schemas()
                for offset in range((end - start).days + 1):
                    day = str(start + dt.timedelta(days=offset))
                    for cadence in CADENCES:
                        sql += pipeline(day, cadence, zone)
                query(database, sql)
                reconciliation = (HERE / "Code/__dispatch_test.sql").read_text().format(
                    SOURCE_CATALOG=SOURCE, TARGET_CATALOG=TARGET,
                    START_DATE=start, END_DATE=end,
                )
                self.assertEqual(query(database, reconciliation), [{"mismatches": 0}])
                for cadence in CADENCES:
                    table = f"{TARGET}.Dispatch_Merchant_Metrics_Snapshot_{cadence}"
                    before = query(database, f"SELECT COUNT(*) AS rows, SUM(metric_value) AS "
                                   f"total FROM {table}")
                    runner = PROJECT / f"marketplace_metric_store/common/{cadence.lower()}_runner.py"
                    rendered = subprocess.check_output(
                        [sys.executable, str(runner),
                         str(HERE / f"Code/Dispatch_Metrics_Snapshot_{cadence}.py")],
                        env={**os.environ, "SOURCE_ZONE": zone, "SNAPSHOT_DATE": str(end),
                             "ENGINE": "duckdb", "PYTHONDONTWRITEBYTECODE": "1"},
                        text=True,
                    )
                    query(database, rendered)
                    self.assertEqual(before, query(database, f"SELECT COUNT(*) AS rows, "
                                                   f"SUM(metric_value) AS total FROM {table}"))
                    health = query(database, f"""
                        SELECT COUNT(DISTINCT SNAPSHOT_DATE) AS days,
                               COUNT(*) FILTER (WHERE SOURCE_ZONE != '{zone}' OR
                                   metric_value < 0 OR metric_value IS NULL OR
                                   merchant_id IS NULL) AS invalid
                        FROM {table}
                    """)[0]
                    self.assertEqual(health, {"days": (end - start).days + 1, "invalid": 0})
                    completeness = query(database, f"""
                        WITH dates AS (
                            SELECT CAST(day AS DATE) AS snapshot_date
                            FROM generate_series(DATE '{start}', DATE '{end}',
                                                 INTERVAL '1 day') days(day)
                        )
                        SELECT COUNT(*) AS missing_rows
                        FROM dates d
                        INNER JOIN {SOURCE}.orders o
                            ON CAST(o.placed_at AS DATE) <= d.snapshot_date
                        CROSS JOIN (VALUES ('{METRICS[0]}'), ('{METRICS[1]}')) m(metric_name)
                        LEFT JOIN {table} t ON t.SNAPSHOT_DATE = d.snapshot_date
                            AND t.merchant_id = o.merchant_id AND t.metric_name = m.metric_name
                        WHERE o.is_deleted = false AND t.merchant_id IS NULL
                    """)
                    self.assertEqual(completeness, [{"missing_rows": 0}])


if __name__ == "__main__":
    unittest.main()
