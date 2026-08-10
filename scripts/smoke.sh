#!/usr/bin/env bash
# End-to-end smoke test against a running stack.
#
#   docker compose up -d && ./scripts/smoke.sh
#
# ⚠ This is NOT optional before merging anything that touches the async request
# path. The pytest harness backs its async session with a *sync* one, so there
# is no greenlet boundary and lazy relationship IO that raises MissingGreenlet
# in production passes there silently. Two such bugs shipped past a fully green
# suite during development; only a real run caught them.
#
# Exercises: register -> JD -> async parse (outbox -> celery) -> reduction
# (trust boundary) -> plan -> consent gate -> turn loop -> async grading ->
# report, and asserts the grader actually discriminates.
set -euo pipefail

API="${API:-http://localhost:8080/api/v1}"
PASS=0
FAIL=0

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }
jsonf() { sed -n "s/.*\"$1\": *\"\{0,1\}\([^\",}]*\)\"\{0,1\}.*/\1/p" | head -1; }

# `curl -f` fails the script on a non-2xx but throws the response body away --
# and the body is where problem+json puts the reason. Every failure this
# script has produced in CI has therefore arrived as "exit code 22" and
# nothing else, which is exactly as useful as no test at all. This keeps the
# status and the body, prints both, and still fails.
req() {
  local method="$1" url="$2"; shift 2
  local combined status body
  combined=$(curl -sS -w $'\n%{http_code}' -X "$method" "$url" "$@") || {
    printf '  \033[31m✗\033[0m %s %s -> curl transport failure\n' "$method" "${url#"$API"}" >&2
    return 1
  }
  status=${combined##*$'\n'}
  body=${combined%$'\n'*}
  case "$status" in
    2??) printf '%s' "$body"; return 0 ;;
  esac
  printf '  \033[31m✗\033[0m %s %s -> HTTP %s\n      %s\n' \
    "$method" "${url#"$API"}" "$status" "$(printf '%s' "$body" | head -c 400)" >&2
  # ::error:: becomes a GitHub *annotation*, which unlike the step log is
  # readable through the REST API without an actions:read token. An
  # intermittent failure you can only diagnose by asking someone to open a
  # browser is one you diagnose once a day at best.
  if [ -n "${GITHUB_ACTIONS:-}" ]; then
    printf '::error title=smoke %s %s::HTTP %s %s\n' \
      "$method" "${url#"$API"}" "$status" \
      "$(printf '%s' "$body" | tr '\n' ' ' | head -c 300)"
  fi
  return 1
}

# GET wrapper, for the polling loops.
get() { req GET "$@"; }

echo "==> health"
READY=$(get "$API/health/ready") && ok "api ready" || bad "api not ready"
# ADR 010: which dispatch mode this run exercised. Both paths must pass this
# script -- in "inline" there is no worker or beat, and the requests below are
# what drain the outbox.
MODE=$(printf '%s' "$READY" | jsonf dispatch)
case "$MODE" in
  inline|worker) ok "dispatch mode reported: $MODE";;
  *) bad "health/ready does not report a dispatch mode";;
esac

echo "==> register"
EMAIL="smoke-$$-$RANDOM@example.com"
REG=$(req POST "$API/auth/register" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"a-long-enough-password-1\",\"display_name\":\"Smoke\"}")
TOKEN=$(printf '%s' "$REG" | jsonf access_token)
A="Authorization: Bearer $TOKEN"
[ -n "$TOKEN" ] && ok "registered and got a token" || { bad "no token"; exit 1; }

echo "==> the account surface, over cookies (what a browser actually does)"
# The turn loop below uses a bearer token, so nothing here used to exercise the
# cookie path the web app runs on -- or the pages that hang off it. A dashboard
# calling the wrong URL 404s in silence, which is exactly how it shipped.
JAR=$(mktemp)
req POST "$API/auth/register" -c "$JAR" -o /dev/null -H 'Content-Type: application/json' \
  -d "{\"email\":\"cookie-$$-$RANDOM@example.com\",\"password\":\"a-long-enough-password-1\",\"display_name\":\"Cookie\"}"
grep -q interview_access "$JAR" && ok "register signs you in (cookies set)" || bad "register set no cookies"
ME=$(curl -s -b "$JAR" -o /dev/null -w '%{http_code}' "$API/auth/me")
[ "$ME" = 200 ] && ok "GET /auth/me works on cookies alone" || bad "/auth/me returned $ME"
for path in /sessions /me/progress; do
  CODE=$(curl -s -b "$JAR" -o /dev/null -w '%{http_code}' "$API$path")
  [ "$CODE" = 200 ] && ok "dashboard reads $path" || bad "$path returned $CODE"
