"""
ingestion/ingest_geolocation.py
────────────────────────────────
Production-grade ingestion pipeline for the Olist geolocation dataset.

Reads ALL paths and credentials from the project root .env file via load_dotenv().
No hardcoded paths — deploy to any machine by setting values in .env.

Capabilities
------------
* Validates raw CSV before loading (bounding-box checks, null checks, dtype checks)
* Deduplicates 1M rows → ~19K unique zip-code prefixes using median coordinates
* Incremental mode: only re-loads if source file hash changed (idempotent)
* Writes to BigQuery `olist_raw.geolocation` (full table) and
  `olist_analytics.DimGeography` (deduped / enriched)
* Emits structured JSON audit logs

Usage
-----
  # From project root:
  python ingestion/ingest_geolocation.py
  python ingestion/ingest_geolocation.py --mode full
  python ingestion/ingest_geolocation.py --mode incremental

Environment variables (set in .env at project root)
-----------------------------------------------------
  GCP_PROJECT_ID                  Your GCP project ID
  GOOGLE_APPLICATION_CREDENTIALS  Path to service-account JSON key
  DATA_DIR                        Path to raw CSV folder (default: ../data/raw)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from dotenv import load_dotenv

# ── Resolve project root and load .env ───────────────────────────────────────
# __file__ = olist_platform/ingestion/ingest_geolocation.py
# PROJECT_ROOT = olist_platform/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ── Conditional BigQuery import ───────────────────────────────────────────────
try:
    from google.cloud import bigquery
    BQ_AVAILABLE = True
except ImportError:
    BQ_AVAILABLE = False
    logging.warning("google-cloud-bigquery not installed — running in simulation mode")

# ─────────────────────────────────────────────────────────────────────────────
# PATHS — all derived from env vars, no hardcoding
# ─────────────────────────────────────────────────────────────────────────────
DATA_DIR   = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data" / "raw")))
GEO_SOURCE = DATA_DIR / "olist_geolocation_dataset.csv"
STATE_FILE = PROJECT_ROOT / "data" / ".geo_state.json"
AUDIT_DIR  = PROJECT_ROOT / "logs"
GCP_PROJECT = os.getenv("GCP_PROJECT_ID", "")

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
BRAZIL_LAT_MIN, BRAZIL_LAT_MAX = -35.0, 5.3
BRAZIL_LNG_MIN, BRAZIL_LNG_MAX = -74.0, -28.0

VALID_STATES = {
    'AC','AL','AM','AP','BA','CE','DF','ES','GO','MA',
    'MG','MS','MT','PA','PB','PE','PI','PR','RJ','RN',
    'RO','RR','RS','SC','SE','SP','TO'
}

STATE_REGION_MAP = {
    'AC':'North','AL':'Northeast','AM':'North','AP':'North','BA':'Northeast',
    'CE':'Northeast','DF':'Midwest','ES':'Southeast','GO':'Midwest','MA':'Northeast',
    'MG':'Southeast','MS':'Midwest','MT':'Midwest','PA':'North','PB':'Northeast',
    'PE':'Northeast','PI':'Northeast','PR':'South','RJ':'Southeast','RN':'Northeast',
    'RO':'North','RR':'North','RS':'South','SC':'South','SE':'Northeast',
    'SP':'Southeast','TO':'North'
}

STATE_NAMES = {
    'AC':'Acre','AL':'Alagoas','AM':'Amazonas','AP':'Amapá','BA':'Bahia',
    'CE':'Ceará','DF':'Distrito Federal','ES':'Espírito Santo','GO':'Goiás',
    'MA':'Maranhão','MG':'Minas Gerais','MS':'Mato Grosso do Sul',
    'MT':'Mato Grosso','PA':'Pará','PB':'Paraíba','PE':'Pernambuco',
    'PI':'Piauí','PR':'Paraná','RJ':'Rio de Janeiro','RN':'Rio Grande do Norte',
    'RO':'Rondônia','RR':'Roraima','RS':'Rio Grande do Sul',
    'SC':'Santa Catarina','SE':'Sergipe','SP':'São Paulo','TO':'Tocantins'
}

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
AUDIT_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s — %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(AUDIT_DIR / "ingest_geolocation.log", mode="a"),
    ]
)
logger = logging.getLogger('geo_ingestor')


# ─────────────────────────────────────────────────────────────────────────────
# DATA QUALITY CHECKS
# ─────────────────────────────────────────────────────────────────────────────
class GeoDataQuality:
    """Run pre-load validation on raw geolocation DataFrame."""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.stats: dict = {}

    def run_all(self) -> bool:
        self._check_schema()
        self._check_nulls()
        self._check_bounding_box()
        self._check_state_codes()
        self._check_zip_format()
        self._compute_stats()
        return len(self.errors) == 0

    def _check_schema(self):
        required = ['geolocation_zip_code_prefix', 'geolocation_lat',
                    'geolocation_lng', 'geolocation_city', 'geolocation_state']
        missing = [c for c in required if c not in self.df.columns]
        if missing:
            self.errors.append(f"Missing columns: {missing}")

    def _check_nulls(self):
        for col, cnt in self.df.isnull().sum().items():
            if cnt > 0:
                pct = cnt / len(self.df) * 100
                if pct > 1.0:
                    self.errors.append(f"Column '{col}' has {cnt} nulls ({pct:.2f}%)")
                else:
                    self.warnings.append(f"Column '{col}' has {cnt} nulls ({pct:.2f}%) — within tolerance")

    def _check_bounding_box(self):
        out_lat = ((self.df['geolocation_lat'] < BRAZIL_LAT_MIN) |
                   (self.df['geolocation_lat'] > BRAZIL_LAT_MAX)).sum()
        out_lng = ((self.df['geolocation_lng'] < BRAZIL_LNG_MIN) |
                   (self.df['geolocation_lng'] > BRAZIL_LNG_MAX)).sum()
        if out_lat > 0:
            self.warnings.append(f"{out_lat} rows outside Brazil lat bounds — will be filtered")
        if out_lng > 0:
            self.warnings.append(f"{out_lng} rows outside Brazil lng bounds — will be filtered")

    def _check_state_codes(self):
        invalid = (~self.df['geolocation_state'].str.upper().isin(VALID_STATES)).sum()
        if invalid > 0:
            self.warnings.append(f"{invalid} rows with invalid state codes")

    def _check_zip_format(self):
        try:
            zip_ints = pd.to_numeric(self.df['geolocation_zip_code_prefix'], errors='coerce')
            invalid_zip = ((zip_ints < 1001) | (zip_ints > 99999)).sum()
            if invalid_zip > 0:
                self.warnings.append(f"{invalid_zip} zip codes outside valid range [01001–99999]")
        except Exception as e:
            self.warnings.append(f"Zip format check failed: {e}")

    def _compute_stats(self):
        self.stats = {
            'total_rows': len(self.df),
            'unique_zips': int(self.df['geolocation_zip_code_prefix'].nunique()),
            'unique_states': int(self.df['geolocation_state'].nunique()),
            'unique_cities': int(self.df['geolocation_city'].nunique()),
        }


# ─────────────────────────────────────────────────────────────────────────────
# TRANSFORMATION
# ─────────────────────────────────────────────────────────────────────────────
def transform_geolocation(df: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate and enrich raw geolocation rows."""
    logger.info("Starting transformation: %d raw rows", len(df))

    df_clean = df[
        df['geolocation_lat'].between(BRAZIL_LAT_MIN, BRAZIL_LAT_MAX) &
        df['geolocation_lng'].between(BRAZIL_LNG_MIN, BRAZIL_LNG_MAX)
    ].copy()

    dropped = len(df) - len(df_clean)
    if dropped > 0:
        logger.warning("Dropped %d rows outside Brazil bounding box", dropped)

    df_clean['geolocation_zip_code_prefix'] = pd.to_numeric(
        df_clean['geolocation_zip_code_prefix'], errors='coerce'
    ).astype('Int64')
    df_clean['geolocation_state'] = df_clean['geolocation_state'].str.upper().str.strip()
    df_clean['geolocation_city']  = df_clean['geolocation_city'].str.lower().str.strip()
    df_clean = df_clean.dropna(subset=['geolocation_zip_code_prefix'])

    def mode_first(s):
        m = s.mode()
        return m.iloc[0] if len(m) > 0 else s.iloc[0]

    geo_agg = (
        df_clean
        .groupby('geolocation_zip_code_prefix', as_index=False)
        .agg(
            latitude=('geolocation_lat', 'median'),
            longitude=('geolocation_lng', 'median'),
            city=('geolocation_city', mode_first),
            state_code=('geolocation_state', mode_first),
            source_row_count=('geolocation_lat', 'count')
        )
    )
    logger.info("Deduplicated to %d unique zip prefixes", len(geo_agg))

    geo_agg['state_name']        = geo_agg['state_code'].map(STATE_NAMES).fillna('Unknown')
    geo_agg['region']            = geo_agg['state_code'].map(STATE_REGION_MAP).fillna('Unknown')
    geo_agg['is_frontier_market']= geo_agg['region'].isin(['North', 'Northeast'])
    geo_agg['geographic_zone']   = np.select(
        [(geo_agg['latitude'] < -15) & (geo_agg['longitude'] > -50),
         geo_agg['latitude'] > -5,
         geo_agg['latitude'].between(-15, -5)],
        ['Coastal', 'Amazon Basin', 'Central Plateau'],
        default='Southern Cone'
    )
    geo_agg['zip_code_formatted'] = geo_agg['geolocation_zip_code_prefix'].astype(str).str.zfill(5)
    geo_agg['dw_inserted_at']     = datetime.now(timezone.utc).isoformat()
    return geo_agg


