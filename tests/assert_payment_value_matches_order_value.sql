-- Test: for delivered orders, total payment_value should be within 1% of total_order_value.
-- Catches transformation bugs where payment aggregation diverges from item totals.
-- Returns rows on failure.

WITH payment_totals AS (
    SELECT order_id, SUM(payment_value) AS sum_paid
    FROM `{{ env_var('GCP_PROJECT_ID', 'olist-analytics-01') }}.olist_analytics.FactPayments`
    GROUP BY order_id
)
SELECT
    fo.order_id,
    fo.total_order_value,
    pt.sum_paid,
    ABS(fo.total_order_value - pt.sum_paid) / NULLIF(fo.total_order_value, 0) AS pct_diff
FROM `{{ env_var('GCP_PROJECT_ID', 'olist-analytics-01') }}.olist_analytics.FactOrders` fo
JOIN payment_totals pt USING (order_id)
WHERE fo.order_status = 'delivered'
  AND fo.total_order_value > 0
  AND ABS(fo.total_order_value - pt.sum_paid) / fo.total_order_value > 0.01
