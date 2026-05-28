-- Test: every order_id in FactOrderItems must exist in FactOrders.
-- Returns rows on failure (DBT convention: 0 rows = pass).

SELECT oi.order_id
FROM `{{ env_var('GCP_PROJECT_ID', 'olist-analytics-01') }}.olist_analytics.FactOrderItems` oi
LEFT JOIN `{{ env_var('GCP_PROJECT_ID', 'olist-analytics-01') }}.olist_analytics.FactOrders`  fo
  ON oi.order_id = fo.order_id
WHERE fo.order_id IS NULL
