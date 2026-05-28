-- Monthly revenue KPI mart for executive dashboards
-- Grain: one row per month × category

{{
  config(
    materialized='table',
    cluster_by=['year', 'month'],
    tags=['mart', 'core', 'revenue']
  )
}}

WITH base AS (
    SELECT
        DATE_TRUNC(o.purchase_date, MONTH)          AS revenue_month,
        EXTRACT(YEAR  FROM o.purchase_date)          AS year,
        EXTRACT(MONTH FROM o.purchase_date)          AS month,
        COALESCE(p.category_english, 'Unknown')      AS category,
        SUM(oi.item_price)                           AS product_revenue,
        SUM(oi.freight_value)                        AS freight_revenue,
        SUM(oi.item_total)                           AS total_revenue,
        COUNT(DISTINCT o.order_id)                   AS order_count,
        COUNT(DISTINCT c.customer_unique_id)         AS unique_customers,
        AVG(oi.item_price)                           AS avg_item_price
    FROM {{ ref('stg_order_items') }}   oi
    JOIN {{ ref('stg_orders') }}        o  USING (order_id)
    JOIN {{ ref('stg_products') }}      p  USING (product_id)
    JOIN {{ ref('stg_customers') }}     c  ON c.customer_id = o.customer_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
    GROUP BY 1, 2, 3, 4
),

with_growth AS (
    SELECT
        *,
        LAG(total_revenue) OVER (
            PARTITION BY category ORDER BY revenue_month
        ) AS prev_month_revenue,

        ROUND(
            SAFE_DIVIDE(
                total_revenue - LAG(total_revenue) OVER (PARTITION BY category ORDER BY revenue_month),
                LAG(total_revenue) OVER (PARTITION BY category ORDER BY revenue_month)
            ) * 100, 1
        ) AS mom_growth_pct,

        SUM(total_revenue) OVER (
            PARTITION BY category, year ORDER BY revenue_month
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS ytd_revenue
    FROM base
)

SELECT
    revenue_month,
    year,
    month,
    category,
    ROUND(product_revenue, 2)                            AS product_revenue,
    ROUND(freight_revenue, 2)                            AS freight_revenue,
    ROUND(total_revenue, 2)                              AS total_revenue,
    order_count,
    unique_customers,
    ROUND(avg_item_price, 2)                             AS avg_item_price,
    ROUND(total_revenue / NULLIF(order_count, 0), 2)     AS avg_order_value,
    prev_month_revenue,
    mom_growth_pct,
    ROUND(ytd_revenue, 2)                                AS ytd_revenue
FROM with_growth
