-- Test: all key mart tables must have at least one row after a pipeline run.
-- A zero-row mart indicates a failed transformation or empty source.
-- Returns one row per empty mart on failure.

WITH mart_counts AS (
    SELECT 'mart_monthly_revenue'         AS mart, COUNT(*) AS row_count
    FROM `{{ env_var('GCP_PROJECT_ID', 'olist-analytics-01') }}.olist_analytics_marts.mart_monthly_revenue`
    UNION ALL
    SELECT 'mart_customer_lifetime_value', COUNT(*)
    FROM `{{ env_var('GCP_PROJECT_ID', 'olist-analytics-01') }}.olist_analytics_marts.mart_customer_lifetime_value`
    UNION ALL
    SELECT 'mart_seller_performance',      COUNT(*)
    FROM `{{ env_var('GCP_PROJECT_ID', 'olist-analytics-01') }}.olist_analytics_marts.mart_seller_performance`
    UNION ALL
    SELECT 'mart_marketing_funnel',        COUNT(*)
    FROM `{{ env_var('GCP_PROJECT_ID', 'olist-analytics-01') }}.olist_analytics_marts.mart_marketing_funnel`
    UNION ALL
    SELECT 'mart_product_performance',     COUNT(*)
    FROM `{{ env_var('GCP_PROJECT_ID', 'olist-analytics-01') }}.olist_analytics_marts.mart_product_performance`
)
SELECT mart, row_count
FROM mart_counts
WHERE row_count = 0
