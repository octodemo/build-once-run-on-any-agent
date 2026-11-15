"""Order daily metrics.

Counts order lifecycle events that occurred on SNAPSHOT_DATE, by merchant.
Every metric column follows total_{entity}_{verb}_count.

Globals (SOURCE_ZONE, SNAPSHOT_DATE, SOURCE_CATALOG, TARGET_CATALOG, CADENCE)
are injected by common/daily_runner.py.
"""

GRAIN_KEYS = {
    "Merchant": ["merchant_id"],
}

METRICS = {
    "total_order_place_count": "placed_at",
    "total_order_cancel_count": "cancelled_at",
}

STATEMENTS = []

for grain, keys in GRAIN_KEYS.items():
    key_list = ", ".join(keys)
    for metric, event_column in METRICS.items():
        STATEMENTS.append(
            f"""
INSERT INTO {TARGET_CATALOG}.Order_{grain}_Metrics_Snapshot_Daily
SELECT
    DATE '{SNAPSHOT_DATE}' AS SNAPSHOT_DATE,
    {key_list},
    '{metric}' AS metric_name,
    COUNT(*) AS metric_value,
    now() AS LOAD_TIMESTAMP,
    '{SOURCE_ZONE}' AS SOURCE_ZONE
FROM {SOURCE_CATALOG}.orders
WHERE is_deleted = false
  AND {event_column} IS NOT NULL
  AND CAST({event_column} AS DATE) = DATE '{SNAPSHOT_DATE}'
GROUP BY {key_list}
"""
        )
