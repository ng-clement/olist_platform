"""
orchestration/dagster/jobs.py
================================
Dagster job definitions for the Olist pipeline.

A job is a named, executable selection of assets. Assets selected into a job
run in dependency order; independent assets (e.g. star_schema_build and
dbt_staging) run in parallel.

Jobs defined here:
  olist_daily_pipeline   — full end-to-end run (all 10 assets)
  olist_ingest_only      — Meltano ELT only (useful for manual re-ingestion)
  olist_dbt_only         — dbt transform + test only (skip ingestion)
"""

from dagster import AssetSelection, define_asset_job

# ── Full pipeline ─────────────────────────────────────────────────────────────

olist_daily_pipeline = define_asset_job(
    name="olist_daily_pipeline",
    selection=AssetSelection.all(),
    description=(
        "Full daily Olist analytics pipeline. "
        "Execution order (Dagster resolves from asset deps): "
        "Meltano ELT → DQ validation → star schema DDL + dbt staging → "
        "dbt marts → dbt tests → analytics charts."
    ),
    tags={"pipeline": "olist", "schedule": "daily", "team": "data-engineering"},
)

# ── Ingestion-only job ────────────────────────────────────────────────────────

olist_ingest_only = define_asset_job(
    name="olist_ingest_only",
    selection=AssetSelection.groups("ingestion", "data_quality"),
    description=(
        "Run Meltano ELT + DQ validation only. "
        "Use when re-ingesting source data without re-running transformations."
    ),
    tags={"pipeline": "olist", "scope": "ingestion"},
)

# ── dbt-only job ──────────────────────────────────────────────────────────────

olist_dbt_only = define_asset_job(
    name="olist_dbt_only",
    selection=AssetSelection.groups("warehouse", "dbt", "analytics"),
    description=(
        "Run star schema DDL, all dbt models, dbt tests, and analytics charts "
        "without re-ingesting. Use when source data has not changed."
    ),
    tags={"pipeline": "olist", "scope": "transformation"},
)