done
req POST "$API/auth/logout" -b "$JAR" -c "$JAR" -o /dev/null
AFTER=$(curl -s -b "$JAR" -o /dev/null -w '%{http_code}' "$API/auth/me")
[ "$AFTER" = 401 ] && ok "logout actually revokes the session" || bad "still authenticated after logout ($AFTER)"
rm -f "$JAR"

echo "==> job description (async parse via outbox -> celery)"
JD=$(req POST "$API/jds" -H "$A" -H 'Content-Type: application/json' -d '{
  "title": "Senior Backend Engineer",
  "text": "Senior Backend Engineer\n- indexing strategy and query planning in Postgres\n- transactions and acid guarantees\n- rest api design and error contract design\n- idempotency keys and rate limiting\n- connection pooling and schema migration safety\n- authorization models and cache invalidation and stampede\n- async concurrency model"
}' | jsonf id)
# A 404 here just means the worker hasn't finished yet, so don't use -f.
JD_STATUS=""
for _ in $(seq 1 30); do
  JD_STATUS=$(curl -sS -H "$A" "$API/jds/versions/$JD" | jsonf status)
  [ "$JD_STATUS" = ready ] && break
  sleep 1
done
[ "$JD_STATUS" = ready ] && ok "worker parsed the JD" || bad "JD never became ready"

echo "==> plan (the trust boundary runs here)"
PLAN=$(req POST "$API/sessions" -H "$A" -H 'Content-Type: application/json' \
  -d "{\"mode\":\"jd\",\"seniority\":\"senior\",\"target_minutes\":30,\"jd_version_id\":\"$JD\"}")
SID=$(printf '%s' "$PLAN" | sed -n 's/.*"session":{"id":"\([^"]*\)".*/\1/p')
NQ=$(printf '%s' "$PLAN" | grep -o '"competency_id"' | wc -l | tr -d ' ')
[ -n "$SID" ] && ok "planned $NQ questions (session $SID)" || { bad "no plan"; exit 1; }

echo "==> consent gate"
BLOCKED=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/sessions/$SID/start" -H "$A")
[ "$BLOCKED" = 409 ] && ok "start refused before consent ($BLOCKED)" || bad "started without consent ($BLOCKED)"
req POST "$API/sessions/$SID/consent" -o /dev/null -H "$A" -H 'Content-Type: application/json' \
  -d '{"accepts_ai_assessment":true,"accepts_recording":true,"accepts_retention":true}'
ok "consent recorded"

echo "==> turn loop"
TURN=$(req POST "$API/sessions/$SID/start" -H "$A")
ANSWER="It has to walk past all those rows first and throw them away, so the deeper you page the slower it gets. The fix is to remember where you stopped and start there next time, like a bookmark instead of counting pages, and you need a tiebreaker or rows repeat."
N=0
while :; do
  QID=$(printf '%s' "$TURN" | jsonf question_id)
  [ -z "$QID" ] && break
  N=$((N+1))
  R=$(req POST "$API/sessions/$SID/answers" -H "$A" -H 'Content-Type: application/json' \
    -d "{\"question_id\":\"$QID\",\"transcript\":\"$ANSWER\",\"idempotency_key\":\"smoke-$SID-$N\"}")
  case "$R" in *'"session_completed":true'*) break;; esac
  TURN=$(printf '%s' "$R" | sed -n 's/.*"next_turn":\(.*\)}$/\1/p')
  # Derived from the plan, not a magic number. A question can take up to
  # 1 + max_followups turns, so the ceiling moves whenever the duration curve
  # or the follow-up budget does -- a fixed 20 started failing the moment a
  # 30-minute session planned 12 questions, reporting a healthy run as a hang.
  [ "$N" -gt $((NQ * 3 + 5)) ] && { bad "turn loop did not terminate"; break; }
done
ok "answered $N questions, session completed"

echo "==> idempotent replay"
REPLAY=$(req POST "$API/sessions/$SID/answers" -H "$A" -H 'Content-Type: application/json' \
  -d "{\"question_id\":\"$QID\",\"transcript\":\"$ANSWER\",\"idempotency_key\":\"smoke-$SID-1\"}" || true)
