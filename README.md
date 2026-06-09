# Olist Modern Data Platform

End-to-end analytics platform for the Brazilian Olist e-commerce dataset.
Covers the full lifecycle: raw CSV ingestion → BigQuery warehouse → dbt ELT →
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
├── dbt_project/                    # dbt transformation project
│   ├── dbt_project.yml             # Project config, materialisation strategy
│   ├── packages.yml                # dbt_utils dependency
│   ├── profiles/
│   │   └── profiles.yml            # dev + prod BigQuery connection profiles
│   ├── models/
│   │   ├── staging/                # Raw → clean layer (views)
│   │   │   ├── schema.yml          # Sources, model tests, column docs (all models)
│   │   │   ├── stg_orders.sql
│   │   │   ├── stg_geolocation.sql # Deduplicates 1M rows → 19K zip prefixes
│   │   │   └── … (stg_customers, stg_products, stg_sellers, stg_payments,
│   │   │          stg_reviews, stg_marketing_leads)
│   │   ├── intermediate/           # (reserved for cross-domain join logic)
│   │   └── marts/
│   │       ├── schema.yml          # Column docs + tests for all 7 marts
│   │       ├── core/mart_monthly_revenue.sql
│   │       ├── customer/mart_customer_lifetime_value.sql   # RFM + CLV
│   │       ├── seller/mart_seller_performance.sql          # GMV tiers + score
│   │       ├── geography/mart_geo_performance.sql          # State × month (incremental)
│   │       ├── marketing/mart_marketing_funnel.sql         # Channel conversion + MoM
│   │       ├── logistics/mart_logistics_performance.sql    # Delivery SLA + review delta
│   │       └── product/mart_product_performance.sql        # Category GMV + tier ranking
│   └── tests/                      # SQL integration tests (dbt singular tests)
│       ├── assert_no_orphaned_order_items.sql
│       ├── assert_payment_value_matches_order_value.sql
│       ├── assert_mart_row_counts_nonzero.sql
│       ├── assert_rfm_segments_cover_all_customers.sql
│       ├── assert_geo_coordinates_in_brazil.sql
│       └── assert_no_future_orders.sql
│
├── data_quality/                   # Pre-load data quality validators (87+ Python checks)
│   ├── dq_validation.py            # 57+ checks: nulls, duplicates, referential integrity,
│   │                               #   business logic (prices > 0, installs ≤ 24, dates)
│   └── dq_geolocation.py          # 30 checks: bounding box, state codes, city names,
│                                   #   statistical outliers, distribution validation
│
├── orchestration/
│   ├── dagster/                    # Dagster asset-based orchestration (primary)
│   │   ├── assets/                 # Meltano + dbt asset definitions
│   │   ├── resources.py            # PROD_RESOURCES (BigQuery, dbt)
│   │   └── __init__.py             # Definitions: assets + schedules
│   └── olist_pipeline_dag.py       # Legacy Airflow DAG (reference only)
│
├── .github/workflows/
│   ├── pipeline-daily.yml          # Daily ELT: 02:00 SGT full · 06:00 SGT dbt-only
│   ├── dbt-ci.yml                  # PR: slim-CI dbt run + test
│   ├── ci.yml                      # PR: ruff lint + format check
│   └── deploy-dashboard.yml        # Publish dashboard/index.html to GitHub Pages
│
├── scripts/
│   ├── run_schema.py               # Apply warehouse/schema.sql DDL to BigQuery
│   ├── setup_bigquery.sh           # Creates BQ datasets + applies IAM bindings
│   ├── check_bq_datasets.py        # Pre-flight: verify required datasets exist
│   └── build_slides.py             # Generates olist_platform_slides.pptx
│
├── notebooks/
│   └── olist_analysis.py           # Full analytics notebook (jupytext format)
│                                   # Revenue, RFM, funnel, geo, logistics,
│                                   # seller, payments — 8 chart outputs
│
├── dashboard/
│   └── index.html                  # Static executive KPI dashboard
│
├── data/
│   └── geo_lookup.csv              # 19,015-row zip → lat/lng/city/state lookup
│
│
├── logs/                           # Runtime audit logs (gitignored)
│
├── .env                            # Credentials — copy from .env.example, never commit
├── .gitignore
├── meltano.yml                     # Meltano ELT config (tap-csv + target-bigquery)
├── olist-environment.yml           # Conda environment definition
├── requirements.txt                # Python dependencies (pinned)
├── ruff.toml                       # Ruff linter + formatter config
├── run_pipeline.sh                 # End-to-end pipeline runner (7 steps, idempotent)
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

