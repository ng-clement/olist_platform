{{ config(materialized='view', tags=['staging']) }}

SELECT
    review_id,
    order_id,
    review_score,
    SAFE_CAST(review_creation_date AS DATE)    AS review_creation_date,
    SAFE_CAST(review_answer_timestamp AS DATE)  AS review_answer_date,
    CURRENT_TIMESTAMP()                        AS _stg_loaded_at
FROM {{ source('olist_raw', 'order_reviews') }}
WHERE review_id IS NOT NULL
  AND order_id IS NOT NULL
