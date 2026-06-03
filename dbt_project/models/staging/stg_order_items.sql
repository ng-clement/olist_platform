{{ config(materialized='view', tags=['staging']) }}

SELECT
    order_id,
    order_item_id,
    product_id,
    seller_id,
    DATE(shipping_limit_date)        AS shipping_limit_date,
    ROUND(SAFE_CAST(price         AS FLOAT64), 2)                         AS item_price,
    ROUND(SAFE_CAST(freight_value AS FLOAT64), 2)                         AS freight_value,
    ROUND(SAFE_CAST(price AS FLOAT64) + SAFE_CAST(freight_value AS FLOAT64), 2) AS item_total,
    CURRENT_TIMESTAMP()              AS _stg_loaded_at
FROM {{ source('olist_raw', 'order_items') }}
WHERE order_id IS NOT NULL
  AND product_id IS NOT NULL
  AND seller_id IS NOT NULL
