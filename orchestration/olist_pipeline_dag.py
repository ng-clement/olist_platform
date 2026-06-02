"""
orchestration/olist_pipeline_dag.py
=====================================
Apache Airflow DAG orchestrating the complete Olist analytics pipeline.

All paths are resolved at runtime from Airflow Variables (set once in the UI):
  project_root   — absolute path to the olist_platform/ folder on the Airflow host
  gcp_project    — GCP project ID
  gcs_bucket     — GCS bucket name
  mongodb_uri    — MongoDB connection string
  slack_webhook  — Slack incoming webhook URL
  geo_source_path— optional override for geolocation CSV path

Schedule  : Daily at 06:00 UTC
SLA       : Must complete within 90 minutes (by 07:30 UTC)
"""

from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
from airflow.utils.trigger_rule import TriggerRule

DEFAULT_ARGS = {
    "owner": "data-engineering",
    "depends_on_past": False,
    "email": ["data-alerts@company.com"],
    "email_on_failure": True,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=30),
}

# ── Resolved at runtime from Airflow Variables ────────────────────────────────
ROOT = "{{ var.value.project_root }}"  # e.g. /home/user/olist_platform
PYTHON = f"cd {ROOT} && python"
DBT = f"cd {ROOT}/dbt_project && dbt"

