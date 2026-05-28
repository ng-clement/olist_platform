{{ config(materialized='view', tags=['staging']) }}

SELECT
    seller_id,
    CAST(seller_zip_code_prefix AS INT64)  AS zip_code_prefix,
    LOWER(TRIM(seller_city))               AS seller_city,
    UPPER(TRIM(seller_state))              AS seller_state,
    CURRENT_TIMESTAMP()                    AS _stg_loaded_at
FROM {{ source('olist_raw', 'sellers') }}
WHERE seller_id IS NOT NULL
