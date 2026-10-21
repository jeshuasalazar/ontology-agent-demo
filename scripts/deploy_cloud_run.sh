#!/usr/bin/env bash
# Deploy the API to Cloud Run (needs a GCP project with billing enabled).
#   ./scripts/deploy_cloud_run.sh <gcp-project> [region]
set -euo pipefail
PROJECT=${1:?gcp project id}; REGION=${2:-us-central1}
gcloud run deploy ontology-agent-demo --project "$PROJECT" --region "$REGION" --source . \
  --allow-unauthenticated --set-env-vars "BIGQUERY_PROJECT=$PROJECT,AUDIT_LOG=/tmp/audit.jsonl"
