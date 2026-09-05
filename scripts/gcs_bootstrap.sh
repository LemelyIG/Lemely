#!/usr/bin/env bash
# One-time setup for the object storage the backend actually writes to:
# the two Google Cloud Storage buckets (self-mark uploads, profile pictures)
# for ONE environment, plus the IAM the Cloud Run runtime service account
# needs to read, write, and sign URLs for them.
#
# `scripts/gcp-bootstrap.sh` is the sibling of this script: that one sets up
# how GitHub Actions *deploys* (Workload Identity Federation, Artifact
# Registry, the deployer service account). This one sets up what the deployed
# service *stores*. They are separate because they are granted to different
# identities — the deployer never touches object data, and the runtime service
# account never deploys.
#
# Run once per environment. Every step is idempotent: a second run creates
# nothing and re-adds bindings that already exist, which GCS and IAM both
# treat as no-ops. Cloud Shell (https://console.cloud.google.com, terminal
# icon top-right) is the easiest place to run it — gcloud is installed and
# authenticated there already.
#
#   PROJECT_ID=lemelyig ENVIRONMENT=staging ./scripts/gcs_bootstrap.sh
#   PROJECT_ID=lemelyig ENVIRONMENT=production ./scripts/gcs_bootstrap.sh
#
# Cost: buckets themselves are free; you pay for stored bytes and egress.
# The GCS always-free tier (5 GiB-months of Standard storage in a US region)
# covers this app's expected footprint several times over.
#
# See docs/deployment.md §3.2 step 5 for how the names here line up with
# LEMELY_STORAGE__BUCKET / LEMELY_STORAGE__AVATAR_BUCKET in
# .github/workflows/deploy.yml.
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID to your GCP project id, e.g. PROJECT_ID=lemelyig ./scripts/gcs_bootstrap.sh}"
: "${REGION:=us-central1}"
: "${ENVIRONMENT:=staging}"

case "$ENVIRONMENT" in
  staging | production) ;;
  *)
    echo "ENVIRONMENT must be 'staging' or 'production' (got '$ENVIRONMENT')." >&2
    exit 2
    ;;
esac

# Must match the defaults deploy.yml computes for LEMELY_STORAGE__BUCKET and
# LEMELY_STORAGE__AVATAR_BUCKET. GCS bucket names are one GLOBAL namespace, so
# these are prefixed with the project id (itself already globally unique)
# rather than being bare "uploads"/"avatars" the way the Supabase buckets were.
: "${UPLOADS_BUCKET:=${PROJECT_ID}-uploads-${ENVIRONMENT}}"
: "${AVATAR_BUCKET:=${PROJECT_ID}-avatars-${ENVIRONMENT}}"

echo "== Project: $PROJECT_ID | Environment: $ENVIRONMENT | Region: $REGION =="
gcloud config set project "$PROJECT_ID" --quiet

# The Cloud Run revision runs as this identity. deploy.yml passes no
# --service-account flag, so that is the project's DEFAULT COMPUTE service
# account. Override RUNTIME_SA if deploy.yml is ever changed to pin a
# dedicated one.
if [ -z "${RUNTIME_SA:-}" ]; then
  PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
  RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
  echo "== RUNTIME_SA not set; using the default compute service account =="
fi
echo "   runtime service account: $RUNTIME_SA"

echo "== Enabling required APIs (safe to re-run) =="
# iamcredentials is not optional here: signed avatar/upload URLs are produced
# by the IAM signBlob API, because a Cloud Run workload-identity credential
# has no local signer (see lemely/io/storage.py's GcsStorageBackend).
gcloud services enable \
  storage.googleapis.com \
  iamcredentials.googleapis.com \
  --quiet

for BUCKET in "$UPLOADS_BUCKET" "$AVATAR_BUCKET"; do
  echo "== Bucket gs://$BUCKET =="
  if gcloud storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1; then
    echo "   already exists, skipping create"
  else
    # --uniform-bucket-level-access turns off per-object ACLs, so access is
    # decided only by the IAM bindings below. --public-access-prevention is
    # the belt-and-braces half: these buckets hold student scans and profile
    # pictures and must never become world-readable by accident. Every read
    # the app serves goes through a short-lived V4 signed URL instead.
    gcloud storage buckets create "gs://${BUCKET}" \
      --project="$PROJECT_ID" \
      --location="$REGION" \
      --uniform-bucket-level-access \
      --public-access-prevention
    echo "   created"
  fi

  echo "   granting roles/storage.objectAdmin to $RUNTIME_SA"
  # objectAdmin, not objectViewer/objectCreator: the backend uploads,
  # downloads, and (since the avatar delete route) removes objects.
  # Scoped to the bucket, never to the project.
  gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/storage.objectAdmin" \
    --quiet >/dev/null
done

echo "== Granting roles/iam.serviceAccountTokenCreator on $RUNTIME_SA to itself =="
# This is the non-obvious one. On Cloud Run the credential has no private key,
# so google-cloud-storage cannot sign a URL locally; it calls IAM signBlob as
# the service account instead. That call is an impersonation of the SA BY the
# SA, which needs this role granted on the service account resource itself.
# Without it every avatar and upload URL comes back as a 403 at sign time and
# the profile route quietly renders no picture.
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --quiet >/dev/null

cat <<EOF

== Done for '$ENVIRONMENT'. What now exists: ==

  gs://${UPLOADS_BUCKET}   (self-mark scans + mark schemes)
  gs://${AVATAR_BUCKET}   (profile pictures)

  Both: uniform bucket-level access, public access prevented, in $REGION.
  ${RUNTIME_SA}
    - roles/storage.objectAdmin on each bucket
    - roles/iam.serviceAccountTokenCreator on itself (V4 signed URLs)

These are exactly the names .github/workflows/deploy.yml computes by default
for this environment, so no GitHub variables are needed. To use different
names, create GCS_UPLOADS_BUCKET / GCS_AVATAR_BUCKET as ENVIRONMENT variables
under Settings > Environments > ${ENVIRONMENT} and re-run this script with
UPLOADS_BUCKET / AVATAR_BUCKET set to match.

Re-run with ENVIRONMENT=production to do the other environment.
IAM changes can take a minute or two to propagate.
EOF
