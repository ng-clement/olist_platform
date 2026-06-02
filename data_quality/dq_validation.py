"""
data_quality/dq_validation.py
==============================
Enterprise data quality validation framework for the Olist pipeline.

Reads ALL paths from the project root .env file via load_dotenv().
No hardcoded paths — deploy to any machine by setting values in .env.

Covers
------
  - Null value checks
  - Uniqueness / duplicate detection
  - Referential integrity
  - Business logic validation
  - Value range validation
  - Schema consistency

Usage
-----
  # From project root:
  python data_quality/dq_validation.py
  python data_quality/dq_validation.py --data-dir /custom/path/to/csvs

Environment variables (set in .env at project root)
-----------------------------------------------------
  DATA_DIR   Path to raw CSV folder (default: data/raw/ relative to project root)
"""

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import pandas as pd
from dotenv import load_dotenv

# ── Resolve project root and load .env ───────────────────────────────────────
# __file__ = olist_platform/data_quality/dq_validation.py
# PROJECT_ROOT = olist_platform/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.getenv("DATA_DIR") or str(PROJECT_ROOT / "data" / "raw"))
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("olist.data_quality")


# ── Validation result ─────────────────────────────────────────────────────────
class ValidationResult:
    def __init__(
        self, rule: str, dataset: str, column: str, passed: bool, detail: str = ""
    ):
        self.rule = rule
        self.dataset = dataset
        self.column = column
        self.passed = passed
        self.detail = detail
        self.timestamp = datetime.now(timezone.utc)

    def __str__(self):
        status = "✅ PASS" if self.passed else "❌ FAIL"
        return f"{status} | {self.dataset}.{self.column} | {self.rule} | {self.detail}"


