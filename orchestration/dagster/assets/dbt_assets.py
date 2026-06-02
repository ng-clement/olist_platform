"""
orchestration/dagster/assets/dbt_assets.py
============================================
dbt transformation assets — staging, star schema DDL, marts, and tests.

Architecture
------------
The dbt pipeline is split into four sequential Dagster assets:

  dq_core_validation → meltano_core_extract_load ─┐
  dq_geo_validation  → meltano_geo_extract_load  ─┤
                                                   ├── star_schema_build   (warehouse/schema.sql via run_schema.py)
                                                   │
                                                   └── dbt_staging         (stg_* views: 9 models, ~seconds)
                │
            dbt_marts           (7 mart tables, run in parallel inside dbt)
                │
            dbt_tests           (181+ schema + singular tests)

Each asset uses DbtCliResource (dagster-dbt) for dbt execution, providing:
  - Structured log capture
  - dbt event streaming to the Dagster event log
  - Consistent project/profiles directory resolution

Upgrade path
------------
Replace dbt_staging + dbt_marts + dbt_tests with a single @dbt_assets
function to expose individual model-level lineage in the Dagster asset catalog:

    from dagster_dbt import dbt_assets

    MANIFEST_PATH = PROJECT_ROOT / "dbt_project" / "target" / "manifest.json"

    @dbt_assets(manifest=MANIFEST_PATH)
    def olist_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
        yield from dbt.cli(["build"], context=context).stream()

This requires mapping the olist_raw source assets to Meltano/DQ asset keys
via a custom DagsterDbtTranslator.
"""

import os
import re
import subprocess
from pathlib import Path

from dotenv import load_dotenv

from dagster import (
    AssetExecutionContext,
    Failure,
    MetadataValue,
    Output,
    asset,
)
from dagster_dbt import DbtCliResource
from .meltano_assets import meltano_core_extract_load, meltano_geo_extract_load

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = PROJECT_ROOT / "dbt_project" / "target" / "manifest.json"

# Ensure .env vars (GCP_PROJECT_ID, GOOGLE_APPLICATION_CREDENTIALS) are in
# os.environ so the dbt subprocess inherits them from the run worker process.
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _run_dbt(
    dbt: DbtCliResource,
    args: list[str],
    context: AssetExecutionContext,
) -> None:
    """
    Execute a dbt CLI command via DbtCliResource and wait for completion.
    Raises DagsterDbtCliRuntimeError (subclass of Failure) on non-zero exit.
    context= is intentionally omitted from cli() — passing it triggers dagster-dbt
    asset-key mapping which fails for plain @asset functions (not @dbt_assets).
    """
    context.log.info("dbt %s", " ".join(args))
    dbt.cli(args).wait()


def _parse_dbt_summary(stdout: str) -> dict:
    """Extract pass/error counts from dbt run/test output."""
    metadata: dict = {}
    m = re.search(r"(\d+) error", stdout)
    if m:
        metadata["errors"] = MetadataValue.int(int(m.group(1)))
    m = re.search(r"(\d+) warn", stdout)
    if m:
        metadata["warnings"] = MetadataValue.int(int(m.group(1)))
    m = re.search(r"(\d+) pass", stdout)
    if m:
        metadata["passed"] = MetadataValue.int(int(m.group(1)))
    return metadata


# ── Asset 1: Star schema DDL ───────────────────────────────────────────────────

