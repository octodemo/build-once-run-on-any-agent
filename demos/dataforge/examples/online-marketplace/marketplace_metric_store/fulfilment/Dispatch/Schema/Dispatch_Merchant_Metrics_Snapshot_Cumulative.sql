-- Dispatch promises at merchant grain through each complete Sydney snapshot day.
CREATE TABLE IF NOT EXISTS {TARGET_CATALOG}.Dispatch_Merchant_Metrics_Snapshot_Cumulative (
    SNAPSHOT_DATE DATE NOT NULL -- Sydney date through which events are counted
    , merchant_id BIGINT NOT NULL -- Merchant responsible for the order
    , metric_name VARCHAR(128) NOT NULL -- Promise meet or miss metric through this day
    , metric_value BIGINT NOT NULL -- Distinct orders for this merchant through this day
    , LOAD_TIMESTAMP TIMESTAMP NOT NULL -- Time this snapshot was loaded
    , SOURCE_ZONE VARCHAR(16) NOT NULL -- Fulfilment region processed
);
