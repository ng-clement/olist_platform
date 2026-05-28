{{ config(materialized='view', tags=['staging']) }}

SELECT
    customer_id,
    customer_unique_id,
    CAST(customer_zip_code_prefix AS INT64)  AS zip_code_prefix,
    LOWER(TRIM(customer_city))               AS customer_city,
    UPPER(TRIM(customer_state))              AS customer_state,
    CURRENT_TIMESTAMP()                      AS _stg_loaded_at
FROM {{ source('olist_raw', 'customers') }}
WHERE customer_id IS NOT NULL
