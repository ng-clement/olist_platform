"""
orchestration/dagster/assets/analytics_assets.py
==================================================
Analytics generation asset — the final step in the Olist pipeline.

Depends on dbt_tests passing so that charts are always generated from
a warehouse that has passed all 181+ quality checks.
"""

import subprocess
from pathlib import Path

from dagster import (
    AssetExecutionContext,
    Failure,
    MetadataValue,
    Output,
    asset,
)
from .dbt_assets import dbt_tests

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CHARTS_DIR = PROJECT_ROOT / "reports" / "charts"

EXPECTED_CHARTS = [
    "01_revenue_trend.png",
    "02_rfm_segments.png",
    "03_marketing_funnel.png",
    "04_category_performance.png",
    "05_delivery_performance.png",
    "06_seller_performance.png",
    "07_geographic.png",
    "08_payments.png",
]


@asset(
    group_name="analytics",
    compute_kind="python",
    deps=[dbt_tests],
    description=(
        "Execute notebooks/olist_analysis.py to generate 8 business intelligence "
        "charts from raw CSV data. Charts saved to reports/charts/. "
        "Only runs after dbt_tests passes — guarantees charts reflect "
        "a quality-validated warehouse."
    ),
)
def olist_analytics_charts(context: AssetExecutionContext) -> Output[None]:
    """
    Runs: python notebooks/olist_analysis.py

    Generates 8 charts:
      01 Monthly revenue & order volume trends
      02 Customer RFM segmentation (pie + spend by segment)
      03 Marketing channel conversion rates
      04 Top 12 product categories by revenue
      05 Delivery days distribution + late rate by state
      06 Seller revenue concentration (Lorenz curve)
      07 Geographic order demand by state
      08 Payment type distribution + installment choices

    Reads directly from data/raw/ CSVs (not BigQuery) for portability.
    Outputs are saved as 150-DPI PNG files in reports/charts/.
    """
    result = subprocess.run(
        ["python", "notebooks/olist_analysis.py"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=1200,
    )
    context.log.info(result.stdout)
    if result.returncode != 0:
        raise Failure(
            description="Analytics chart generation failed.",
            metadata={"stderr": MetadataValue.text(result.stderr[-2000:])},
        )

    # Verify expected output files were created
    charts_found = (
        [f.name for f in CHARTS_DIR.glob("*.png")] if CHARTS_DIR.exists() else []
    )
    missing = [c for c in EXPECTED_CHARTS if c not in charts_found]

    return Output(
        value=None,
        metadata={
            "charts_generated": MetadataValue.int(len(charts_found)),
            "charts_dir": MetadataValue.path(str(CHARTS_DIR)),
            "missing_charts": MetadataValue.text(
                ", ".join(missing) if missing else "none — all 8 charts present"
            ),
            "stdout_tail": MetadataValue.text(
                result.stdout[-1000:] if result.stdout else ""
            ),
        },
    )
