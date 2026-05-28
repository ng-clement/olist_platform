-- Seller performance mart — KPIs for marketplace operations dashboard
-- Grain: one row per seller_id (all-time aggregate)
-- Audience: COO, marketplace team, engineering leadership

{{
  config(
    materialized = 'table',
    cluster_by   = ['seller_state', 'seller_tier'],
    tags         = ['mart', 'seller', 'daily']
  )
}}

WITH seller_items AS (
    SELECT
        oi.seller_id,
        oi.order_id,
        oi.order_item_id,
        oi.item_price,
        oi.freight_value,
        oi.item_total,
        oi.product_id,
        oi.shipping_limit_date,
        o.purchase_date,
        o.delivered_date,
        o.estimated_delivery_date,
        o.order_status,
        r.review_score,
        o.is_on_time
    FROM {{ ref('stg_order_items') }}  oi
    JOIN {{ ref('stg_orders') }}       o  USING (order_id)
    LEFT JOIN {{ ref('stg_reviews') }} r  ON oi.order_id = r.order_id
),

seller_agg AS (
    SELECT
        seller_id,
        COUNT(DISTINCT order_id)                              AS total_orders,
        COUNT(order_item_id)                                  AS total_items_sold,
        COUNT(DISTINCT product_id)                            AS unique_products,
        ROUND(SUM(item_price),        2)                      AS gross_merchandise_value,
        ROUND(SUM(freight_value),     2)                      AS total_freight_charged,
        ROUND(SUM(item_total),        2)                      AS total_revenue,
        ROUND(AVG(item_price),        2)                      AS avg_item_price,
        ROUND(AVG(item_total),        2)                      AS avg_order_value,

        -- Delivery SLA compliance
        COUNTIF(is_on_time = TRUE)                            AS on_time_deliveries,
        COUNTIF(is_on_time = FALSE)                           AS late_deliveries,
        COUNTIF(is_on_time IS NOT NULL)                       AS deliveries_with_status,
        ROUND(
            SAFE_DIVIDE(
                COUNTIF(is_on_time = TRUE),
                NULLIF(COUNTIF(is_on_time IS NOT NULL), 0)
            ) * 100, 1
        )                                                     AS on_time_delivery_pct,

        -- Customer satisfaction
        ROUND(AVG(review_score), 2)                           AS avg_review_score,
        COUNTIF(review_score >= 4)                            AS positive_reviews,
        COUNTIF(review_score <= 2)                            AS negative_reviews,
        COUNTIF(review_score IS NOT NULL)                     AS reviews_with_score,

        -- Order mix
        COUNTIF(order_status = 'delivered')                   AS delivered_orders,
        COUNTIF(order_status = 'canceled')                    AS canceled_orders,
        ROUND(
            SAFE_DIVIDE(
                COUNTIF(order_status = 'canceled'),
                NULLIF(COUNT(DISTINCT order_id), 0)
            ) * 100, 1
        )                                                     AS cancellation_rate_pct,

        MIN(purchase_date)                                    AS first_sale_date,
        MAX(purchase_date)                                    AS last_sale_date,
        DATE_DIFF(MAX(purchase_date), MIN(purchase_date), DAY) AS active_selling_days
    FROM seller_items
    GROUP BY seller_id
),

-- Decile-rank sellers by GMV for tiering
ranked AS (
    SELECT
        *,
        NTILE(10) OVER (ORDER BY gross_merchandise_value DESC) AS gmv_decile
    FROM seller_agg
),

tiered AS (
    SELECT
        *,
        CASE
            WHEN gmv_decile = 1                      THEN 'Platinum'
            WHEN gmv_decile BETWEEN 2 AND 3          THEN 'Gold'
            WHEN gmv_decile BETWEEN 4 AND 6          THEN 'Silver'
            ELSE                                          'Bronze'
        END AS seller_tier,

        -- Performance score composite (0–100)
        ROUND(
            COALESCE(avg_review_score / 5.0, 0) * 40       -- 40% weight: satisfaction
            + COALESCE(on_time_delivery_pct / 100.0, 0) * 35  -- 35% weight: delivery SLA
            + GREATEST(0, 1 - COALESCE(cancellation_rate_pct / 100.0, 0)) * 25  -- 25% weight: cancellation
            , 1
        )                                                   AS performance_score
    FROM ranked
)

SELECT
    t.seller_id,
    s.seller_state,
    s.seller_city,
    g.region                                        AS seller_region,
    t.seller_tier,
    t.performance_score,
    t.total_orders,
    t.total_items_sold,
    t.unique_products,
    t.gross_merchandise_value,
    t.total_freight_charged,
    t.total_revenue,
    t.avg_item_price,
    t.avg_order_value,
    t.on_time_deliveries,
    t.late_deliveries,
    t.on_time_delivery_pct,
    t.avg_review_score,
    t.positive_reviews,
    t.negative_reviews,
    t.delivered_orders,
    t.canceled_orders,
    t.cancellation_rate_pct,
    t.first_sale_date,
    t.last_sale_date,
    t.active_selling_days,
    CURRENT_TIMESTAMP()                             AS _dbt_updated_at
FROM tiered t
LEFT JOIN {{ ref('stg_sellers') }}     s USING (seller_id)
LEFT JOIN {{ ref('stg_geolocation') }} g ON s.zip_code_prefix = g.zip_code_prefix
