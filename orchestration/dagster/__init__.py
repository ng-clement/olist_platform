"""
orchestration/dagster/__init__.py
===================================
Dagster Definitions — the single entry point that the Dagster server loads.

This module wires together:
  assets    — the 10 pipeline assets across 4 groups (ingestion, data_quality, dbt, analytics)
  resources — shared DbtCliResource (dagster-dbt) and Meltano project config
  jobs      — olist_daily_pipeline, olist_ingest_only, olist_dbt_only
  schedules — olist_daily_at_0600_utc (06:00 UTC, daily)

Asset execution order (resolved from deps graph):
  ┌─ meltano_core_extract_load ─► dq_core_validation ─┐
  │                                                    ├─► star_schema_build ─┐
  └─ meltano_geo_extract_load  ─► dq_geo_validation  ─┘                      │
                                                        └─► dbt_staging ──────┤
                                                                               ▼
                                                                          dbt_marts
                                                                               ▼
                                                                          dbt_tests
                                                                               ▼
                                                                    olist_analytics_charts

Launch the Dagster UI:
  cd olist_platform
  DAGSTER_HOME=$(pwd) dagster dev -m orchestration.dagster

  Or with persistent daemon + webserver:
  DAGSTER_HOME=$(pwd) dagster-daemon run &
  DAGSTER_HOME=$(pwd) dagster-webserver -m orchestration.dagster -p 3000 &
"""

from dagster import Definitions, load_assets_from_modules

from .assets import analytics_assets, dbt_assets, dq_assets, meltano_assets
from .jobs import olist_daily_pipeline, olist_dbt_only, olist_ingest_only
from .resources import PROD_RESOURCES
from .schedules import olist_daily_schedule

# ── Collect all assets ────────────────────────────────────────────────────────
all_assets = load_assets_from_modules(
    [meltano_assets, dq_assets, dbt_assets, analytics_assets]
)

# ── Definitions — the Dagster server reads this object ───────────────────────
defs = Definitions(
    assets=all_assets,
    resources=PROD_RESOURCES,
    jobs=[
        olist_daily_pipeline,
        olist_ingest_only,
        olist_dbt_only,
    ],
    schedules=[olist_daily_schedule],
)
