-- Dispatch promise metrics at merchant grain, counting promise outcomes on the day they occur.
-- Match the long-form metric_name and metric_value layout used by Order.

CREATE TABLE IF NOT EXISTS {TARGET_CATALOG}.Dispatch_Merchant_Metrics_Snapshot_Daily (
    SNAPSHOT_DATE   DATE         NOT NULL,
    merchant_id     BIGINT       NOT NULL,
    metric_name     VARCHAR(128) NOT NULL,
    metric_value    BIGINT       NOT NULL,
    LOAD_TIMESTAMP  TIMESTAMP    NOT NULL,
    SOURCE_ZONE     VARCHAR(16)  NOT NULL
);