# ── Validator class ───────────────────────────────────────────────────────────
class DataQualityValidator:
    def __init__(self):
        self.results: List[ValidationResult] = []

    def _record(self, rule, dataset, column, passed, detail=""):
        r = ValidationResult(rule, dataset, column, passed, detail)
        self.results.append(r)
        log_fn = logger.info if passed else logger.warning
        log_fn(str(r))
        return r

    def expect_column_not_null(self, df, col, dataset, max_null_rate=0.0):
        null_rate = df[col].isna().mean()
        passed = null_rate <= max_null_rate
        return self._record(
            "not_null",
            dataset,
            col,
            passed,
            f"null_rate={null_rate * 100:.2f}% (threshold={max_null_rate * 100:.1f}%)",
        )

    def expect_column_unique(self, df, col, dataset):
        dup_count = df[col].duplicated().sum()
        return self._record(
            "unique", dataset, col, dup_count == 0, f"duplicate_count={dup_count}"
        )

    def expect_column_between(self, df, col, dataset, min_val=None, max_val=None):
        series = df[col].dropna()
        violations = 0
        if min_val is not None:
            violations += (series < min_val).sum()
        if max_val is not None:
            violations += (series > max_val).sum()
        return self._record(
            "between",
            dataset,
            col,
            violations == 0,
            f"violations={violations} (min={min_val}, max={max_val})",
        )

    def expect_column_values_in_set(self, df, col, dataset, value_set):
        non_null = df[col].dropna()
        invalid = non_null[~non_null.isin(value_set)]
        return self._record(
            "accepted_values",
            dataset,
            col,
            len(invalid) == 0,
            f"invalid_count={len(invalid)}, examples={invalid.unique()[:3].tolist()}",
        )

    def expect_referential_integrity(
        self, df_child, fk_col, df_parent, pk_col, child_name, parent_name
    ):
        orphans = set(df_child[fk_col].dropna()) - set(df_parent[pk_col].dropna())
        return self._record(
            "referential_integrity",
            child_name,
            fk_col,
            len(orphans) == 0,
            f"orphaned_keys={len(orphans)} in {child_name}.{fk_col} "
            f"not in {parent_name}.{pk_col}",
        )

    def expect_business_rule(
        self, df, expression, dataset, rule_name, max_violations=0
    ):
        try:
            violations = df.query(f"not ({expression})")
            passed = len(violations) <= max_violations
            detail = f"violations={len(violations)} (threshold={max_violations})"
        except Exception as e:
            passed, detail = False, f"evaluation_error={e}"
        return self._record(
            f"business_rule:{rule_name}", dataset, "multiple", passed, detail
        )

    def get_summary(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "rule": r.rule,
                    "dataset": r.dataset,
                    "column": r.column,
                    "passed": r.passed,
                    "detail": r.detail,
                }
                for r in self.results
            ]
        )

    def print_summary(self):
        df = self.get_summary()
        total = len(df)
        if total == 0:
            print("\nNo datasets loaded — nothing to validate.")
            return df
        passed = int(df["passed"].sum())
        failed = total - passed
        print(f"\n{'=' * 60}")
        print(
            f"DATA QUALITY REPORT — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        print(f"{'=' * 60}")
        print(f"Total checks : {total}")
        print(f"Passed       : {passed} ({passed / total * 100:.1f}%)")
        print(f"Failed       : {failed} ({failed / total * 100:.1f}%)")
        print(f"{'=' * 60}")
        if failed > 0:
            print("\nFailed Checks:")
            for _, row in df[~df["passed"]].iterrows():
                print(
                    f"  ❌ [{row['dataset']}] {row['column']}: {row['rule']} — {row['detail']}"
                )
        print()
        return df


# ── Rule suites ───────────────────────────────────────────────────────────────
def load_datasets(data_dir: Path) -> Dict[str, pd.DataFrame]:
    """Load all raw datasets for validation."""
    files = {
        "orders": "olist_orders_dataset.csv",
        "order_items": "olist_order_items_dataset.csv",
        "customers": "olist_customers_dataset.csv",
        "products": "olist_products_dataset.csv",
        "sellers": "olist_sellers_dataset.csv",
        "payments": "olist_order_payments_dataset.csv",
        "reviews": "olist_order_reviews_dataset.csv",
        "mql": "olist_marketing_qualified_leads_dataset.csv",
        "closed_deals": "olist_closed_deals_dataset.csv",
    }
    datasets = {}
    for name, fname in files.items():
        path = data_dir / fname
        try:
            datasets[name] = pd.read_csv(path, low_memory=False)
            logger.info("Loaded %s: %s", name, datasets[name].shape)
        except FileNotFoundError:
            logger.warning("File not found: %s — skipping", path)
    return datasets


def run_orders_suite(v, ds):
    orders = ds["orders"]
    v.expect_column_not_null(orders, "order_id", "orders")
    v.expect_column_not_null(orders, "customer_id", "orders")
    v.expect_column_not_null(orders, "order_status", "orders")
    v.expect_column_not_null(orders, "order_purchase_timestamp", "orders")
    v.expect_column_unique(orders, "order_id", "orders")
    v.expect_column_values_in_set(
        orders,
        "order_status",
        "orders",
        {
            "delivered",
            "shipped",
            "canceled",
            "unavailable",
            "invoiced",
            "processing",
            "created",
            "approved",
        },
    )
    orders_ts = orders.copy()
    orders_ts["has_approval"] = orders_ts["order_approved_at"].notna()
    v.expect_business_rule(
        orders_ts,
        "order_status != 'approved' or has_approval == True",
        "orders",
        "approved_needs_timestamp",
    )


def run_order_items_suite(v, ds):
    items = ds["order_items"]
    v.expect_column_not_null(items, "order_id", "order_items")
    v.expect_column_not_null(items, "product_id", "order_items")
    v.expect_column_not_null(items, "seller_id", "order_items")
    v.expect_column_not_null(items, "price", "order_items")
    v.expect_column_between(items, "price", "order_items", min_val=0)
    v.expect_column_between(items, "freight_value", "order_items", min_val=0)
    v.expect_referential_integrity(
        items, "order_id", ds["orders"], "order_id", "order_items", "orders"
    )
    v.expect_referential_integrity(
        items, "product_id", ds["products"], "product_id", "order_items", "products"
    )
    v.expect_referential_integrity(
        items, "seller_id", ds["sellers"], "seller_id", "order_items", "sellers"
    )


def run_customers_suite(v, ds):
    customers = ds["customers"]
    v.expect_column_not_null(customers, "customer_id", "customers")
    v.expect_column_not_null(customers, "customer_unique_id", "customers")
    v.expect_column_unique(customers, "customer_id", "customers")


def run_payments_suite(v, ds):
    payments = ds["payments"]
    v.expect_column_not_null(payments, "order_id", "payments")
    v.expect_column_not_null(payments, "payment_type", "payments")
    v.expect_column_not_null(payments, "payment_value", "payments")
    v.expect_column_between(payments, "payment_value", "payments", min_val=0)
    v.expect_column_between(
        payments, "payment_installments", "payments", min_val=0, max_val=24
    )
    v.expect_column_values_in_set(
        payments,
        "payment_type",
        "payments",
        {"credit_card", "boleto", "voucher", "debit_card", "not_defined"},
    )
    v.expect_referential_integrity(
        payments, "order_id", ds["orders"], "order_id", "payments", "orders"
    )


def run_reviews_suite(v, ds):
    reviews = ds["reviews"]
    v.expect_column_not_null(reviews, "review_id", "reviews")
    v.expect_column_not_null(reviews, "order_id", "reviews")
    v.expect_column_not_null(reviews, "review_score", "reviews")
    v.expect_column_between(reviews, "review_score", "reviews", min_val=1, max_val=5)


def run_marketing_suite(v, ds):
    mql = ds["mql"]
    closed = ds["closed_deals"]
    v.expect_column_not_null(mql, "mql_id", "mql")
    v.expect_column_unique(mql, "mql_id", "mql")
    v.expect_column_not_null(mql, "first_contact_date", "mql")
    v.expect_column_not_null(
        mql, "origin", "mql", max_null_rate=0.01
    )  # ~60/8000 have no origin in source data
    v.expect_column_not_null(closed, "mql_id", "closed_deals")
    v.expect_column_not_null(closed, "seller_id", "closed_deals")
    v.expect_referential_integrity(
        closed, "mql_id", mql, "mql_id", "closed_deals", "mql"
    )
    merged = mql.merge(closed[["mql_id", "won_date"]], on="mql_id", how="inner")
    merged["first_contact_date"] = pd.to_datetime(merged["first_contact_date"])
    merged["won_date"] = pd.to_datetime(merged["won_date"])
    v.expect_business_rule(
        merged,
        "won_date >= first_contact_date",
        "marketing_funnel",
        "won_after_contact",
        max_violations=1,
    )  # 1 known anomaly in source data


def run_products_suite(v, ds):
    products = ds["products"]
    v.expect_column_not_null(products, "product_id", "products")
    v.expect_column_unique(products, "product_id", "products")
    v.expect_column_between(products, "product_weight_g", "products", min_val=0)
    v.expect_column_between(products, "product_photos_qty", "products", min_val=0)


def run_sellers_suite(v, ds):
    sellers = ds["sellers"]
    v.expect_column_not_null(sellers, "seller_id", "sellers")
    v.expect_column_unique(sellers, "seller_id", "sellers")
    v.expect_column_not_null(sellers, "seller_state", "sellers")


# ── Main runner ───────────────────────────────────────────────────────────────
def run_all_validations(data_dir: Path = DATA_DIR):
    """Run complete DQ validation suite and return (results_df, all_passed)."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s"
    )

    print(f"Loading datasets from: {data_dir}")
    ds = load_datasets(data_dir)

    validator = DataQualityValidator()
    if "orders" in ds:
        run_orders_suite(validator, ds)
    if "order_items" in ds:
        run_order_items_suite(validator, ds)
    if "customers" in ds:
        run_customers_suite(validator, ds)
    if "products" in ds:
        run_products_suite(validator, ds)
    if "sellers" in ds:
        run_sellers_suite(validator, ds)
    if "payments" in ds:
        run_payments_suite(validator, ds)
    if "reviews" in ds:
        run_reviews_suite(validator, ds)
    if "mql" in ds:
        run_marketing_suite(validator, ds)

    results_df = validator.print_summary()
    out_path = LOG_DIR / "dq_results.csv"
    results_df.to_csv(out_path, index=False)
    print(f"Results saved to {out_path}")

    failed = (~results_df["passed"]).sum()
    return results_df, failed == 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Olist Data Quality Validator")
    parser.add_argument(
        "--data-dir",
        default=str(DATA_DIR),
        help="Raw CSV directory (default: data/raw/)",
    )
    args = parser.parse_args()

    _, all_passed = run_all_validations(data_dir=Path(args.data_dir))
    sys.exit(0 if all_passed else 1)
