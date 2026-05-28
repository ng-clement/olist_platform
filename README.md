# Olist Modern Data Platform

End-to-end analytics platform for the Brazilian Olist e-commerce dataset.
Covers the full lifecycle: raw CSV ingestion → BigQuery warehouse → DBT ELT →
data quality → business analytics → executive reporting.

**Dataset**: 99,441 orders · 96,096 customers · 3,095 sellers · 1M geolocation
rows · R$15.8M GMV · 2016–2018

---

## Repository Structure

```
olist_platform/
│
├── ingestion/                      # Data ingestion scripts
│   ├── ingest_to_bigquery.py       # Core datasets (orders, customers, products …)
│   └── ingest_geolocation.py       # Geolocation (1M rows, incremental/hash-gated)
│
├── warehouse/
│   └── schema.sql                  # Complete star schema DDL (7 dims + 4 facts)
│                                   # DimDate, DimGeography, DimCustomer, DimProduct
│                                   # DimSeller, DimPaymentType, DimMarketingChannel
│                                   # FactOrders, FactOrderItems, FactPayments,
│                                   # FactMarketingFunnel
│
├── dbt_project/                    # DBT transformation project
│   ├── dbt_project.yml             # Project config, materialization strategy
│   ├── packages.yml                # dbt_utils dependency
│   ├── profiles/
│   │   └── profiles.yml            # dev + prod BigQuery connection profiles
│   └── models/
│       ├── staging/                # Raw → clean layer (views)
│       │   ├── schema.yml          # Sources, model tests, column docs (all models)
│       │   ├── stg_orders.sql
│       │   ├── stg_geolocation.sql # Deduplicates 1M rows → 19K zip prefixes
│       │   └── … (stg_customers, stg_products, stg_sellers, stg_payments,
│       │          stg_reviews, stg_marketing_leads)
│       ├── intermediate/           # (reserved for cross-domain join logic)
│       └── marts/
│           ├── schema.yml          # Column docs + tests for all 7 marts
│           ├── core/
│           │   └── mart_monthly_revenue.sql
│           ├── customer/
│           │   └── mart_customer_lifetime_value.sql  # RFM + CLV
│           ├── seller/
│           │   └── mart_seller_performance.sql       # GMV tiers + performance score
│           ├── geography/
│           │   └── mart_geo_performance.sql          # State × month (incremental)
│           ├── marketing/
│           │   └── mart_marketing_funnel.sql         # Channel conversion + MoM
│           ├── logistics/
│           │   └── mart_logistics_performance.sql    # Delivery SLA + review delta
│           └── product/
│               └── mart_product_performance.sql      # Category GMV + tier ranking
│
├── data_quality/                   # Pre-load data quality validators (81 Python checks)
│   ├── dq_validation.py            # 51+ checks: nulls, duplicates, referential integrity,
│   │                               #   business logic (prices > 0, installs ≤ 24, dates)
│   └── dq_geolocation.py          # 30 checks: bounding box, state codes, city names,
│                                   #   statistical outliers, distribution validation
│
├── tests/                          # SQL integration tests (dbt test-paths)
│   ├── assert_no_orphaned_order_items.sql
│   ├── assert_payment_value_matches_order_value.sql
│   ├── assert_mart_row_counts_nonzero.sql
│   ├── assert_rfm_segments_cover_all_customers.sql
│   ├── assert_geo_coordinates_in_brazil.sql
│   └── assert_no_future_orders.sql
│
├── orchestration/
│   └── olist_pipeline_dag.py       # Airflow DAG: daily 06:00 UTC
│                                   # ingest → DQ → staging → 7 marts → test →
│                                   # analysis → archive → notify
│
├── notebooks/
│   └── olist_analysis.py           # Full analytics notebook (jupytext format)
│                                   # Revenue, RFM, funnel, geo, logistics,
│                                   # seller, payments — 8 chart outputs
│
├── scripts/
│   └── setup_bigquery.sh           # Creates BQ datasets + applies IAM bindings
│
├── data/
│   └── geo_lookup.csv              # 19,015-row zip → lat/lng/city/state lookup
│
├── docs/
│   ├── architecture/
│   │   └── pipeline_overview.md        # Architecture decisions, schema rationale,
│   │                                   # tool selection justifications, lineage diagram
│   ├── technical_specification.md      # Full technical spec: system overview,
│   │                                   # security & governance, deployment guide,
│   │                                   # testing strategy, future roadmap
│   ├── data_dictionary.md              # Column-level documentation for all tables:
│   │                                   # staging views, warehouse dims/facts, mart tables
│   │                                   # business glossary
│   ├── kpi_definitions.md              # Complete KPI catalogue: 17 KPIs across 7 domains
│   │                                   # formulas, benchmarks, targets, ownership
│   ├── data_quality_framework.md       # All 81+ quality rules documented: pre-load Python
│   │                                   # checks, DBT schema tests, SQL integration tests
│   └── presentation_transcript.md      # Speaker notes for all 12 presentation slides
│                                       # with Q&A preparation guide
│
├── dashboard/
│   └── index.html                  # Static executive KPI dashboard
│
├── logs/                           # Runtime audit logs (gitignored in production)
│
├── .env.example                    # Credential template — copy to .env and fill in
├── .gitignore                      # Excludes: .env, *.json keys, data/raw, logs
├── requirements.txt                # Python dependencies (pinned)
├── run_pipeline.sh                 # End-to-end pipeline runner (portable, venv-aware)
└── README.md
```

