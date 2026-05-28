-- =============================================================================
-- warehouse/schema.sql
-- Complete Star Schema DDL — Olist Analytics Platform
-- Target database : BigQuery
-- Target dataset  : `olist_analytics`   (all tables use this single dataset)
-- Run order       : dimensions → facts  (facts reference dimension keys)
-- =============================================================================


-- =============================================================================
-- SECTION 1: DIMENSION TABLES
-- =============================================================================


-- ─────────────────────────────────────────────────────────────────────────────
-- DimDate
-- Grain  : one row per calendar day, 2016-01-01 → 2020-12-31
-- Purpose: time-based slicing across all fact tables
-- ─────────────────────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS `olist_analytics.DimDate`;
CREATE OR REPLACE TABLE `olist_analytics.DimDate`
CLUSTER BY year, month
OPTIONS (description = 'Calendar date dimension. Covers 2016–2020.')
AS
WITH date_spine AS (
  SELECT DATE_ADD(DATE '2016-01-01', INTERVAL n DAY) AS full_date
  FROM UNNEST(GENERATE_ARRAY(0, 1826)) AS n
),
date_attrs AS (
  SELECT
    full_date,
    FORMAT_DATE('%Y%m%d', full_date)              AS date_key,
    EXTRACT(YEAR        FROM full_date)            AS year,
    EXTRACT(QUARTER     FROM full_date)            AS quarter,
    EXTRACT(MONTH       FROM full_date)            AS month,
    FORMAT_DATE('%B',    full_date)                AS month_name,
    FORMAT_DATE('%b',    full_date)                AS month_abbr,
    EXTRACT(WEEK        FROM full_date)            AS week_of_year,
    EXTRACT(DAY         FROM full_date)            AS day_of_month,
    EXTRACT(DAYOFWEEK   FROM full_date)            AS day_of_week,
    FORMAT_DATE('%A',    full_date)                AS day_name,
    CASE EXTRACT(DAYOFWEEK FROM full_date)
      WHEN 1 THEN FALSE WHEN 7 THEN FALSE ELSE TRUE
    END                                            AS is_weekday,
    -- Brazilian public holidays (fixed-date only)
    CASE
      WHEN FORMAT_DATE('%m-%d', full_date) IN
           ('01-01','04-21','05-01','09-07','10-12','11-02','11-15','12-25')
      THEN TRUE ELSE FALSE
    END                                            AS is_public_holiday,
    DATE_TRUNC(full_date, MONTH)                   AS first_day_of_month,
    LAST_DAY(full_date, MONTH)                     AS last_day_of_month,
    DATE_TRUNC(full_date, QUARTER)                 AS first_day_of_quarter,
    CASE
      WHEN EXTRACT(MONTH FROM full_date) <= 6 THEN
        DATE_TRUNC(full_date, YEAR)
      ELSE
        DATE_ADD(DATE_TRUNC(full_date, YEAR), INTERVAL 6 MONTH)
    END                                            AS first_day_of_half_year,
    CONCAT('H',
      CASE WHEN EXTRACT(MONTH FROM full_date) <= 6 THEN '1' ELSE '2' END,
      '-', CAST(EXTRACT(YEAR FROM full_date) AS STRING)
    )                                              AS half_year_label
  FROM date_spine
)
SELECT * FROM date_attrs;


