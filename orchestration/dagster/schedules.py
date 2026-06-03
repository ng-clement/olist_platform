"""
orchestration/dagster/schedules.py
=====================================
Dagster schedule definitions for the Olist pipeline.

Schedules are attached to jobs and trigger them on a cron cadence.
The execution_timezone="UTC" is explicit — Dagster requires timezone-aware
schedules to avoid DST-related scheduling drift.

Primary orchestration is now handled by GitHub Actions (pipeline-daily.yml).
Dagster is kept for manual on-demand runs and local development.

Activate manually via:
  dagster schedule start olist_daily_at_0600_utc
Or in the Dagster UI: Automation → Schedules → Toggle on.
"""

from dagster import DefaultScheduleStatus, ScheduleDefinition

from .jobs import olist_daily_pipeline

# ── Schedule: daily at 06:00 UTC (manual activation only) ────────────────────
# Primary daily orchestration runs via GitHub Actions (pipeline-daily.yml)
# at 02:00 SGT (18:00 UTC). This schedule is kept for ad-hoc use and local
# development — set to STOPPED so it does not auto-fire on dagster dev start.
# To run manually: toggle on in UI (Automation → Schedules) or use:
#   dagster job execute -m orchestration.dagster -j olist_daily_pipeline

olist_daily_schedule = ScheduleDefinition(
    job=olist_daily_pipeline,
    cron_schedule="0 6 * * *",
    execution_timezone="UTC",
    name="olist_daily_at_0600_utc",
    description=(
        "Full Olist daily pipeline — manual activation only. "
        "Primary schedule is GitHub Actions pipeline-daily.yml at 02:00 SGT."
    ),
    default_status=DefaultScheduleStatus.STOPPED,  # manual activation — GitHub Actions is primary
)
