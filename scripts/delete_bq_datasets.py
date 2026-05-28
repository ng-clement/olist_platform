"""
scripts/delete_bq_datasets.py
Delete all four Olist BigQuery datasets and every table inside them.
"""

from google.cloud import bigquery
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

PROJECT = os.environ["GCP_PROJECT_ID"]
DATASETS = [
    "olist_raw",
    "olist_analytics",
    "olist_analytics_staging",
    "olist_analytics_marts",
]

client = bigquery.Client(project=PROJECT)

for dataset_id in DATASETS:
    full_id = f"{PROJECT}.{dataset_id}"
    client.delete_dataset(full_id, delete_contents=True, not_found_ok=True)
    print(f"Deleted {full_id}")

print("Done.")