-- ─────────────────────────────────────────────────────────────────────────────
-- DimGeography
-- Grain  : one row per zip_code_prefix (19,015 rows)
-- Source : olist_geolocation_dataset.csv (1,000,163 raw rows, deduplicated)
-- Purpose: geographic enrichment for customers, sellers, and geo mart
-- ─────────────────────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS `olist_analytics.DimGeography`;
CREATE OR REPLACE TABLE `olist_analytics.DimGeography`
CLUSTER BY state_code, region
OPTIONS (
  description = 'Geographic dimension. One row per zip code prefix. '
                'Coordinates are median values across all raw geolocation entries for that prefix.',
  labels = [('domain', 'geography'), ('layer', 'dimension'), ('pii', 'false')]
)
AS
WITH raw_geo AS (
  SELECT
    CAST(geolocation_zip_code_prefix AS INT64)  AS zip_code_prefix,
    geolocation_lat                             AS lat,
    geolocation_lng                             AS lng,
    TRIM(LOWER(geolocation_city))               AS city_raw,
    UPPER(TRIM(geolocation_state))              AS state_code
  FROM `olist_raw.geolocation`
  WHERE
    geolocation_lat  BETWEEN -35.0 AND 5.3
    AND geolocation_lng BETWEEN -74.0 AND -28.0
    AND geolocation_zip_code_prefix IS NOT NULL
),
deduped AS (
  SELECT
    zip_code_prefix,
    APPROX_QUANTILES(lat, 100)[OFFSET(50)]                 AS latitude,
    APPROX_QUANTILES(lng, 100)[OFFSET(50)]                 AS longitude,
    APPROX_TOP_COUNT(city_raw,   1)[OFFSET(0)].value       AS city_normalized,
    APPROX_TOP_COUNT(state_code, 1)[OFFSET(0)].value       AS state_code,
    COUNT(*)                                               AS raw_row_count
  FROM raw_geo
  GROUP BY zip_code_prefix
),
state_meta AS (
  SELECT * FROM UNNEST([
    STRUCT('AC' AS state_code, 'Acre'              AS state_name, 'North'     AS region, FALSE AS is_frontier_market),
    STRUCT('AL',               'Alagoas',                         'Northeast',            TRUE),
    STRUCT('AM',               'Amazonas',                        'North',                FALSE),
    STRUCT('AP',               'Amapá',                           'North',                FALSE),
    STRUCT('BA',               'Bahia',                           'Northeast',            TRUE),
    STRUCT('CE',               'Ceará',                           'Northeast',            TRUE),
    STRUCT('DF',               'Distrito Federal',                'Midwest',              TRUE),
    STRUCT('ES',               'Espírito Santo',                  'Southeast',            TRUE),
    STRUCT('GO',               'Goiás',                           'Midwest',              TRUE),
    STRUCT('MA',               'Maranhão',                        'Northeast',            FALSE),
    STRUCT('MG',               'Minas Gerais',                    'Southeast',            TRUE),
    STRUCT('MS',               'Mato Grosso do Sul',              'Midwest',              FALSE),
    STRUCT('MT',               'Mato Grosso',                     'Midwest',              FALSE),
    STRUCT('PA',               'Pará',                            'North',                FALSE),
    STRUCT('PB',               'Paraíba',                         'Northeast',            FALSE),
    STRUCT('PE',               'Pernambuco',                      'Northeast',            TRUE),
    STRUCT('PI',               'Piauí',                           'Northeast',            FALSE),
    STRUCT('PR',               'Paraná',                          'South',                TRUE),
    STRUCT('RJ',               'Rio de Janeiro',                  'Southeast',            TRUE),
    STRUCT('RN',               'Rio Grande do Norte',             'Northeast',            FALSE),
    STRUCT('RO',               'Rondônia',                        'North',                FALSE),
    STRUCT('RR',               'Roraima',                         'North',                FALSE),
    STRUCT('RS',               'Rio Grande do Sul',               'South',                TRUE),
    STRUCT('SC',               'Santa Catarina',                  'South',                TRUE),
    STRUCT('SE',               'Sergipe',                         'Northeast',            FALSE),
    STRUCT('SP',               'São Paulo',                       'Southeast',            TRUE),
    STRUCT('TO',               'Tocantins',                       'North',                FALSE)
  ])
)
SELECT
  FARM_FINGERPRINT(CAST(d.zip_code_prefix AS STRING)) AS geo_key,
  d.zip_code_prefix,
  LPAD(CAST(d.zip_code_prefix AS STRING), 5, '0')     AS zip_code_formatted,
  ROUND(d.latitude,  6)                               AS latitude,
  ROUND(d.longitude, 6)                               AS longitude,
  ST_GEOGPOINT(d.longitude, d.latitude)               AS geo_point,
  INITCAP(REPLACE(d.city_normalized, '-', ' '))        AS city,
  d.city_normalized,
  d.state_code,
  sm.state_name,
  sm.region,
  sm.is_frontier_market,
  CASE
    WHEN d.latitude < -15 AND d.longitude > -50 THEN 'Coastal'
    WHEN d.latitude > -5                         THEN 'Amazon Basin'
    WHEN d.latitude BETWEEN -15 AND -5           THEN 'Central Plateau'
    ELSE 'Southern Cone'
  END                                                 AS geographic_zone,
  d.raw_row_count,
  CURRENT_TIMESTAMP()                                 AS dw_inserted_at
