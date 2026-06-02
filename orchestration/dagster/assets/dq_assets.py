"""
orchestration/dagster/assets/dq_assets.py
==========================================
Data Quality gate assets.

Both assets run BEFORE dbt transformation. A CRITICAL failure (non-zero exit)
raises Failure, which Dagster marks as an error and blocks all downstream
assets — dbt staging, star schema, marts, and analytics will not run.

WARNING-level failures (exit 0 but with logged warnings) are surfaced as
Dagster metadata on the materialisation and monitored via Dagster alerting.
"""

import os
import re
import subprocess
from pathlib import Path

from dagster import (
    AssetExecutionContext,
    Failure,
    MetadataValue,
    Output,
    asset,
)
from google.api_core.exceptions import GoogleAPIError
from google.cloud import bigquery

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env", override=False)

_REQUIRED_DATASETS = [
    ("olist_raw",               "Raw ingestion layer — all source CSVs loaded here"),
    ("olist_analytics",         "Star schema — dimension and fact tables"),
    ("olist_analytics_staging", "dbt staging views"),
    ("olist_analytics_marts",   "dbt mart tables (pre-aggregated KPIs)"),
]


# ── Asset 0: BigQuery dataset readiness ───────────────────────────────────────

@asset(
    group_name="data_quality",
    compute_kind="bigquery",
    description=(
        "Ensure all 4 required BigQuery datasets exist before any data moves. "
        "Creates missing datasets automatically (exists_ok=True — idempotent). "
        "Replaces the interactive Step 0 check from run_pipeline.sh."
    ),
)
def bq_datasets_ready(context: AssetExecutionContext) -> Output[None]:
    project = os.environ.get("GCP_PROJECT_ID")
    if not project:
        raise Failure("GCP_PROJECT_ID is not set — cannot verify BigQuery datasets.")

    region = os.environ.get("GCP_REGION", "US")
    client = bigquery.Client(project=project)
    created, existing = [], []

    try:
        for ds_id, desc in _REQUIRED_DATASETS:
            ds_ref = f"{project}.{ds_id}"
            try:
                client.get_dataset(ds_ref)
                existing.append(ds_id)
                context.log.info("Dataset exists: %s", ds_id)
            except Exception:
                ds = bigquery.Dataset(ds_ref)
                ds.location = region
                ds.description = desc
                client.create_dataset(ds, exists_ok=True)
                created.append(ds_id)
                context.log.info("Created dataset: %s", ds_id)
    except GoogleAPIError as exc:
        raise Failure(f"BigQuery API error during dataset check: {exc}") from exc

    return Output(
        value=None,
        metadata={
            "project": MetadataValue.text(project),
            "region": MetadataValue.text(region),
            "datasets_existing": MetadataValue.int(len(existing)),
            "datasets_created": MetadataValue.int(len(created)),
            "created_list": MetadataValue.text(", ".join(created) or "none"),
        },
    )


def _run_dq(script: str, context: AssetExecutionContext, timeout: int = 900) -> tuple[int, str]:
    """Run a DQ script and return (returncode, stdout)."""
    result = subprocess.run(
        ["python", script],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.stdout:
        context.log.info(result.stdout)
    if result.stderr:
        context.log.warning(result.stderr[-1000:])
    return result.returncode, result.stdout


def _parse_core_summary(stdout: str) -> dict:
    """Extract pass/fail counts from dq_validation.py output."""
    metadata: dict = {}
    for label, key in [
        ("Total checks", "total_checks"),
        ("Passed", "checks_passed"),
        ("Failed", "checks_failed"),
    ]:
        m = re.search(rf"{label}\s*:\s*(\d+)", stdout)
        if m:
            metadata[key] = MetadataValue.int(int(m.group(1)))
    return metadata


# ── Asset 1: Core dataset validation ──────────────────────────────────────────

@asset(
    group_name="data_quality",
    compute_kind="python",
    deps=[bq_datasets_ready],
    description=(
        "Run 57+ pre-load DQ checks on olist_raw core datasets. "
        "Covers: null rates, duplicate PKs, referential integrity "
        "(order_items → orders → customers → products → sellers), "
        "business logic (prices > 0, installments ≤ 24, won_date ≥ first_contact_date). "
        "CRITICAL failures halt the pipeline."
    ),
)
def dq_core_validation(context: AssetExecutionContext) -> Output[None]:
    """
    Runs: python data_quality/dq_validation.py

    Validates 9 datasets:
      orders, order_items, customers, products, sellers,
      payments, reviews, mql, closed_deals

    Exit code:
      0 → all CRITICAL checks passed (WARNINGs logged but non-blocking)
      1 → at least one CRITICAL failure → Dagster marks this asset Failed
    """
    returncode, stdout = _run_dq("data_quality/dq_validation.py", context, timeout=900)
    metadata = _parse_core_summary(stdout)
    metadata["log_tail"] = MetadataValue.text(stdout[-2000:] if stdout else "(no output)")
    if returncode != 0:
        failed = metadata.get("checks_failed", MetadataValue.int(0))
        raise Failure(
            description=(
                f"Core DQ validation failed — "
                f"{failed} CRITICAL check(s) triggered. "
                "Downstream dbt transformation blocked."
            ),
            metadata=metadata,
        )
    return Output(value=None, metadata=metadata)


# ── Asset 2: Geolocation validation ───────────────────────────────────────────

@asset(
    group_name="data_quality",
    compute_kind="python",
    deps=[bq_datasets_ready],
    description=(
        "Run 30 geolocation-specific DQ checks: Brazil bounding box, "
        "state code validity, city name quality, coordinate precision, "
        "statistical outlier detection (IQR, std dev). "
        "CRITICAL failures halt the pipeline."
    ),
)
def dq_geo_validation(context: AssetExecutionContext) -> Output[None]:
    """
    Runs: python data_quality/dq_geolocation.py

    Validates olist_geolocation_dataset.csv (1,000,163 rows) across 6 categories:
      Schema, Completeness, Coordinate validity, Referential integrity,
      Business logic, Statistical outliers

    Reports are written to logs/dq_geolocation_report.json.

    Exit code:
      0 → no CRITICAL failures (pipeline may proceed)
      1 → CRITICAL failure → blocks all downstream assets
    """
    returncode, stdout = _run_dq("data_quality/dq_geolocation.py", context, timeout=600)

    # Parse pass rate from JSON summary line if present
    metadata: dict = {"log_tail": MetadataValue.text(stdout[-2000:] if stdout else "(no output)")}
    m = re.search(r'"pass_rate":\s*([\d.]+)', stdout)
    if m:
        metadata["pass_rate_pct"] = MetadataValue.float(float(m.group(1)))
    m = re.search(r'"total_checks":\s*(\d+)', stdout)
    if m:
        metadata["total_checks"] = MetadataValue.int(int(m.group(1)))

    if returncode != 0:
        raise Failure(
            description=(
                "Geolocation DQ validation failed — CRITICAL check(s) triggered. "
                "Check logs/dq_geolocation_report.json for details."
            ),
            metadata=metadata,
        )
    return Output(value=None, metadata=metadata)
