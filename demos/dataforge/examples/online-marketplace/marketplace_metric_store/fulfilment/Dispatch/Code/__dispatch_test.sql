WITH RECURSIVE
test_window AS (
    SELECT
        GREATEST(
            MIN(CAST(placed_at AS DATE)),
            CAST(CURRENT_DATE - INTERVAL 30 DAY AS DATE)
        ) AS start_date,
        CAST(CURRENT_DATE - INTERVAL 1 DAY AS DATE) AS end_date
    FROM demo_gold_commerce.orders
    WHERE is_deleted = false
),
date_series(snapshot_date) AS (
    SELECT start_date
    FROM test_window
    UNION ALL
    SELECT CAST(snapshot_date + INTERVAL 1 DAY AS DATE)
    FROM date_series
    WHERE snapshot_date < (SELECT end_date FROM test_window)
),
first_dispatch AS (
    SELECT
        order_id,
        MIN(attempted_at) AS dispatched_at
    FROM demo_gold_commerce.dispatch_attempts
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
    FROM demo_gold_commerce.orders o
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
),
daily_expected AS (
    SELECT
        event_date AS snapshot_date,
        merchant_id,
        CASE event_type
            WHEN 'meet' THEN 'total_dispatch_meet_count'
            WHEN 'miss' THEN 'total_dispatch_miss_count'
        END AS metric_name,
        COUNT(DISTINCT order_id) AS metric_value
    FROM promise_events
    CROSS JOIN test_window
    WHERE event_type IS NOT NULL
      AND event_date BETWEEN start_date AND end_date
    GROUP BY event_date, merchant_id, event_type
),
cumulative_expected AS (
    SELECT
        d.snapshot_date,
        p.merchant_id,
        CASE p.event_type
            WHEN 'meet' THEN 'total_dispatch_meet_count'
            WHEN 'miss' THEN 'total_dispatch_miss_count'
        END AS metric_name,
        COUNT(DISTINCT p.order_id) AS metric_value
    FROM date_series d
    JOIN promise_events p
        ON p.event_date <= d.snapshot_date
    CROSS JOIN test_window
    WHERE p.event_type IS NOT NULL
      AND d.snapshot_date <= end_date
    GROUP BY d.snapshot_date, p.merchant_id, p.event_type
),
expected AS (
    SELECT
        'Daily' AS cadence,
        snapshot_date,
        merchant_id,
        metric_name,
        metric_value
    FROM daily_expected
    UNION ALL
    SELECT
        'Cumulative' AS cadence,
        snapshot_date,
        merchant_id,
        metric_name,
        metric_value
    FROM cumulative_expected
),
actual AS (
    SELECT
        'Daily' AS cadence,
        SNAPSHOT_DATE AS snapshot_date,
        merchant_id,
        metric_name,
        metric_value
    FROM demo_gold_marketplace_metric_store.Dispatch_Merchant_Metrics_Snapshot_Daily
    CROSS JOIN test_window
    WHERE SNAPSHOT_DATE BETWEEN start_date AND end_date
    UNION ALL
    SELECT
        'Cumulative' AS cadence,
        SNAPSHOT_DATE AS snapshot_date,
        merchant_id,
        metric_name,
        metric_value
    FROM demo_gold_marketplace_metric_store.Dispatch_Merchant_Metrics_Snapshot_Cumulative
    CROSS JOIN test_window
    WHERE SNAPSHOT_DATE BETWEEN start_date AND end_date
),
expected_row_counts AS (
    SELECT cadence, snapshot_date, COUNT(*) AS row_count
    FROM expected
    GROUP BY cadence, snapshot_date
),
actual_row_counts AS (
    SELECT cadence, snapshot_date, COUNT(*) AS row_count
    FROM actual
    GROUP BY cadence, snapshot_date
),
row_count_failures AS (
    SELECT COUNT(*) AS failure_count
    FROM expected_row_counts e
    FULL OUTER JOIN actual_row_counts a
        ON e.cadence = a.cadence
       AND e.snapshot_date = a.snapshot_date
    WHERE e.row_count IS DISTINCT FROM a.row_count
),
metric_rollup_failures AS (
    SELECT COUNT(*) AS failure_count
    FROM expected e
    FULL OUTER JOIN actual a
        ON e.cadence = a.cadence
       AND e.snapshot_date = a.snapshot_date
       AND e.merchant_id = a.merchant_id
       AND e.metric_name = a.metric_name
    WHERE e.metric_value IS DISTINCT FROM a.metric_value
),
expected_grains AS (
    SELECT cadence, snapshot_date, COUNT(DISTINCT merchant_id) AS merchant_count
    FROM expected
    GROUP BY cadence, snapshot_date
),
actual_grains AS (
    SELECT cadence, snapshot_date, COUNT(DISTINCT merchant_id) AS merchant_count
    FROM actual
    GROUP BY cadence, snapshot_date
),
grain_failures AS (
    SELECT COUNT(*) AS failure_count
    FROM expected_grains e
    FULL OUTER JOIN actual_grains a
        ON e.cadence = a.cadence
       AND e.snapshot_date = a.snapshot_date
    WHERE e.merchant_count IS DISTINCT FROM a.merchant_count
),
expected_dates AS (
    SELECT DISTINCT cadence, snapshot_date
    FROM expected
),
actual_dates AS (
    SELECT DISTINCT cadence, snapshot_date
    FROM actual
),
date_failures AS (
    SELECT COUNT(*) AS failure_count
    FROM expected_dates e
    FULL OUTER JOIN actual_dates a
        ON e.cadence = a.cadence
       AND e.snapshot_date = a.snapshot_date
    WHERE e.snapshot_date IS NULL
       OR a.snapshot_date IS NULL
),
null_failures AS (
    SELECT
        (SELECT COUNT(*) FROM demo_gold_marketplace_metric_store.Dispatch_Merchant_Metrics_Snapshot_Daily
         CROSS JOIN test_window
        WHERE SNAPSHOT_DATE IS NULL
           OR (SNAPSHOT_DATE BETWEEN start_date AND end_date
               AND (merchant_id IS NULL OR metric_name IS NULL OR metric_value IS NULL)))
        +
        (SELECT COUNT(*) FROM demo_gold_marketplace_metric_store.Dispatch_Merchant_Metrics_Snapshot_Cumulative
        CROSS JOIN test_window
        WHERE SNAPSHOT_DATE IS NULL
           OR (SNAPSHOT_DATE BETWEEN start_date AND end_date
               AND (merchant_id IS NULL OR metric_name IS NULL OR metric_value IS NULL)))
        AS failure_count
),
daily_schema_expected AS (
    SELECT * FROM (VALUES
        (1, 'SNAPSHOT_DATE', 'DATE'),
        (2, 'merchant_id', 'BIGINT'),
        (3, 'metric_name', 'VARCHAR'),
        (4, 'metric_value', 'BIGINT'),
        (5, 'LOAD_TIMESTAMP', 'TIMESTAMP'),
        (6, 'SOURCE_ZONE', 'VARCHAR')
    ) AS columns_expected(ordinal_position, column_name, data_type)
),
cumulative_schema_expected AS (
    SELECT * FROM daily_schema_expected
),
daily_schema_actual AS (
    SELECT ordinal_position, column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'demo_gold_marketplace_metric_store'
      AND table_name = 'Dispatch_Merchant_Metrics_Snapshot_Daily'
),
cumulative_schema_actual AS (
    SELECT ordinal_position, column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'demo_gold_marketplace_metric_store'
      AND table_name = 'Dispatch_Merchant_Metrics_Snapshot_Cumulative'
),
schema_failures AS (
    SELECT
        (SELECT COUNT(*)
         FROM daily_schema_expected e
         FULL OUTER JOIN daily_schema_actual a USING (ordinal_position)
         WHERE e.column_name IS DISTINCT FROM a.column_name
            OR e.data_type IS DISTINCT FROM a.data_type)
        +
        (SELECT COUNT(*)
         FROM cumulative_schema_expected e
         FULL OUTER JOIN cumulative_schema_actual a USING (ordinal_position)
         WHERE e.column_name IS DISTINCT FROM a.column_name
            OR e.data_type IS DISTINCT FROM a.data_type)
        AS failure_count
)
SELECT 'source_vs_target_row_count' AS test_name, failure_count
FROM row_count_failures
UNION ALL
SELECT 'metric_rollup', failure_count
FROM metric_rollup_failures
UNION ALL
SELECT 'grain_completeness', failure_count
FROM grain_failures
UNION ALL
SELECT 'date_range_coverage', failure_count
FROM date_failures
UNION ALL
SELECT 'null_checks', failure_count
FROM null_failures
UNION ALL
SELECT 'schema_alignment', failure_count
FROM schema_failures
ORDER BY test_name;
