-- Returns zero mismatches after loading both cadences for the test window.
-- Expected outcomes use correlated existence checks, independently of pipeline CTEs.
WITH successful_attempts AS (
    SELECT order_id, attempted_at
    FROM {SOURCE_CATALOG}.dispatch_attempts
    WHERE is_deleted = false AND outcome = 'dispatched'
)
, eligible_orders AS (
    SELECT
        o.order_id
        , o.merchant_id
        , o.placed_at + INTERVAL '48 hours' AS deadline_at
        , (
            SELECT MIN(a.attempted_at)
            FROM successful_attempts a
            WHERE a.order_id = o.order_id
        ) AS dispatched_at
    FROM {SOURCE_CATALOG}.orders o
    WHERE o.is_deleted = false
      AND (
          o.cancelled_at IS NULL
          OR o.cancelled_at > o.placed_at + INTERVAL '48 hours'
          OR EXISTS (
              SELECT 1
              FROM successful_attempts a
              WHERE a.order_id = o.order_id
                AND a.attempted_at <= o.cancelled_at
          )
      )
)
, events AS (
    SELECT
        merchant_id
        , CASE
            WHEN dispatched_at <= deadline_at THEN CAST(dispatched_at AS DATE)
            ELSE CAST(deadline_at AS DATE)
          END AS event_date
        , CASE
            WHEN dispatched_at <= deadline_at THEN 'total_dispatch_meet_count'
            ELSE 'total_dispatch_miss_count'
          END AS metric_name
    FROM eligible_orders
)
, snapshots AS (
    SELECT CAST(day AS DATE) AS snapshot_date
    FROM generate_series(DATE '{START_DATE}', DATE '{END_DATE}', INTERVAL '1 day') dates(day)
)
, expected AS (
    SELECT
        'Daily' AS cadence
        , s.snapshot_date
        , e.merchant_id
        , e.metric_name
        , COUNT(*) AS metric_value
    FROM snapshots s
    INNER JOIN events e ON e.event_date = s.snapshot_date
    GROUP BY ALL
    UNION ALL
    SELECT
        'Cumulative' AS cadence
        , s.snapshot_date
        , e.merchant_id
        , e.metric_name
        , COUNT(*) AS metric_value
    FROM snapshots s
    INNER JOIN events e ON e.event_date <= s.snapshot_date
    GROUP BY ALL
)
, actual AS (
    SELECT 'Daily' AS cadence, SNAPSHOT_DATE, merchant_id, metric_name, metric_value
    FROM {TARGET_CATALOG}.Dispatch_Merchant_Metrics_Snapshot_Daily
    WHERE SNAPSHOT_DATE BETWEEN DATE '{START_DATE}' AND DATE '{END_DATE}'
    UNION ALL
    SELECT 'Cumulative' AS cadence, SNAPSHOT_DATE, merchant_id, metric_name, metric_value
    FROM {TARGET_CATALOG}.Dispatch_Merchant_Metrics_Snapshot_Cumulative
    WHERE SNAPSHOT_DATE BETWEEN DATE '{START_DATE}' AND DATE '{END_DATE}'
)
SELECT COUNT(*) AS mismatches
FROM expected e
FULL OUTER JOIN actual a
    ON a.cadence = e.cadence
    AND a.SNAPSHOT_DATE = e.snapshot_date
    AND a.merchant_id = e.merchant_id
    AND a.metric_name = e.metric_name
WHERE COALESCE(a.metric_value, 0) != COALESCE(e.metric_value, 0);
