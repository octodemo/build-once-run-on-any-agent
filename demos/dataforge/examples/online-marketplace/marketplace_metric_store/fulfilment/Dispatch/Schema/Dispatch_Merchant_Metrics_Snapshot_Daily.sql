-- Dispatch promises at merchant grain on each complete Sydney snapshot day.
CREATE TABLE IF NOT EXISTS {TARGET_CATALOG}.Dispatch_Merchant_Metrics_Snapshot_Daily (
    SNAPSHOT_DATE DATE NOT NULL -- Sydney date of dispatch or missed deadline
    , merchant_id BIGINT NOT NULL -- Merchant responsible for the order
    , metric_name VARCHAR(128) NOT NULL -- Promise meet or miss metric on this day
    , metric_value BIGINT NOT NULL -- Distinct orders for this merchant on this day
    , LOAD_TIMESTAMP TIMESTAMP NOT NULL -- Time this snapshot was loaded
    , SOURCE_ZONE VARCHAR(16) NOT NULL -- Fulfilment region processed
);
