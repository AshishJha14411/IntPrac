#!/usr/bin/env bash
# Push every GitHub Actions secret the deploy workflow needs, in one command.
#
#   gh auth login          # once, opens a browser
#   ./scripts/github-secrets.sh
#
# Ten secrets set by hand through the web UI is ten chances to paste a value
# with a trailing newline, or into the wrong field, or to miss one entirely --
# and a missing one does not fail until the deploy is most of the way through.
# Everything here is derived from .env.production and the live GCP project, so
# it agrees with what was actually created by gcp-bootstrap.sh.
#
# Nothing is printed. `gh secret set` reads from stdin so the values do not
# appear in your shell history or in this script's output either.

set -euo pipefail

die() { printf '\033[31merror\033[0m %s\n' "$*" >&2; exit 1; }
say() { printf '\033[36m==>\033[0m %s\n' "$*"; }
ok()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }
skip(){ printf '  \033[33m—\033[0m %s\n' "$*"; }

command -v gh >/dev/null || die "gh not found.
  Windows:  winget install --id GitHub.cli
  WSL:      sudo apt install gh
  then:     gh auth login"
gh auth status >/dev/null 2>&1 || die "gh is installed but not logged in. Run: gh auth login"

# Same key/value parser as gcp-bootstrap: a .env file is not a shell script,
# and sourcing one truncates any value containing an unquoted `&`.
load_env() {
  local file="$1" line key value
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in '' | '#'*) continue ;; esac
    case "$line" in *=*) ;; *) continue ;; esac
    key=${line%%=*}
    value=${line#*=}
    key=${key#"${key%%[![:space:]]*}"}
    key=${key%"${key##*[![:space:]]}"}
    case "$value" in
      \"*\") value=${value#\"}; value=${value%\"} ;;
      \'*\') value=${value#\'}; value=${value%\'} ;;
    esac
    export "$key=$value"
  done < "$file"
}

ENV_FILE="${ENV_FILE:-.env.production}"
[ -f "$ENV_FILE" ] || die "$ENV_FILE not found -- run from the repo root."
load_env "./$ENV_FILE"

: "${GCP_PROJECT:?missing in $ENV_FILE}"
: "${GCP_REGION:?missing in $ENV_FILE}"
: "${GITHUB_REPO:?missing in $ENV_FILE}"

command -v gcloud >/dev/null || die "gcloud not found (needed for the project number)"
NUMBER=$(gcloud projects describe "$GCP_PROJECT" --format='value(projectNumber)' 2>/dev/null) \
  || die "cannot read project $GCP_PROJECT"

# printf, not echo: echo appends a newline, and a secret with a trailing
# newline fails in ways that look like a wrong value rather than a wrong
# length. This is the single most common way this task goes wrong by hand.
put() {
  local name="$1" value="${2:-}"
  if [ -z "$value" ]; then
    skip "$name (no value -- set it and re-run)"
    return
  fi
  printf '%s' "$value" | gh secret set "$name" --repo "$GITHUB_REPO" >/dev/null
  ok "$name"
}

say "GCP"
put GCP_PROJECT                    "$GCP_PROJECT"
put GCP_REGION                     "$GCP_REGION"
put GCP_SERVICE_ACCOUNT            "interview-deployer@${GCP_PROJECT}.iam.gserviceaccount.com"
put GCP_WORKLOAD_IDENTITY_PROVIDER "projects/${NUMBER}/locations/global/workloadIdentityPools/github/providers/intprac"
put GCS_BUCKET                     "${GCS_BUCKET:-}"

say "Origins"
put API_ORIGIN      "${API_ORIGIN:-}"
put FRONTEND_ORIGIN "${FRONTEND_ORIGIN:-}"

say "Vercel"
# Written by `vercel link`, so read it rather than asking for it again.
LINK="frontend/.vercel/project.json"
if [ -f "$LINK" ]; then
  ORG=$(sed -n 's/.*"orgId" *: *"\([^"]*\)".*/\1/p' "$LINK" | head -1)
  PROJ=$(sed -n 's/.*"projectId" *: *"\([^"]*\)".*/\1/p' "$LINK" | head -1)
else
  ORG="${VERCEL_ORG_ID:-}"; PROJ="${VERCEL_PROJECT_ID:-}"
  skip "no $LINK -- run 'cd frontend && npx vercel link' to fill these in"
fi
put VERCEL_ORG_ID     "$ORG"
put VERCEL_PROJECT_ID "$PROJ"
put VERCEL_TOKEN      "${VERCEL_TOKEN:-}"

echo
say "What the repo has now"
gh secret list --repo "$GITHUB_REPO" --json name --jq '.[].name' 2>/dev/null | sort | sed 's/^/  /'
echo
echo "Missing any? Set the value and re-run -- this is idempotent."
echo "When the list is complete:  git checkout main && git merge dev && git push"
