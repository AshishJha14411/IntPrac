#!/usr/bin/env bash
# Ask Google whether our OAuth client is actually usable, without a browser.
#
#   ./scripts/check-google-oauth.sh                 # against localhost
#   API=https://your-backend/api/v1 ./scripts/check-google-oauth.sh
#
# Why this exists: `redirect_uri_mismatch` is by far the most common way a
# working OAuth implementation looks broken, and it is a *console* problem that
# nothing in the repo can see. Without this you find out by clicking through to
# a Google error page -- or worse, a user does. Google decides on the redirect
# before showing a consent screen, so the whole check is one unauthenticated
# request and costs nothing.
#
# Run it after changing GOOGLE_REDIRECT_URI, and again after deploying, because
# production needs its own URI registered on the same client.
set -euo pipefail

API="${API:-http://localhost:8080/api/v1}"

STATUS=$(curl -fsS "$API/auth/google/status")
case "$STATUS" in
  *'"enabled":true'*) ;;
  *) echo "✗ Google sign-in is not configured on $API"; echo "  $STATUS"; exit 1;;
esac

CONSENT=$(curl -fsS -D - -o /dev/null "$API/auth/google/login" \
  | grep -i '^location:' | sed 's/^[Ll]ocation: //' | tr -d '\r')
[ -n "$CONSENT" ] || { echo "✗ /auth/google/login did not redirect"; exit 1; }

BODY=$(mktemp)
# Follow the chain: Google answers a bad client or redirect with a 302 to its
# own error page rather than an HTTP error status, so the status code alone
# tells you nothing.
curl -fsS -L --max-redirs 5 -A "Mozilla/5.0" -o "$BODY" "$CONSENT" >/dev/null || true

fail() { echo "✗ $1"; rm -f "$BODY"; exit 1; }

if grep -qi "redirect_uri_mismatch" "$BODY"; then
  REGISTERED=$(printf '%s' "$CONSENT" | sed 's/.*redirect_uri=\([^&]*\).*/\1/' \
    | sed 's/%3A/:/g; s/%2F/\//g')
  echo "✗ redirect_uri_mismatch"
  echo
  echo "  Google has no such redirect URI on this client. Add it verbatim at"
  echo "  https://console.cloud.google.com/apis/credentials -> your OAuth client"
  echo "  -> Authorised redirect URIs:"
  echo
  echo "      $REGISTERED"
  echo
  fail "not registered yet"
fi
grep -qi "invalid_client\|deleted_client" "$BODY" && fail "invalid_client — check GOOGLE_CLIENT_ID"
grep -qi "access_blocked\|has not completed the Google verification" "$BODY" \
  && fail "consent screen blocks this account — add it under Test users"
grep -qi "invalid_request" "$BODY" && fail "invalid_request — usually a relative GOOGLE_REDIRECT_URI"

rm -f "$BODY"
echo "✓ client id accepted, redirect URI registered, consent screen reachable"
echo "  Sign-in should work in a browser now."
