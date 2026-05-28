{{ config(materialized='view', tags=['staging']) }}

SELECT
    order_id,
    order_item_id,
    product_id,
    seller_id,
    DATE(shipping_limit_date)        AS shipping_limit_date,
    ROUND(price, 2)                  AS item_price,
    ROUND(freight_value, 2)          AS freight_value,
    ROUND(price + freight_value, 2)  AS item_total,
    CURRENT_TIMESTAMP()              AS _stg_loaded_at
FROM {{ source('olist_raw', 'order_items') }}
WHERE order_id IS NOT NULL
  AND product_id IS NOT NULL
  AND seller_id IS NOT NULL
