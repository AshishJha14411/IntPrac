#!/usr/bin/env bash
# One-time GCP setup for the deploy workflow. Idempotent -- safe to re-run
# after a partial failure, which is the whole reason this is a script and not
# a list of console clicks. Every step is describe-then-create, so re-running
# after "you already have one of those" errors is normal, not a recovery.
#
#   cp .env.production.example .env.production   # fill it in
#   ./scripts/gcp-bootstrap.sh
#
# Then paste the GitHub secrets it prints at the end into
#   Settings -> Secrets and variables -> Actions
#
# What it will NOT do: create the Neon database, the Upstash Redis, the Google
# OAuth client, or the Vercel project. Those live outside GCP and are three
# signup forms; their values go in .env.production and this script pushes them
# into Secret Manager so they never touch the repo or a workflow file.

set -euo pipefail

die() { printf '\033[31merror\033[0m %s\n' "$*" >&2; exit 1; }
say() { printf '\033[36m==>\033[0m %s\n' "$*"; }
ok()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }

command -v gcloud >/dev/null || die "gcloud not found: https://cloud.google.com/sdk/docs/install"

# Phases. The infrastructure half needs three non-secret values; the Secret
# Manager half needs ten live credentials from four different providers. They
# are split because you can usefully do the first before you have the second,
# and being blocked on a Vercel token is no reason to have done none of it.
#
#   ./scripts/gcp-bootstrap.sh infra     APIs, registry, service account, WIF
#   ./scripts/gcp-bootstrap.sh secrets   Secret Manager only
#   ./scripts/gcp-bootstrap.sh           both (default)
PHASE="${1:-all}"
case "$PHASE" in
  infra | secrets | all) ;;
  *) die "unknown phase '$PHASE' (want: infra, secrets, all)" ;;
esac

ENV_FILE="${ENV_FILE:-.env.production}"
if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  set -a; . "./$ENV_FILE"; set +a
elif [ "$PHASE" = "infra" ] && [ -n "${GCP_PROJECT:-}" ]; then
  say "no $ENV_FILE; using the environment (infra needs no credentials)"
else
  die "$ENV_FILE not found. Copy .env.production.example and fill it in."
fi

: "${GCP_PROJECT:?set GCP_PROJECT in $ENV_FILE (the project ID, not its display name or number)}"
: "${GCP_REGION:?set GCP_REGION in $ENV_FILE, e.g. asia-south1}"
: "${GITHUB_REPO:?set GITHUB_REPO in $ENV_FILE, e.g. AshishJha14411/IntPrac}"

SA_NAME="interview-deployer"
SA="${SA_NAME}@${GCP_PROJECT}.iam.gserviceaccount.com"
POOL="github"
PROVIDER="intprac"

gcloud config set project "$GCP_PROJECT" --quiet >/dev/null
PROJECT_NUMBER=$(gcloud projects describe "$GCP_PROJECT" --format='value(projectNumber)' 2>/dev/null) \
  || die "cannot read project '$GCP_PROJECT'. Check the ID (not the display
  name, not the number) and that $(gcloud config get account) can see it."
ok "project $GCP_PROJECT (number $PROJECT_NUMBER)"

# Checked here, first, because every single command below fails without it and
# the errors do not say so. `gcloud services enable run.googleapis.com` on an
# unbilled project reports a generic FAILED_PRECONDITION, which sends you
# looking at IAM. One explicit check up front is worth the round trip.
BILLING=$(gcloud beta billing projects describe "$GCP_PROJECT" \
            --format='value(billingEnabled)' 2>/dev/null || echo "unknown")
if [ "$BILLING" != "True" ]; then
  die "billing is not linked to $GCP_PROJECT.

  Link one: https://console.cloud.google.com/billing/linkedaccount?project=$GCP_PROJECT

  A card is required, but this stack is built to sit inside the always-free
  tier: Cloud Run bills only while serving a request (--min-instances 0), and
  the scheduled jobs run for seconds a day. Set a budget alert while you are
  in there -- Billing -> Budgets & alerts -> Create budget -- so a surprise
  is an email rather than a statement."
fi
ok "billing linked"

if [ "$PHASE" = "secrets" ]; then
  say "phase 'secrets': skipping APIs, registry, service account and WIF"
else

# ---------------------------------------------------------------------------
say "APIs"
# cloudscheduler is easy to forget and fails late: the deploy gets all the way
# through building and shipping the image before the schedule step dies.
gcloud services enable \
  run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com \
  cloudscheduler.googleapis.com iamcredentials.googleapis.com sts.googleapis.com \
  cloudresourcemanager.googleapis.com --quiet
ok "enabled"

# ---------------------------------------------------------------------------
say "Artifact Registry"
gcloud artifacts repositories describe interview --location="$GCP_REGION" --quiet >/dev/null 2>&1 \
  || gcloud artifacts repositories create interview \
       --repository-format=docker --location="$GCP_REGION" \
       --description="interview-app images" --quiet
ok "$GCP_REGION-docker.pkg.dev/$GCP_PROJECT/interview"

# ---------------------------------------------------------------------------
say "Service account"
gcloud iam service-accounts describe "$SA" --quiet >/dev/null 2>&1 \
  || gcloud iam service-accounts create "$SA_NAME" \
       --display-name="GitHub Actions deployer" --quiet

