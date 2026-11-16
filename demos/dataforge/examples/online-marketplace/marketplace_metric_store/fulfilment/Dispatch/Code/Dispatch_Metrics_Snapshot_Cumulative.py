"""Dispatch promise outcomes through SNAPSHOT_DATE, by merchant.

The shared cumulative runner injects the date, zone, and catalog globals.
Recomputes from source events rather than reading earlier metric snapshots.
"""

STATEMENTS = [
    "BEGIN TRANSACTION",
    f"""
DELETE FROM {TARGET_CATALOG}.Dispatch_Merchant_Metrics_Snapshot_Cumulative
WHERE SNAPSHOT_DATE = DATE '{SNAPSHOT_DATE}'
""",
    f"""
INSERT INTO {TARGET_CATALOG}.Dispatch_Merchant_Metrics_Snapshot_Cumulative
WITH first_dispatch AS (
    SELECT
        order_id
        , MIN(attempted_at) AS dispatched_at
    FROM {SOURCE_CATALOG}.dispatch_attempts
    WHERE is_deleted = false
      AND outcome = 'dispatched'
      AND attempted_at < DATE '{SNAPSHOT_DATE}' + INTERVAL '1 day'
    GROUP BY ALL
)
, promises AS (
    SELECT
        o.order_id
        , o.merchant_id
        , o.placed_at + INTERVAL '48 hours' AS deadline_at
        , d.dispatched_at
        , (
            o.cancelled_at IS NULL
            OR o.cancelled_at > o.placed_at + INTERVAL '48 hours'
            OR (d.dispatched_at IS NOT NULL AND d.dispatched_at <= o.cancelled_at)
        ) AS is_eligible
    FROM {SOURCE_CATALOG}.orders o
    LEFT JOIN first_dispatch d ON d.order_id = o.order_id
    WHERE o.is_deleted = false
      AND o.placed_at < DATE '{SNAPSHOT_DATE}' + INTERVAL '1 day'
)
, dispatch_metrics AS (
    SELECT
        merchant_id
        , COUNT(
            DISTINCT CASE
                WHEN is_eligible
                  AND dispatched_at <= deadline_at
                  AND CAST(dispatched_at AS DATE) <= DATE '{SNAPSHOT_DATE}' THEN order_id
                ELSE NULL
            END
        ) AS total_dispatch_meet_count
        , COUNT(
            DISTINCT CASE
                WHEN is_eligible
                  AND (dispatched_at IS NULL OR dispatched_at > deadline_at)
                  AND CAST(deadline_at AS DATE) <= DATE '{SNAPSHOT_DATE}' THEN order_id
                ELSE NULL
            END
        ) AS total_dispatch_miss_count
    FROM promises
    GROUP BY ALL
)
SELECT
    DATE '{SNAPSHOT_DATE}' AS SNAPSHOT_DATE
    , merchant_id
    , metric_name
    , metric_value
    , now() AS LOAD_TIMESTAMP
    , '{SOURCE_ZONE}' AS SOURCE_ZONE
FROM dispatch_metrics
CROSS JOIN LATERAL (
    VALUES
        ('total_dispatch_meet_count', total_dispatch_meet_count)
        , ('total_dispatch_miss_count', total_dispatch_miss_count)
) AS metrics(metric_name, metric_value)
""",
    "COMMIT",
]
