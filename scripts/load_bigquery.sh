#!/usr/bin/env bash
# Load the sample data into BigQuery (the free sandbox works) and point the API at it.
#   gcloud auth login && gcloud auth application-default login
#   ./scripts/load_bigquery.sh <gcp-project> [dataset]
#   BIGQUERY_PROJECT=<gcp-project> uv run --extra bigquery uvicorn ontology_agent_demo.api:app
set -euo pipefail
PROJECT=${1:?gcp project id}; DATASET=${2:-ontology_demo}
bq --project_id="$PROJECT" mk -f --dataset "$PROJECT:$DATASET"
for t in products stores suppliers sales inventory; do
  bq --project_id="$PROJECT" load --replace --autodetect --source_format=CSV --skip_leading_rows=1 "$DATASET.$t" "data/$t.csv"
done
echo "Loaded into $PROJECT.$DATASET"
