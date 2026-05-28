#!/usr/bin/env bash
# scripts/setup_bigquery.sh
# ─────────────────────────────────────────────────────────────────────────────
# Creates all required BigQuery datasets and applies the minimum IAM bindings
# needed to run the Olist Analytics Platform pipeline.
#
# Prerequisites:
#   - gcloud CLI installed and authenticated (gcloud auth application-default login)
#   - GCP_PROJECT_ID set in .env or exported in the shell
#   - bq CLI available (comes with gcloud)
#
# Usage:
#   bash scripts/setup_bigquery.sh
#   GCP_PROJECT_ID=my-project bash scripts/setup_bigquery.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Load .env if present
[ -f "$ROOT/.env" ] && set -a && source "$ROOT/.env" && set +a

PROJECT="${GCP_PROJECT_ID:?GCP_PROJECT_ID is not set. Export it or add it to .env}"
REGION="${GCP_REGION:-US}"
SERVICE_ACCOUNT="${AIRFLOW_SERVICE_ACCOUNT:-}"

echo ""
echo "══════════════════════════════════════════════════════"
echo "  Olist Analytics Platform — BigQuery Setup"
echo "  Project : $PROJECT"
echo "  Region  : $REGION"
echo "══════════════════════════════════════════════════════"

# ── 1. Create datasets ─────────────────────────────────────────────────────────
DATASETS=(
    "olist_raw:Raw ingestion layer — all source CSVs loaded here"
    "olist_analytics:Star schema — dimension and fact tables"
    "olist_analytics_staging:DBT staging views"
    "olist_analytics_marts:DBT mart tables (pre-aggregated KPIs)"
)

for entry in "${DATASETS[@]}"; do
    DATASET="${entry%%:*}"
    DESCRIPTION="${entry##*:}"

    if bq --project_id="$PROJECT" ls --datasets 2>/dev/null | grep -q "$DATASET"; then
        echo "  ✓  Dataset already exists: $DATASET"
    else
        bq --project_id="$PROJECT" mk \
            --dataset \
            --location="$REGION" \
            --description="$DESCRIPTION" \
            "$PROJECT:$DATASET"
        echo "  ✅ Created dataset: $DATASET"
    fi
done

# ── 2. IAM bindings (only if service account is specified) ────────────────────
if [ -n "$SERVICE_ACCOUNT" ]; then
    echo ""
    echo "Applying IAM bindings for: $SERVICE_ACCOUNT"

    ROLES=(
        "roles/bigquery.dataEditor"
        "roles/bigquery.jobUser"
        "roles/storage.objectCreator"
    )

    for ROLE in "${ROLES[@]}"; do
        gcloud projects add-iam-policy-binding "$PROJECT" \
            --member="serviceAccount:$SERVICE_ACCOUNT" \
            --role="$ROLE" \
            --quiet
        echo "  ✅ Granted $ROLE to $SERVICE_ACCOUNT"
    done
else
    echo ""
    echo "  ⚠️  AIRFLOW_SERVICE_ACCOUNT not set — skipping IAM bindings."
    echo "     Add AIRFLOW_SERVICE_ACCOUNT=<sa-email> to .env to apply IAM automatically."
fi

# ── 3. Enable required APIs ────────────────────────────────────────────────────
echo ""
echo "Enabling required GCP APIs..."
gcloud services enable bigquery.googleapis.com storage.googleapis.com \
    --project="$PROJECT" --quiet
echo "  ✅ APIs enabled: BigQuery, Cloud Storage"

# ── 4. Verify ─────────────────────────────────────────────────────────────────
echo ""
echo "Verifying datasets..."
bq --project_id="$PROJECT" ls --datasets
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  ✅  BigQuery setup complete!                        ║"
echo "║  Next: ./run_pipeline.sh                             ║"
echo "╚══════════════════════════════════════════════════════╝"
