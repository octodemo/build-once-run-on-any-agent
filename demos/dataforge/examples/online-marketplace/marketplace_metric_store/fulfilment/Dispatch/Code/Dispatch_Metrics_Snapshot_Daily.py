"""Daily dispatch promise metrics by merchant."""

GRAIN_KEYS = {
    "Merchant": ["merchant_id"],
}

METRIC_RULES = {
    "total_dispatch_meet_count": (
        "(first_successful_attempt_at <= deadline_at) "
        "AND (cancelled_at IS NULL OR cancelled_at >= deadline_at)",
        "first_successful_attempt_at",
    ),
    "total_dispatch_miss_count": (
        "(first_successful_attempt_at IS NULL OR first_successful_attempt_at > deadline_at) "
        "AND (cancelled_at IS NULL OR cancelled_at >= deadline_at)",
        "deadline_at",
    ),
}

STATEMENTS = []

for grain, keys in GRAIN_KEYS.items():
    key_list = ", ".join(f"p.{key}" for key in keys)
    for metric, (condition, event_date) in METRIC_RULES.items():
        STATEMENTS.append(
            f"""
BEGIN TRANSACTION;
DELETE FROM {TARGET_CATALOG}.Dispatch_{grain}_Metrics_Snapshot_Daily
WHERE SNAPSHOT_DATE = DATE '{SNAPSHOT_DATE}'
  AND metric_name = '{metric}'
  AND SOURCE_ZONE = '{SOURCE_ZONE}';
INSERT INTO {TARGET_CATALOG}.Dispatch_{grain}_Metrics_Snapshot_Daily
WITH first_successful_dispatch AS (
    SELECT
        order_id
        , MIN(attempted_at) AS first_successful_attempt_at
    FROM {SOURCE_CATALOG}.dispatch_attempts
    WHERE is_deleted = false
      AND outcome = 'dispatched'
      AND attempted_at < TIMESTAMP '{SNAPSHOT_DATE}' + INTERVAL 1 DAY
    GROUP BY order_id
),
promise_orders AS (
    SELECT
        o.order_id
        , o.merchant_id
        , o.placed_at
        , o.placed_at + INTERVAL 48 HOUR AS deadline_at
        , o.cancelled_at
        , d.first_successful_attempt_at
    FROM {SOURCE_CATALOG}.orders o
    LEFT JOIN first_successful_dispatch d
        ON o.order_id = d.order_id
    WHERE o.is_deleted = false
      AND o.order_id IS NOT NULL
      AND o.merchant_id IS NOT NULL
      AND o.placed_at IS NOT NULL
      AND o.placed_at >= TIMESTAMP '{SNAPSHOT_DATE}' - INTERVAL 48 HOUR
      AND o.placed_at < TIMESTAMP '{SNAPSHOT_DATE}' + INTERVAL 1 DAY
)
SELECT
    DATE '{SNAPSHOT_DATE}' AS SNAPSHOT_DATE
    , {key_list}
    , '{metric}' AS metric_name
    , COUNT(DISTINCT CASE
        WHEN {condition}
         AND CAST({event_date} AS DATE) = DATE '{SNAPSHOT_DATE}'
        THEN p.order_id
        ELSE NULL
      END) AS metric_value
    , now() AS LOAD_TIMESTAMP
    , '{SOURCE_ZONE}' AS SOURCE_ZONE
FROM promise_orders p
GROUP BY {key_list}
;
COMMIT
"""
        )
