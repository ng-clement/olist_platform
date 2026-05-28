-- Test: no order_purchase_timestamp should exceed the dataset's known end date (2018-12-31).
-- Catches data loading errors or timezone conversion bugs.

SELECT order_id, purchase_date
FROM `{{ env_var('GCP_PROJECT_ID', 'olist-analytics-01') }}.olist_analytics.FactOrders`
WHERE purchase_date > DATE '{{ var("project_end_date") }}'
