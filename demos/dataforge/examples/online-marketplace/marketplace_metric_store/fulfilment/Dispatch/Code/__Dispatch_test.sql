WITH first_successful_dispatch AS (
    SELECT
        order_id
        , MIN(attempted_at) AS first_successful_attempt_at
    FROM demo_gold_commerce.dispatch_attempts
    WHERE is_deleted = false
      AND outcome = 'dispatched'
      AND attempted_at < CAST(CURRENT_DATE AS TIMESTAMP)
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
    FROM demo_gold_commerce.orders o
    LEFT JOIN first_successful_dispatch d
        ON o.order_id = d.order_id
    WHERE o.is_deleted = false
      AND o.order_id IS NOT NULL
      AND o.merchant_id IS NOT NULL
      AND o.placed_at IS NOT NULL
      AND o.placed_at < CAST(CURRENT_DATE AS TIMESTAMP)
),
daily_expected AS (
    SELECT
        merchant_id
        , 'total_dispatch_meet_count' AS metric_name
        , COUNT(DISTINCT CASE
            WHEN first_successful_attempt_at <= deadline_at
             AND (cancelled_at IS NULL OR cancelled_at >= deadline_at)
             AND CAST(first_successful_attempt_at AS DATE) = CURRENT_DATE - INTERVAL 1 DAY
            THEN order_id
            ELSE NULL
          END) AS metric_value
    FROM promise_orders
    WHERE placed_at >= CAST(CURRENT_DATE - INTERVAL 3 DAY AS TIMESTAMP)
    GROUP BY merchant_id

    UNION ALL

    SELECT
        merchant_id
        , 'total_dispatch_miss_count' AS metric_name
        , COUNT(DISTINCT CASE
            WHEN (first_successful_attempt_at IS NULL OR first_successful_attempt_at > deadline_at)
             AND (cancelled_at IS NULL OR cancelled_at >= deadline_at)
             AND CAST(deadline_at AS DATE) = CURRENT_DATE - INTERVAL 1 DAY
            THEN order_id
            ELSE NULL
          END) AS metric_value
    FROM promise_orders
    WHERE placed_at >= CAST(CURRENT_DATE - INTERVAL 3 DAY AS TIMESTAMP)
    GROUP BY merchant_id
),
daily_actual AS (
    SELECT merchant_id, metric_name, SUM(metric_value) AS metric_value, COUNT(*) AS row_count
    FROM demo_gold_marketplace_metric_store.Dispatch_Merchant_Metrics_Snapshot_Daily
    WHERE SNAPSHOT_DATE = CURRENT_DATE - INTERVAL 1 DAY
    GROUP BY merchant_id, metric_name
),
daily_differences AS (
    SELECT COALESCE(e.merchant_id, a.merchant_id) AS merchant_id
    FROM daily_expected e
    FULL OUTER JOIN daily_actual a
        USING (merchant_id, metric_name)
    WHERE e.metric_value IS DISTINCT FROM a.metric_value
       OR a.row_count IS DISTINCT FROM 1
),
cumulative_expected AS (
    SELECT
        merchant_id
        , 'total_dispatch_meet_count' AS metric_name
        , COUNT(DISTINCT CASE
            WHEN first_successful_attempt_at <= deadline_at
             AND (cancelled_at IS NULL OR cancelled_at >= deadline_at)
             AND CAST(first_successful_attempt_at AS DATE) <= CURRENT_DATE - INTERVAL 1 DAY
            THEN order_id
            ELSE NULL
          END) AS metric_value
    FROM promise_orders
    GROUP BY merchant_id

    UNION ALL

    SELECT
        merchant_id
        , 'total_dispatch_miss_count' AS metric_name
        , COUNT(DISTINCT CASE
            WHEN (first_successful_attempt_at IS NULL OR first_successful_attempt_at > deadline_at)
             AND (cancelled_at IS NULL OR cancelled_at >= deadline_at)
             AND CAST(deadline_at AS DATE) <= CURRENT_DATE - INTERVAL 1 DAY
            THEN order_id
            ELSE NULL
          END) AS metric_value
    FROM promise_orders
    GROUP BY merchant_id
),
cumulative_actual AS (
    SELECT merchant_id, metric_name, SUM(metric_value) AS metric_value, COUNT(*) AS row_count
    FROM demo_gold_marketplace_metric_store.Dispatch_Merchant_Metrics_Snapshot_Cumulative
    WHERE SNAPSHOT_DATE = CURRENT_DATE - INTERVAL 1 DAY
    GROUP BY merchant_id, metric_name
),
cumulative_differences AS (
    SELECT COALESCE(e.merchant_id, a.merchant_id) AS merchant_id
    FROM cumulative_expected e
    FULL OUTER JOIN cumulative_actual a
        USING (merchant_id, metric_name)
    WHERE e.metric_value IS DISTINCT FROM a.metric_value
       OR a.row_count IS DISTINCT FROM 1
)
SELECT 'daily' AS cadence, COUNT(*) AS mismatch_count
FROM daily_differences

UNION ALL

SELECT 'cumulative' AS cadence, COUNT(*) AS mismatch_count
FROM cumulative_differences;