FROM deduped d
LEFT JOIN state_meta sm ON d.state_code = sm.state_code
WHERE d.zip_code_prefix IS NOT NULL;


-- ─────────────────────────────────────────────────────────────────────────────
-- DimCustomer
-- Grain  : one row per customer_id
-- Purpose: customer attributes for segmentation; enriched by geo dimension
-- ─────────────────────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS `olist_analytics.DimCustomer`;
CREATE OR REPLACE TABLE `olist_analytics.DimCustomer`
CLUSTER BY state_code
OPTIONS (description = 'Customer dimension. One row per unique customer_id.')
AS
SELECT
  c.customer_id,
  c.customer_unique_id,
  CAST(c.customer_zip_code_prefix AS INT64)   AS zip_code_prefix,
  LOWER(TRIM(c.customer_city))                AS city,
  UPPER(TRIM(c.customer_state))               AS state_code,
  g.state_name,
  g.region,
  g.latitude                                  AS customer_lat,
  g.longitude                                 AS customer_lng,
  g.geographic_zone,
  g.is_frontier_market,
  CURRENT_TIMESTAMP()                         AS dw_inserted_at
FROM `olist_raw.raw_customers` c
LEFT JOIN `olist_analytics.DimGeography` g
  ON CAST(c.customer_zip_code_prefix AS INT64) = g.zip_code_prefix;


-- ─────────────────────────────────────────────────────────────────────────────
-- DimProduct
-- Grain  : one row per product_id
-- Purpose: product attributes including translated category names
-- ─────────────────────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS `olist_analytics.DimProduct`;
CREATE OR REPLACE TABLE `olist_analytics.DimProduct`
CLUSTER BY category_english
OPTIONS (description = 'Product dimension with translated category names.')
AS
SELECT
  p.product_id,
  p.product_category_name,
  COALESCE(t.product_category_name_english, p.product_category_name) AS category_english,
  p.product_name_lenght         AS product_name_length,
  p.product_description_lenght  AS product_description_length,
  p.product_photos_qty,
  p.product_weight_g,
  p.product_length_cm,
  p.product_height_cm,
  p.product_width_cm,
  ROUND(
    p.product_length_cm * p.product_height_cm * p.product_width_cm / 1000000, 4
  )                              AS volume_litres,
  CURRENT_TIMESTAMP()            AS dw_inserted_at
FROM `olist_raw.raw_products` p
LEFT JOIN `olist_raw.raw_category_translation` t
  USING (product_category_name);


-- ─────────────────────────────────────────────────────────────────────────────
-- DimSeller
-- Grain  : one row per seller_id
-- Purpose: seller attributes enriched with geo coordinates
-- ─────────────────────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS `olist_analytics.DimSeller`;
CREATE OR REPLACE TABLE `olist_analytics.DimSeller`
CLUSTER BY state_code
OPTIONS (description = 'Seller dimension enriched with geolocation.')
AS
SELECT
  s.seller_id,
  CAST(s.seller_zip_code_prefix AS INT64)  AS zip_code_prefix,
  LOWER(TRIM(s.seller_city))               AS city,
  UPPER(TRIM(s.seller_state))              AS state_code,
  g.state_name,
  g.region,
  g.latitude                               AS seller_lat,
  g.longitude                              AS seller_lng,
  g.geographic_zone,
  CURRENT_TIMESTAMP()                      AS dw_inserted_at
