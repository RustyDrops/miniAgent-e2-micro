#!/usr/bin/env bash
# Production Hardened Deployment Script for MiniAgent Ephemeral Sandbox
set -euo pipefail

PROJECT_ID="$(gcloud config get-value project)"
REGION="${REGION:-us-central1}"
SERVICE_NAME="miniagent-sandbox"
IMAGE_TAG="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:latest"
SA_NAME="miniagent-sandbox-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "=== 1. Building Container Image with Cloud Build ==="
gcloud builds submit sandbox_service/ --tag "${IMAGE_TAG}"

echo "=== 2. Provisioning Zero-Privilege Runtime Service Account ==="
if ! gcloud iam service-accounts describe "${SA_EMAIL}" >/dev/null 2>&1; then
    gcloud iam service-accounts create "${SA_NAME}" \
        --description="Minimal execution service account for ephemeral sandbox with ZERO project permissions" \
        --display-name="MiniAgent Sandbox Runner"
    echo "Created service account: ${SA_EMAIL}"
else
    echo "Service account ${SA_EMAIL} already exists."
fi

echo "=== 3. Deploying Hardened Cloud Run Service ==="
# Hardening parameters:
# - --no-allow-unauthenticated: Disallow public unauthenticated invocations (prevents open RCE)
# - --concurrency 1: Strictly one execution per container instance (prevents cross-request state pollution)
# - --service-account: Minimal identity without GCP roles (prevents metadata token abuse)
# - --memory 512Mi / --cpu 1: Bound resource usage
# - --min-instances 0 / --max-instances 2: Prevent runaway scaling bills
gcloud run deploy "${SERVICE_NAME}" \
    --image "${IMAGE_TAG}" \
    --platform managed \
    --region "${REGION}" \
    --memory 512Mi \
    --cpu 1 \
    --concurrency 1 \
    --min-instances 0 \
    --max-instances 2 \
    --service-account "${SA_EMAIL}" \
    --no-allow-unauthenticated

SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" --platform managed --region "${REGION}" --format 'value(status.url)')"
echo "=== Deployment Complete ==="
echo "Service Endpoint: ${SERVICE_URL}"
echo ""
echo "To bind this endpoint in your local .env:"
echo "CLOUD_RUN_SANDBOX_URL=${SERVICE_URL}"
