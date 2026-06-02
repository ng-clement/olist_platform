"""
orchestration/dagster/resources.py
====================================
Shared Dagster resources for the Olist pipeline.

Resources are injectable dependencies — every asset that needs BigQuery or dbt
receives the resource via its function signature rather than importing it directly.
This makes individual assets unit-testable by swapping in mock resources.
"""

from pathlib import Path

from dagster_dbt import DbtCliResource

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DBT_PROJECT_DIR = PROJECT_ROOT / "dbt_project"
DBT_PROFILES_DIR = DBT_PROJECT_DIR / "profiles"


def get_resources(target: str = "dev") -> dict:
    """
    Return the resource dictionary for a given dbt target.

    Args:
        target: dbt profile target — "dev" (local) or "prod" (scheduled run).

    Usage in Definitions:
        Definitions(resources=get_resources(target="prod"), ...)
    """
    return {
        # ── dbt resource ──────────────────────────────────────────────────────
        # DbtCliResource wraps the dbt CLI; assets call dbt.cli(["run", ...])
        # instead of shelling out directly, so Dagster can capture structured logs.
        "dbt": DbtCliResource(
            project_dir=str(DBT_PROJECT_DIR),
            profiles_dir=str(DBT_PROFILES_DIR),
            target=target,
            global_config_flags=["--no-use-colors"],
        ),
    }


# ── Environment-specific resource sets ────────────────────────────────────────
DEV_RESOURCES = get_resources(target="dev")
PROD_RESOURCES = get_resources(target="prod")