FROM `olist_raw.raw_sellers` s
LEFT JOIN `olist_analytics.DimGeography` g
  ON CAST(s.seller_zip_code_prefix AS INT64) = g.zip_code_prefix;


-- ─────────────────────────────────────────────────────────────────────────────
-- DimPaymentType
-- Grain  : one row per payment_type code
-- Purpose: payment method enrichment for FactPayments and FactOrders
-- ─────────────────────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS `olist_analytics.DimPaymentType`;
CREATE OR REPLACE TABLE `olist_analytics.DimPaymentType`
OPTIONS (description = 'Payment type dimension. One row per payment method code.')
AS
SELECT
  ROW_NUMBER() OVER (ORDER BY payment_type)        AS payment_type_key,
  payment_type                                     AS payment_type_code,
  CASE payment_type
    WHEN 'credit_card'  THEN 'Credit Card'
    WHEN 'boleto'       THEN 'Boleto Bancário'
    WHEN 'voucher'      THEN 'Voucher'
    WHEN 'debit_card'   THEN 'Debit Card'
    ELSE INITCAP(REPLACE(payment_type, '_', ' '))
  END                                              AS payment_type_name,
  CASE payment_type
    WHEN 'credit_card'  THEN 'Card'
    WHEN 'debit_card'   THEN 'Card'
    WHEN 'boleto'       THEN 'Bank Transfer'
    WHEN 'voucher'      THEN 'Voucher'
    ELSE 'Other'
  END                                              AS payment_category,
  CASE payment_type
    WHEN 'credit_card'  THEN TRUE
    WHEN 'debit_card'   THEN TRUE
    ELSE FALSE
  END                                              AS supports_installments,
  CASE payment_type
    WHEN 'boleto'       THEN TRUE
    ELSE FALSE
  END                                              AS is_offline_payment,
  CURRENT_TIMESTAMP()                              AS dw_inserted_at
FROM (
  SELECT DISTINCT payment_type
  FROM `olist_raw.raw_order_payments`
  WHERE payment_type != 'not_defined'
);


-- ─────────────────────────────────────────────────────────────────────────────
-- DimMarketingChannel
-- Grain  : one row per origin channel
-- Purpose: marketing attribution dimension
-- ─────────────────────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS `olist_analytics.DimMarketingChannel`;
CREATE OR REPLACE TABLE `olist_analytics.DimMarketingChannel`
OPTIONS (description = 'Marketing channel dimension derived from MQL origin field.')
AS
SELECT
  ROW_NUMBER() OVER (ORDER BY origin)  AS channel_key,
  origin                               AS channel_code,
  CASE origin
    WHEN 'paid_search'   THEN 'Paid Search'
    WHEN 'organic_search' THEN 'Organic Search'
    WHEN 'social'        THEN 'Social Media'
    WHEN 'email'         THEN 'Email'
    WHEN 'referral'      THEN 'Referral'
    WHEN 'direct_traffic' THEN 'Direct Traffic'
    WHEN 'display'       THEN 'Display Ads'
    WHEN 'other_publicities' THEN 'Other Paid'
    ELSE INITCAP(REPLACE(origin, '_', ' '))
  END                                  AS channel_name,
  CASE origin
    WHEN 'paid_search'   THEN 'Paid'
    WHEN 'organic_search' THEN 'Organic'
    WHEN 'social'        THEN 'Paid'
    WHEN 'email'         THEN 'Owned'
    WHEN 'referral'      THEN 'Earned'
    WHEN 'direct_traffic' THEN 'Organic'
    WHEN 'display'       THEN 'Paid'
    ELSE 'Other'
  END                                  AS channel_type,
  CURRENT_TIMESTAMP()                  AS dw_inserted_at
FROM (
  SELECT DISTINCT origin FROM `olist_raw.raw_marketing_qualified_leads`
  WHERE origin IS NOT NULL
);