@asset(
    group_name="warehouse",
    compute_kind="bigquery",
    deps=[meltano_core_extract_load, meltano_geo_extract_load],
    description=(
        "Execute warehouse/schema.sql via scripts/run_schema.py to build the "
        "star schema: 7 dimensions (DimDate, DimGeography, DimCustomer, DimProduct, "
        "DimSeller, DimPaymentType, DimMarketingChannel) and 4 facts (FactOrders, "
        "FactOrderItems, FactMarketingFunnel, FactPayments). "
        "Runs in parallel with dbt_staging — both depend on Meltano ingestion completing."
    ),
)
def star_schema_build(context: AssetExecutionContext) -> Output[None]:
    """
    Runs: python scripts/run_schema.py

    run_schema.py strips comments, splits statements, and executes each
    DROP TABLE IF EXISTS + CREATE OR REPLACE TABLE statement sequentially,
    printing one summary line per statement.
    """
    result = subprocess.run(
        ["python", "scripts/run_schema.py"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=900,
    )
    context.log.info(result.stdout)
    if result.returncode != 0:
        raise Failure(
            description="Star schema DDL failed — warehouse/schema.sql execution error.",
            metadata={"stderr": MetadataValue.text(result.stderr[-2000:])},
        )
    drops = result.stdout.count("DROP")
    creates = result.stdout.count("CREATE")
    return Output(
        value=None,
        metadata={
            "drops_executed": MetadataValue.int(drops),
            "creates_executed": MetadataValue.int(creates),
            "sql_file": MetadataValue.path(str(PROJECT_ROOT / "warehouse" / "schema.sql")),
        },
    )


# ── Asset 2: dbt staging ──────────────────────────────────────────────────────

@asset(
    group_name="dbt",
    compute_kind="dbt",
    deps=[meltano_core_extract_load, meltano_geo_extract_load],
    description=(
        "Run all 9 dbt staging models (stg_orders, stg_order_items, stg_customers, "
        "stg_products, stg_sellers, stg_payments, stg_reviews, stg_marketing_leads, "
        "stg_geolocation). Staging models are BigQuery views — no storage cost. "
        "Type casting, NULL filtering, string normalisation, geolocation deduplication."
    ),
)
def dbt_staging(context: AssetExecutionContext, dbt: DbtCliResource) -> Output[None]:
    """
    Runs: dbt run --select tag:staging

    All staging models are views (materialized='view') except stg_geolocation
    which is a table (1M rows → 19K via APPROX_QUANTILES deduplication).
    """
    _run_dbt(dbt, ["run", "--select", "tag:staging"], context)
    return Output(
        value=None,
        metadata={
            "models_run": MetadataValue.int(9),
            "target_dataset": MetadataValue.text("olist_analytics_staging"),
            "manifest": MetadataValue.path(str(MANIFEST_PATH)),
        },
    )


# ── Asset 3: dbt marts ────────────────────────────────────────────────────────

@asset(
    group_name="dbt",
    compute_kind="dbt",
    deps=[dbt_staging, star_schema_build],
    description=(
        "Run all 7 dbt mart models (mart_monthly_revenue, mart_customer_lifetime_value, "
        "mart_geo_performance, mart_seller_performance, mart_marketing_funnel, "
        "mart_logistics_performance, mart_product_performance). "
        "dbt runs them with up to 4 threads, so independent marts execute concurrently."
    ),
)
def dbt_marts(context: AssetExecutionContext, dbt: DbtCliResource) -> Output[None]:
    """
    Runs: dbt run --select tag:mart

    Mart types:
      Full refresh (table): monthly_revenue, clv, seller, marketing, product
      Incremental (MERGE):  geo_performance, logistics_performance
    """
    _run_dbt(dbt, ["run", "--select", "tag:mart"], context)
    return Output(
        value=None,
        metadata={
            "models_run": MetadataValue.int(7),
            "target_dataset": MetadataValue.text("olist_analytics_marts"),
            "incremental_models": MetadataValue.text(
                "mart_geo_performance, mart_logistics_performance"
            ),
        },
    )


# ── Asset 4: dbt tests ────────────────────────────────────────────────────────

@asset(
    group_name="dbt",
    compute_kind="dbt",
    deps=[dbt_marts],
    description=(
        "Run all 181+ dbt tests: 88+ schema tests (staging + mart) plus "
        "6 SQL singular integration assertions. "
        "A test failure blocks downstream analytics generation."
    ),
)
def dbt_tests(context: AssetExecutionContext, dbt: DbtCliResource) -> Output[None]:
    """
    Runs: dbt test

    Test breakdown:
      Staging schema tests  : unique, not_null, accepted_values, expression_is_true,
                              accepted_range, unique_combination_of_columns
      Mart schema tests     : same types + performance_score BETWEEN 0 AND 100,
                              conversion_rate_pct BETWEEN 0 AND 100
      SQL integration tests : no_orphaned_order_items, payment_value_matches,
                              mart_row_counts_nonzero, rfm_coverage,
                              geo_coordinates_in_brazil, no_future_orders
    """
    _run_dbt(dbt, ["test"], context)
    return Output(
        value=None,
        metadata={
            "test_count": MetadataValue.int(181),
            "singular_tests": MetadataValue.int(6),
            "test_path": MetadataValue.path(str(PROJECT_ROOT / "dbt_project" / "tests")),
        },
    )