Or with Conda:

```bash
conda env create -f olist-environment.yml
conda activate olist
```

### 2. Credentials

```bash
cp .env.example .env
# Fill in:
#   GCP_PROJECT_ID=olist-analytics-01
#   GOOGLE_APPLICATION_CREDENTIALS=/path/to/olist-analytics-gcp-key.json
#   GCS_BUCKET_NAME=olist-bucket-01
```

### 3. Set up BigQuery (first time only)

```bash
bash scripts/setup_bigquery.sh
# Creates: olist_raw, olist_analytics, olist_analytics_staging, olist_analytics_marts
```

### 4. Run the full pipeline (single command)

```bash
./run_pipeline.sh
```

This runs all 7 steps in sequence: DQ validation → geolocation DQ → ingest → geolocation ingest → star schema DDL → dbt run + test → analytics charts.

For an append-only incremental ingest:

```bash
./run_pipeline.sh --incremental   # prompts for confirmation before appending
```

---

## Running Steps Individually

### Data quality checks

```bash
python data_quality/dq_validation.py    # 57+ checks on core datasets
python data_quality/dq_geolocation.py   # 30 checks on geolocation
```

### Ingest raw CSVs to BigQuery

```bash
# Uses DATA_DIR env var (default: data/raw/) and credentials from .env
python ingestion/ingest_to_bigquery.py
python ingestion/ingest_geolocation.py

# Flags
python ingestion/ingest_to_bigquery.py --incremental   # WRITE_APPEND mode
python ingestion/ingest_to_bigquery.py --dry-run       # validate without loading
python ingestion/ingest_to_bigquery.py --datasets orders customers  # subset
```

### Apply warehouse schema

```bash
python scripts/run_schema.py
# Executes warehouse/schema.sql against BigQuery (olist_analytics dataset)
```

### Run dbt

```bash
cd dbt_project
dbt deps --profiles-dir profiles
dbt run  --profiles-dir profiles --target prod
dbt test --profiles-dir profiles --target prod

# Subsets
dbt run  --select tag:staging --profiles-dir profiles --target prod
dbt test --select "test_type:singular" --profiles-dir profiles --target prod
```

### Analytics notebook

```bash
# Run as a script (generates reports/charts/*.png)
python notebooks/olist_analysis.py

# Or convert to Jupyter notebook (requires jupytext)
jupytext --to notebook notebooks/olist_analysis.py
jupyter lab notebooks/olist_analysis.ipynb
```

---

## Orchestration

### Dagster (primary — local and scheduled)

```bash
# Developer mode: file-watching, hot reload, UI at http://localhost:3000
dagster dev -m orchestration.dagster

# Production mode: persistent daemon + separate webserver
dagster-daemon run &
dagster-webserver -h 0.0.0.0 -p 3000 -w workspace.yaml &
```

The Dagster schedule fires at **06:00 UTC daily** (`DefaultScheduleStatus.STOPPED` — must be
enabled once in the UI or via CLI). All assets write to production BigQuery regardless of
launch mode (`PROD_RESOURCES` is hardcoded in `orchestration/dagster/__init__.py`).

### GitHub Actions (CI/CD — cloud scheduled)

Four workflows under `.github/workflows/`:

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `pipeline-daily.yml` | Cron 02:00 SGT + manual | Full ELT: DQ → ingest → schema → dbt → tests |
| `dbt-ci.yml` | Pull request | Slim-CI: only changed dbt models |
| `ci.yml` | Pull request | ruff lint + format |
| `deploy-dashboard.yml` | Push to main | Publish dashboard to GitHub Pages |

Required GitHub Secrets: `GCP_SERVICE_ACCOUNT_KEY`, `SLACK_WEBHOOK_URL` (optional).  
Required GitHub Variables: `GCP_PROJECT_ID`, `GCS_BUCKET_NAME`.

---

---

## Assignment

Module 2 — Big Data Engineering · May 2026