-- =============================================================================
-- SECTION 2: FACT TABLES
-- Run after all dimension tables are populated.
-- =============================================================================


-- ─────────────────────────────────────────────────────────────────────────────
-- FactOrders
-- Grain  : one row per order
-- Joins  : DimDate, DimCustomer, DimGeography
-- ─────────────────────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS `olist_analytics.FactOrders`;
CREATE OR REPLACE TABLE `olist_analytics.FactOrders`
PARTITION BY purchase_date
CLUSTER BY customer_state, order_status
OPTIONS (description = 'Order-level fact table. Grain: one row per order_id.')
AS
WITH order_payments AS (
  SELECT
    order_id,
    SUM(payment_value)                                              AS total_payment_value,
    MAX(payment_installments)                                       AS max_installments,
    ARRAY_AGG(payment_type ORDER BY payment_value DESC LIMIT 1)[OFFSET(0)]
                                                                    AS primary_payment_type
  FROM `olist_raw.raw_order_payments`
  WHERE payment_type != 'not_defined'
  GROUP BY order_id
),
order_items_agg AS (
  SELECT
    order_id,
    COUNT(*)                           AS item_count,
    SUM(price)                         AS product_revenue,
    SUM(freight_value)                 AS freight_revenue,
    SUM(price + freight_value)         AS total_order_value,
    COUNT(DISTINCT seller_id)          AS seller_count,
    COUNT(DISTINCT product_id)         AS distinct_products
  FROM `olist_raw.raw_order_items`
  GROUP BY order_id
),
order_reviews AS (
  SELECT
    order_id,
    MAX(review_score) AS review_score
  FROM `olist_raw.raw_order_reviews`
  GROUP BY order_id
)
SELECT
  o.order_id,
  o.customer_id,
  DATE(o.order_purchase_timestamp)                 AS purchase_date,
  DATE(o.order_approved_at)                        AS approved_date,
  DATE(o.order_delivered_carrier_date)             AS carrier_date,
  DATE(o.order_delivered_customer_date)            AS delivered_date,
  DATE(o.order_estimated_delivery_date)            AS estimated_delivery_date,
  o.order_status,

  -- Metrics
  COALESCE(oi.item_count, 0)                       AS item_count,
  COALESCE(oi.distinct_products, 0)                AS distinct_products,
  COALESCE(oi.seller_count, 0)                     AS seller_count,
  COALESCE(oi.product_revenue, 0)                  AS product_revenue,
  COALESCE(oi.freight_revenue, 0)                  AS freight_revenue,
  COALESCE(oi.total_order_value, 0)                AS total_order_value,
  COALESCE(op.total_payment_value, 0)              AS total_payment_value,
  COALESCE(op.max_installments, 1)                 AS payment_installments,
  op.primary_payment_type,
  r.review_score,

  -- Derived delivery metrics
  DATE_DIFF(
    DATE(o.order_delivered_customer_date),
    DATE(o.order_purchase_timestamp),
    DAY
  )                                                AS actual_delivery_days,
  DATE_DIFF(
    DATE(o.order_estimated_delivery_date),
    DATE(o.order_purchase_timestamp),
    DAY
  )                                                AS estimated_delivery_days,
  CASE
    WHEN o.order_delivered_customer_date IS NULL THEN NULL
    WHEN o.order_delivered_customer_date <= o.order_estimated_delivery_date THEN TRUE
    ELSE FALSE
  END                                              AS is_on_time,

  -- Customer geography (denormalised for query performance)
  c.state_code                                     AS customer_state,
  c.region                                         AS customer_region,

  CURRENT_TIMESTAMP()                              AS dw_inserted_at
FROM `olist_raw.raw_orders` o
LEFT JOIN order_items_agg   oi ON o.order_id = oi.order_id
LEFT JOIN order_payments     op ON o.order_id = op.order_id
LEFT JOIN order_reviews      r  ON o.order_id = r.order_id
LEFT JOIN `olist_analytics.DimCustomer` c ON o.customer_id = c.customer_id;


