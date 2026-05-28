-- Geographic performance mart: joins orders + customers + geo for BI reporting.
-- Grain: one row per (state_code, order_month)

{{
    config(
        materialized         = 'incremental',
        unique_key           = ['state_code', 'order_month'],
        partition_by         = {"field": "order_month", "data_type": "date", "granularity": "month"},
        cluster_by           = ['region', 'state_code'],
        incremental_strategy = 'merge',
        tags                 = ['geography', 'mart', 'daily']
    )
}}

WITH orders AS (
    SELECT
        o.order_id,
        o.customer_id,
        DATE_TRUNC(o.purchase_date, MONTH)       AS order_month,
        oi.item_price + oi.freight_value          AS order_value
    FROM {{ ref('stg_orders') }}      o
    JOIN {{ ref('stg_order_items') }} oi ON o.order_id = oi.order_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
    {% if is_incremental() %}
        AND o.purchase_date >= DATE_SUB(
            (SELECT MAX(order_month) FROM {{ this }}),
            INTERVAL 1 MONTH
        )
    {% endif %}
),

customers_geo AS (
    SELECT
        c.customer_id,
        c.zip_code_prefix,
        COALESCE(g.state_code, c.customer_state)    AS state_code,
        COALESCE(g.state_name,  c.customer_state)   AS state_name,
        COALESCE(g.region, CASE c.customer_state
            WHEN 'SP' THEN 'Southeast' WHEN 'RJ' THEN 'Southeast'
            WHEN 'MG' THEN 'Southeast' WHEN 'ES' THEN 'Southeast'
            WHEN 'RS' THEN 'South'     WHEN 'PR' THEN 'South'     WHEN 'SC' THEN 'South'
            WHEN 'GO' THEN 'Midwest'   WHEN 'DF' THEN 'Midwest'
            WHEN 'MT' THEN 'Midwest'   WHEN 'MS' THEN 'Midwest'
            WHEN 'BA' THEN 'Northeast' WHEN 'PE' THEN 'Northeast' WHEN 'CE' THEN 'Northeast'
            WHEN 'MA' THEN 'Northeast' WHEN 'PB' THEN 'Northeast' WHEN 'RN' THEN 'Northeast'
            WHEN 'AL' THEN 'Northeast' WHEN 'PI' THEN 'Northeast' WHEN 'SE' THEN 'Northeast'
            ELSE 'North'
        END)                                        AS region,
        COALESCE(g.high_ecomm_penetration,
            CASE COALESCE(g.state_code, c.customer_state)
                WHEN 'AC' THEN FALSE WHEN 'AL' THEN FALSE WHEN 'AM' THEN FALSE
                WHEN 'AP' THEN FALSE WHEN 'MA' THEN FALSE WHEN 'PB' THEN FALSE
                WHEN 'RN' THEN FALSE WHEN 'RO' THEN FALSE WHEN 'RR' THEN FALSE
                WHEN 'TO' THEN FALSE ELSE TRUE
            END
        )                                           AS is_frontier_market,
        g.latitude,
        g.longitude
    FROM {{ ref('stg_customers') }}   c
    LEFT JOIN {{ ref('stg_geolocation') }} g ON c.zip_code_prefix = g.zip_code_prefix
),

joined AS (
    SELECT
        cg.state_code,
        ANY_VALUE(cg.state_name)                AS state_name,
        ANY_VALUE(cg.region)                    AS region,
        ANY_VALUE(cg.is_frontier_market)        AS is_frontier_market,
        AVG(cg.latitude)                        AS state_lat_center,
        AVG(cg.longitude)                       AS state_lng_center,
        o.order_month,
        COUNT(DISTINCT o.order_id)              AS total_orders,
        COUNT(DISTINCT o.customer_id)           AS unique_customers,
        SUM(o.order_value)                      AS total_revenue,
        AVG(o.order_value)                      AS avg_order_value,
        SAFE_DIVIDE(
            SUM(o.order_value),
            NULLIF(COUNT(DISTINCT o.customer_id), 0)
        )                                       AS revenue_per_customer,
        CASE cg.state_code
            WHEN 'SP' THEN 46649132 WHEN 'MG' THEN 21292666 WHEN 'RJ' THEN 17366189
            WHEN 'BA' THEN 14930634 WHEN 'PR' THEN 11516840 WHEN 'RS' THEN 11466630
            WHEN 'PE' THEN 9674793  WHEN 'CE' THEN 9240580  WHEN 'PA' THEN 8777124
            WHEN 'SC' THEN 7338473  WHEN 'MA' THEN 7153262  WHEN 'GO' THEN 7206589
            WHEN 'AM' THEN 4207714  WHEN 'ES' THEN 4108508  WHEN 'PB' THEN 4059905
            WHEN 'RN' THEN 3560903  WHEN 'MT' THEN 3567234  WHEN 'MS' THEN 2839188
            WHEN 'PI' THEN 3289290  WHEN 'AL' THEN 3351543  WHEN 'DF' THEN 3094325
            WHEN 'RO' THEN 1815278  WHEN 'TO' THEN 1607363  WHEN 'SE' THEN 2338474
            WHEN 'AC' THEN 906876   WHEN 'AP' THEN 877613   WHEN 'RR' THEN 652713
            ELSE NULL
        END                                     AS state_population,
        CURRENT_TIMESTAMP()                     AS _dbt_updated_at
    FROM orders o
    JOIN customers_geo cg ON o.customer_id = cg.customer_id
    GROUP BY cg.state_code, o.order_month
),

with_penetration AS (
    SELECT
        *,
        SAFE_DIVIDE(total_orders * 1000.0, state_population) AS orders_per_1k_pop,
        SAFE_DIVIDE(total_revenue, state_population)          AS revenue_per_capita
    FROM joined
)

SELECT * FROM with_penetration