# run.admin: deploy services and jobs. artifactregistry.writer: push images.
# secretmanager.secretAccessor: let the *deploy* read nothing, but Cloud Run
# needs it at runtime and this SA is also the Cloud Run identity.
# cloudscheduler.admin: create the two schedules.
# iam.serviceAccountUser on ITSELF: Cloud Scheduler jobs are created with
# --oauth-service-account-email=$SA, and creating a resource that runs as an
# SA requires actAs on that SA. Missing this is the single most common reason
# the schedule step fails with a bare PERMISSION_DENIED.
for role in roles/run.admin roles/artifactregistry.writer \
            roles/secretmanager.secretAccessor roles/cloudscheduler.admin; do
  gcloud projects add-iam-policy-binding "$GCP_PROJECT" \
    --member="serviceAccount:$SA" --role="$role" --quiet >/dev/null
done
gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --member="serviceAccount:$SA" --role=roles/iam.serviceAccountUser --quiet >/dev/null
ok "$SA"

# ---------------------------------------------------------------------------
say "Workload Identity Federation (keyless -- no service-account JSON anywhere)"
gcloud iam workload-identity-pools describe "$POOL" --location=global --quiet >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools create "$POOL" \
       --location=global --display-name="GitHub Actions" --quiet

# The attribute-condition is not optional and not a formality. Without it, a
# workflow in ANY GitHub repository on the internet can mint a token for this
# pool and deploy to your project. Google now rejects providers that omit it,
# which is one of the better breaking changes they have made.
gcloud iam workload-identity-pools providers describe "$PROVIDER" \
  --location=global --workload-identity-pool="$POOL" --quiet >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
       --location=global --workload-identity-pool="$POOL" \
       --display-name="IntPrac" \
       --issuer-uri="https://token.actions.githubusercontent.com" \
       --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
       --attribute-condition="assertion.repository=='${GITHUB_REPO}'" \
       --quiet

POOL_ID="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}"
gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/${POOL_ID}/attribute.repository/${GITHUB_REPO}" \
  --quiet >/dev/null
ok "only ${GITHUB_REPO} can assume $SA_NAME"

fi # end infra phase

# ---------------------------------------------------------------------------
if [ "$PHASE" = "infra" ]; then
  say "phase 'infra': skipping Secret Manager"
else
say "Secret Manager"
put() {
  local name="$1" value="${2:-}"
  [ -n "$value" ] || die "$name has no value -- set it in $ENV_FILE"
  gcloud secrets describe "$name" --quiet >/dev/null 2>&1 \
    || gcloud secrets create "$name" --replication-policy=automatic --quiet >/dev/null
  # Only add a version when the value actually changed, so re-running does not
  # pile up identical versions (each is billed, and it makes the history
  # useless for working out when something last changed).
  local current=""
  current=$(gcloud secrets versions access latest --secret="$name" 2>/dev/null || true)
  if [ "$current" = "$value" ]; then
    ok "$name (unchanged)"
  else
    printf '%s' "$value" | gcloud secrets versions add "$name" --data-file=- --quiet >/dev/null
    ok "$name (new version)"
  fi
}

put interview-db-url             "${DATABASE_URL:-}"
put interview-sync-db-url        "${SYNC_DATABASE_URL:-}"
put interview-migration-db-url   "${MIGRATION_DATABASE_URL:-}"
put interview-redis-url          "${REDIS_URL:-}"
put interview-jwt-secret         "${JWT_SECRET:-}"
put interview-gemini-key         "${GEMINI_API_KEY:-}"
put interview-google-client-id   "${GOOGLE_CLIENT_ID:-}"
put interview-google-client-secret "${GOOGLE_CLIENT_SECRET:-}"
put interview-s3-key-id          "${S3_ACCESS_KEY_ID:-}"
put interview-s3-secret          "${S3_SECRET_ACCESS_KEY:-}"

fi # end secrets phase

# ---------------------------------------------------------------------------
cat <<EOF

$(printf '\033[32m----------------------------------------------------------------\033[0m')
GCP is ready. Now set these nine in GitHub:
  https://github.com/${GITHUB_REPO}/settings/secrets/actions

  GCP_PROJECT                       ${GCP_PROJECT}
  GCP_REGION                        ${GCP_REGION}
  GCP_SERVICE_ACCOUNT               ${SA}
  GCP_WORKLOAD_IDENTITY_PROVIDER    ${POOL_ID}/providers/${PROVIDER}
  API_ORIGIN                        (fill after the first deploy, see below)
  FRONTEND_ORIGIN                   ${FRONTEND_ORIGIN:-https://<your-vercel-app>.vercel.app}
  VERCEL_TOKEN                      from vercel.com/account/tokens
  VERCEL_ORG_ID                     from .vercel/project.json after 'vercel link'
  VERCEL_PROJECT_ID                 from the same file

API_ORIGIN is a chicken-and-egg: Cloud Run mints the URL on first deploy. Get
it without one by deploying by hand once --

  gcloud run deploy interview-api --region ${GCP_REGION} \\
    --image ${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/interview/api:bootstrap \\
    --allow-unauthenticated --format='value(status.url)'

-- or just run the workflow, read the URL off the failed verify step, set the
secret, and re-run. Both work; the second is less typing.

Last: add \${API_ORIGIN}/api/v1/auth/google/callback to the Authorised redirect
URIs of your OAuth client. It is compared byte for byte, so a trailing slash
is a different URI.
$(printf '\033[32m----------------------------------------------------------------\033[0m')
EOF