-- ─────────────────────────────────────────────────────────────────────────────
-- FactOrderItems
-- Grain  : one row per (order_id, order_item_id)
-- Joins  : FactOrders, DimProduct, DimSeller, DimDate
-- ─────────────────────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS `olist_analytics.FactOrderItems`;
CREATE OR REPLACE TABLE `olist_analytics.FactOrderItems`
PARTITION BY shipping_limit_date
CLUSTER BY seller_id, product_id
OPTIONS (description = 'Order-item fact table. Grain: one row per (order_id, item_id).')
AS
SELECT
  oi.order_id,
  oi.order_item_id,
  oi.product_id,
  oi.seller_id,
  DATE(oi.shipping_limit_date)                     AS shipping_limit_date,
  ROUND(oi.price, 2)                               AS item_price,
  ROUND(oi.freight_value, 2)                       AS freight_value,
  ROUND(oi.price + oi.freight_value, 2)            AS item_total,
  p.category_english                               AS product_category,
  p.product_weight_g,
  s.state_code                                     AS seller_state,
  s.region                                         AS seller_region,
  o.purchase_date,
  o.order_status,
  o.customer_state,
  CURRENT_TIMESTAMP()                              AS dw_inserted_at
FROM `olist_raw.raw_order_items` oi
LEFT JOIN `olist_analytics.DimProduct`  p ON oi.product_id = p.product_id
LEFT JOIN `olist_analytics.DimSeller`   s ON oi.seller_id  = s.seller_id
LEFT JOIN `olist_analytics.FactOrders`  o ON oi.order_id   = o.order_id;


-- ─────────────────────────────────────────────────────────────────────────────
-- FactMarketingFunnel
-- Grain  : one row per mql_id
-- Joins  : DimMarketingChannel, DimDate
-- ─────────────────────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS `olist_analytics.FactMarketingFunnel`;
CREATE OR REPLACE TABLE `olist_analytics.FactMarketingFunnel`
PARTITION BY first_contact_date
CLUSTER BY channel_code, business_segment
OPTIONS (description = 'Marketing funnel fact. Grain: one row per MQL.')
AS
SELECT
  m.mql_id,
  m.landing_page_id,
  m.origin                                         AS channel_code,
  DATE(m.first_contact_date)                       AS first_contact_date,
  DATE(d.won_date)                                             AS won_date,
  d.seller_id,
  d.business_segment,
  d.lead_type,
  d.lead_behaviour_profile,
  d.business_type,
  COALESCE(d.declared_monthly_revenue, 0)          AS declared_monthly_revenue,
  CASE WHEN d.seller_id IS NOT NULL THEN TRUE ELSE FALSE END AS is_converted,
  DATE_DIFF(DATE(d.won_date), DATE(m.first_contact_date), DAY) AS days_to_close,
  CURRENT_TIMESTAMP()                              AS dw_inserted_at
FROM `olist_raw.raw_marketing_qualified_leads` m
LEFT JOIN `olist_raw.raw_closed_deals` d USING (mql_id);


-- ─────────────────────────────────────────────────────────────────────────────
-- FactPayments
-- Grain  : one row per (order_id, payment_sequential)
-- Joins  : FactOrders, DimDate
-- ─────────────────────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS `olist_analytics.FactPayments`;
CREATE OR REPLACE TABLE `olist_analytics.FactPayments`
CLUSTER BY payment_type
OPTIONS (description = 'Payment fact. Grain: one row per payment line (order × sequential).')
AS
SELECT
  p.order_id,
  p.payment_sequential,
  p.payment_type,
  p.payment_installments,
  ROUND(p.payment_value, 2)                        AS payment_value,
  o.purchase_date,
  o.customer_state,
  o.order_status,
  CURRENT_TIMESTAMP()                              AS dw_inserted_at
FROM `olist_raw.raw_order_payments` p
LEFT JOIN `olist_analytics.FactOrders` o ON p.order_id = o.order_id
WHERE p.payment_type != 'not_defined';
