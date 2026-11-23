-- Dispatch promise outcomes through this snapshot day, at merchant grain.
CREATE TABLE IF NOT EXISTS {TARGET_CATALOG}.Dispatch_Merchant_Metrics_Snapshot_Cumulative (
    SNAPSHOT_DATE DATE NOT NULL
    , merchant_id BIGINT NOT NULL
    , metric_name VARCHAR(128) NOT NULL
        CHECK (metric_name IN ('total_dispatch_meet_count', 'total_dispatch_miss_count'))
    , metric_value BIGINT NOT NULL CHECK (metric_value >= 0)
    , LOAD_TIMESTAMP TIMESTAMP NOT NULL
    , SOURCE_ZONE VARCHAR(16) NOT NULL
    , PRIMARY KEY (SNAPSHOT_DATE, merchant_id, metric_name)
);
