-- Logistics & Delivery Performance Mart
-- Grain: one row per (customer_state, order_month)
-- Audience: COO, operations, supply chain team
-- Answers: which states have worst delivery SLA, how does delivery speed
--          correlate with review score, what is the delay distribution?

{{
  config(
    materialized         = 'incremental',
    unique_key           = ['customer_state', 'order_month'],
    partition_by         = {"field": "order_month", "data_type": "date", "granularity": "month"},
    cluster_by           = ['customer_state', 'region'],
    incremental_strategy = 'merge',
    tags                 = ['mart', 'logistics', 'daily']
  )
}}

WITH delivered_orders AS (
    SELECT
        o.order_id,
        o.customer_id,
        o.purchase_date,
        o.delivered_date,
        o.estimated_delivery_date,
        o.carrier_pickup_date,
        o.delivery_days,
        o.estimated_delivery_days,
        o.is_on_time,
        o.is_late,
        o.order_status,
        r.review_score,
        DATE_TRUNC(o.purchase_date, MONTH)              AS order_month

    FROM {{ ref('stg_orders') }} o
    LEFT JOIN (
        SELECT order_id, MAX(review_score) AS review_score
        FROM {{ ref('stg_reviews') }}
        GROUP BY order_id
    ) r USING (order_id)

    WHERE o.order_status = 'delivered'
      AND o.delivery_days IS NOT NULL
      AND o.delivery_days >= 0

    {% if is_incremental() %}
        AND o.purchase_date >= DATE_SUB(
            (SELECT MAX(order_month) FROM {{ this }}),
            INTERVAL 1 MONTH
        )
    {% endif %}
),

customer_geo AS (
    SELECT
        c.customer_id,
        c.customer_state,
        g.region
    FROM {{ ref('stg_customers') }} c
    LEFT JOIN {{ ref('stg_geolocation') }} g USING (zip_code_prefix)
),

joined AS (
    SELECT
        cg.customer_state,
        MAX(cg.region)                                 AS region,
        d.order_month,

        -- Volume
        COUNT(DISTINCT d.order_id)                     AS total_delivered_orders,

        -- Delivery timing
        ROUND(AVG(d.delivery_days), 1)                 AS avg_delivery_days,
        ROUND(APPROX_QUANTILES(d.delivery_days, 100)[OFFSET(50)], 1)
                                                       AS median_delivery_days,
        ROUND(APPROX_QUANTILES(d.delivery_days, 100)[OFFSET(90)], 1)
                                                       AS p90_delivery_days,
        MIN(d.delivery_days)                           AS min_delivery_days,
        MAX(d.delivery_days)                           AS max_delivery_days,

        -- SLA performance
        COUNTIF(d.is_on_time = TRUE)                   AS on_time_orders,
        COUNTIF(d.is_on_time = FALSE)                  AS late_orders,
        ROUND(
            SAFE_DIVIDE(COUNTIF(d.is_on_time = TRUE),
                        COUNT(DISTINCT d.order_id)) * 100, 2
        )                                              AS on_time_pct,

        -- Delay magnitude (late orders only)
        ROUND(AVG(
            CASE WHEN d.is_late THEN
                DATE_DIFF(d.delivered_date, d.estimated_delivery_date, DAY)
            END
        ), 1)                                          AS avg_delay_days_when_late,
        MAX(
            CASE WHEN d.is_late THEN
                DATE_DIFF(d.delivered_date, d.estimated_delivery_date, DAY)
            END
        )                                              AS max_delay_days,

        -- Customer satisfaction correlation
        ROUND(AVG(d.review_score), 3)                  AS avg_review_score,
        ROUND(AVG(CASE WHEN d.is_on_time = TRUE  THEN d.review_score END), 3)
                                                       AS avg_review_on_time,
        ROUND(AVG(CASE WHEN d.is_on_time = FALSE THEN d.review_score END), 3)
                                                       AS avg_review_late,

        -- Delivery speed buckets (orders)
        COUNTIF(d.delivery_days <= 5)                  AS orders_0_5_days,
        COUNTIF(d.delivery_days BETWEEN 6  AND 10)     AS orders_6_10_days,
        COUNTIF(d.delivery_days BETWEEN 11 AND 20)     AS orders_11_20_days,
        COUNTIF(d.delivery_days BETWEEN 21 AND 30)     AS orders_21_30_days,
        COUNTIF(d.delivery_days > 30)                  AS orders_over_30_days,

        CURRENT_TIMESTAMP()                            AS _dbt_updated_at

    FROM delivered_orders d
    JOIN customer_geo cg ON d.customer_id = cg.customer_id
    GROUP BY cg.customer_state, d.order_month
),

-- State population for penetration / per-capita metrics
with_sla_flag AS (
    SELECT
        *,
        CASE
            WHEN on_time_pct >= 95 THEN 'Excellent'
            WHEN on_time_pct >= 90 THEN 'Good'
            WHEN on_time_pct >= 80 THEN 'Needs Improvement'
            ELSE                        'Critical'
        END                                            AS sla_performance_band,
        CASE
            WHEN avg_review_late IS NOT NULL
             AND avg_review_on_time IS NOT NULL
            THEN ROUND(avg_review_on_time - avg_review_late, 3)
            ELSE NULL
        END                                            AS review_score_delta_on_time_vs_late
    FROM joined
)

SELECT * FROM with_sla_flag
