-- Test: all geolocation coordinates in DimGeography must fall within Brazil's bounding box.
-- Catches rows that bypassed the coordinate filter during ingestion.

SELECT
    zip_code_prefix,
    latitude,
    longitude,
    state_code
FROM `{{ env_var('GCP_PROJECT_ID', 'olist-analytics-01') }}.olist_analytics.DimGeography`
WHERE
    latitude  NOT BETWEEN -35.0 AND 5.3
    OR longitude NOT BETWEEN -74.0 AND -28.0