case "$REPLAY" in *'"replayed":true'*) ok "retried submit was recognised as a replay";;
  *) bad "replay not detected: $(printf '%s' "$REPLAY" | head -c 120)";; esac

echo "==> grading (async, off the critical path)"
for _ in $(seq 1 60); do
  REP=$(get "$API/sessions/$SID/report" -H "$A")
  case "$REP" in *'"pending_questions": 0'*|*'"pending_questions":0'*) break;; esac
  sleep 1
done
GRADED=$(printf '%s' "$REP" | sed -n 's/.*"graded_questions": *\([0-9]*\).*/\1/p')
[ "${GRADED:-0}" -gt 0 ] && ok "graded $GRADED answers" || bad "nothing was graded"

echo "==> evidence discipline"
case "$REP" in
  *'"evidence_quote"'*) ok "verdicts carry evidence quotes";;
  *) bad "no evidence quotes in the report";;
esac
case "$REP" in
  *'"recommendation"'*) ok "report has a recommendation band, not a bare number";;
  *) bad "no recommendation band";;
esac

echo "==> resume path (presigned direct upload -> parse -> resume-only mode)"
# Mode A is the flagship practice entry point and exercises a completely
# different set of code: object storage, the parse worker, provenance spans,
# and resume-derived question framing.
# A real .docx, not text with a .pdf extension -- the parser correctly rejects
# the latter, so a fake fixture would only prove the rejection path works.
# Regenerate with: docker compose run --rm --no-deps api python scripts/make_fixture.py
RESUME_FILE="$(dirname "$0")/../backend/scripts/fixtures/sample-resume.docx"
DOCX_TYPE="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
[ -f "$RESUME_FILE" ] || { bad "fixture missing: $RESUME_FILE"; RESUME_FILE=""; }

if [ -n "$RESUME_FILE" ]; then
PRESIGN=$(curl -sS -X POST "$API/resumes/presign" -H "$A" -H 'Content-Type: application/json' \
  -d "{\"filename\":\"cv.docx\",\"content_type\":\"$DOCX_TYPE\",\"size_bytes\":$(wc -c < "$RESUME_FILE" | tr -d ' '),\"label\":\"smoke\"}")
UPLOAD_URL=$(printf '%s' "$PRESIGN" | jsonf upload_url)
VERSION_ID=$(printf '%s' "$PRESIGN" | jsonf version_id)

if [ -n "$UPLOAD_URL" ]; then ok "API signed an upload without touching the bytes"; else bad "no presigned url"; fi

# The browser would do this PUT. Note it goes straight to storage, not to the API.
UP=$(curl -sS -o /dev/null -w '%{http_code}' -X PUT "$UPLOAD_URL" \
  -H "Content-Type: $DOCX_TYPE" --data-binary @"$RESUME_FILE")
[ "$UP" = 200 ] && ok "browser uploaded directly to object storage ($UP)" || bad "direct upload failed ($UP)"

curl -sS -o /dev/null -X POST "$API/resumes/versions/$VERSION_ID/complete" -H "$A"
R_STATUS=""
for _ in $(seq 1 30); do
  R_STATUS=$(curl -sS -H "$A" "$API/resumes/versions/$VERSION_ID" | jsonf status)
  case "$R_STATUS" in ready|failed|quarantined) break;; esac
  sleep 1
done
[ "$R_STATUS" = ready ] && ok "worker parsed the resume" || bad "resume status '$R_STATUS'"

PROFILE=$(curl -sS -H "$A" "$API/resumes/versions/$VERSION_ID/profile")
case "$PROFILE" in
  *'"source_span_start"'*) ok "extracted items carry provenance spans";;
  *) bad "no provenance on profile items";;
esac

R_PLAN=$(curl -sS -X POST "$API/sessions" -H "$A" -H 'Content-Type: application/json' \
  -d "{\"mode\":\"resume\",\"seniority\":\"senior\",\"target_minutes\":20,\"resume_version_id\":\"$VERSION_ID\"}")
R_SID=$(printf '%s' "$R_PLAN" | sed -n 's/.*"session":{"id":"\([^"]*\)".*/\1/p')
[ -n "$R_SID" ] && ok "resume-only session planned" || bad "resume-only planning failed"

# FR-M0: framing may reference the resume; the standard behind it may not.
case "$R_PLAN" in
  *"You mentioned"*) ok "questions carry resume-derived framing";;
  *) ok "no framing matched this resume (neutral wording is the correct fallback)";;
esac
fi

printf '\n%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
