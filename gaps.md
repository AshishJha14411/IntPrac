# Codebase gap review

Reviewed: 2026-08-08  
Scope: Next.js frontend, FastAPI API, authentication and authorization, interview state machine, voice flow, document intake, grading/reporting, workers/outbox, persistence, Docker/CI, tests, UX, accessibility, privacy, and the stated requirements.

## Executive summary

The codebase has a thoughtful core: the scoring-isolation boundary is unusually explicit, rubrics are frozen per session, error responses are consistent, the transactional outbox is well motivated, and the backend has a substantial test suite. The current build is not ready for a public beta, however. The highest-risk gaps are authorization around referenced documents and reviewer mutations, turn-order enforcement, non-durable answer retries, voice submission races, reports that poll forever, and privacy/retention promises that are not implemented.

The most important theme is a mismatch between comments/requirements and enforceable behavior. Several properties described as guarantees are currently conventions or UI behavior only. A direct API caller can bypass them.

### Priority definitions

- **P0 — release blocker:** security boundary failure, data-integrity risk, core-flow breakage, or an explicit privacy promise that is false.
- **P1 — fix before beta:** major UX/reliability/accessibility gap or a likely production failure.
- **P2 — planned hardening:** maintainability, observability, test depth, performance, or defense-in-depth.
- **P3 — roadmap:** intentionally unbuilt product scope.

## Validation performed

| Check | Result | Notes |
|---|---:|---|
| Backend tests | Pass | 306 passed; one dependency deprecation warning. |
| Backend coverage | 81% | Document routes/services are 37–48%; worker parsing/grading/retention entrypoints are 0%. |
| Ruff | Pass | No lint findings. |
| Mypy | Fail | 23 errors in 9 files; CI marks this check `continue-on-error`. |
| Alembic drift check | Pass | No new upgrade operations detected. |
| Frontend production Docker build | Pass | Next.js 15.5.23 compiled and type-checked. |
| Frontend ESLint | Pass | `next lint` is deprecated and must be replaced before Next.js 16. |
| Deterministic frontend install | Fail | `npm ci` rejects `package-lock.json` as out of sync (missing optional Sharp and resolver packages). |
| `.env.example` boot check | Fail | Its `SameSite=None` + `Secure=false` combination is rejected by the application's own settings validator. |

The existing shell smoke test was inspected but not treated as browser coverage: it does not start the web app, exercise a real browser, validate accessibility, or test object-storage CORS.

## P0 — release blockers

### G-001 — Session creation accepts another user's resume or JD ID

