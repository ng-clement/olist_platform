"""
scripts/check_bq_datasets.py
Check that all required BigQuery datasets exist before the pipeline runs.

Behaviour:
  - Any datasets missing  → create all four automatically (safe, no prompt)
  - All datasets present, olist_raw has tables  → prompt to confirm overwrite
  - All datasets present and empty              → proceed silently

Exit codes:
  0  pipeline may proceed
  1  user aborted, or unrecoverable error
"""

import sys
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery
from google.api_core.exceptions import NotFound
import os

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

PROJECT = os.environ.get("GCP_PROJECT_ID")
if not PROJECT:
    print("❌  GCP_PROJECT_ID is not set in .env")
    sys.exit(1)

REGION = os.environ.get("GCP_REGION", "US")

REQUIRED_DATASETS = [
    ("olist_raw", "Raw ingestion layer — all source CSVs loaded here"),
    ("olist_analytics", "Star schema — dimension and fact tables"),
    ("olist_analytics_staging", "DBT staging views"),
    ("olist_analytics_marts", "DBT mart tables (pre-aggregated KPIs)"),
]


def dataset_exists(client: bigquery.Client, dataset_id: str) -> bool:
    try:
        client.get_dataset(f"{PROJECT}.{dataset_id}")
        return True
    except NotFound:
        return False


def create_dataset(client: bigquery.Client, dataset_id: str, description: str):
    ds = bigquery.Dataset(f"{PROJECT}.{dataset_id}")
    ds.location = REGION
    ds.description = description
    client.create_dataset(ds, exists_ok=True)
    print(f"  ✅ Created dataset: {dataset_id}")


def olist_raw_has_tables(client: bigquery.Client) -> bool:
    tables = list(client.list_tables(f"{PROJECT}.olist_raw"))
    return len(tables) > 0


def main():
    print(f"  Project : {PROJECT}")
    print(f"  Region  : {REGION}")
    print()

    client = bigquery.Client(project=PROJECT)

    missing = [
        (ds_id, desc)
        for ds_id, desc in REQUIRED_DATASETS
        if not dataset_exists(client, ds_id)
    ]

    if missing:
        print(f"  📦 Missing datasets ({len(missing)}/{len(REQUIRED_DATASETS)}):")
        for ds_id, _ in missing:
            print(f"       • {ds_id}")
        print()
        print("  Creating all required datasets automatically...")
        for ds_id, desc in REQUIRED_DATASETS:
            create_dataset(client, ds_id, desc)
        print()
        print("  ✅ All datasets ready — pipeline will proceed.")
        sys.exit(0)

    # All datasets exist — check whether olist_raw already has data
    if olist_raw_has_tables(client):
        print("  ⚠️  WARNING — olist_raw already contains tables.")
        print()
        print("  Choose an option:")
        print(
            "    [y] Overwrite in-place  — keep datasets, WRITE_TRUNCATE replaces table data"
        )
        print(
            "    [d] Drop and reset      — delete all 4 datasets, recreate empty, then proceed"
        )
        print("    [n] Abort               — stop now, do nothing")
        print()
        answer = input("  Your choice  [y/d/N]: ").strip().lower()

        if answer == "d":
            print()
            print("  Dropping all datasets...")
            for ds_id, _ in REQUIRED_DATASETS:
                client.delete_dataset(
                    f"{PROJECT}.{ds_id}", delete_contents=True, not_found_ok=True
                )
                print(f"  🗑️  Dropped: {ds_id}")
            print()
            print("  Recreating datasets...")
            for ds_id, desc in REQUIRED_DATASETS:
                create_dataset(client, ds_id, desc)
            print()
            print("  ✅ Clean reset complete — pipeline will proceed.")

        elif answer == "y":
            print()
            print("  ✅ Confirmed overwrite — pipeline will proceed.")

        else:
            print()
            print("  Aborted.")
            sys.exit(1)
    else:
        print("  ✅ All datasets present and empty — pipeline will proceed.")

    sys.exit(0)


if __name__ == "__main__":
    main()
