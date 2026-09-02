#!/usr/bin/env bash
# One-time setup for the `deploy-backend` job in .github/workflows/deploy.yml:
# Workload Identity Federation (WIF), so GitHub Actions can deploy to Cloud
# Run without ever holding a long-lived GCP service-account key, plus the
# Artifact Registry repo the backend image gets pushed to.
#
# Run this ONCE per GCP project (it is safe to re-run — every step is
# idempotent), ideally in Cloud Shell (https://console.cloud.google.com —
# the terminal icon top-right) since gcloud is already installed and
# authenticated there. See docs/ci-cd.md for the credentials this produces
# and where they go.
#
# Prerequisites this script does NOT do for you:
#   - Create the GCP project itself and link a billing account to it
#     (Cloud Run requires one even to stay within the Always Free tier —
#     console.cloud.google.com/billing).
#   - Nothing here costs money by itself; Cloud Run/Artifact Registry only
#     bill for what deploy.yml actually runs (see docs/ci-cd.md's free-tier
#     notes).
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID to your GCP project id, e.g. PROJECT_ID=lemely-prod ./scripts/gcp-bootstrap.sh}"
: "${GITHUB_REPO:=LemelyIG/Lemely}"
REGION="us-central1"
POOL_ID="github"
PROVIDER_ID="github-lemely"
SERVICE_ACCOUNT_ID="lemely-deployer"
AR_REPO="lemely"

echo "== Project: $PROJECT_ID | Repo: $GITHUB_REPO | Region: $REGION =="
gcloud config set project "$PROJECT_ID" --quiet

echo "== Enabling required APIs (safe to re-run) =="
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  iamcredentials.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com \
  --quiet

echo "== Artifact Registry repo '$AR_REPO' in $REGION =="
if ! gcloud artifacts repositories describe "$AR_REPO" --location="$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$AR_REPO" \
    --repository-format=docker \
    --location="$REGION" \
    --description="Lemely backend images (staging + production)"
else
  echo "   already exists, skipping"
fi

echo "== Workload Identity Pool '$POOL_ID' =="
if ! gcloud iam workload-identity-pools describe "$POOL_ID" --location=global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "$POOL_ID" \
    --location=global \
    --display-name="GitHub Actions"
else
  echo "   already exists, skipping"
fi

POOL_NAME="$(gcloud iam workload-identity-pools describe "$POOL_ID" --location=global --format='value(name)')"

echo "== OIDC Provider '$PROVIDER_ID', locked to $GITHUB_REPO only =="
if ! gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" --location=global --workload-identity-pool="$POOL_ID" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
    --location=global \
    --workload-identity-pool="$POOL_ID" \
    --display-name="Lemely repo" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition="assertion.repository == '${GITHUB_REPO}'" \
    --issuer-uri="https://token.actions.githubusercontent.com"
else
  echo "   already exists, skipping"
fi

echo "== Deploy service account '$SERVICE_ACCOUNT_ID' =="
SA_EMAIL="${SERVICE_ACCOUNT_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SERVICE_ACCOUNT_ID" \
    --display-name="Lemely GitHub Actions deployer"
else
  echo "   already exists, skipping"
fi

echo "== Granting roles (idempotent — re-adding an existing binding is a no-op) =="
# run.admin: create/update the Cloud Run services. artifactregistry.writer:
# push built images. serviceAccountUser: required to deploy a Cloud Run
# revision that runs as a service account (the project's default compute SA
# unless deploy.yml is changed to specify --service-account).
for ROLE in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="$ROLE" \
    --condition=None \
    --quiet >/dev/null
done

echo "== Binding WIF: only workflows running as $GITHUB_REPO may impersonate $SA_EMAIL =="
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${POOL_NAME}/attribute.repository/${GITHUB_REPO}" \
  --quiet >/dev/null

PROVIDER_NAME="$(gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" --location=global --workload-identity-pool="$POOL_ID" --format='value(name)')"

cat <<EOF

== Done. Add these as GitHub repository VARIABLES (not secrets — none of ==
== this is sensitive; WIF has no key to leak) — Settings > Secrets and    ==
== variables > Actions > Variables tab:                                  ==

  GCP_PROJECT_ID                 = ${PROJECT_ID}
  GCP_WORKLOAD_IDENTITY_PROVIDER  = ${PROVIDER_NAME}
  GCP_SERVICE_ACCOUNT             = ${SA_EMAIL}

It can take a few minutes for IAM/WIF changes to propagate — if the first
deploy run 403s on the auth step, re-run it once things settle.
EOF
