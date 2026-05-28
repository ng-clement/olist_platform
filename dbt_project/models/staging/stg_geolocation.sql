-- stg_geolocation.sql
-- Stage raw geolocation data from BigQuery external table.
-- Deduplicates 1M rows to ~19K unique zip code prefixes.
-- Grain: one row per geolocation_zip_code_prefix

{{
    config(
        materialized = 'table',
        cluster_by   = ["state_code", "region"],
        tags         = ["geography", "dimension"],
        meta = {
            "owner": "data_engineering",
            "description": "Deduplicated and validated geolocation dimension",
            "source_rows": "~1,000,163",
            "output_rows": "~19,015"
        }
    )
}}

WITH source AS (
    SELECT
        CAST(geolocation_zip_code_prefix AS INT64)  AS zip_code_prefix,
        geolocation_lat                             AS latitude_raw,
        geolocation_lng                             AS longitude_raw,
        TRIM(LOWER(geolocation_city))               AS city_raw,
        UPPER(TRIM(geolocation_state))              AS state_code
    FROM {{ source('olist_raw', 'geolocation') }}
    WHERE geolocation_zip_code_prefix IS NOT NULL
),

bounds_filtered AS (
    -- Remove the ~29 rows with coordinates outside Brazil
    SELECT *
    FROM source
    WHERE
        latitude_raw  BETWEEN -35.0 AND 5.3
        AND longitude_raw BETWEEN -74.0 AND -28.0
        AND state_code IN (
            'AC','AL','AM','AP','BA','CE','DF','ES','GO','MA',
            'MG','MS','MT','PA','PB','PE','PI','PR','RJ','RN',
            'RO','RR','RS','SC','SE','SP','TO'
        )
),

deduped AS (
    SELECT
        zip_code_prefix,
        APPROX_QUANTILES(latitude_raw,  100)[OFFSET(50)]            AS latitude,
        APPROX_QUANTILES(longitude_raw, 100)[OFFSET(50)]            AS longitude,
        APPROX_TOP_COUNT(city_raw,   1)[OFFSET(0)].value            AS city,
        APPROX_TOP_COUNT(state_code, 1)[OFFSET(0)].value            AS state_code,
        COUNT(*)                                                     AS raw_row_count
    FROM bounds_filtered
    GROUP BY zip_code_prefix
),

enriched AS (
    SELECT
        d.zip_code_prefix,
        LPAD(CAST(d.zip_code_prefix AS STRING), 5, '0')             AS zip_code_formatted,
        ROUND(d.latitude,  6)                                        AS latitude,
        ROUND(d.longitude, 6)                                        AS longitude,
        INITCAP(REPLACE(d.city, '-', ' '))                          AS city,
        d.city                                                       AS city_normalized,
        d.state_code,

        -- State full name lookup
        CASE d.state_code
            WHEN 'AC' THEN 'Acre'               WHEN 'AL' THEN 'Alagoas'
            WHEN 'AM' THEN 'Amazonas'           WHEN 'AP' THEN 'Amapá'
            WHEN 'BA' THEN 'Bahia'              WHEN 'CE' THEN 'Ceará'
            WHEN 'DF' THEN 'Distrito Federal'   WHEN 'ES' THEN 'Espírito Santo'
            WHEN 'GO' THEN 'Goiás'              WHEN 'MA' THEN 'Maranhão'
            WHEN 'MG' THEN 'Minas Gerais'       WHEN 'MS' THEN 'Mato Grosso do Sul'
            WHEN 'MT' THEN 'Mato Grosso'        WHEN 'PA' THEN 'Pará'
            WHEN 'PB' THEN 'Paraíba'            WHEN 'PE' THEN 'Pernambuco'
            WHEN 'PI' THEN 'Piauí'              WHEN 'PR' THEN 'Paraná'
            WHEN 'RJ' THEN 'Rio de Janeiro'     WHEN 'RN' THEN 'Rio Grande do Norte'
            WHEN 'RO' THEN 'Rondônia'           WHEN 'RR' THEN 'Roraima'
            WHEN 'RS' THEN 'Rio Grande do Sul'  WHEN 'SC' THEN 'Santa Catarina'
            WHEN 'SE' THEN 'Sergipe'            WHEN 'SP' THEN 'São Paulo'
            WHEN 'TO' THEN 'Tocantins'          ELSE 'Unknown'
        END                                                          AS state_name,

        -- Region classification
        CASE d.state_code
            WHEN 'SP' THEN 'Southeast' WHEN 'RJ' THEN 'Southeast'
            WHEN 'MG' THEN 'Southeast' WHEN 'ES' THEN 'Southeast'
            WHEN 'RS' THEN 'South'     WHEN 'PR' THEN 'South'
            WHEN 'SC' THEN 'South'
            WHEN 'GO' THEN 'Midwest'   WHEN 'DF' THEN 'Midwest'
            WHEN 'MT' THEN 'Midwest'   WHEN 'MS' THEN 'Midwest'
            WHEN 'BA' THEN 'Northeast' WHEN 'PE' THEN 'Northeast'
            WHEN 'CE' THEN 'Northeast' WHEN 'MA' THEN 'Northeast'
            WHEN 'PB' THEN 'Northeast' WHEN 'RN' THEN 'Northeast'
            WHEN 'AL' THEN 'Northeast' WHEN 'PI' THEN 'Northeast'
            WHEN 'SE' THEN 'Northeast'
            ELSE 'North'
        END                                                          AS region,

        -- Business flags
        CASE d.state_code
            WHEN 'AC' THEN FALSE WHEN 'AL' THEN FALSE WHEN 'AM' THEN FALSE
            WHEN 'AP' THEN FALSE WHEN 'MA' THEN FALSE WHEN 'PB' THEN FALSE
            WHEN 'RN' THEN FALSE WHEN 'RO' THEN FALSE WHEN 'RR' THEN FALSE
            WHEN 'TO' THEN FALSE ELSE TRUE
        END                                                          AS high_ecomm_penetration,

        -- Geographic zone
        CASE
            WHEN d.latitude < -15 AND d.longitude > -50 THEN 'Coastal'
            WHEN d.latitude > -5  THEN 'Amazon Basin'
            WHEN d.latitude BETWEEN -15 AND -5 THEN 'Central Plateau'
            ELSE 'Southern Cone'
        END                                                          AS geographic_zone,

        d.raw_row_count,
        CURRENT_TIMESTAMP()                                          AS _dbt_loaded_at

    FROM deduped d
)

SELECT * FROM enriched