with DAG(
    dag_id="olist_daily_pipeline",
    default_args=DEFAULT_ARGS,
    description="Olist end-to-end analytics pipeline: ingest → quality → transform → export",
    schedule_interval="0 6 * * *",
    start_date=pendulum.datetime(2024, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["olist", "production", "daily"],
) as dag:
    # ── 0. Bookends ───────────────────────────────────────────────────────────
    start = EmptyOperator(task_id="pipeline_start")
    end = EmptyOperator(
        task_id="pipeline_end",
        trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS,
    )

    # ── 1a. Core ingestion ────────────────────────────────────────────────────
    ingest_core = BashOperator(
        task_id="ingest_core_datasets",
        bash_command=f"{PYTHON} ingestion/ingest_to_bigquery.py",
        execution_timeout=timedelta(minutes=30),
        doc_md="Loads all core Olist CSVs from data/raw/ into BigQuery olist_raw.",
    )

    # ── 1b. Geolocation ingestion ─────────────────────────────────────────────
    ingest_geo = BashOperator(
        task_id="ingest_geolocation",
        bash_command=f"{PYTHON} ingestion/ingest_geolocation.py --mode incremental",
        execution_timeout=timedelta(minutes=20),
        doc_md="Loads geolocation CSV from data/raw/ — skips if file hash unchanged.",
    )

    # ── 2. Data quality ───────────────────────────────────────────────────────
    dq_core = BashOperator(
        task_id="dq_validate_core",
        bash_command=(
            f"{PYTHON} data_quality/dq_validation.py "
            f"2>&1 | tee {ROOT}/logs/dq_core_{{{{ ds }}}}.log"
        ),
        execution_timeout=timedelta(minutes=15),
    )

    dq_geo = BashOperator(
        task_id="dq_validate_geolocation",
        bash_command=(
            f"{PYTHON} data_quality/dq_geolocation.py "
            f"2>&1 | tee {ROOT}/logs/dq_geo_{{{{ ds }}}}.log"
        ),
        execution_timeout=timedelta(minutes=10),
    )

    dq_gate = EmptyOperator(task_id="dq_gate")

    # ── 3. Star schema DDL ────────────────────────────────────────────────────
    build_schema = BashOperator(
        task_id="build_star_schema",
        bash_command=f"{PYTHON} scripts/run_schema.py",
        execution_timeout=timedelta(minutes=15),
        doc_md="Build dimension and fact tables (DimDate, DimGeography, FactOrders, etc.).",
    )

    # ── 4. DBT Staging ────────────────────────────────────────────────────────
    dbt_stg_core = BashOperator(
        task_id="dbt_staging_core",
        bash_command=f"{DBT} run --select tag:staging --exclude stg_geolocation --target prod",
        execution_timeout=timedelta(minutes=20),
    )

    dbt_stg_geo = BashOperator(
        task_id="dbt_staging_geolocation",
        bash_command=f"{DBT} run --select stg_geolocation --target prod",
        execution_timeout=timedelta(minutes=10),
    )

    staging_gate = EmptyOperator(task_id="staging_gate")

    # ── 4. DBT Marts ──────────────────────────────────────────────────────────
    dbt_mart_revenue = BashOperator(
        task_id="dbt_mart_monthly_revenue",
        bash_command=f"{DBT} run --select mart_monthly_revenue --target prod",
        execution_timeout=timedelta(minutes=10),
    )
    dbt_mart_clv = BashOperator(
        task_id="dbt_mart_customer_clv",
        bash_command=f"{DBT} run --select mart_customer_lifetime_value --target prod",
        execution_timeout=timedelta(minutes=10),
    )
    dbt_mart_geo = BashOperator(
        task_id="dbt_mart_geo_performance",
        bash_command=f"{DBT} run --select mart_geo_performance --target prod",
        execution_timeout=timedelta(minutes=10),
    )
    dbt_mart_seller = BashOperator(
        task_id="dbt_mart_seller_performance",
        bash_command=f"{DBT} run --select mart_seller_performance --target prod",
        execution_timeout=timedelta(minutes=10),
    )
    dbt_mart_marketing = BashOperator(
        task_id="dbt_mart_marketing_funnel",
        bash_command=f"{DBT} run --select mart_marketing_funnel --target prod",
        execution_timeout=timedelta(minutes=10),
    )
    dbt_mart_logistics = BashOperator(
        task_id="dbt_mart_logistics_performance",
        bash_command=f"{DBT} run --select mart_logistics_performance --target prod",
        execution_timeout=timedelta(minutes=10),
    )
    dbt_mart_product = BashOperator(
        task_id="dbt_mart_product_performance",
        bash_command=f"{DBT} run --select mart_product_performance --target prod",
        execution_timeout=timedelta(minutes=10),
    )

    marts_gate = EmptyOperator(task_id="marts_gate")

    # ── 5. DBT Tests ──────────────────────────────────────────────────────────
    dbt_test = BashOperator(
        task_id="dbt_test_all",
        bash_command=f"{DBT} test --target prod",
        execution_timeout=timedelta(minutes=20),
    )

    # ── 6. Analysis notebook ──────────────────────────────────────────────────
    run_analysis = BashOperator(
        task_id="run_analysis_notebook",
        bash_command=f"{PYTHON} notebooks/olist_analysis.py",
        execution_timeout=timedelta(minutes=20),
    )

    # ── 7. Archive to GCS ─────────────────────────────────────────────────────
    archive_gcs = BashOperator(
        task_id="archive_to_gcs",
        bash_command=(
            "bq extract --destination_format NEWLINE_DELIMITED_JSON "
            "'{{{{ var.value.gcp_project }}}}:olist_analytics.FactOrders' "
            "gs://{{{{ var.value.gcs_bucket }}}}/olist/archive/{{{{ ds }}}}/orders_*.jsonl"
        ),
        execution_timeout=timedelta(minutes=15),
    )

    # ── 8. Notifications ──────────────────────────────────────────────────────
    notify_ok = BashOperator(
        task_id="notify_success",
        bash_command=(
            "curl -s -X POST {{{{ var.value.slack_webhook }}}} "
            '-d \'{"text": "✅ olist_daily_pipeline completed — {{{{ ds }}}}"}\''
        ),
        trigger_rule=TriggerRule.ALL_SUCCESS,
    )
    notify_fail = BashOperator(
        task_id="notify_failure",
        bash_command=(
            "curl -s -X POST {{{{ var.value.slack_webhook }}}} "
            '-d \'{"text": "❌ olist_daily_pipeline FAILED — {{{{ ds }}}} — check logs"}\''
        ),
        trigger_rule=TriggerRule.ONE_FAILED,
    )

    # ── Dependency graph ──────────────────────────────────────────────────────
    start >> [ingest_core, ingest_geo]
    ingest_core >> dq_core
    ingest_geo >> dq_geo
    [dq_core, dq_geo] >> dq_gate
    dq_gate >> [build_schema, dbt_stg_core, dbt_stg_geo]
    [build_schema, dbt_stg_core, dbt_stg_geo] >> staging_gate
    staging_gate >> [
        dbt_mart_revenue,
        dbt_mart_clv,
        dbt_mart_geo,
        dbt_mart_seller,
        dbt_mart_marketing,
        dbt_mart_logistics,
        dbt_mart_product,
    ]
    [
        dbt_mart_revenue,
        dbt_mart_clv,
        dbt_mart_geo,
        dbt_mart_seller,
        dbt_mart_marketing,
        dbt_mart_logistics,
        dbt_mart_product,
    ] >> marts_gate
    marts_gate >> dbt_test
    dbt_test >> [run_analysis, archive_gcs]
    [run_analysis, archive_gcs] >> [notify_ok, notify_fail]
    [notify_ok, notify_fail] >> end
