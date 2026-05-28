{{ config(materialized='view', tags=['staging']) }}

SELECT
    p.product_id,
    p.product_category_name,
    COALESCE(t.product_category_name_english, p.product_category_name, 'Unknown') AS category_english,
    p.product_name_lenght         AS product_name_length,
    p.product_description_lenght  AS product_description_length,
    p.product_photos_qty,
    p.product_weight_g,
    p.product_length_cm,
    p.product_height_cm,
    p.product_width_cm,
    CURRENT_TIMESTAMP()           AS _stg_loaded_at
FROM {{ source('olist_raw', 'products') }} p
LEFT JOIN {{ source('olist_raw', 'product_category_translation') }} t
    USING (product_category_name)
