"""Run with python3 -m unittest discover -s marketplace_metric_store/fulfilment/Dispatch/Code.

Warehouse reconciliation uses disposable copies, never the deployed zone files.
Only aggregate validation results leave DuckDB.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

CODE = pathlib.Path(__file__).resolve().parent
PROJECT = CODE.parents[3]
SOURCE = "demo_gold_commerce"
TARGET = "demo_gold_marketplace_metric_store"
CADENCES = ("Daily", "Cumulative")


def query(database: pathlib.Path | str, sql: str) -> list[dict]:
    result = subprocess.run(
        ["duckdb", str(database), "-bail", "-json"],
        input=sql,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else []


def schema_sql() -> str:
    return "\n".join(
        (CODE.parent / "Schema" / f"Dispatch_Merchant_Metrics_Snapshot_{cadence}.sql")
        .read_text()
        .format(TARGET_CATALOG=TARGET)
        for cadence in CADENCES
    )


def pipeline_sql(day: dt.date, cadence: str, zone: str) -> str:
    path = CODE / f"Dispatch_Metrics_Snapshot_{cadence}.py"
    namespace = {
        "SOURCE_CATALOG": SOURCE,
        "TARGET_CATALOG": TARGET,
        "SOURCE_ZONE": zone,
        "SNAPSHOT_DATE": str(day),
    }
    exec(compile(path.read_text(), str(path), "exec"), namespace)
    return ";\n".join(namespace["STATEMENTS"]) + ";\n"


def backfill_sql(start: dt.date, end: dt.date, zone: str) -> str:
    return "".join(
        pipeline_sql(start + dt.timedelta(days=offset), cadence, zone)
        for offset in range((end - start).days + 1)
        for cadence in CADENCES
    )


class DispatchTests(unittest.TestCase):
    def test_deadlines_retries_cancellations_and_deleted_rows(self) -> None:
        # All promises start Jan 1 at 09:00 and expire Jan 3 at 09:00.
        setup = f"""
CREATE SCHEMA {SOURCE};
CREATE SCHEMA {TARGET};
CREATE TABLE {SOURCE}.orders AS
SELECT
    id AS order_id
    , 1::BIGINT AS merchant_id
    , TIMESTAMP '2026-01-01 09:00:00' AS placed_at
    , CASE
        WHEN id = 4 THEN TIMESTAMP '2026-01-03 08:59:59'
        WHEN id = 5 THEN TIMESTAMP '2026-01-03 09:00:01'
        WHEN id = 6 THEN TIMESTAMP '2026-01-03 09:00:00'
      END AS cancelled_at
    , id = 7 AS is_deleted
FROM range(1, 13) AS orders(id);
CREATE TABLE {SOURCE}.dispatch_attempts (
    order_id BIGINT, attempted_at TIMESTAMP, outcome VARCHAR, is_deleted BOOLEAN
);
INSERT INTO {SOURCE}.dispatch_attempts VALUES
    (1, '2026-01-02 09:00:00', 'dispatched', false),
    (1, '2026-01-01 10:00:00', 'failed', false),
    (1, '2026-01-03 08:00:00', 'dispatched', false),
    (2, '2026-01-03 09:00:00', 'dispatched', false),
    (3, '2026-01-03 09:00:01', 'dispatched', false),
    (4, '2026-01-02 09:00:00', 'dispatched', false),
    (5, '2026-01-04 09:00:00', 'dispatched', false),
    (7, '2026-01-02 09:00:00', 'dispatched', false),
    (8, '2026-01-02 09:00:00', 'dispatched', true),
    (8, '2026-01-04 09:00:00', 'dispatched', false),
    (9, '2026-01-01 10:00:00', 'failed', false),
    (9, '2026-01-02 09:00:00', 'dispatched', false),
    (10, '2026-01-02 08:00:00', 'failed', false),
    (11, '2026-01-02 23:59:59', 'dispatched', false),
    (12, '2026-01-03 00:00:00', 'dispatched', false);
"""
        sql = setup + schema_sql() + backfill_sql(
            dt.date(2026, 1, 1), dt.date(2026, 1, 4), "test"
        )
        sql += f"""
