-- stg_orders.sql
-- Cleans and standardises the raw orders table.
-- Grain: one row per order_id
-- Adds: delivery_days, estimated_delivery_days, is_on_time, is_late

{{ config(materialized='view', tags=['staging']) }}

SELECT
    order_id,
    customer_id,
    order_status,

    -- Cast timestamps to DATE for clean joins with DimDate
    DATE(order_purchase_timestamp)          AS purchase_date,
    DATE(order_approved_at)                 AS approved_date,
    DATE(order_delivered_carrier_date)      AS carrier_pickup_date,
    DATE(order_delivered_customer_date)     AS delivered_date,
    DATE(order_estimated_delivery_date)     AS estimated_delivery_date,

    -- Derived delivery metrics
    DATE_DIFF(
        DATE(order_delivered_customer_date),
        DATE(order_purchase_timestamp),
        DAY
    )                                       AS delivery_days,

    DATE_DIFF(
        DATE(order_estimated_delivery_date),
        DATE(order_purchase_timestamp),
        DAY
    )                                       AS estimated_delivery_days,

    CASE
        WHEN order_delivered_customer_date IS NULL THEN NULL
        WHEN order_delivered_customer_date
             <= order_estimated_delivery_date THEN TRUE
        ELSE FALSE
    END                                     AS is_on_time,

    CASE
        WHEN order_delivered_customer_date IS NULL THEN FALSE
        WHEN order_delivered_customer_date
             > order_estimated_delivery_date THEN TRUE
        ELSE FALSE
    END                                     AS is_late,

    CURRENT_TIMESTAMP()                     AS _stg_loaded_at

FROM {{ source('olist_raw', 'orders') }}
WHERE order_id IS NOT NULL
  AND customer_id IS NOT NULL
