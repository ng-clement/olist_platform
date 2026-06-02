"""
orchestration/dagster/assets/meltano_assets.py
================================================
Meltano ELT assets — Extract (tap-csv) + Load (target-bigquery) → BigQuery olist_raw.

Meltano replaces the legacy ingest_to_bigquery.py for all core datasets.
The geolocation asset continues to use ingest_geolocation.py because it
performs custom MD5-hash incremental detection and coordinate deduplication
that Singer does not natively support.

Each asset materialises when its subprocess completes successfully (exit 0).
A non-zero exit raises Failure, which Dagster marks as a pipeline error and
retries per the job retry policy.
"""

import os
import subprocess
from pathlib import Path

from dagster import (
    AssetExecutionContext,
    Failure,
    MetadataValue,
    Output,
    asset,
)
from .dq_assets import dq_core_validation, dq_geo_validation

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _run(cmd: list[str], context: AssetExecutionContext, timeout: int = 1800) -> str:
    """Run a subprocess, stream stdout to Dagster log, raise Failure on non-zero exit."""
    context.log.info("Running: %s", " ".join(str(c) for c in cmd))
    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ},
    )
    if result.stdout:
        context.log.info(result.stdout[-4000:])
    if result.returncode != 0:
        raise Failure(
            description=f"Command failed (exit {result.returncode}): {cmd[0]}",
            metadata={"stderr": MetadataValue.text(result.stderr[-3000:] or "(empty)")},
        )
    return result.stdout


# ── Asset 1: Core ELT ─────────────────────────────────────────────────────────
# NOTE: Meltano tap-csv + target-bigquery has upstream incompatibilities with
# google-cloud-bigquery 3.x (adswerve: SchemaField API mismatch; pipelinewise:
# orjson 3.6.1 requires Rust build). Using ingest_to_bigquery.py directly —
# it uses the same google-cloud-bigquery library that works in this environment.

@asset(
    group_name="ingestion",
    compute_kind="python",
    deps=[dq_core_validation],
    description=(
        "Load all 10 core Olist CSVs to BigQuery olist_raw (WRITE_TRUNCATE). "
        "Uses ingestion/ingest_to_bigquery.py via the olist conda environment."
    ),
)
def meltano_core_extract_load(context: AssetExecutionContext) -> Output[None]:
    """
    Runs: python ingestion/ingest_to_bigquery.py

    Loads 10 tables to olist_raw:
      raw_orders, raw_order_items, raw_customers, raw_products,
      raw_sellers, raw_order_payments, raw_order_reviews,
      raw_marketing_qualified_leads, raw_closed_deals, raw_category_translation
    """
    stdout = _run(
        ["python", "ingestion/ingest_to_bigquery.py"],
        context,
        timeout=1800,
    )
    return Output(
        value=None,
        metadata={
            "tables_loaded": MetadataValue.int(10),
            "destination": MetadataValue.text("BigQuery: olist_raw.*"),
            "log_tail": MetadataValue.text(stdout[-2000:] if stdout else "(no output)"),
        },
    )


# ── Asset 2: Geolocation ingestion ────────────────────────────────────────────

@asset(
    group_name="ingestion",
    compute_kind="python",
    deps=[dq_geo_validation],
    description=(
        "Ingest olist_geolocation_dataset.csv → BigQuery olist_raw.geolocation "
        "and olist_analytics.DimGeography. Uses MD5-hash incremental check: "
        "skips reload when source file is unchanged AND both target tables exist."
    ),
)
def meltano_geo_extract_load(context: AssetExecutionContext) -> Output[None]:
    """
    Runs: python ingestion/ingest_geolocation.py --mode incremental

    The geolocation pipeline is kept as a Python script rather than a Meltano
    tap because it performs:
      - Brazil bounding-box coordinate filtering
      - 1M → 19K row deduplication (median lat/lng per zip prefix)
      - State enrichment (region, state_name, is_frontier_market)
      - MD5 hash incremental detection (skips load if file unchanged)

    These transformations are not expressible in a generic Singer tap.
    """
    stdout = _run(
        ["python", "ingestion/ingest_geolocation.py", "--mode", "incremental"],
        context,
        timeout=1200,
    )
    skipped = "Skipping load" in stdout or "skipped_no_change" in stdout
    return Output(
        value=None,
        metadata={
            "mode": MetadataValue.text("incremental"),
            "skipped": MetadataValue.bool(skipped),
            "tables_written": MetadataValue.text(
                "skipped (no change)" if skipped
                else "olist_raw.geolocation, olist_analytics.DimGeography"
            ),
            "log_tail": MetadataValue.text(stdout[-2000:] if stdout else "(no output)"),
        },
    )
