#!/usr/bin/env bash
# Olist Analytics Platform — end-to-end pipeline runner
# Every step is && -chained; a failure stops the run immediately.
#
# Usage:
#   ./run_pipeline.sh                  # full refresh (safe, idempotent)
#   ./run_pipeline.sh --incremental    # append-only ingest (risk: duplicates)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── Resolve Python and dbt executables ───────────────────────────────────────
# Priority: .venv (project-local) → active venv → system PATH
if [ -f "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
  DBT="$ROOT/.venv/bin/dbt"
elif command -v python &>/dev/null; then
  PYTHON="$(command -v python)"
  DBT="$(command -v dbt)"
else
  echo "❌  Python not found. Create a venv: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

banner() { echo ""; echo "══════════════════════════════════════════"; echo "  $1"; echo "══════════════════════════════════════════"; }

# ── Parse flags ───────────────────────────────────────────────────────────────
INCREMENTAL=false
for arg in "$@"; do
  case "$arg" in
    --incremental) INCREMENTAL=true ;;
    *) echo "❌  Unknown flag: $arg"; echo "    Usage: $0 [--incremental]"; exit 1 ;;
  esac
done

# ── Incremental guard ─────────────────────────────────────────────────────────
if [ "$INCREMENTAL" = true ]; then
  echo ""
  echo "⚠️  WARNING — INCREMENTAL MODE"
  echo "   WRITE_APPEND will be used for: orders, order_items, reviews, mql, closed_deals"
  echo "   Re-running on already-loaded data WILL create duplicates in olist_raw."
  echo "   Only use this flag when ingesting genuinely new rows."
  echo ""
  printf "   Type YES to continue, anything else to abort: "
  read -r CONFIRM
  if [ "$CONFIRM" != "YES" ]; then
    echo "Aborted."
    exit 1
  fi
  INGEST_FLAGS="--incremental"
else
  INGEST_FLAGS=""
fi

# ── Load environment variables ────────────────────────────────────────────────
[ -f "$ROOT/.env" ] && set -a && source "$ROOT/.env" && set +a

cd "$ROOT"

PROJECT="${GCP_PROJECT_ID:?GCP_PROJECT_ID is not set in .env}"

# ── 0. BigQuery dataset check ─────────────────────────────────────────────────
banner "STEP 0 · BigQuery dataset check"
$PYTHON "$ROOT/scripts/check_bq_datasets.py" || exit 1

# ── 1. Data quality — core datasets ──────────────────────────────────────────
banner "STEP 1 · DQ Validation (core datasets)"
$PYTHON data_quality/dq_validation.py &&

# ── 2. Data quality — geolocation ────────────────────────────────────────────
banner "STEP 2 · DQ Validation (geolocation)"
$PYTHON data_quality/dq_geolocation.py &&

# ── 3. Ingest raw CSVs → BigQuery olist_raw ───────────────────────────────────
banner "STEP 3 · Ingest raw CSVs → BigQuery (olist_raw)  [mode: $( [ "$INCREMENTAL" = true ] && echo 'incremental' || echo 'full refresh' )]"
$PYTHON ingestion/ingest_to_bigquery.py $INGEST_FLAGS &&

# ── 4. Ingest geolocation → DimGeography ─────────────────────────────────────
banner "STEP 4 · Ingest geolocation → BigQuery (DimGeography)"
$PYTHON ingestion/ingest_geolocation.py &&

# ── 5. Build star schema (olist_analytics) ────────────────────────────────────
banner "STEP 5 · Build star schema (olist_analytics)"
$PYTHON "$ROOT/scripts/run_schema.py" &&

# ── 6. dbt — install packages, run models, run tests ─────────────────────────
banner "STEP 6 · dbt deps + run + test"
(cd "$ROOT/dbt_project" && $DBT deps && $DBT run && $DBT test) &&

# ── 7. Generate analytics charts ─────────────────────────────────────────────
banner "STEP 7 · Generate analytics charts"
$PYTHON notebooks/olist_analysis.py &&

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  ✅  Pipeline completed successfully!    ║"
echo "║  Open dashboard/index.html to explore.   ║"
echo "╚══════════════════════════════════════════╝"
