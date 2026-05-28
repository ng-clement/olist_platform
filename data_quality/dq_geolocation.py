"""
data_quality/dq_geolocation.py
================================
Geolocation-specific data quality validation (30 checks across 6 categories).

Reads ALL paths from the project root .env file via load_dotenv().
No hardcoded paths — deploy to any machine by setting values in .env.

Usage
-----
  # From project root:
  python data_quality/dq_geolocation.py
  python data_quality/dq_geolocation.py --source /custom/path/geolocation.csv

Environment variables (set in .env at project root)
-----------------------------------------------------
  DATA_DIR   Path to raw CSV folder (default: data/raw/ relative to project root)
"""

from __future__ import annotations

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
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR   = Path(os.getenv("DATA_DIR") or str(PROJECT_ROOT / "data" / "raw"))
LOG_DIR    = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger('dq_geolocation')

BRAZIL_BOUNDS = dict(lat_min=-35.0, lat_max=5.3, lng_min=-74.0, lng_max=-28.0)
VALID_STATES = {
    'AC','AL','AM','AP','BA','CE','DF','ES','GO','MA',
    'MG','MS','MT','PA','PB','PE','PI','PR','RJ','RN',
    'RO','RR','RS','SC','SE','SP','TO'
}


class GeoQualityChecker:
    """Run all 30 DQ checks on raw geolocation data."""

    def __init__(self, df: pd.DataFrame, df_deduped: Optional[pd.DataFrame] = None,
                 customer_zips: Optional[pd.Series] = None):
        self.df          = df.copy()
        self.df_deduped  = df_deduped
        self.customer_zips = customer_zips
        self.results: list[dict] = []
        self._check_id = 0

    def _result(self, category, name, passed, severity, rows_affected=0, detail=''):
        self._check_id += 1
        status = 'PASS' if passed else ('FAIL' if severity == 'CRITICAL' else 'WARN')
        r = {
            'check_id': f"GEO-{self._check_id:02d}", 'category': category,
            'name': name, 'status': status, 'severity': severity,
            'rows_affected': rows_affected, 'detail': detail
        }
        icon = '✅' if passed else ('❌' if severity == 'CRITICAL' else '⚠️')
        logger.info(f"{icon} [{r['check_id']}] {name} — {status} | {detail}")
        self.results.append(r)
        return r

    # ── Schema ────────────────────────────────────────────────────────────────
    def check_required_columns(self):
        required = ['geolocation_zip_code_prefix','geolocation_lat',
                    'geolocation_lng','geolocation_city','geolocation_state']
        missing = [c for c in required if c not in self.df.columns]
        self._result('Schema','Required columns present',len(missing)==0,'CRITICAL',
                     len(missing),f"Missing: {missing}" if missing else "All 5 required columns present")

    def check_column_count(self):
        self._result('Schema','Column count matches expected',len(self.df.columns)==5,
                     'WARNING',0,f"Expected 5, found {len(self.df.columns)}")

    def check_lat_numeric(self):
        n = pd.to_numeric(self.df['geolocation_lat'],errors='coerce').isna().sum()
        self._result('Schema','Latitude is numeric',n==0,'CRITICAL',n,f"{n} non-numeric lat values")

    def check_lng_numeric(self):
        n = pd.to_numeric(self.df['geolocation_lng'],errors='coerce').isna().sum()
        self._result('Schema','Longitude is numeric',n==0,'CRITICAL',n,f"{n} non-numeric lng values")

    def check_zip_parseable(self):
        n = pd.to_numeric(self.df['geolocation_zip_code_prefix'],errors='coerce').isna().sum()
        self._result('Schema','Zip code prefix is numeric-parseable',n==0,'WARNING',n,f"{n} non-numeric zip values")

    # ── Completeness ──────────────────────────────────────────────────────────
    def check_null_zip(self):
        n = self.df['geolocation_zip_code_prefix'].isna().sum()
        self._result('Completeness','No null zip code prefixes',n==0,'CRITICAL',n,f"{n} null zip values")

    def check_null_lat(self):
        n = self.df['geolocation_lat'].isna().sum()
        self._result('Completeness','No null latitudes',n==0,'CRITICAL',n,f"{n} null lat values")

    def check_null_lng(self):
        n = self.df['geolocation_lng'].isna().sum()
        self._result('Completeness','No null longitudes',n==0,'CRITICAL',n,f"{n} null lng values")

    def check_null_city(self):
        n = self.df['geolocation_city'].isna().sum()
        pct = n / len(self.df) * 100
        self._result('Completeness','No null city names',pct < 0.5,'WARNING',n,
                     f"{n} null city values ({pct:.3f}%)")

    def check_null_state(self):
        n = self.df['geolocation_state'].isna().sum()
        self._result('Completeness','No null state codes',n==0,'CRITICAL',n,f"{n} null state values")

    # ── Coordinate validity ───────────────────────────────────────────────────
    def check_lat_range_global(self):
        out = ((self.df['geolocation_lat']<-90)|(self.df['geolocation_lat']>90)).sum()
        self._result('Coordinate','Latitude within global range [-90,90]',out==0,'CRITICAL',int(out),f"{out} out of range")

    def check_lng_range_global(self):
        out = ((self.df['geolocation_lng']<-180)|(self.df['geolocation_lng']>180)).sum()
        self._result('Coordinate','Longitude within global range [-180,180]',out==0,'CRITICAL',int(out),f"{out} out of range")

    def check_lat_brazil(self):
        b=BRAZIL_BOUNDS
        out=((self.df['geolocation_lat']<b['lat_min'])|(self.df['geolocation_lat']>b['lat_max'])).sum()
        pct=out/len(self.df)*100
        self._result('Coordinate','Latitude within Brazil bounding box',pct<0.01,'WARNING',out,
                     f"{out} rows ({pct:.4f}%) outside [{b['lat_min']},{b['lat_max']}]")

    def check_lng_brazil(self):
        b=BRAZIL_BOUNDS
        out=((self.df['geolocation_lng']<b['lng_min'])|(self.df['geolocation_lng']>b['lng_max'])).sum()
        pct=out/len(self.df)*100
        self._result('Coordinate','Longitude within Brazil bounding box',pct<0.01,'WARNING',out,
                     f"{out} rows ({pct:.4f}%) outside [{b['lng_min']},{b['lng_max']}]")

    def check_zero_coordinates(self):
        z=((self.df['geolocation_lat']==0)&(self.df['geolocation_lng']==0)).sum()
        self._result('Coordinate','No (0,0) null-island coordinates',z==0,'CRITICAL',z,f"{z} (0,0) rows")

    def check_lat_lng_not_swapped(self):
        s=(self.df['geolocation_lat']>10).sum()
        self._result('Coordinate','Latitude not accidentally positive-large',s<10,'WARNING',int(s),f"{s} rows lat>10")

    def check_coordinate_precision(self):
        lp=self.df['geolocation_lat'].apply(
            lambda x: len(str(x).split('.')[-1]) if '.' in str(x) else 0)
        low=(lp<4).sum()
        pct=low/len(self.df)*100
        self._result('Coordinate','Coordinates have ≥4 decimal places',pct<5,'INFO',int(low),
                     f"{low} rows ({pct:.2f}%) with lat precision < 4 d.p.")

    # ── Referential integrity ─────────────────────────────────────────────────
    def check_valid_state_codes(self):
        inv=(~self.df['geolocation_state'].str.upper().str.strip().isin(VALID_STATES|{''})).sum()
        self._result('ReferentialIntegrity','All state codes are valid',inv==0,'WARNING',int(inv),f"{inv} invalid state codes")

    def check_state_count(self):
        n=self.df['geolocation_state'].str.upper().str.strip().nunique()
        self._result('ReferentialIntegrity','All 27 Brazilian states present',n>=27,'INFO',0,
                     f"{n} distinct state codes (expected 27)")

    def check_zip_range(self):
        zips=pd.to_numeric(self.df['geolocation_zip_code_prefix'],errors='coerce')
        out=((zips<1001)|(zips>99999)).sum()
        self._result('ReferentialIntegrity','Zip codes within [01001–99999]',out==0,'WARNING',int(out),f"{out} invalid zip codes")

    def check_customer_zip_coverage(self):
        if self.customer_zips is None:
            self._result('ReferentialIntegrity','Customer zip coverage (skipped)',True,'INFO',0,'No customer zip series provided')
            return
        geo_zips=set(pd.to_numeric(self.df['geolocation_zip_code_prefix'],errors='coerce').dropna().astype(int))
        cust_zips=set(pd.to_numeric(self.customer_zips,errors='coerce').dropna().astype(int))
        missing=cust_zips-geo_zips
        pct=len(missing)/len(cust_zips)*100 if cust_zips else 0
        self._result('ReferentialIntegrity','All customer zips have geo coverage',pct<5,'WARNING',len(missing),
                     f"{len(missing)} of {len(cust_zips)} customer zips ({pct:.1f}%) not in geo table")

    # ── Business logic ────────────────────────────────────────────────────────
    def check_sp_is_largest_state(self):
        counts=self.df['geolocation_state'].str.upper().value_counts()
        largest=counts.index[0] if len(counts)>0 else None
        self._result('BusinessLogic','SP is largest state (expected)',largest=='SP','INFO',0,f"Largest: {largest}")

    def check_unique_zip_count(self):
        n=self.df['geolocation_zip_code_prefix'].nunique()
        self._result('BusinessLogic','Unique zip count within [15K–25K]',15000<=n<=25000,'WARNING',0,
                     f"{n:,} unique zips (expected ~19,015)")

    def check_total_row_count(self):
        n=len(self.df)
        self._result('BusinessLogic','Total row count within [900K–1.1M]',900_000<=n<=1_100_000,'WARNING',0,
                     f"{n:,} total rows (expected ~1,000,163)")

    def check_dedup_ratio(self):
        if self.df_deduped is None:
            self._result('BusinessLogic','Dedup ratio check (skipped)',True,'INFO',0,'No deduped df provided')
            return
        ratio=len(self.df)/max(len(self.df_deduped),1)
        self._result('BusinessLogic','Dedup ratio ~50x',40<=ratio<=60,'INFO',0,
                     f"Dedup ratio={ratio:.1f}x ({len(self.df):,} → {len(self.df_deduped):,})")

    def check_city_name_quality(self):
        sus=self.df['geolocation_city'].apply(
            lambda x: len(str(x).strip())<2 or str(x).strip().isdigit()).sum()
        pct=sus/len(self.df)*100
        self._result('BusinessLogic','City names are meaningful strings',pct<1.0,'WARNING',int(sus),
                     f"{sus} rows ({pct:.3f}%) with suspicious city names")

    # ── Statistical outliers ──────────────────────────────────────────────────
    def check_lat_iqr_outliers(self):
        q1,q3=self.df['geolocation_lat'].quantile([0.01,0.99])
        out=((self.df['geolocation_lat']<q1)|(self.df['geolocation_lat']>q3)).sum()
        pct=out/len(self.df)*100
        self._result('StatisticalOutlier','Lat 1%-99% IQR: <2% outliers',pct<2.0,'INFO',int(out),
                     f"{out} rows ({pct:.2f}%) outside [{q1:.2f},{q3:.2f}]")

    def check_lng_iqr_outliers(self):
        q1,q3=self.df['geolocation_lng'].quantile([0.01,0.99])
        out=((self.df['geolocation_lng']<q1)|(self.df['geolocation_lng']>q3)).sum()
        pct=out/len(self.df)*100
        self._result('StatisticalOutlier','Lng 1%-99% IQR: <2% outliers',pct<2.0,'INFO',int(out),
                     f"{out} rows ({pct:.2f}%) outside [{q1:.2f},{q3:.2f}]")

    def check_lat_std(self):
        std=self.df['geolocation_lat'].std()
        self._result('StatisticalOutlier','Lat std dev within [4–8]°',4<=std<=8,'INFO',0,
                     f"std={std:.3f}° (Brazil ~5.7°)")

    def check_lng_std(self):
        std=self.df['geolocation_lng'].std()
        self._result('StatisticalOutlier','Lng std dev within [3–6]°',3<=std<=6,'INFO',0,
                     f"std={std:.3f}° (Brazil ~4.3°)")

    # ── Run all ───────────────────────────────────────────────────────────────
    def run_all(self) -> dict:
        t0 = time.time()
        logger.info("="*60)
        logger.info("GEOLOCATION DATA QUALITY VALIDATION")
        logger.info("Rows: %d | Columns: %d", len(self.df), len(self.df.columns))
        logger.info("="*60)

        for method in [
            self.check_required_columns, self.check_column_count,
            self.check_lat_numeric, self.check_lng_numeric, self.check_zip_parseable,
            self.check_null_zip, self.check_null_lat, self.check_null_lng,
            self.check_null_city, self.check_null_state,
            self.check_lat_range_global, self.check_lng_range_global,
            self.check_lat_brazil, self.check_lng_brazil,
            self.check_zero_coordinates, self.check_lat_lng_not_swapped,
            self.check_coordinate_precision,
            self.check_valid_state_codes, self.check_state_count,
            self.check_zip_range, self.check_customer_zip_coverage,
            self.check_sp_is_largest_state, self.check_unique_zip_count,
            self.check_total_row_count, self.check_dedup_ratio,
            self.check_city_name_quality,
            self.check_lat_iqr_outliers, self.check_lng_iqr_outliers,
            self.check_lat_std, self.check_lng_std,
        ]:
            method()

        elapsed = round(time.time() - t0, 2)
        passed  = sum(1 for r in self.results if r['status'] == 'PASS')
        warned  = sum(1 for r in self.results if r['status'] == 'WARN')
        failed  = sum(1 for r in self.results if r['status'] == 'FAIL')
        total   = len(self.results)

        summary = {
            'dataset': 'olist_geolocation',
            'run_at': datetime.now(timezone.utc).isoformat(),
            'total_checks': total, 'passed': passed,
            'warned': warned, 'failed': failed,
            'pass_rate': round(passed / total * 100, 1),
            'elapsed_seconds': elapsed,
            'pipeline_can_proceed': failed == 0,
            'results': self.results
        }

        logger.info("─"*60)
        logger.info("SUMMARY: %d/%d passed | %d warnings | %d failures | %.1fs",
                    passed, total, warned, failed, elapsed)
        logger.info("Pipeline proceed: %s", "✅ YES" if failed == 0 else "❌ NO")
        return summary


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import argparse

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s')

    parser = argparse.ArgumentParser(description='Olist Geolocation DQ Checker')
    parser.add_argument('--source', default=str(DATA_DIR / 'olist_geolocation_dataset.csv'),
                        help='Path to geolocation CSV (default: data/raw/olist_geolocation_dataset.csv)')
    args = parser.parse_args()

    source_path = Path(args.source)
    if not source_path.exists():
        print(f"❌ File not found: {source_path}")
        print(f"   Place olist_geolocation_dataset.csv in {DATA_DIR}/")
        sys.exit(1)

    df = pd.read_csv(source_path, dtype={
        'geolocation_zip_code_prefix': str,
        'geolocation_lat': float, 'geolocation_lng': float,
        'geolocation_city': str, 'geolocation_state': str
    })

    checker = GeoQualityChecker(df)
    summary = checker.run_all()

    out_path = LOG_DIR / "dq_geolocation_report.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nDQ report saved → {out_path}")
    print(f"Pass rate: {summary['pass_rate']}% | Pipeline proceed: {summary['pipeline_can_proceed']}")
    sys.exit(0 if summary['pipeline_can_proceed'] else 1)
