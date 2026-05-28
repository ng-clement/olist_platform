-- Test: every customer in mart_customer_lifetime_value must have a non-null rfm_segment.
-- Catches NULL-falling-through edge cases in the NTILE + CASE segmentation logic.

SELECT customer_unique_id
FROM `{{ env_var('GCP_PROJECT_ID', 'olist-analytics-01') }}.olist_analytics_marts.mart_customer_lifetime_value`
WHERE rfm_segment IS NULL
   OR value_tier IS NULL