SELECT CAST(SNAPSHOT_DATE AS VARCHAR) AS day, metric_name, metric_value
FROM {TARGET}.Dispatch_Merchant_Metrics_Snapshot_Daily
ORDER BY SNAPSHOT_DATE, metric_name;
"""
        rows = query(":memory:", sql)
        expected = [(0, 0), (3, 0), (2, 5), (0, 0)]
        for index, (meet, miss) in enumerate(expected):
            with self.subTest(day=index + 1):
                self.assertEqual(
                    [row["metric_value"] for row in rows[index * 2 : index * 2 + 2]],
                    [meet, miss],
                )

    def test_warehouse_history_reconciliation_and_reruns(self) -> None:
        for zone in ("east", "west"):
            with self.subTest(zone=zone), tempfile.TemporaryDirectory() as directory:
                database = pathlib.Path(directory) / f"{zone}.duckdb"
                shutil.copy2(PROJECT / "warehouse" / f"{zone}.duckdb", database)
                bounds = query(
                    database,
                    f"SELECT MIN(CAST(placed_at AS DATE)) AS start_date, "
                    f"MAX(CAST(placed_at AS DATE)) AS end_date FROM {SOURCE}.orders;",
                )[0]
                start = dt.date.fromisoformat(bounds["start_date"])
                end = dt.date.fromisoformat(bounds["end_date"])
                query(database, schema_sql() + backfill_sql(start, end, zone))
                validation = (CODE / "__dispatch_test.sql").read_text().format(
                    SOURCE_CATALOG=SOURCE,
                    TARGET_CATALOG=TARGET,
                    SOURCE_ZONE=zone,
                    SNAPSHOT_DATE=str(end),
                )
                results = query(database, validation)
                self.assertTrue(results)
                for result in results:
                    self.assertEqual(result["failures"], 0, result["check_name"])
                before = self.snapshot_counts(database)
                for cadence in CADENCES:
                    runner = PROJECT / "marketplace_metric_store" / "common" / (
                        f"{cadence.lower()}_runner.py"
                    )
                    compiled = subprocess.run(
                        [sys.executable, str(runner), str(
                            CODE / f"Dispatch_Metrics_Snapshot_{cadence}.py"
                        )],
                        env={
                            **os.environ,
                            "ENGINE": "duckdb",
                            "SOURCE_ZONE": zone,
                            "SNAPSHOT_DATE": str(end),
                        },
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    query(database, compiled.stdout)
                self.assertEqual(self.snapshot_counts(database), before)
                for result in query(database, validation):
                    self.assertEqual(result["failures"], 0, result["check_name"])
                self.assert_schema(database)
                self.assert_transaction_rollback(database, end, zone)

    def snapshot_counts(self, database: pathlib.Path) -> list[dict]:
        parts = [
            f"SELECT '{cadence}' AS cadence, SNAPSHOT_DATE, COUNT(*) AS rows, "
            f"SUM(metric_value) AS value FROM {TARGET}."
            f"Dispatch_Merchant_Metrics_Snapshot_{cadence} GROUP BY ALL"
            for cadence in CADENCES
        ]
        return query(database, " UNION ALL ".join(parts) + " ORDER BY cadence, SNAPSHOT_DATE;")

    def assert_schema(self, database: pathlib.Path) -> None:
        expected = [
            ("SNAPSHOT_DATE", "DATE"),
            ("merchant_id", "BIGINT"),
            ("metric_name", "VARCHAR"),
            ("metric_value", "BIGINT"),
            ("LOAD_TIMESTAMP", "TIMESTAMP"),
            ("SOURCE_ZONE", "VARCHAR"),
        ]
        for cadence in CADENCES:
            columns = query(
                database,
                f"DESCRIBE {TARGET}.Dispatch_Merchant_Metrics_Snapshot_{cadence};",
            )
            self.assertEqual(
                [(column["column_name"], column["column_type"]) for column in columns],
                expected,
            )
            self.assertTrue(all(column["null"] == "NO" for column in columns))

    def assert_transaction_rollback(
        self, database: pathlib.Path, day: dt.date, zone: str
    ) -> None:
        before = self.snapshot_counts(database)
        path = CODE / "Dispatch_Metrics_Snapshot_Daily.py"
        namespace = dict(
            SOURCE_CATALOG="missing_source",
            TARGET_CATALOG=TARGET,
            SOURCE_ZONE=zone,
            SNAPSHOT_DATE=str(day),
        )
        exec(compile(path.read_text(), str(path), "exec"), namespace)
        with self.assertRaises(subprocess.CalledProcessError):
            query(database, ";\n".join(namespace["STATEMENTS"]) + ";")
        self.assertEqual(self.snapshot_counts(database), before)


if __name__ == "__main__":
    unittest.main()