---

## Key Metrics

| KPI | Value |
|-----|-------|
| Total GMV | R$ 15.8M |
| Total Orders | 99,441 |
| Unique Customers | 96,096 |
| Avg Order Value | R$ 137.75 |
| On-Time Delivery | 91.9% |
| Avg Review Score | 4.09 / 5.0 |
| MQL Conversion Rate | 10.5% |
| Repeat Purchase Rate | 3.0% |

---

## Quick Start

### 1. Environment

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Credentials

```bash
cp .env.example .env
# Fill in GCP_PROJECT_ID, GOOGLE_APPLICATION_CREDENTIALS,
# GCS_BUCKET_NAME, MONGODB_URI, REDIS_HOST, REDIS_PASSWORD
```

### 3. Set up BigQuery (first time only)

```bash
bash scripts/setup_bigquery.sh
# Creates: olist_raw, olist_analytics, olist_analytics_staging, olist_analytics_marts
```

### 4. Ingest raw data into BigQuery

```bash
python ingestion/ingest_to_bigquery.py --data-dir /path/to/csvs --incremental
python ingestion/ingest_geolocation.py --source /path/to/olist_geolocation_dataset.csv
```

### 5. Create the warehouse schema

```bash
# Run schema.sql in the BigQuery console or via bq CLI
bq query --use_legacy_sql=false < warehouse/schema.sql
```

### 6. Run DBT

```bash
cd dbt_project
# Copy profiles.yml to ~/.dbt/ or set DBT_PROFILES_DIR
cp profiles/profiles.yml ~/.dbt/profiles.yml
dbt deps
dbt run
dbt test
```

### 7. Run data quality checks

```bash
python data_quality/dq_validation.py
python data_quality/dq_geolocation.py
```

### 8. Open the analytics notebook

```bash
# Convert to .ipynb first (requires jupytext)
jupytext --to notebook notebooks/olist_analysis.py
jupyter lab notebooks/olist_analysis.ipynb
```

### 9. Orchestration (Airflow)

```bash
export AIRFLOW_HOME=$(pwd)/airflow_home
airflow db init
airflow dags trigger olist_daily_pipeline
```

---

## Architecture

See [`docs/architecture/pipeline_overview.md`](docs/architecture/pipeline_overview.md)
for the full pipeline diagram, schema design rationale, tool selection decisions,
and data quality philosophy.

---

## Assignment
Module 2 — Big Data Engineering · May 2026