# ─────────────────────────────────────────────────────────────────────────────
# BIGQUERY LOADER
# ─────────────────────────────────────────────────────────────────────────────
class GeoBigQueryLoader:
    """Load deduped geolocation data to BigQuery."""

    def __init__(self, project: str, raw_dataset: str = 'olist_raw',
                 analytics_dataset: str = 'olist_analytics'):
        self.project          = project
        self.raw_dataset      = raw_dataset
        self.analytics_dataset= analytics_dataset
        self.client = bigquery.Client(project=project) if BQ_AVAILABLE else None
        if not BQ_AVAILABLE:
            logger.warning("Running in simulation mode — no BigQuery writes")

    def load_raw(self, df: pd.DataFrame) -> int:
        table_ref = f"{self.project}.{self.raw_dataset}.geolocation"
        logger.info("Loading %d raw rows → %s", len(df), table_ref)
        if not self.client:
            logger.info("[SIM] Would write %d rows to %s", len(df), table_ref)
            return len(df)
        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE, autodetect=True)
        job = self.client.load_table_from_dataframe(df, table_ref, job_config=job_config)
        job.result()
        logger.info("Raw load complete: %d rows", job.output_rows)
        return job.output_rows

    def load_dimension(self, df: pd.DataFrame) -> int:
        table_ref = f"{self.project}.{self.analytics_dataset}.DimGeography"
        logger.info("Loading %d dimension rows → %s", len(df), table_ref)
        if not self.client:
            logger.info("[SIM] Would write %d rows to %s", len(df), table_ref)
            return len(df)
        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE, autodetect=True)
        job = self.client.load_table_from_dataframe(df, table_ref, job_config=job_config)
        job.result()
        logger.info("Dimension load complete: %d rows", job.output_rows)
        return job.output_rows


