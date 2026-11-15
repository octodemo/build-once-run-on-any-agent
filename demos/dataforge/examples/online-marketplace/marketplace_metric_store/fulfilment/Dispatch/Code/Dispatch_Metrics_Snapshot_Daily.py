"""Dispatch promise metrics for the daily snapshot.

Each order contributes one event: a meet on its first on-time dispatch date,
or a miss on the date its 48-hour deadline expires.

Globals are injected by common/daily_runner.py.
"""

GRAIN_KEYS = {
    "Merchant": ["merchant_id"],
}

STATEMENTS = []

for grain, keys in GRAIN_KEYS.items():
    key_list = ", ".join(keys)
    target_table = f"{TARGET_CATALOG}.Dispatch_{grain}_Metrics_Snapshot_Daily"
    STATEMENTS.append(
        f"""
BEGIN TRANSACTION;

DELETE FROM {target_table}
WHERE SNAPSHOT_DATE = DATE '{SNAPSHOT_DATE}';

INSERT INTO {target_table} (
    SNAPSHOT_DATE,
    {key_list},
    metric_name,
    metric_value,
    LOAD_TIMESTAMP,
    SOURCE_ZONE
)
WITH first_dispatch AS (
    SELECT
        order_id,
        MIN(attempted_at) AS dispatched_at
    FROM {SOURCE_CATALOG}.dispatch_attempts
    WHERE is_deleted = false
      AND outcome = 'dispatched'
    GROUP BY order_id
),
order_promises AS (
    SELECT
        o.order_id,
        o.merchant_id,
        o.placed_at,
        o.cancelled_at,
        o.placed_at + INTERVAL 48 HOURS AS deadline_at,
        d.dispatched_at
    FROM {SOURCE_CATALOG}.orders o
    LEFT JOIN first_dispatch d
        ON o.order_id = d.order_id
    WHERE o.is_deleted = false
),
promise_events AS (
    SELECT
        order_id,
        merchant_id,
        CASE
            WHEN cancelled_at < deadline_at THEN NULL
            WHEN dispatched_at <= deadline_at THEN 'meet'
            WHEN dispatched_at IS NULL OR dispatched_at > deadline_at THEN 'miss'
        END AS event_type,
        CASE
            WHEN cancelled_at < deadline_at THEN NULL
            WHEN dispatched_at <= deadline_at THEN CAST(dispatched_at AS DATE)
            WHEN dispatched_at IS NULL OR dispatched_at > deadline_at THEN CAST(deadline_at AS DATE)
        END AS event_date
    FROM order_promises
)
SELECT
    DATE '{SNAPSHOT_DATE}' AS SNAPSHOT_DATE,
    {key_list},
    'total_dispatch_meet_count' AS metric_name,
    COUNT(DISTINCT order_id) AS metric_value,
    now() AS LOAD_TIMESTAMP,
    '{SOURCE_ZONE}' AS SOURCE_ZONE
FROM promise_events
WHERE event_type = 'meet'
  AND event_date = DATE '{SNAPSHOT_DATE}'
GROUP BY {key_list}
UNION ALL
SELECT
    DATE '{SNAPSHOT_DATE}' AS SNAPSHOT_DATE,
    {key_list},
    'total_dispatch_miss_count' AS metric_name,
    COUNT(DISTINCT order_id) AS metric_value,
    now() AS LOAD_TIMESTAMP,
    '{SOURCE_ZONE}' AS SOURCE_ZONE
FROM promise_events
WHERE event_type = 'miss'
  AND event_date = DATE '{SNAPSHOT_DATE}'
GROUP BY {key_list};

COMMIT;
"""
    )