**Area:** authorization / privacy  
**Evidence:** [`create_session`](backend/app/api/v1/sessions.py#L104) loads `ResumeVersion`, `ResumeProfile`, `JDVersion`, and `JDProfile` by caller-supplied UUID at [lines 123–155](backend/app/api/v1/sessions.py#L123), but never checks the document owner or organization.

**Impact:** an authenticated user who obtains a UUID can build an interview from another user's resume or another organization's JD. Resume-derived framing and selected competencies can disclose information even though the grader remains isolated from the source prose.

**Recommendation:** load resources through ownership/org-scoped query helpers; return the same 404/403 shape for missing and inaccessible IDs; add cross-user and cross-org integration tests for resume, JD, and combined modes.

### G-002 — Reviewer read access is reused for candidate mutations

**Area:** authorization / session integrity  
**Evidence:** [`_owned_session`](backend/app/api/v1/sessions.py#L91) always grants the `SESSION_READ_ORG` escape hatch. The same helper is used by consent, start, answer, hint, and abandon endpoints at [lines 266–402](backend/app/api/v1/sessions.py#L266).

**Impact:** a reviewer in the same organization can consent for a candidate, start or abandon their session, submit answers, and consume hints. `Answerer` does not prevent this because reviewer/admin roles inherit member capabilities.

**Recommendation:** split `load_owned_candidate_session` from `load_reviewable_session`; mutation routes should require candidate ownership unless a distinct, narrowly defined administrative capability explicitly allows the action. Add a reviewer mutation-denial matrix.

### G-003 — Answers and hints are not restricted to the current turn

**Area:** functionality / scoring integrity  
**Evidence:** answer and hint routes accept any question ID belonging to the session ([`sessions.py`](backend/app/api/v1/sessions.py#L328)); [`submit_answer`](backend/app/services/interview.py#L230) only checks that the session is answerable, while [`give_hint`](backend/app/services/interview.py#L427) does not check session state at all.

**Impact:** a caller can answer future or already-answered questions, add extra turns without a follow-up prompt, request hints before consent or after completion, and mark future concepts as hint-discounted. The server, rather than the UI, must own the turn order.

**Recommendation:** compare the submitted ID to `current_question(interview)`, require `IN_PROGRESS`, reject answered/skipped questions, and lock the session/question row during mutation. Add out-of-order, stale-tab, pre-consent, post-completion, and reviewer tests.

### G-004 — The browser creates a new idempotency key on every resend

**Area:** broken retry behavior / data integrity  
**Evidence:** the answer mutation calls [`newIdempotencyKey()`](frontend/src/app/interview/[sessionId]/InterviewRoom.tsx#L86) inside `mutationFn` at [line 101](frontend/src/app/interview/[sessionId]/InterviewRoom.tsx#L101). The key is not retained in component state/ref for a logical submission.

**Impact:** if the server commits but the response is lost, the UI shows an error and the next click sends a new key. The API can treat the same answer as a new turn, trigger an unintended follow-up, or advance twice. This contradicts the nearby “reused across retries” comment.

**Recommendation:** create a key before the first attempt, retain it until a definitive response or answer edit/new attempt, and reuse it for automatic and manual retries. Disable answer editing while the outcome is ambiguous or provide a clear “check submission status” recovery path.

### G-005 — Database idempotency does not return the original outcome

**Area:** backend reliability  
**Evidence:** [`submit_answer`](backend/app/services/interview.py#L230) checks whether the session is still answerable before looking up the key, and an existing key returns a newly fabricated `build_turn(...)` response with `session_completed=False` at [lines 248–253](backend/app/services/interview.py#L248). The original response lives only in Redis for 24 hours ([`idempotency.py`](backend/app/core/idempotency.py#L26)).

**Impact:** after Redis loss/expiry, a replay of the final answer returns 409; a replay during a later question can return the wrong turn. The database prevents a duplicate row but does not provide the promised original result.

**Recommendation:** persist the idempotent operation's response/transition result transactionally, scope keys to user/session, check replay before current-state validation, and return the stored original response. Test with Redis disabled, after session completion, after advancing to another question, and after TTL expiry.

### G-006 — Submitting while listening can drop the last spoken words

**Area:** voice / scoring correctness  
**Evidence:** form submission calls `speech.stop()` and immediately submits the render's current `speech.text` ([`InterviewRoom.tsx`](frontend/src/app/interview/[sessionId]/InterviewRoom.tsx#L409)). Native recognition explicitly flushes final text asynchronously on `stop()` ([`useSpeechRecognition.ts`](frontend/src/hooks/useSpeechRecognition.ts#L159)); the WASM `stop()` clears the partial text without finalizing it ([`useWasmRecognition.ts`](frontend/src/hooks/useWasmRecognition.ts#L72)).

**Impact:** the end of an answer can be absent from the transcript and therefore from the score. This is a core correctness failure for a product whose transcript is the artifact of record.

**Recommendation:** make `stop/finalize` awaitable and return the final transcript/segments; only submit after the native `onend`/final result or the WASM recognizer's finalization method. Add hook tests with an in-flight partial and browser-level voice tests using a fake recognizer.

### G-007 — Question speech can restart or repeat indefinitely

**Area:** voice UX / accessibility  
**Evidence:** the auto-read effect depends on the whole `voice` object ([`InterviewRoom.tsx`](frontend/src/app/interview/[sessionId]/InterviewRoom.tsx#L159)). [`useSpeechSynthesis`](frontend/src/hooks/useSpeechSynthesis.ts#L64) returns a new object whenever `speaking` changes. The effect cleanup cancels speech and the next effect starts it again.

**Impact:** starting, ending, or manually stopping speech can retrigger the effect, causing repeated/restarted questions and making “Stop reading” unreliable.

**Recommendation:** depend only on stable `speak`/`cancel` callbacks and the prompt/mode flags, or memoize the hook result; distinguish automatic reads from manual replay. Cover start, natural end, stop, mute, follow-up, and React Strict Mode behavior.

### G-008 — Reports poll forever for skipped or quarantined questions

**Area:** report functionality / background jobs  
**Evidence:** [`build_report`](backend/app/services/report.py#L108) increments `pending` whenever there is no complete evaluation at [lines 148–151](backend/app/services/report.py#L148). Skipped answers are deliberately never evaluated ([`grading.py`](backend/app/services/grading.py#L99)), and quarantined evaluations are not considered complete. The page polls while `pending_questions > 0` ([`report page`](frontend/src/app/report/[sessionId]/page.tsx#L53)).

**Impact:** any skipped question, and any malformed grader result, leaves “still being graded” and a four-second refresh loop forever—even when the session has been published.

**Recommendation:** model report states separately (`skipped`, `pending`, `complete`, `quarantined/failed`), exclude skipped questions from pending, show an actionable grading-failed state, and stop polling terminal failures. Add integration/UI tests for both cases.

### G-009 — Retention and deletion disclosures are not implemented

**Area:** privacy / user trust  
**Evidence:** consent states that data is retained up to 24 months and can be deleted at any time ([`InterviewRoom.tsx`](frontend/src/app/interview/[sessionId]/InterviewRoom.tsx#L221), [`sessions.py`](backend/app/api/v1/sessions.py#L276)). There is no session-delete, account-delete, or consent-withdrawal API/UI. [`apply_retention`](backend/app/workers/tasks/retention.py#L26) deletes old resume objects only; it never removes transcripts after `transcript_retention_days`.

**Impact:** the product asks users to agree to capabilities it does not provide and promises automatic transcript deletion that does not occur. Transcripts are sensitive and can remain indefinitely.

**Recommendation:** implement session deletion, full account deletion, consent withdrawal semantics, and scheduled transcript/evaluation deletion; expose status and confirmation in the UI; audit and test every deletion path including object-store failures. Rewrite disclosures to match actual behavior until this ships.

### G-010 — Cross-site cookie mode is CSRF-vulnerable

**Area:** web security  
**Evidence:** the supported split-domain configuration uses `SameSite=None` ([`config.py`](backend/app/core/config.py#L91)). The auth comment claims every mutation is JSON/preflighted ([`auth.py`](backend/app/api/v1/auth.py#L54)), but multiple cookie-authenticated POSTs require no JSON body: refresh, logout, session start/abandon, and upload completion.

**Impact:** a third-party page can submit simple cross-site forms that rotate/logout a session, start or abandon an interview, or trigger upload completion. CORS controls response reading; it does not prevent the request.

**Recommendation:** add a CSRF token or strict `Origin`/`Referer` validation for all cookie-authenticated unsafe methods, require an explicit JSON/content-type contract, and test hostile origins. Reject wildcard CORS origins in production.

### G-011 — Browser auth responses expose refresh tokens to JavaScript

**Area:** authentication security  
**Evidence:** `_issue` sets HttpOnly cookies but also returns both access and raw refresh tokens ([`auth.py`](backend/app/api/v1/auth.py#L89), [`TokenResponse`](backend/app/schemas/auth.py#L38)). [`AuthForm`](frontend/src/app/login/AuthForm.tsx#L32) parses that response into TanStack mutation state despite comments claiming tokens never touch JavaScript.

**Impact:** an XSS can read a 30-day refresh token directly from the response/mutation object. HttpOnly protection is partly defeated for the primary browser flow.

**Recommendation:** provide a cookie-only browser response with no token body, or separate browser and API-client endpoints/grants. Never return the refresh token to the web frontend.

### G-012 — Cookie deletion and refresh rotation are unsafe under production conditions

**Area:** authentication correctness  
**Evidence:** `_clear_cookies` omits the configured cookie domain ([`auth.py`](backend/app/api/v1/auth.py#L84)), so a domain-scoped cookie may survive logout. Refresh selects and later rotates a token without a row lock or atomic compare-and-set ([lines 191–268](backend/app/api/v1/auth.py#L191)).

**Impact:** logout can appear successful while cookies remain; two concurrent refreshes (for example, two tabs) can both mint active descendants from one supposedly single-use token.

**Recommendation:** delete with the exact original domain/path attributes; serialize refresh with `SELECT ... FOR UPDATE` or an atomic state transition; test concurrent refresh, domain cookies, logout, reuse detection, and multiple tabs.

### G-013 — The documented quick start and CI smoke environment cannot boot

**Area:** broken setup  
**Evidence:** [`.env.example`](.env.example#L86) sets `AUTH_COOKIE_SECURE=false` and [line 92](.env.example#L92) sets `AUTH_COOKIE_SAMESITE=none`. The validator correctly rejects that pair ([`config.py`](backend/app/core/config.py#L157)). README tells users to copy the file, and CI does exactly that ([`ci.yml`](.github/workflows/ci.yml#L96)).

**Impact:** a fresh documented setup and the smoke job fail at API import before serving a request.

**Recommendation:** default local/example configuration to `SameSite=lax`; provide a separate production example for `None + Secure`; add a config-import job for every supplied environment example.

### G-014 — Quarantined documents remain usable for planning

**Area:** prompt-injection boundary / functionality  
**Evidence:** parsers create profiles and mark versions quarantined ([`documents.py`](backend/app/services/documents.py#L189)). Session creation only checks that rows exist, not that versions are `READY` ([`sessions.py`](backend/app/api/v1/sessions.py#L123)). The JD form discards the returned parse status ([`NewSessionForm.tsx`](frontend/src/app/practice/NewSessionForm.tsx#L70)).

**Impact:** direct API callers—and the JD UI—can plan from quarantined content. The scoring boundary limits the blast radius, but the stated “nothing from it will be used” behavior is false and topic selection can still be manipulated.

**Recommendation:** enforce `READY` server-side for every referenced version, reject failed/quarantined versions with distinct actionable errors, and surface a review/retry workflow.

### G-015 — Split-domain deployment breaks server-rendered reports

**Area:** deployment architecture / authentication  
**Evidence:** the app explicitly supports frontend and API on different registrable domains ([`config.py`](backend/app/core/config.py#L91)). The report is rendered by the frontend server and forwards cookies received on the frontend request ([`report page`](frontend/src/app/report/[sessionId]/page.tsx#L18)). Cookies set for an unrelated API domain are not sent to the frontend domain.

**Impact:** browser-side API calls can work with `SameSite=None`, while `/report/{id}` consistently renders unauthenticated in the same deployment.

**Recommendation:** require a shared parent domain and correctly scoped cookie, proxy API auth through the frontend/BFF, or make the report a client-authenticated fetch. Add an end-to-end test using genuinely different sites, not just different localhost ports.

## P1 — fix before beta

| ID | Area | Gap and impact | Recommended improvement |
|---|---|---|---|
| G-016 | Frontend dependencies | `npm ci` fails because [`package-lock.json`](frontend/package-lock.json) is inconsistent. CI and Docker use `npm install` ([`ci.yml`](.github/workflows/ci.yml#L78), [`Dockerfile`](frontend/Dockerfile#L7)), masking drift and making builds non-reproducible. | Regenerate/commit a clean lockfile with the supported Node/npm version; switch CI and Docker to `npm ci`; add a lockfile-only validation job. |
| G-017 | Local resume upload | Compose claims to configure permissive MinIO CORS but [`minio-init`](docker-compose.yml#L99) only creates/private-locks the bucket. The curl smoke path cannot detect browser CORS failures. | Configure and test the exact allowed web origins/methods/headers; add a Playwright upload test. |
| G-018 | Voice data model | Switching between speech and typing is advertised as mid-answer, but submission records one mode and discards all segments/duration when the final mode is text ([`InterviewRoom.tsx`](frontend/src/app/interview/[sessionId]/InterviewRoom.tsx#L86)). | Represent mixed input or preserve speech provenance regardless of the final editor mode; test both switch directions. |
| G-019 | Voice device check | “Check my microphone” only obtains permission ([`InterviewRoom.tsx`](frontend/src/app/interview/[sessionId]/InterviewRoom.tsx#L131)); it does not load/test the selected WASM model, recognition, audio worklet, locale, or TTS. | Run a short record/transcribe/playback test before consent/start and show which engine/locale will be used. |
| G-020 | WASM voice | WASM is reported `supported: true` unconditionally and stopping clears partial text without finalization ([`useWasmRecognition.ts`](frontend/src/hooks/useWasmRecognition.ts#L72)). | Feature-detect secure context, media devices, AudioWorklet, and model availability; finalize pending audio; fall back explicitly. |
| G-021 | Speech locale | Native speech defaults to `en-GB`, the offline model is `en-US`, and there is no locale selector despite parameterized hooks. | Add language/locale choice, persist it per user/session, disclose model limits, and test representative accents/locales. |
| G-022 | Auth state UX | Password login/register only `router.push`es ([`AuthForm.tsx`](frontend/src/app/login/AuthForm.tsx#L32)); it does not invalidate `['me']`, so the persistent nav can continue showing “Sign in.” | Set/invalidate the identity query on success and add login/logout navigation tests. |
| G-023 | Interview errors | Consent/start/hint mutations have no rendered error, and a failed turn query falls through to “Loading the next question…” forever ([`InterviewRoom.tsx`](frontend/src/app/interview/[sessionId]/InterviewRoom.tsx#L65)). | Render operation-specific errors with retry/recovery; distinguish loading, unauthorized, stale state, offline, abandoned, and terminal states. |
| G-024 | JD intake | The parser polling loop has no “not ready after all attempts” branch and discards `thin`, `status`, and quarantine fields ([`NewSessionForm.tsx`](frontend/src/app/practice/NewSessionForm.tsx#L61)). | Use a typed status poll with timeout/cancellation; show thin-JD enrichment guidance; stop on failed/quarantined; let users edit before planning. |
| G-025 | Dashboard errors | Non-auth errors from progress/history are silently treated as empty arrays ([`Dashboard.tsx`](frontend/src/app/dashboard/Dashboard.tsx#L47)). | Show partial-failure states, retry buttons, and retain successfully loaded sections. |
| G-026 | Stub scoring disclosure | Missing `GEMINI_API_KEY` silently switches to a lexical stub in settings/logs ([`config.py`](backend/app/core/config.py#L157)), but the candidate report presents its scores as normal. | Put a prominent “demo/stub grading” badge on setup, interview, and report; include grader/model provenance; consider disabling claims/recommendations in stub mode. |
| G-027 | Evidence integrity | Non-missing evidence is required to be non-empty, but it is never checked against the submitted transcript ([`schemas.py`](backend/app/llm/schemas.py#L18)). | Normalize and verify every quote is a real transcript substring (or a bounded fuzzy match); quarantine hallucinated evidence and test it. |
| G-028 | Document parsing reliability | Resume parsing catches every exception—including transient storage failures—and commits `FAILED`, so Celery never retries ([`documents.py`](backend/app/services/documents.py#L199)). Quarantined/failed redelivery can also insert a duplicate profile because only `READY` is idempotent. | Distinguish permanent parse errors from retryable upstream errors; make every terminal status idempotent; upsert/replace profile data safely; test redelivery. |
| G-029 | Background publication | In broker mode the outbox marks `session.completed` published once Celery accepts it, but `publish_session_task` has only five retries ([`grading task`](backend/app/workers/tasks/grading.py#L45)). A long grading outage can leave a completed session unpublished after grading later succeeds. | Trigger publication after each terminal grade, persist a publish ledger, or keep retrying from an observable reconciliation job. |
| G-030 | Worker isolation | Compose calls separate queue names “bulkheads” but one two-slot worker consumes all queues ([`docker-compose.yml`](docker-compose.yml#L168)). Slow parsing/media can occupy all slots and starve grading. | Run separate worker pools or enforce per-queue concurrency/priority; add backlog/latency metrics. |
| G-031 | Readiness | Readiness reports `dispatch: worker` from a config flag, not actual worker/beat health ([`health.py`](backend/app/api/v1/health.py#L29)). A missing worker, broken broker, or growing outbox still reports ready. | Report outbox age/depth, broker reachability, and worker heartbeat separately; alert on stale/failed events. |
| G-032 | LLM request path | Session creation holds a DB transaction/connection while an external reduction call can take 90 seconds with two retries ([`sessions.py`](backend/app/api/v1/sessions.py#L182), [`config.py`](backend/app/core/config.py#L130)). | Move reduction/planning to an async job or split it into short transactions; add an explicit planning status and cancellation/retry UX. |
| G-033 | Cost accounting | Reduction usage is returned by the LLM adapter but never persisted ([`reduction.py`](backend/app/services/reduction.py#L98)); the spend cap and report therefore omit one paid call per session. Zero-cost/stub calls also leave no positive “measured” ledger row. | Record reduction input/output tokens against the user/session; distinguish measured-zero from unknown; test report totals and caps. |
| G-034 | Org scoping | Session history and progress filter by `user_id` only ([`sessions.py`](backend/app/api/v1/sessions.py#L223), [`report.py`](backend/app/services/report.py#L267)); resume lookup also omits organization ([`documents.py`](backend/app/api/v1/documents.py#L58)). | Scope every query by active organization as well as user; add multi-membership isolation tests before org features are exposed. |
| G-035 | Official mode | Any member can submit `purpose='official'` and `accommodation=true` through [`CreateSessionRequest`](backend/app/schemas/interview.py#L20), with no posting/invite or verified-email gate. | Separate practice creation from official invite acceptance; derive protected fields from the posting/invite, never candidate input. |
| G-036 | Rate limiting | A 429 error class exists, but no routes are rate-limited. Login, registration, OAuth, document creation, and paid session creation can be spammed. | Add user/IP-aware limits with proxy-safe client IP handling; protect auth and cost-incurring endpoints first; return `Retry-After`. |
| G-037 | Production config | Production only rejects secrets starting with `dev-only`; the example's `change-me-in-any-real-environment` passes ([`.env.example`](.env.example#L83), [`config.py`](backend/app/core/config.py#L163)). Wildcard CORS is also not rejected. | Require a high-entropy secret, validate trusted origins/URLs, and fail closed on insecure production combinations. |
| G-038 | Upload safety | A 10 MB compressed PDF/DOCX can expand or consume unbounded CPU/memory in the parser; there are no page/expanded-size/time limits or malware checks. | Add decompression-bomb/page/text limits, worker resource/time limits, MIME/magic validation, and malware scanning if files may ever be served to reviewers. |
| G-039 | Async API blocking | Boto3 calls (`presign`, `head`, deletes) are synchronous inside async endpoints ([`documents.py`](backend/app/api/v1/documents.py#L45)). Resume deletion can perform multiple network calls before the DB transaction commits. | Move storage IO to a threadpool/async client; use an outbox-backed deletion workflow and expose pending/failed deletion status. |
| G-040 | Accessibility semantics | Multiple pages nest `<button>` inside `<a>/<Link>` ([home](frontend/src/app/page.tsx#L49), [dashboard](frontend/src/app/dashboard/Dashboard.tsx#L181), [Google button](frontend/src/app/login/GoogleButton.tsx#L43), [404](frontend/src/app/not-found.tsx#L12)). Tabs lack complete tab/tabpanel keyboard semantics. | Style links as buttons; use native buttons for mode toggles or implement the full ARIA tabs pattern with roving focus and panels. |
| G-041 | Accessibility contrast | Dark-mode primary buttons use white text on `#6ea8fe` ([`globals.css`](frontend/src/app/globals.css#L6)), roughly 2.4:1 contrast and below WCAG AA for normal text. | Use a darker accent for filled controls or dark text on the current accent; run automated and manual contrast/focus checks. |
| G-042 | Accessibility/data visualization | Dashboard trend bars rely on `title` for date/score and have no chart semantics; raw competency slugs are shown as user labels ([`Dashboard.tsx`](frontend/src/app/dashboard/Dashboard.tsx#L106)). | Provide an accessible table/summary, visible dates, human competency names, and screen-reader labels. |
| G-043 | Frontend security headers | Next responses set only nosniff/referrer/frame headers ([`next.config.ts`](frontend/next.config.ts#L9)); there is no CSP, Permissions-Policy, or production HSTS on the user-facing origin. | Add a tested CSP (accounting for Next and current inline styles), restrict microphone/camera, and set HSTS at the edge/frontend origin. |
| G-044 | Proxy trust | Uvicorn trusts forwarded headers from every source with `forwarded_allow_ips='*'` ([`entrypoints/api.py`](backend/app/entrypoints/api.py#L15)). | Restrict trusted proxy networks and prevent direct public access around the edge proxy. |

## P2 — engineering and maintainability improvements

| ID | Area | Gap | Recommended improvement |
|---|---|---|---|
| G-045 | API contract | [`frontend/src/lib/types.ts`](frontend/src/lib/types.ts#L1) is hand-written; the advertised generated `api-types.ts` does not exist. Several API routes use bare `dict` instead of response schemas. | Generate OpenAPI types in CI, commit or build them deterministically, use explicit response models, and fail on contract drift. |
| G-046 | Frontend testing | There are no component, hook, integration, Playwright, or automated accessibility tests. This is why auth-cache, TTS-effect, voice-finalization, report-polling, and CORS behaviors are uncovered. | Add Vitest/React Testing Library for hooks/components and Playwright for login, JD/resume, interview, retry, skip, report, mobile, and axe checks. |
| G-047 | Worker/privacy testing | Coverage is 0% for worker grading/parsing/retention task modules and 37–48% for document endpoints/storage. | Add real S3/MinIO, redelivery, transient outage, retention, purge, quarantine, and object/DB partial-failure tests. |
| G-048 | Type safety | Mypy has 23 errors and is non-blocking ([`ci.yml`](.github/workflows/ci.yml#L60)). Some errors are on important interview/report paths. | Fix the baseline and make mypy blocking; use narrowly justified ignores only. |
| G-049 | Backend reproducibility | [`requirements.txt`](backend/requirements.txt#L1) claims `requirements.lock.txt` is the reproducible artifact, but that file and the referenced lock script are absent; the runtime image installs dev requirements. | Add a hash-pinned lock, separate runtime/dev dependency stages, and verify it in CI. |
| G-050 | CI effectiveness | Push CI only targets `main` while the current branch is `master`; coverage has no minimum; Trivy uses unpinned `@master`, exits 0, and is `continue-on-error` ([`ci.yml`](.github/workflows/ci.yml#L3)). | Align the default branch, add a coverage floor, pin actions by version/SHA, and enforce an agreed vulnerability baseline. |
| G-051 | Smoke coverage | Smoke never starts the frontend and uses curl rather than a browser ([`ci.yml`](.github/workflows/ci.yml#L90)). It cannot catch hydration, cookies across sites, MinIO CORS, accessibility, or voice behavior. | Keep the API smoke test, then add a separate real-browser end-to-end job. |
| G-052 | System-design test fixture | Production seed includes system-design questions, but the main test fixture/governance aggregate largely seeds only database/backend banks ([`conftest.py`](backend/tests/conftest.py#L39)). | Seed `app.content.seed.ALL_QUESTIONS` in integration tests and run each authored domain through planning/grading. |
| G-053 | Auditability | `AuditLog` is written only for refresh-token reuse; session transitions, report views, corrections, deletions, and administrative actions are not recorded despite model/comments claiming an audit trail. | Centralize audit event creation for sensitive reads/writes and add tamper/coverage tests plus retention policy. |
| G-054 | Model download | [`fetch-model.mjs`](frontend/scripts/fetch-model.mjs#L24) trusts any non-empty existing file, has no checksum, writes directly to the final path, and treats download failure as a successful build. | Pin a checksum/version, stream to a temp file, verify, atomically rename, and expose a build/runtime capability flag when unavailable. |
| G-055 | Docker images | There is no `.dockerignore`; backend runtime includes tests/dev tools/runtime artifacts; frontend runtime copies all development dependencies. Compose exposes Postgres, Redis, and MinIO on all host interfaces with default credentials. | Add `.dockerignore`, slim production stages/standalone Next output, bind dev infra to `127.0.0.1`, and provide production-only manifests/secrets. |
| G-056 | Runtime artifacts | `backend/celerybeat-schedule` is present and not ignored. | Ignore or relocate Celery beat state to an explicit writable runtime volume/path. |
| G-057 | Frontend deployment config | `NEXT_PUBLIC_API_BASE_URL` is baked during `next build`; changing only the runtime environment of the production image will not update client bundles ([`next.config.ts`](frontend/next.config.ts#L3)). | Supply a documented build arg, use same-origin proxying, or load runtime config safely. |
| G-058 | Error semantics | The report page catches API 401/403/404 and renders a normal page instead of redirecting/not-found/propagating an appropriate HTTP status ([`report page`](frontend/src/app/report/[sessionId]/page.tsx#L26)). Generic app error copy also claims logging and answer safety without evidence. | Preserve HTTP semantics and make recovery copy conditional on what is actually known. |
| G-059 | Dashboard/report UX | Reports have no next action (retry topic, start focused practice, return to history), no model/rubric provenance, and use hiring-style recommendation language for practice. | Add actionable practice loops, plain-language competency names, provenance/version details, and calibrated score explanations. |
| G-060 | Auth UX | There is no password reset, password setup for OAuth-only users, email verification flow, show-password control, session/device management, or return-to-original-page handling after login. | Add account recovery and `next` redirects before broader rollout; expose active sessions and revoke-all behavior. |
| G-061 | Document UX | Resume profile review/correction APIs exist but have no UI; users cannot reuse/list/delete prior resumes or JDs; combined mode and JD file upload are absent from the form. | Build a document library and review step, then expose combined mode with clear provenance and thin/quarantine handling. |
| G-062 | Session UX | There is no abandon/delete control, confirmation, or recovery guidance; abandoned direct URLs and some stale statuses fall into indefinite loading. | Add explicit pause/abandon/delete actions and exhaustive UI rendering for every state-machine status. |
| G-063 | Content/API mismatch | The API enum accepts fresher/junior, but the bank has 0 rubrics at those levels; only mid/senior are usable. | Reject unsupported level/domain combinations from a capability endpoint or author the missing rubrics before advertising them. |
| G-064 | Documentation drift | README says 260 tests and 52 rubrics/277 concepts/104 goldens; current results are 306 tests and 64/332/128. It also gives conflicting smoke assertion counts. | Generate inventory/test counts where possible and keep one verified quick-start path. |
| G-065 | Grader recovery | Malformed schema-valid/invalid grader output is quarantined after one attempt even though module documentation says it is retried before quarantine ([`grading.py`](backend/app/services/grading.py#L145)). There is no operator UI/regrade action. | Retry bounded validation failures with a repair-free fresh call, then expose quarantine/regrade operations and alerts. |
| G-066 | Observability | There are structured logs but no metrics/SLOs for planning latency, grading latency, outbox age, failed events, quarantine rate, upload failures, refresh reuse, or cost anomalies. | Add a small metrics surface and alerts tied to user-visible failure modes; avoid a large observability stack at this scale. |
| G-067 | Data integrity | Many state/enum/numeric fields are unconstrained strings/floats in the database; application validation can be bypassed by workers/scripts/migrations. | Add targeted check constraints for statuses, modes, scores, confidence, durations, counts, and retention ranges. |
| G-068 | Cost message | The spend-cap error says text-only mode remains available, but the cap blocks creation of every session and text answers still incur grading cost ([`spend.py`](backend/app/services/spend.py#L35)). | Change the message and provide an actually free/stub/local option if that is intended. |

## P3 — intentionally unbuilt or roadmap scope

These are acknowledged in the README/requirements, but should remain visible as product gaps so the UI and marketing do not imply they already exist:

- Webcam/video/audio recording, resumable multipart media upload, playback, and transcript/media synchronization.
- Official interview invitations, posting templates, organization/member management, verified-email gate, candidate visibility policy workflow, and reviewer decision workspace.
- Human ratings, advance/hold/reject decisions, reviewer audit history, and model-versus-human comparison.
- Candidate email verification delivery and recovery flows.
- Full taxonomy coverage beyond the currently authored mid/senior database, backend, and system-design domains.
- JD file upload and a complete combined resume × JD workflow in the UI.
- Candidate-facing export/download and a self-service privacy/account center.

## What is working well

- The resume/JD-to-selector trust boundary and frozen rubric design are strong and well tested; keeping grading payload construction whitelist-only is the right architecture.
- Backend state transitions, concept scoring, score invariance, sanitization, problem+json errors, and bank governance have meaningful unit/integration coverage.
- Refresh tokens are hashed at rest and reuse detection is intentionally persisted even when the response is 401.
- The transaction-per-request seam and transactional outbox address real failure modes, and workerless mode is documented rather than hidden.
- The UI has useful accessibility foundations: skip link, visible focus, labels, live regions, keyboard-operable controls, and non-color verdict labels.
- The repository contains unusually useful ADRs and explanatory comments. The next step is to convert the most important comments into enforced invariants and tests.

## Recommended implementation order

1. Fix G-001 through G-005 and add authorization/current-turn/idempotency tests.
2. Fix voice finalization and speech-effect behavior (G-006/G-007) with hook and browser tests.
3. Correct report terminal states and privacy/deletion/retention behavior (G-008/G-009).
4. Harden cookie auth and cross-site deployment (G-010 through G-012 and G-015).
5. Repair `.env.example`, lockfiles, CI install behavior, and MinIO CORS (G-013/G-016/G-017).
6. Address P1 UX/reliability items, especially visible errors, quarantine handling, stub disclosure, publication reconciliation, and frontend accessibility.
7. Make type checks/contracts/tests blocking, then proceed with the P3 product surfaces.