# ─────────────────────────────────────────────────────────────────────────────
# FILE HASH (INCREMENTAL MODE)
# ─────────────────────────────────────────────────────────────────────────────
def compute_file_hash(path: Path) -> str:
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def load_last_hash(state_file: Path) -> Optional[str]:
    if state_file.exists():
        return json.loads(state_file.read_text()).get('last_hash')
    return None


def save_hash(state_file: Path, file_hash: str, rows_loaded: int):
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({
        'last_hash': file_hash, 'rows_loaded': rows_loaded,
        'updated_at': datetime.now(timezone.utc).isoformat()
    }, indent=2))


def target_tables_exist(project: str, raw_dataset: str, analytics_dataset: str) -> bool:
    """Return True only if both target BQ tables are present."""
    if not BQ_AVAILABLE:
        return False
    client = bigquery.Client(project=project)
    for table_ref in [
        f"{project}.{raw_dataset}.geolocation",
        f"{project}.{analytics_dataset}.DimGeography",
    ]:
        try:
            client.get_table(table_ref)
        except Exception:
            return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='Ingest Olist geolocation data')
    parser.add_argument('--source',            default=str(GEO_SOURCE),
                        help='Path to geolocation CSV (default: data/raw/olist_geolocation_dataset.csv)')
    parser.add_argument('--project',           default=GCP_PROJECT,
                        help='GCP project ID (default: from .env GCP_PROJECT_ID)')
    parser.add_argument('--raw-dataset',       default='olist_raw')
    parser.add_argument('--analytics-dataset', default='olist_analytics')
    parser.add_argument('--mode',              choices=['full', 'incremental'], default='incremental')
    args = parser.parse_args()

    source_path = Path(args.source)
    run_id = f"geo_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    t0     = time.time()
    run_info = {
        'run_id': run_id, 'source': str(source_path), 'mode': args.mode,
        'started_at': datetime.now(timezone.utc).isoformat(),
        'status': 'running', 'rows_raw': 0, 'rows_dimension': 0,
        'dq_errors': [], 'dq_warnings': [], 'dq_stats': {}
    }

    try:
        # ── 1. Incremental check ──────────────────────────────────────────────
        if args.mode == 'incremental' and source_path.exists():
            current_hash = compute_file_hash(source_path)
            last_hash    = load_last_hash(STATE_FILE)
            if current_hash == last_hash:
                if target_tables_exist(args.project, args.raw_dataset, args.analytics_dataset):
                    logger.info("Source file unchanged (hash match) and tables present. Skipping load.")
                    run_info['status'] = 'skipped_no_change'
                    (AUDIT_DIR / f"{run_id}.json").write_text(json.dumps(run_info, indent=2, default=str))
                    return
                else:
                    logger.info("Source file unchanged but target tables missing — forcing reload.")

        # ── 2. Load CSV ───────────────────────────────────────────────────────
        if not source_path.exists():
            raise FileNotFoundError(
                f"Geolocation CSV not found: {source_path}\n"
                f"Place olist_geolocation_dataset.csv in {DATA_DIR}/"
            )

        logger.info("Loading CSV from %s ...", source_path)
        df_raw = pd.read_csv(source_path, dtype={
            'geolocation_zip_code_prefix': str,
            'geolocation_lat': float, 'geolocation_lng': float,
            'geolocation_city': str,  'geolocation_state': str
        }, low_memory=False)
        logger.info("Loaded %d raw rows", len(df_raw))
        run_info['rows_raw'] = len(df_raw)

        # ── 3. Data quality ───────────────────────────────────────────────────
        dq = GeoDataQuality(df_raw)
        dq_passed = dq.run_all()
        run_info.update({'dq_errors': dq.errors, 'dq_warnings': dq.warnings, 'dq_stats': dq.stats})
        if not dq_passed:
            raise ValueError(f"Data quality failed: {dq.errors}")
        for w in dq.warnings:
            logger.warning("[DQ WARNING] %s", w)

        # ── 4. Transform ──────────────────────────────────────────────────────
        df_dim = transform_geolocation(df_raw)
        run_info['rows_dimension'] = len(df_dim)

        # ── 5. Load to BigQuery ───────────────────────────────────────────────
        loader = GeoBigQueryLoader(args.project, args.raw_dataset, args.analytics_dataset)
        loader.load_raw(df_raw)
        loader.load_dimension(df_dim)

        # ── 6. Save state & audit ─────────────────────────────────────────────
        if source_path.exists():
            save_hash(STATE_FILE, compute_file_hash(source_path), len(df_dim))

        run_info['status'] = 'success'
        run_info['elapsed_seconds'] = round(time.time() - t0, 2)
        logger.info("✅ Geo ingestion complete in %.1fs — %d zip prefixes loaded",
                    run_info['elapsed_seconds'], len(df_dim))

    except Exception as exc:
        run_info.update({'status': 'failed', 'error': str(exc)})
        logger.exception("❌ Geo ingestion failed: %s", exc)
        sys.exit(1)
    finally:
        run_info['finished_at'] = datetime.now(timezone.utc).isoformat()
        audit_path = AUDIT_DIR / f"{run_id}.json"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps(run_info, indent=2, default=str))
        logger.info("Audit log → %s", audit_path)


if __name__ == '__main__':
    main()
