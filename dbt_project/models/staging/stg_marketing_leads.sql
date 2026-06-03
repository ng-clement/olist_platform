{{ config(materialized='view', tags=['staging']) }}

SELECT
    m.mql_id,
    m.landing_page_id,
    m.origin,
    DATE(m.first_contact_date)               AS first_contact_date,
    d.seller_id,
    DATE(d.won_date)                         AS won_date,
    d.business_segment,
    d.lead_type,
    d.lead_behaviour_profile,
    d.business_type,
    COALESCE(SAFE_CAST(d.declared_monthly_revenue AS FLOAT64), 0) AS declared_monthly_revenue,
    d.seller_id IS NOT NULL                                   AS is_converted,
    CURRENT_TIMESTAMP()                      AS _stg_loaded_at
FROM {{ source('olist_raw', 'marketing_qualified_leads') }} m
LEFT JOIN {{ source('olist_raw', 'closed_deals') }} d USING (mql_id)
WHERE m.mql_id IS NOT NULL
