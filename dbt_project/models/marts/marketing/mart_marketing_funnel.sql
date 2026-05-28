-- Marketing Funnel Performance Mart
-- Grain: one row per (origin channel, first_contact_month)
-- Audience: CMO, marketing analytics, growth team
-- Answers: which channels convert best, where does the funnel drop off,
--          what is the avg deal size and days-to-close per channel?

{{
  config(
    materialized  = 'table',
    cluster_by    = ['origin', 'conversion_tier'],
    tags          = ['mart', 'marketing', 'daily']
  )
}}

WITH base AS (
    SELECT
        mql_id,
        origin,
        landing_page_id,
        first_contact_date,
        won_date,
        seller_id,
        business_segment,
        lead_type,
        lead_behaviour_profile,
        business_type,
        declared_monthly_revenue,
        is_converted,
        DATE_DIFF(won_date, first_contact_date, DAY)  AS days_to_close
    FROM {{ ref('stg_marketing_leads') }}
    WHERE origin IS NOT NULL
),

channel_monthly AS (
    SELECT
        origin,
        DATE_TRUNC(first_contact_date, MONTH)         AS cohort_month,
        EXTRACT(YEAR  FROM first_contact_date)         AS cohort_year,
        EXTRACT(MONTH FROM first_contact_date)         AS cohort_month_num,

        -- Volume
        COUNT(mql_id)                                  AS total_leads,
        COUNTIF(is_converted)                          AS converted_leads,
        COUNT(mql_id) - COUNTIF(is_converted)          AS dropped_leads,

        -- Conversion rate
        ROUND(
            SAFE_DIVIDE(COUNTIF(is_converted), COUNT(mql_id)) * 100, 2
        )                                              AS conversion_rate_pct,

        -- Deal quality (converted only)
        ROUND(AVG(CASE WHEN is_converted THEN days_to_close END), 1)
                                                       AS avg_days_to_close,
        MIN(CASE WHEN is_converted THEN days_to_close END)
                                                       AS min_days_to_close,
        MAX(CASE WHEN is_converted THEN days_to_close END)
                                                       AS max_days_to_close,
        ROUND(AVG(CASE WHEN is_converted THEN declared_monthly_revenue END), 2)
                                                       AS avg_declared_monthly_revenue,
        ROUND(SUM(CASE WHEN is_converted THEN declared_monthly_revenue ELSE 0 END), 2)
                                                       AS total_declared_monthly_revenue,

        -- Segment breakdown (most common among converted)
        APPROX_TOP_COUNT(
            CASE WHEN is_converted THEN business_segment END, 1
        )[SAFE_OFFSET(0)].value                        AS top_converted_segment,

        APPROX_TOP_COUNT(
            CASE WHEN is_converted THEN lead_type END, 1
        )[SAFE_OFFSET(0)].value                        AS top_converted_lead_type
    FROM base
    GROUP BY 1, 2, 3, 4
),

-- Channel-level all-time summary for tier ranking
channel_totals AS (
    SELECT
        origin,
        SUM(total_leads)                               AS all_time_leads,
        SUM(converted_leads)                           AS all_time_conversions,
        ROUND(
            SAFE_DIVIDE(SUM(converted_leads), SUM(total_leads)) * 100, 2
        )                                              AS all_time_conversion_pct
    FROM channel_monthly
    GROUP BY origin
),

channel_tier AS (
    SELECT
        origin,
        all_time_leads,
        all_time_conversions,
        all_time_conversion_pct,
        CASE
            WHEN all_time_conversion_pct >= 10 THEN 'High Converting'
            WHEN all_time_conversion_pct >= 5  THEN 'Mid Converting'
            ELSE                                    'Low Converting'
        END AS conversion_tier
    FROM channel_totals
),

-- Month-over-month lead volume growth per channel
with_mom AS (
    SELECT
        cm.*,
        LAG(cm.total_leads) OVER (
            PARTITION BY cm.origin ORDER BY cm.cohort_month
        )                                              AS prev_month_leads,
        ROUND(
            SAFE_DIVIDE(
                cm.total_leads - LAG(cm.total_leads) OVER (
                    PARTITION BY cm.origin ORDER BY cm.cohort_month
                ),
                NULLIF(LAG(cm.total_leads) OVER (
                    PARTITION BY cm.origin ORDER BY cm.cohort_month
                ), 0)
            ) * 100, 1
        )                                              AS mom_lead_growth_pct
    FROM channel_monthly cm
)

SELECT
    wm.origin,
    ct.conversion_tier,
    wm.cohort_month,
    wm.cohort_year,
    wm.cohort_month_num,
    wm.total_leads,
    wm.converted_leads,
    wm.dropped_leads,
    wm.conversion_rate_pct,
    wm.avg_days_to_close,
    wm.min_days_to_close,
    wm.max_days_to_close,
    wm.avg_declared_monthly_revenue,
    wm.total_declared_monthly_revenue,
    wm.top_converted_segment,
    wm.top_converted_lead_type,
    wm.prev_month_leads,
    wm.mom_lead_growth_pct,
    ct.all_time_leads,
    ct.all_time_conversions,
    ct.all_time_conversion_pct,
    CURRENT_TIMESTAMP()                                AS _dbt_updated_at
FROM with_mom wm
LEFT JOIN channel_tier ct USING (origin)
