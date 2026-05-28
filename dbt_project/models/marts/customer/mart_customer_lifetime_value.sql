-- Customer Lifetime Value mart with RFM segmentation
-- Materialized as table, refreshed daily

{{
  config(
    materialized='table',
    partition_by={'field': 'first_order_date', 'data_type': 'date'},
    cluster_by=['customer_state', 'rfm_segment'],
    tags=['mart', 'customer', 'clv']
  )
}}

WITH orders_delivered AS (
    SELECT
        o.order_id,
        o.customer_id,
        o.purchase_date,
        SUM(oi.item_price)    AS product_revenue,
        SUM(oi.freight_value) AS freight_revenue
    FROM {{ ref('stg_orders') }}      o
    JOIN {{ ref('stg_order_items') }} oi USING (order_id)
    WHERE o.order_status = 'delivered'
    GROUP BY 1, 2, 3
),

customer_orders AS (
    SELECT
        c.customer_unique_id,
        MAX(c.customer_state)                                          AS customer_state,
        MAX(c.customer_city)                                           AS customer_city,
        MAX(od.purchase_date)                                          AS last_order_date,
        MIN(od.purchase_date)                                          AS first_order_date,
        COUNT(DISTINCT od.order_id)                                    AS order_count,
        SUM(od.product_revenue)                                        AS total_product_spend,
        SUM(od.freight_revenue)                                        AS total_freight_spend,
        SUM(od.product_revenue + od.freight_revenue)                   AS total_spend,
        AVG(od.product_revenue)                                        AS avg_order_value,
        DATE_DIFF(MAX(od.purchase_date), MIN(od.purchase_date), DAY)   AS customer_tenure_days
    FROM {{ ref('stg_customers') }}   c
    JOIN orders_delivered              od ON od.customer_id = c.customer_id
    GROUP BY 1
),

recency_calc AS (
    SELECT
        *,
        DATE_DIFF(DATE('{{ var("project_end_date") }}'), last_order_date, DAY) AS recency_days
    FROM customer_orders
),

rfm_scored AS (
    SELECT
        *,
        NTILE(4) OVER (ORDER BY recency_days DESC)  AS r_score,
        NTILE(4) OVER (ORDER BY order_count ASC)    AS f_score,
        NTILE(4) OVER (ORDER BY total_spend ASC)    AS m_score
    FROM recency_calc
),

segmented AS (
    SELECT
        *,
        CASE
            WHEN r_score >= 4 AND f_score >= 4                          THEN 'Champions'
            WHEN r_score >= 3 AND f_score >= 3                          THEN 'Loyal Customers'
            WHEN r_score >= 4 AND f_score <= 2                          THEN 'New Customers'
            WHEN r_score = 3  AND f_score <= 2                          THEN 'Potential Loyalists'
            WHEN r_score <= 2 AND f_score >= 3                          THEN 'At Risk'
            WHEN r_score = 1  AND f_score >= 3                          THEN 'Cant Lose Them'
            WHEN r_score <= 2 AND f_score <= 2 AND m_score >= 3         THEN 'Sleeping Giants'
            ELSE 'Hibernating'
        END AS rfm_segment,
        CASE
            WHEN r_score >= 4 AND f_score >= 4 THEN 'High Value'
            WHEN r_score >= 3 AND m_score >= 3 THEN 'Medium Value'
            ELSE 'Low Value'
        END AS value_tier,
        ROUND(total_spend * (1 + 0.3 * LEAST(order_count - 1, 5)), 2) AS estimated_clv
    FROM rfm_scored
)

SELECT
    customer_unique_id,
    customer_state,
    customer_city,
    first_order_date,
    last_order_date,
    order_count,
    ROUND(total_product_spend, 2)   AS total_product_spend,
    ROUND(total_freight_spend, 2)   AS total_freight_spend,
    ROUND(total_spend, 2)           AS total_spend,
    ROUND(avg_order_value, 2)       AS avg_order_value,
    customer_tenure_days,
    recency_days,
    r_score,
    f_score,
    m_score,
    rfm_segment,
    value_tier,
    estimated_clv
FROM segmented
