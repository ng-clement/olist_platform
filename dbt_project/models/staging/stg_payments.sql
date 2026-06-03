{{ config(materialized='view', tags=['staging']) }}

SELECT
    order_id,
    payment_sequential,
    payment_type,
    payment_installments,
    ROUND(SAFE_CAST(payment_value AS FLOAT64), 2) AS payment_value,
    CURRENT_TIMESTAMP()     AS _stg_loaded_at
FROM {{ source('olist_raw', 'order_payments') }}
WHERE payment_type != 'not_defined'
  AND order_id IS NOT NULL
