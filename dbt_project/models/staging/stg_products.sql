{{ config(materialized='view', tags=['staging']) }}

SELECT
    p.product_id,
    p.product_category_name,
    COALESCE(t.product_category_name_english, p.product_category_name, 'Unknown') AS category_english,
    SAFE_CAST(p.product_name_lenght        AS INT64)   AS product_name_length,
    SAFE_CAST(p.product_description_lenght AS INT64)   AS product_description_length,
    SAFE_CAST(p.product_photos_qty         AS INT64)   AS product_photos_qty,
    SAFE_CAST(p.product_weight_g           AS FLOAT64) AS product_weight_g,
    SAFE_CAST(p.product_length_cm          AS FLOAT64) AS product_length_cm,
    SAFE_CAST(p.product_height_cm          AS FLOAT64) AS product_height_cm,
    SAFE_CAST(p.product_width_cm           AS FLOAT64) AS product_width_cm,
    CURRENT_TIMESTAMP()           AS _stg_loaded_at
FROM {{ source('olist_raw', 'products') }} p
LEFT JOIN {{ source('olist_raw', 'product_category_translation') }} t
    USING (product_category_name)
