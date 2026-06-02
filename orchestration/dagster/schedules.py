"""
orchestration/dagster/schedules.py
=====================================
Dagster schedule definitions for the Olist pipeline.

Schedules are attached to jobs and trigger them on a cron cadence.
The execution_timezone="UTC" is explicit — Dagster requires timezone-aware
schedules to avoid DST-related scheduling drift.

Activate schedules via:
  dagster schedule start olist_daily_at_0600_utc
Or in the Dagster UI: Automation → Schedules → Toggle on.
"""

from dagster import DefaultScheduleStatus, ScheduleDefinition

from .jobs import olist_daily_pipeline

# ── Primary schedule: daily at 06:00 UTC ─────────────────────────────────────
# 06:00 UTC = 14:00 SGT = 02:00 EST — runs after midnight US East Coast
# so the previous day's orders are fully settled in the source system.
# SLA: pipeline must complete by 07:30 UTC (90-minute budget).

olist_daily_schedule = ScheduleDefinition(
    job=olist_daily_pipeline,
    cron_schedule="0 6 * * *",
    execution_timezone="UTC",
    name="olist_daily_at_0600_utc",
    description=(
        "Trigger the full Olist daily pipeline at 06:00 UTC. "
        "SLA: complete by 07:30 UTC. "
        "Failure triggers Slack notification via Dagster alerting."
    ),
    default_status=DefaultScheduleStatus.RUNNING,  # auto-start when Dagster server starts
)
