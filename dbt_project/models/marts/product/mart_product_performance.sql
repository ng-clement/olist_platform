-- Product & Category Performance Mart
-- Grain: one row per product_category (all-time aggregates with monthly breakdowns as separate CTEs)
-- Audience: CMO, Category Managers, Merchandise team
-- Answers: which categories drive GMV, what is avg price and review score per category,
--          what is repeat-purchase behaviour, which products are rising/declining?

{{
  config(
    materialized = 'table',
    cluster_by   = ['category_english', 'performance_tier'],
    tags         = ['mart', 'product', 'daily']
  )
}}

WITH item_base AS (
    SELECT
        oi.order_id,
        oi.order_item_id,
        oi.product_id,
        oi.seller_id,
        oi.item_price,
        oi.freight_value,
        oi.item_total,
        oi.shipping_limit_date,
        p.category_english,
        p.product_weight_g,
        p.product_photos_qty,
        p.product_name_length,
        o.purchase_date,
        o.order_status,
        c.customer_state,
        r.review_score,
        o.is_on_time,
        o.customer_id
    FROM {{ ref('stg_order_items') }}  oi
    JOIN {{ ref('stg_products') }}     p  USING (product_id)
    JOIN {{ ref('stg_orders') }}       o  USING (order_id)
    LEFT JOIN {{ ref('stg_reviews') }}   r  ON oi.order_id   = r.order_id
    LEFT JOIN {{ ref('stg_customers') }} c  ON o.customer_id = c.customer_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
),

-- Product-level aggregates
product_agg AS (
    SELECT
        product_id,
        category_english,
        COUNT(DISTINCT order_id)               AS total_orders,
        COUNT(order_item_id)                   AS total_units_sold,
        COUNT(DISTINCT customer_id)            AS unique_customers,
        ROUND(SUM(item_price), 2)              AS gross_revenue,
        ROUND(AVG(item_price), 2)              AS avg_selling_price,
        ROUND(MIN(item_price), 2)              AS min_price,
        ROUND(MAX(item_price), 2)              AS max_price,
        ROUND(AVG(review_score), 3)            AS avg_review_score,
        COUNTIF(review_score >= 4)             AS positive_reviews,
        COUNTIF(review_score <= 2)             AS negative_reviews,
        ROUND(AVG(CAST(product_weight_g AS FLOAT64)), 0)   AS avg_weight_g,
        MAX(product_photos_qty)                AS product_photos_qty,
        MAX(product_name_length)               AS product_name_length,
        MIN(purchase_date)                     AS first_sold_date,
        MAX(purchase_date)                     AS last_sold_date
    FROM item_base
    GROUP BY 1, 2
),

-- Repeat-purchase rate per product
repeat_buyers AS (
    SELECT
        product_id,
        COUNTIF(purchase_count > 1) AS repeat_buyer_count,
        COUNT(DISTINCT customer_id) AS total_distinct_buyers
    FROM (
        SELECT
            product_id,
            customer_id,
            COUNT(*) AS purchase_count
        FROM item_base
        GROUP BY 1, 2
    )
    GROUP BY 1
),

-- Category-level rollup
category_agg AS (
    SELECT
        category_english,
        COUNT(DISTINCT product_id)            AS total_skus,
        COUNT(DISTINCT order_id)              AS total_orders,
        COUNT(order_item_id)                  AS total_units_sold,
        COUNT(DISTINCT customer_id)           AS unique_customers,
        ROUND(SUM(item_price), 2)             AS category_gross_revenue,
        ROUND(SUM(freight_value), 2)          AS category_freight_revenue,
        ROUND(AVG(item_price), 2)             AS avg_item_price,
        ROUND(APPROX_QUANTILES(item_price, 100)[OFFSET(50)], 2)
                                              AS median_item_price,
        ROUND(AVG(review_score), 3)           AS avg_review_score,
        COUNTIF(review_score >= 4)            AS positive_reviews,
        COUNTIF(review_score <= 2)            AS negative_reviews,
        ROUND(
            SAFE_DIVIDE(COUNTIF(is_on_time = TRUE),
                        COUNTIF(is_on_time IS NOT NULL)) * 100, 2
        )                                     AS on_time_delivery_pct,
        MIN(purchase_date)                    AS first_sale_date,
        MAX(purchase_date)                    AS last_sale_date
    FROM item_base
    GROUP BY 1
),

-- GMV decile ranking for performance tier
category_ranked AS (
    SELECT
        *,
        NTILE(4) OVER (ORDER BY category_gross_revenue DESC) AS gmv_quartile,
        ROUND(
            SAFE_DIVIDE(category_gross_revenue,
                SUM(category_gross_revenue) OVER ()) * 100, 3
        )                                     AS revenue_share_pct,
        SUM(category_gross_revenue) OVER (
            ORDER BY category_gross_revenue DESC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )                                     AS cumulative_revenue,
        ROUND(
            SAFE_DIVIDE(
                SUM(category_gross_revenue) OVER (
                    ORDER BY category_gross_revenue DESC
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ),
                SUM(category_gross_revenue) OVER ()
            ) * 100, 2
        )                                     AS cumulative_revenue_pct
    FROM category_agg
),

tiered AS (
    SELECT
        *,
        CASE gmv_quartile
            WHEN 1 THEN 'Tier 1 — Core'
            WHEN 2 THEN 'Tier 2 — Growth'
            WHEN 3 THEN 'Tier 3 — Niche'
            ELSE         'Tier 4 — Tail'
        END AS performance_tier
    FROM category_ranked
)

SELECT
    category_english,
    performance_tier,
    gmv_quartile,
    total_skus,
    total_orders,
    total_units_sold,
    unique_customers,
    category_gross_revenue,
    category_freight_revenue,
    ROUND(category_gross_revenue + category_freight_revenue, 2)  AS total_category_revenue,
    avg_item_price,
    median_item_price,
    revenue_share_pct,
    cumulative_revenue_pct,
    avg_review_score,
    positive_reviews,
    negative_reviews,
    ROUND(
        SAFE_DIVIDE(positive_reviews, NULLIF(positive_reviews + negative_reviews, 0)) * 100, 2
    )                                                            AS positive_review_rate_pct,
    on_time_delivery_pct,
    ROUND(SAFE_DIVIDE(total_units_sold, NULLIF(total_orders, 0)), 2)
                                                                 AS avg_units_per_order,
    ROUND(SAFE_DIVIDE(category_gross_revenue, NULLIF(total_orders, 0)), 2)
                                                                 AS revenue_per_order,
    first_sale_date,
    last_sale_date,
    DATE_DIFF(last_sale_date, first_sale_date, DAY)              AS active_selling_days,
    CURRENT_TIMESTAMP()                                          AS _dbt_updated_at
FROM tiered
