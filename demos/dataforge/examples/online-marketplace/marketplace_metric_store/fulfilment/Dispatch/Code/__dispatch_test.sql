-- Independent event-based reconciliation through the requested snapshot.
-- Returns aggregate failure counts only, never raw source records.
WITH snapshots AS (
    SELECT CAST(day AS DATE) AS snapshot_date
    FROM generate_series(
        (SELECT MIN(CAST(placed_at AS DATE)) FROM {SOURCE_CATALOG}.orders)
        , DATE '{SNAPSHOT_DATE}'
        , INTERVAL '1 day'
    ) AS dates(day)
)
, eligible_orders AS (
    SELECT
        order_id
        , merchant_id
        , placed_at
        , placed_at + INTERVAL '48 hours' AS deadline_at
    FROM {SOURCE_CATALOG}.orders
    WHERE is_deleted = false
      AND (cancelled_at IS NULL OR cancelled_at >= placed_at + INTERVAL '48 hours')
)
, promise_events AS (
    SELECT DISTINCT
        o.order_id
        , CAST(a.attempted_at AS DATE) AS event_date
        , 'total_dispatch_meet_count' AS metric_name
    FROM eligible_orders o
    JOIN {SOURCE_CATALOG}.dispatch_attempts a ON a.order_id = o.order_id
    WHERE a.is_deleted = false
      AND a.outcome = 'dispatched'
      AND a.attempted_at <= o.deadline_at
      AND NOT EXISTS (
          SELECT 1
          FROM {SOURCE_CATALOG}.dispatch_attempts earlier
          WHERE earlier.order_id = a.order_id
            AND earlier.is_deleted = false
            AND earlier.outcome = 'dispatched'
            AND earlier.attempted_at < a.attempted_at
      )
    UNION ALL
    SELECT
        o.order_id
        , CAST(o.deadline_at AS DATE) AS event_date
        , 'total_dispatch_miss_count' AS metric_name
    FROM eligible_orders o
    WHERE NOT EXISTS (
        SELECT 1
        FROM {SOURCE_CATALOG}.dispatch_attempts a
        WHERE a.order_id = o.order_id
          AND a.is_deleted = false
          AND a.outcome = 'dispatched'
          AND a.attempted_at <= o.deadline_at
    )
)
, expected AS (
    SELECT
        s.snapshot_date
        , o.merchant_id
        , c.cadence
        , m.metric_name
        , COUNT(DISTINCT e.order_id) AS metric_value
    FROM snapshots s
    JOIN eligible_orders o ON o.placed_at < s.snapshot_date + INTERVAL '1 day'
    CROSS JOIN (VALUES ('Daily'), ('Cumulative')) c(cadence)
    CROSS JOIN (VALUES ('total_dispatch_meet_count'), ('total_dispatch_miss_count')) m(metric_name)
    LEFT JOIN promise_events e ON e.order_id = o.order_id
        AND e.metric_name = m.metric_name
        AND e.event_date <= s.snapshot_date
        AND (c.cadence = 'Cumulative' OR e.event_date = s.snapshot_date)
    GROUP BY ALL
)
, actual AS (
    SELECT
        SNAPSHOT_DATE
        , merchant_id
        , metric_name
        , metric_value
        , SOURCE_ZONE
        , LOAD_TIMESTAMP
        , 'Daily' AS cadence
    FROM {TARGET_CATALOG}.Dispatch_Merchant_Metrics_Snapshot_Daily
    WHERE SNAPSHOT_DATE BETWEEN (SELECT MIN(snapshot_date) FROM snapshots) AND DATE '{SNAPSHOT_DATE}'
    UNION ALL
    SELECT
        SNAPSHOT_DATE
        , merchant_id
        , metric_name
        , metric_value
        , SOURCE_ZONE
        , LOAD_TIMESTAMP
        , 'Cumulative' AS cadence
    FROM {TARGET_CATALOG}.Dispatch_Merchant_Metrics_Snapshot_Cumulative
    WHERE SNAPSHOT_DATE BETWEEN (SELECT MIN(snapshot_date) FROM snapshots) AND DATE '{SNAPSHOT_DATE}'
)
, duplicates AS (
    SELECT SNAPSHOT_DATE, merchant_id, metric_name, cadence
    FROM actual
    GROUP BY ALL
    HAVING COUNT(*) != 1
)
SELECT 'source_target_reconciliation' AS check_name, COUNT(*) AS failures
FROM expected e
FULL OUTER JOIN actual a USING (snapshot_date, merchant_id, metric_name, cadence)
WHERE e.metric_value IS DISTINCT FROM a.metric_value
UNION ALL
SELECT 'source_target_row_count', ABS((SELECT COUNT(*) FROM expected) - COUNT(*))
FROM actual
UNION ALL
SELECT 'grain_uniqueness', COUNT(*) FROM duplicates
UNION ALL
SELECT 'nulls_negative_values_and_zone', COUNT(*)
FROM actual
WHERE SNAPSHOT_DATE IS NULL OR merchant_id IS NULL OR metric_name IS NULL
   OR metric_value IS NULL OR metric_value < 0 OR LOAD_TIMESTAMP IS NULL
   OR SOURCE_ZONE IS DISTINCT FROM '{SOURCE_ZONE}'
UNION ALL
SELECT 'date_coverage', COUNT(*)
FROM snapshots s
CROSS JOIN (VALUES ('Daily'), ('Cumulative')) c(cadence)
WHERE NOT EXISTS (
    SELECT 1 FROM actual a
    WHERE a.SNAPSHOT_DATE = s.snapshot_date AND a.cadence = c.cadence
)
UNION ALL
SELECT 'daily_cumulative_consistency', COUNT(*)
FROM actual cumulative
WHERE cumulative.cadence = 'Cumulative'
  AND cumulative.metric_value != (
      SELECT COALESCE(SUM(daily.metric_value), 0)
      FROM actual daily
      WHERE daily.cadence = 'Daily'
        AND daily.merchant_id = cumulative.merchant_id
        AND daily.metric_name = cumulative.metric_name
        AND daily.SNAPSHOT_DATE <= cumulative.SNAPSHOT_DATE
);
