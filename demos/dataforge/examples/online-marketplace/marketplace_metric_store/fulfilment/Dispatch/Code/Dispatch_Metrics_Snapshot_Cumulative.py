"""Dispatch promises through SNAPSHOT_DATE, using globals from cumulative_runner."""

TABLE = f"{TARGET_CATALOG}.Dispatch_Merchant_Metrics_Snapshot_Cumulative"

STATEMENTS = [
    "BEGIN TRANSACTION",
    f"DELETE FROM {TABLE} WHERE SNAPSHOT_DATE = DATE '{SNAPSHOT_DATE}'",
    f"""
INSERT INTO {TABLE}
WITH first_success AS (
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
        , o.cancelled_at
        , s.dispatched_at
    FROM {SOURCE_CATALOG}.orders o
    LEFT JOIN first_success s ON s.order_id = o.order_id
    WHERE o.is_deleted = false
      AND o.placed_at < DATE '{SNAPSHOT_DATE}' + INTERVAL '1 day'
)
, eligible_promises AS (
    SELECT
        order_id
        , merchant_id
        , deadline_at
        , dispatched_at
    FROM promises
    WHERE cancelled_at IS NULL OR cancelled_at >= deadline_at
)
, dispatch_metrics AS (
    SELECT
        merchant_id
        , COUNT(
            DISTINCT CASE
                WHEN CAST(dispatched_at AS DATE) <= DATE '{SNAPSHOT_DATE}'
                  AND dispatched_at <= deadline_at
                THEN order_id
                ELSE NULL
            END
        ) AS total_dispatch_meet_count
        , COUNT(
            DISTINCT CASE
                WHEN CAST(deadline_at AS DATE) <= DATE '{SNAPSHOT_DATE}'
                  AND (dispatched_at IS NULL OR dispatched_at > deadline_at)
                THEN order_id
                ELSE NULL
            END
        ) AS total_dispatch_miss_count
    FROM eligible_promises
    GROUP BY ALL
)
, combined_metrics AS (
    SELECT
        merchant_id
        , 'total_dispatch_meet_count' AS metric_name
        , total_dispatch_meet_count AS metric_value
    FROM dispatch_metrics
    UNION ALL
    SELECT
        merchant_id
        , 'total_dispatch_miss_count' AS metric_name
        , total_dispatch_miss_count AS metric_value
    FROM dispatch_metrics
)
SELECT
    DATE '{SNAPSHOT_DATE}' AS SNAPSHOT_DATE
    , merchant_id
    , metric_name
    , metric_value
    , now() AS LOAD_TIMESTAMP
    , '{SOURCE_ZONE}' AS SOURCE_ZONE
FROM combined_metrics
""",
    "COMMIT",
]
