"""Authored question bank -- domain: backend-engineering.

Same authoring bar as the databases bank. Read a few ``acceptable_signals``
and the grading philosophy should be obvious from the data alone: the phrases
that earn credit are the ones a person says when they understand the
mechanism, not the ones they say when they have memorised the name for it.
"""

from __future__ import annotations

from app.content.types import GoldenSpec, QuestionSpec, bonus, core, sup
from app.domain.enums import QuestionArchetype, Seniority

MID, SENIOR = Seniority.MID, Seniority.SENIOR


QUESTIONS: tuple[QuestionSpec, ...] = (
    # ══════════════════════════════════════════════════════════════════════
    # idempotency-keys
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="idempotency-keys",
        seniority=MID,
        neutral_wording=(
            "A user's payment request times out on their phone and the app retries it. How do you "
            "make sure they're only charged once?"
        ),
        reframe_wording=(
            "Another way in: the client can't tell whether the first request worked. It's going to "
            "send it again. What do you build so that's safe?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "client-cannot-know-outcome",
                "A timeout tells the client nothing about whether the server did the work, so "
                "retrying is correct behaviour and the server has to absorb it",
                "Framing the retry as correct is what moves the fix to the right side.",
                (
                    "the client has no idea if it went through",
                    "the timeout doesn't mean it failed",
                    "retrying is the right thing for the client to do",
                    "the server has to handle being asked twice",
                ),
                "Think about what the phone actually knows when the connection drops.",
                ("the client should just not retry",),
            ),
            core(
                "client-supplied-key-identifies-attempt",
                "The client generates a key that identifies the *attempt*, and sends the same key "
                "on every retry, so the server can recognise the repeat",
                "The key has to come from the client, or retries look like new requests.",
                (
                    "the client makes up an id for the attempt",
                    "it sends the same id when it retries",
                    "the server uses it to spot the duplicate",
                    "same key means same request, not a new one",
                ),
                "Think about what would let the server tell 'again' apart from 'another'.",
                ("the server can generate the key itself",),
            ),
            core(
                "return-the-original-result",
                "On a repeat, the server returns the original outcome rather than doing the work "
                "again or returning an error",
                "Half the value is not double-charging; the other half is the client getting an "
                "answer it can use.",
                (
                    "give back the same response as the first time",
                    "don't do the work twice",
                    "the retry should look successful to the client",
                    "store the result against the key",
                ),
                "Think about what the phone should see the second time, so the user isn't stuck.",
            ),
            sup(
                "storage-needs-a-ttl",
                "Keys are stored with an expiry, because keeping them forever is unbounded growth",
                "Any 'remember this' design needs a forgetting story.",
                ("expire them after a day or so",),
            ),
            sup(
                "constraint-as-backstop",
                "A unique constraint on the key makes the guarantee hold even if the cache is "
                "unavailable",
                "The cache is an optimisation; the database is the guarantee.",
                ("put a unique constraint on it too", "the cache can be flushed, the database can't lie"),
            ),
            bonus(
                "concurrent-retry-window",
                "Two retries can arrive at once, so the claim itself has to be atomic",
                "Recognises the race inside the fix for the race.",
                ("both retries could arrive at the same moment",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "The client has no idea if it went through -- the timeout doesn't mean it failed -- "
                "so retrying is the right thing for the client to do and the server has to handle "
                "being asked twice. The way I'd do it is the client makes up an id for the attempt "
                "and sends the same id when it retries, so the server uses it to spot the "
                "duplicate. On the repeat you give back the same response as the first time rather "
                "than doing the work twice, so the retry looks successful to the client. I'd store "
                "the result against the key and expire them after a day or so, and put a unique "
                "constraint on it too, because the cache can be flushed and the database can't lie. "
                "Both retries could arrive at the same moment, so claiming the key has to be atomic.",
                {
                    "client-cannot-know-outcome": "covered",
                    "client-supplied-key-identifies-attempt": "covered",
                    "return-the-original-result": "covered",
                    "storage-needs-a-ttl": "covered",
                    "constraint-as-backstop": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd have the server generate a request id and check whether a payment already "
                "exists for that user in the last few seconds. If it does, return an error so the "
                "client knows not to retry.",
                {
                    "client-cannot-know-outcome": "partial",
                    "client-supplied-key-identifies-attempt": "contradicted",
                    "return-the-original-result": "contradicted",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="idempotency-keys",
        seniority=SENIOR,
        neutral_wording=(
            "You're adding idempotency to an existing write endpoint that's already in production "
            "and already gets retried. How do you roll it out, and what edge cases would you make "
            "sure are handled?"
        ),
        reframe_wording=(
            "Put it differently: the mechanism is understood. What makes it hard to add to "
            "something that's already live and already being double-called?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.EDGE,
        concepts=(
            core(
                "same-key-different-body",
                "A client can reuse a key with different content, and the server has to reject "
                "that rather than silently returning the wrong old result",
                "This is the edge case that turns idempotency into a data-corruption bug.",
                (
                    "what if they send the same key with a different amount",
                    "you have to compare the request, not just the key",
                    "reject it rather than returning the old answer",
                    "hash the body and check it matches",
                ),
                "Think about a client that reuses a key by mistake for a genuinely different "
                "request.",
                ("the key alone is enough to identify the request",),
            ),
            core(
                "in-flight-vs-completed",
                "There are two distinct states -- still running and already finished -- and a "
                "retry arriving mid-flight needs a defined answer",
                "Most naive implementations only model 'done', and then deadlock or duplicate.",
                (
                    "the first one might still be running",
                    "you need to distinguish in-progress from finished",
                    "tell the client to retry shortly rather than starting it again",
                    "claim the key before you start the work, not after",
                ),
                "Think about a retry arriving one millisecond after the original, before it "
                "finished.",
                ("if the key exists you can always return the stored response",),
            ),
            core(
                "incremental-rollout",
                "You accept the header optionally first, observe real traffic, and only then "
                "require it -- because existing clients don't send it yet",
                "Requiring it on day one breaks every client that hasn't shipped.",
                (
                    "make it optional at first",
                    "existing clients don't send it yet",
                    "log how many requests have it before enforcing",
                    "then require it once the clients have updated",
                ),
                "Think about what happens to the app version already on people's phones.",
            ),
            sup(
                "scope-the-key",
                "Keys are scoped per user or per endpoint, so one client can't collide with or "
                "probe another's",
                "A global key namespace is both a bug and a leak.",
                ("scope it to the user so keys can't collide across accounts",),
            ),
            sup(
                "failed-requests-are-retryable",
                "A genuine failure should release the key so the client can legitimately try again",
                "Otherwise the first failure permanently blocks the operation.",
                ("if it actually failed, let them retry with the same key",),
            ),
            bonus(
                "observability",
                "You measure how often duplicates are caught, which tells you whether it's working",
                "The counter is how you know the feature is earning its keep.",
                ("count how many duplicates you catch",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "The rollout part is that existing clients don't send it yet, so I'd make it "
                "optional at first, log how many requests have it, then require it once the clients "
                "have updated. The edge cases that matter: what if they send the same key with a "
                "different amount -- you have to compare the request, not just the key, so hash the "
                "body and reject it rather than returning the old answer. And the first one might "
                "still be running, so you need to distinguish in-progress from finished; claim the "
                "key before you start the work, not after, and tell the client to retry shortly "
                "rather than starting it again. I'd scope it to the user so keys can't collide "
                "across accounts, and if it actually failed, let them retry with the same key. "
                "Then count how many duplicates you catch so you know it's doing something.",
                {
                    "same-key-different-body": "covered",
                    "in-flight-vs-completed": "covered",
                    "incremental-rollout": "covered",
                    "scope-the-key": "covered",
                    "failed-requests-are-retryable": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd make the header required and store each key in a table. If the key exists, "
                "return the stored response. The key uniquely identifies the request so that's all "
                "you need to check.",
                {
                    "same-key-different-body": "contradicted",
                    "in-flight-vs-completed": "missing",
                    "incremental-rollout": "contradicted",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # cache-invalidation-and-stampede
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="cache-invalidation-and-stampede",
        seniority=MID,
        neutral_wording=(
            "A cached response expires and immediately your database load spikes hard for a few "
            "seconds. Why, and what would you do about it?"
        ),
        reframe_wording=(
            "Same thing put differently: everything was fine, one cache entry expired, and the "
            "database fell over. What happened in that instant?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "simultaneous-misses-hit-the-origin",
                "The moment the entry expires, every concurrent request misses at once and they "
                "all go to the database to recompute the same thing",
                "This is the mechanism; without it 'add caching' is the fix people reach for.",
                (
                    "they all miss at the same time",
                    "every request goes to the database at once",
                    "a thousand requests all recompute the same value",
                    "the cache was absorbing all of that a second ago",
                ),
                "Think about how many requests are in flight in the instant the entry disappears.",
                ("the cache expiring shouldn't cause extra load",),
            ),
            core(
                "one-recompute-others-wait",
                "The fix is to let exactly one request recompute while the rest wait for it or "
                "serve the stale value",
                "Collapsing the herd to one is the whole idea.",
                (
                    "let one of them do the work and the others wait",
                    "take a lock so only one recomputes",
                    "serve the old value while it refreshes",
                    "collapse them into a single fetch",
                ),
                "Think about what you'd want the other 999 requests to do while one of them works.",
                ("a longer TTL removes the stampede",),
            ),
            sup(
                "jitter-the-ttl",
                "Randomising expiry spreads the misses instead of synchronising them",
                "Identical TTLs are how many keys expire in the same second.",
                ("add some randomness to the expiry", "otherwise everything expires together"),
            ),
            sup(
                "cache-anonymous-responses-only",
                "Only responses that don't vary per user belong in a shared cache",
                "Per-user data in a shared key is a data leak, not a performance bug.",
                ("don't cache per-user responses in a shared cache", "you'd serve one user's data to another"),
            ),
            bonus(
                "invalidate-explicitly",
                "Expiry is a fallback; the write path should invalidate what it changed",
                "Time-based expiry alone means stale data for the whole TTL.",
                ("when the data changes, clear the key",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "They all miss at the same time -- a thousand requests all recompute the same value "
                "and every one of them goes to the database, which the cache was absorbing a second "
                "ago. The fix is to let one of them do the work and the others wait, so take a lock "
                "so only one recomputes, or serve the old value while it refreshes. I'd also add "
                "some randomness to the expiry, otherwise everything expires together. Separately, "
                "I'd check we're not caching per-user responses in a shared cache, because you'd "
                "serve one user's data to another. And when the data changes I'd clear the key "
                "rather than waiting for it to expire.",
                {
                    "simultaneous-misses-hit-the-origin": "covered",
                    "one-recompute-others-wait": "covered",
                    "jitter-the-ttl": "covered",
                    "cache-anonymous-responses-only": "covered",
                    "invalidate-explicitly": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "The TTL is probably too short. I'd increase it so the cache expires less often, "
                "and maybe cache more endpoints so there's less database traffic overall.",
                {
                    "simultaneous-misses-hit-the-origin": "missing",
                    "one-recompute-others-wait": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="cache-invalidation-and-stampede",
        seniority=SENIOR,
        neutral_wording=(
            "You're designing caching for an expensive resource that's shared across users but "
            "changes occasionally. How would you decide what to cache, where, and how you'd know "
            "it's working?"
        ),
        reframe_wording=(
            "Another angle: you have a budget of one caching layer. Where do you spend it, and "
            "what evidence tells you it paid off?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.DECISION,
        concepts=(
            core(
                "correctness-before-speed",
                "The first question is what may safely be stale and for how long, because caching "
                "trades freshness for speed and only the domain can price that",
                "Starting from the invalidation question is what separates design from reflex.",
                (
                    "first work out what's allowed to be out of date",
                    "how stale can this be before it's wrong",
                    "some things you can't cache at all",
                    "the business decides the tolerance, not me",
                ),
                "Start from what the user would notice if the answer were a minute old.",
                ("cache everything and invalidate aggressively",),
            ),
            core(
                "layer-choice-has-consequences",
                "Where it lives -- client, shared server-side, or origin -- changes who can see it "
                "and how you invalidate it",
                "A shared cache and a private one have completely different blast radii.",
                (
                    "a browser cache you can't clear once it's out there",
                    "a shared cache is one place you can invalidate",
                    "anything per-user must not go in a shared layer",
                    "mark it private if the body varies by who's asking",
                ),
                "Think about who else could receive a copy of what you stored, and who can delete it.",
                ("a private cache header is enough to stop shared caching",),
            ),
            core(
                "measure-hit-rate-and-tail",
                "You judge it on hit rate and tail latency, and on origin load actually dropping "
                "-- not on the cache existing",
                "Caches that never hit are pure cost plus a staleness risk.",
                (
                    "look at the hit rate",
                    "check the database load actually went down",
                    "watch p95, not the average",
                    "a cache that never hits is just risk",
                ),
                "Think about what number would prove the cache is doing anything at all.",
            ),
            sup(
                "revalidation-over-blind-ttl",
                "Conditional requests let clients revalidate cheaply instead of refetching whole "
                "bodies",
                "Revalidation gets most of the win without the staleness.",
                ("use an etag so they can ask 'has this changed'", "304 instead of the whole body"),
            ),
            sup(
                "single-flight-on-miss",
                "One recompute per key on a miss, with the rest waiting or served stale",
                "The stampede protection is part of the design, not a later patch.",
                ("only one request recomputes it",),
            ),
            bonus(
                "precomputed-read-model",
                "Some expensive reads are better served by a maintained projection than by caching "
                "the computation",
                "Recognises when caching is papering over the wrong data model.",
                ("sometimes you precompute it into a table instead",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "I'd start by working out what's allowed to be out of date -- how stale can this be "
                "before it's wrong -- because the business decides the tolerance, not me, and some "
                "things you can't cache at all. Then where: a shared cache is one place you can "
                "invalidate, whereas a browser cache you can't clear once it's out there, and "
                "anything per-user must not go in a shared layer, so I'd mark it private if the "
                "body varies by who's asking. I'd use an etag so clients can ask 'has this changed' "
                "and get a 304 instead of the whole body. On a miss, only one request recomputes it. "
                "To know it's working I'd look at the hit rate, check the database load actually "
                "went down, and watch p95 rather than the average -- a cache that never hits is "
                "just risk. If the computation is really expensive, sometimes you precompute it "
                "into a table instead.",
                {
                    "correctness-before-speed": "covered",
                    "layer-choice-has-consequences": "covered",
                    "measure-hit-rate-and-tail": "covered",
                    "revalidation-over-blind-ttl": "covered",
                    "single-flight-on-miss": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd put a cache in front of everything with a five minute TTL and invalidate "
                "aggressively whenever anything changes. Caching everything is the safest default "
                "because it always reduces load.",
                {
                    "correctness-before-speed": "contradicted",
                    "layer-choice-has-consequences": "missing",
                    "measure-hit-rate-and-tail": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # error-contract-design
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="error-contract-design",
        seniority=MID,
        neutral_wording=(
            "You're designing how your API reports errors to clients. What does a good error "
            "response contain, and what would you avoid?"
        ),
        reframe_wording=(
            "Put it another way: a client just got a failure from your API. What do they need in "
            "order to do something sensible about it?"
        ),
        expected_minutes=4,
        concepts=(
            core(
                "machine-readable-and-human-readable",
                "An error needs something the client can branch on programmatically *and* "
                "something a person can read -- a prose message alone forces string matching",
                "String-matching error messages is how a copy edit becomes a production incident.",
                (
                    "a stable code the client can switch on",
                    "and a message for a human",
                    "otherwise they end up matching on the text",
                    "if you reword the message their code breaks",
                ),
                "Think about how the client's code decides what to do next.",
                ("a clear message is enough on its own",),
            ),
            core(
                "one-shape-everywhere",
                "Every endpoint returns errors in the same shape, so clients write the handling "
                "once instead of per endpoint",
                "Consistency is the feature; a second error dialect doubles client work.",
                (
                    "the same shape for every error",
                    "one format across the whole API",
                    "so the client parses it once",
                    "validation errors and auth errors look the same on the outside",
                ),
                "Think about what a client has to write if each endpoint invents its own format.",
                ("consistency is a nice-to-have once the messages are clear",),
            ),
            sup(
                "status-code-carries-class",
                "The status code should already tell you the class of problem -- client mistake, "
                "auth, conflict, or server fault",
                "The status is the first branch; the body refines it.",
                ("the status code says whether it's my fault or theirs",),
            ),
            sup(
                "no-internals-in-the-body",
                "Stack traces, SQL, and internal identifiers don't belong in a client-facing error",
                "Error bodies are an information-disclosure surface.",
                ("don't leak stack traces", "no SQL in the response"),
            ),
            bonus(
                "correlation-id-in-the-body",
                "Including the request id lets a user paste it into a support ticket and lets you "
                "find the exact log line",
                "Turns 'it broke' into a one-command investigation.",
                ("include the request id so you can find it in the logs",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "It needs a stable code the client can switch on and a message for a human -- if "
                "there's only a message they end up matching on the text, and if you reword it "
                "their code breaks. And it should be the same shape for every error, one format "
                "across the whole API, so the client parses it once and validation errors and auth "
                "errors look the same on the outside. The status code says whether it's my fault "
                "or theirs, so that's the first thing they branch on. I'd avoid leaking stack "
                "traces or SQL in the response. I'd include the request id so you can find it in "
                "the logs when someone reports it.",
                {
                    "machine-readable-and-human-readable": "covered",
                    "one-shape-everywhere": "covered",
                    "status-code-carries-class": "covered",
                    "no-internals-in-the-body": "covered",
                    "correlation-id-in-the-body": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "A clear error message explaining what went wrong is the main thing, so the "
                "developer reading it knows what to fix. I'd return a 400 with a message field.",
                {
                    "machine-readable-and-human-readable": "contradicted",
                    "one-shape-everywhere": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="error-contract-design",
        seniority=SENIOR,
        neutral_wording=(
            "Your API has grown several different error formats over time and clients handle them "
            "inconsistently. How would you consolidate that without breaking anyone?"
        ),
        reframe_wording=(
            "Put differently: three error shapes exist in production and clients depend on all "
            "three. What's the path to one?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.DECISION,
        concepts=(
            core(
                "handlers-not-call-sites",
                "You centralise error translation in one place so every failure -- including ones "
                "raised by the framework -- exits through the same code",
                "Per-endpoint fixes always miss the errors nobody wrote by hand.",
                (
                    "one place that turns exceptions into responses",
                    "register handlers rather than formatting at each call site",
                    "otherwise the framework's own errors still slip through",
                    "the ones you didn't write are the ones that leak",
                ),
                "Think about the errors your own code never raises but your users still see.",
                ("update each endpoint to return the new format",),
            ),
            core(
                "migrate-without-breaking-clients",
                "You add the new shape alongside the old, give clients time, and measure who is "
                "still on the old path before removing it",
                "Consolidation is a client migration, not a refactor.",
                (
                    "serve both for a while",
                    "add the new fields without removing the old ones",
                    "check who's still relying on the old shape",
                    "version it if you have to break it",
                ),
                "Think about the client you can't deploy for.",
                ("clients can be told to update before the change ships",),
            ),
            core(
                "the-handler-itself-can-fail",
                "The error path needs its own tests, because an exception thrown *inside* the error "
                "handler turns every 4xx into a 5xx",
                "This is the specific failure that hides until someone sends a malformed body.",
                (
                    "make sure the handler can serialise whatever it's given",
                    "if the handler throws, you get a 500 instead of a 400",
                    "raw bytes in a validation error can break the encoder",
                    "test it with a deliberately malformed request",
                ),
                "Think about what happens if the thing you're trying to describe can't be turned "
                "into JSON.",
            ),
            sup(
                "contract-tests",
                "Tests assert the shape against the published schema, so drift is caught in CI",
                "A documented contract with no test is documentation.",
                ("test the responses against the schema we publish",),
            ),
            sup(
                "never-a-5xx-for-client-input",
                "Bad input should never produce a server error, and a fuzz pass over the surface "
                "proves it",
                "The 4xx/5xx boundary is a real signal and worth defending.",
                ("fuzz the endpoints and assert you never get a 500",),
            ),
            bonus(
                "problem-details-standard",
                "Adopting an existing standard beats inventing a format, because tooling already "
                "understands it",
                "Reuse over invention where a standard exists.",
                ("use a standard format rather than making one up",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "I'd centralise it: one place that turns exceptions into responses, registered as "
                "handlers rather than formatting at each call site, because otherwise the "
                "framework's own errors still slip through and the ones you didn't write are the "
                "ones that leak. For the migration I'd serve both for a while, add the new fields "
                "without removing the old ones, and check who's still relying on the old shape "
                "before dropping it. The thing I'd be careful about is that the handler itself can "
                "fail -- if the handler throws you get a 500 instead of a 400, and raw bytes in a "
                "validation error can break the encoder, so I'd test it with a deliberately "
                "malformed request. I'd add contract tests against the schema we publish and fuzz "
                "the endpoints to assert we never get a 500 from bad input. And I'd use a standard "
                "format rather than making one up.",
                {
                    "handlers-not-call-sites": "covered",
                    "migrate-without-breaking-clients": "covered",
                    "the-handler-itself-can-fail": "covered",
                    "contract-tests": "covered",
                    "never-a-5xx-for-client-input": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd pick the best of the three formats and update each endpoint to return the new "
                "format, then tell client teams to update. It's a small change per endpoint.",
                {
                    "handlers-not-call-sites": "contradicted",
                    "migrate-without-breaking-clients": "missing",
                    "the-handler-itself-can-fail": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # authorization-models
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="authorization-models",
        seniority=MID,
        neutral_wording=(
            "Your app has admins, reviewers and regular users, and permission checks are spread "
            "through the codebase. How would you structure authorization instead?"
        ),
        reframe_wording=(
            "Same question from another side: someone asks 'who can delete a posting?' and the "
            "only way to answer is to grep. How would you make that answerable?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "check-capability-not-role",
                "Call sites should ask whether the caller *can do the thing*, not what they are "
                "named -- so adding a role doesn't mean editing every endpoint",
                "Role-name comparisons scattered through the code are unauditable and unchangeable.",
                (
                    "ask 'can they do this' not 'are they an admin'",
                    "check the permission, not the role name",
                    "otherwise adding a role means touching every endpoint",
                    "the role maps to a set of things you're allowed to do",
                ),
                "Think about what a new role would force you to change under each approach.",
                ("comparing the role string at each endpoint is fine if it's consistent",),
            ),
            core(
                "one-policy-layer",
                "There's a single place that answers the question, so the rules are auditable and "
                "testable in one file",
                "The value is being able to read the whole policy at once.",
                (
                    "one place that owns the decision",
                    "so you can read all the rules together",
                    "you can test the whole grid in one place",
                    "not scattered through the handlers",
                ),
                "Think about where someone would look to find out who is allowed to do what.",
                ("the rules belong next to the code they protect",),
            ),
            core(
                "ownership-is-separate-from-role",
                "Being allowed to edit *a* thing and being allowed to edit *this* thing are "
                "different checks, and both are required",
                "Skipping the second is the object-level access-control bug in every top-ten list.",
                (
                    "having the permission doesn't mean it's yours",
                    "you also have to check they own this particular record",
                    "otherwise anyone can edit anyone else's by changing the id",
                    "role check plus ownership check, not one or the other",
                ),
                "Think about a user with the right role passing in someone else's record id.",
            ),
            sup(
                "build-the-map-bottom-up",
                "Define the hierarchy once -- a reviewer is a member plus extras -- rather than "
                "listing every permission per role",
                "One expression of the hierarchy means one place to change it.",
                ("an admin is a reviewer plus a few more",),
            ),
            sup(
                "test-with-an-independent-table",
                "The permission matrix is tested against a hand-written expectation, not against "
                "the implementation's own map",
                "A test that imports the map under test proves nothing.",
                ("write out the expected grid by hand", "if you import the same map you're testing nothing"),
            ),
            bonus(
                "deny-by-default",
                "Unknown roles and unlisted actions resolve to denied",
                "Fail-closed is the only safe default for authorization.",
                ("default to no", "unknown means denied"),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "I'd have call sites ask 'can they do this' rather than 'are they an admin', "
                "because the role maps to a set of things you're allowed to do, and otherwise "
                "adding a role means touching every endpoint. All of it lives in one place that "
                "owns the decision, so you can read all the rules together and test the whole grid "
                "in one place. Crucially, having the permission doesn't mean it's yours -- you also "
                "have to check they own this particular record, otherwise anyone can edit anyone "
                "else's by changing the id. I'd build the map bottom-up so an admin is a reviewer "
                "plus a few more, and write out the expected grid by hand in the test, because if "
                "you import the same map you're testing nothing. Unknown means denied.",
                {
                    "check-capability-not-role": "covered",
                    "one-policy-layer": "covered",
                    "ownership-is-separate-from-role": "covered",
                    "build-the-map-bottom-up": "covered",
                    "test-with-an-independent-table": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd add a decorator on each endpoint that checks the user's role string against "
                "the roles allowed for that endpoint. It's consistent as long as everyone uses the "
                "decorator, and it keeps the rules next to the code they apply to.",
                {
                    "check-capability-not-role": "contradicted",
                    "one-policy-layer": "contradicted",
                    "ownership-is-separate-from-role": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="authorization-models",
        seniority=SENIOR,
        neutral_wording=(
            "A multi-tenant product needs to guarantee that no request can ever read another "
            "tenant's data. How would you make that hard to get wrong, and how would you convince "
            "yourself it holds?"
        ),
        reframe_wording=(
            "Put it another way: one missed WHERE clause leaks another customer's data. How do you "
            "design so that a mistake doesn't have that consequence?"
        ),
        expected_minutes=7,
        archetype=QuestionArchetype.EDGE,
        concepts=(
            core(
                "scoping-must-be-hard-to-omit",
                "Tenant scoping should be structurally difficult to forget -- applied by default "
                "rather than remembered at each query",
                "Relying on discipline for a leak-class control fails on the first tired afternoon.",
                (
                    "make it the default rather than something you remember",
                    "apply it in one layer so queries can't skip it",
                    "if it's opt-in someone will forget",
                    "the unsafe version should be the awkward one to write",
                ),
                "Think about the difference between 'we always remember to' and 'you can't not'.",
                ("a code review checklist is sufficient to prevent this",),
            ),
            core(
                "defence-in-depth",
                "More than one layer enforces it -- application scoping plus a database-level "
                "control -- so a single mistake is not a breach",
                "One control means one bug is a breach.",
                (
                    "have more than one thing enforcing it",
                    "row-level security as a backstop",
                    "so one missed filter isn't a leak",
                    "the database enforces it too, not just the app",
                ),
                "Think about what still protects you when the first control is missed.",
            ),
            core(
                "prove-it-negatively",
                "You test the *forbidden* cases explicitly -- another tenant's id must produce a "
                "not-found, and that test runs on every route",
                "Positive tests never catch this class; only negative ones do.",
                (
                    "test that another tenant's id returns not found",
                    "the tests have to try the thing that should fail",
                    "a test that only checks the happy path proves nothing here",
                    "run it across every endpoint, not one",
                ),
                "Think about what a test would have to attempt in order to fail on a leaky version.",
                ("a passing happy-path test implies the forbidden case is blocked",),
            ),
            sup(
                "not-found-over-forbidden",
                "Responding not-found rather than forbidden avoids confirming that a record exists",
                "Forbidden is itself an information leak about existence.",
                ("return 404 rather than 403 so you don't confirm it exists",),
            ),
            sup(
                "audit-every-access",
                "Reads of sensitive records are logged, so a leak is detectable after the fact",
                "Detection matters when prevention fails.",
                ("log who looked at what",),
            ),
            bonus(
                "id-shape",
                "Non-sequential identifiers reduce trivial enumeration, though they are not the "
                "control itself",
                "Correctly ranks obscurity as a nicety, not a defence.",
                ("uuids make guessing harder but that's not the protection",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "I'd make it the default rather than something you remember -- apply it in one "
                "layer so queries can't skip it, because if it's opt-in someone will forget, and "
                "the unsafe version should be the awkward one to write. Then I'd have more than one "
                "thing enforcing it: row-level security as a backstop so the database enforces it "
                "too, not just the app, and one missed filter isn't a leak. To convince myself, I'd "
                "test that another tenant's id returns not found, across every endpoint rather than "
                "one, because a test that only checks the happy path proves nothing here. I'd "
                "return 404 rather than 403 so you don't confirm it exists, and log who looked at "
                "what so a leak is at least detectable. UUIDs make guessing harder but that's not "
                "the protection.",
                {
                    "scoping-must-be-hard-to-omit": "covered",
                    "defence-in-depth": "covered",
                    "prove-it-negatively": "covered",
                    "not-found-over-forbidden": "covered",
                    "audit-every-access": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "Every query includes the tenant id in the WHERE clause. We review PRs carefully so "
                "nobody forgets it, and we have tests that check a user can see their own data.",
                {
                    "scoping-must-be-hard-to-omit": "contradicted",
                    "defence-in-depth": "missing",
                    "prove-it-negatively": "contradicted",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # rate-limiting
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="rate-limiting",
        seniority=MID,
        neutral_wording=(
            "You need to stop one client from overwhelming an endpoint. How would you limit them, "
            "and what does the client see when they hit the limit?"
        ),
        reframe_wording=(
            "Another way in: one caller is sending far more than their share. What do you put in "
            "front of them, and how do you tell them about it?"
        ),
        expected_minutes=4,
        concepts=(
            core(
                "allowance-that-refills-over-time",
                "You give each client an allowance that refills over time, so short bursts are "
                "tolerated but sustained excess isn't",
                "The refill model is what distinguishes a usable limit from a brittle one.",
                (
                    "they get a budget that tops back up",
                    "a burst is fine, sustained load isn't",
                    "it refills at a steady rate",
                    "like a bucket that drips full again",
                ),
                "Think about how to allow a quick burst without allowing it continuously.",
                ("counting requests per minute and resetting on the minute is equivalent",),
            ),
            core(
                "tell-the-client-how-to-behave",
                "The rejection has to say when to try again, or clients retry immediately and make "
                "it worse",
                "A limit that doesn't teach the client to back off amplifies the problem.",
                (
                    "tell them when they can retry",
                    "send a retry-after",
                    "otherwise they just hammer it harder",
                    "a 429 with no guidance makes it worse",
                ),
                "Think about what a well-behaved client does with your rejection.",
                ("clients will back off on their own once they see errors",),
            ),
            sup(
                "shared-state-across-instances",
                "With several app instances the counter has to be shared, or the effective limit "
                "is multiplied by the instance count",
                "Per-process limits silently don't limit.",
                ("keep the counter in a shared store", "otherwise each instance allows the full quota"),
            ),
            sup(
                "choose-the-key-carefully",
                "What you key on -- user, API key, or IP -- decides who gets punished when it's "
                "wrong",
                "IP-keyed limits hurt shared networks and miss distributed abuse.",
                ("key it per account rather than per IP where you can",),
            ),
            bonus(
                "fixed-window-boundary",
                "Naive per-minute counters allow a double burst across the boundary",
                "Names the specific flaw in the obvious implementation.",
                ("with a fixed window you can send double at the boundary",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "I'd give each client a budget that tops back up at a steady rate, like a bucket "
                "that drips full again, so a burst is fine but sustained load isn't. When they hit "
                "it I'd tell them when they can retry with a retry-after, because otherwise they "
                "just hammer it harder. The counter has to live in a shared store, otherwise each "
                "instance allows the full quota and the real limit is however many instances you "
                "have. I'd key it per account rather than per IP where I can, since IPs are shared. "
                "A plain per-minute counter is tempting but with a fixed window you can send double "
                "at the boundary.",
                {
                    "allowance-that-refills-over-time": "covered",
                    "tell-the-client-how-to-behave": "covered",
                    "shared-state-across-instances": "covered",
                    "choose-the-key-carefully": "covered",
                    "fixed-window-boundary": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd count requests per minute per IP in memory and return a 429 once they go over "
                "100. Resetting the counter each minute is simple and effectively the same as any "
                "other approach.",
                {
                    "allowance-that-refills-over-time": "contradicted",
                    "tell-the-client-how-to-behave": "partial",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="rate-limiting",
        seniority=SENIOR,
        neutral_wording=(
            "An expensive downstream dependency is being overwhelmed by your service during traffic "
            "spikes. Rate limiting your own callers isn't enough. What else would you put in place?"
        ),
        reframe_wording=(
            "Put it differently: you are the bad client now. What protects the thing you depend on, "
            "and what protects you from it?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.SCENARIO,
        concepts=(
            core(
                "bound-your-own-concurrency",
                "You cap how much work you send downstream at once, so your own service can't "
                "amplify a spike into an outage there",
                "Limiting inbound doesn't bound outbound; those are different valves.",
                (
                    "cap how many calls you have in flight to them",
                    "queue the rest rather than firing everything",
                    "a limit on your callers doesn't limit what you send",
                    "put a bulkhead around that dependency",
                ),
                "Think about which valve controls what leaves your service, rather than what enters "
                "it.",
                ("limiting inbound requests automatically limits outbound calls",),
            ),
            core(
                "stop-calling-when-it-is-failing",
                "When the dependency is failing, you stop calling it for a while instead of "
                "retrying into a service that's already down",
                "Retrying a failing dependency is how a partial outage becomes a total one.",
                (
                    "stop calling it for a bit once it starts failing",
                    "retrying into something that's down just keeps it down",
                    "fail fast instead of waiting for a timeout every time",
                    "let it recover, then try one request to see",
                ),
                "Think about what your retries are doing to a service that is already struggling.",
                ("retrying harder gets you through a downstream outage sooner",),
            ),
            core(
                "retries-need-jitter-and-a-budget",
                "Retries are spread randomly and capped, because synchronised retries recreate the "
                "spike you were smoothing",
                "Unjittered retries are a self-inflicted thundering herd.",
                (
                    "add randomness to the backoff",
                    "otherwise everyone retries at the same instant",
                    "cap the number of retries",
                    "a retry storm is worse than the original spike",
                ),
                "Think about what happens when a thousand clients all wait exactly two seconds.",
            ),
            sup(
                "degrade-rather-than-fail",
                "When the breaker is open you serve something reduced -- cached, partial, or a "
                "clear message -- rather than a hard error",
                "Graceful degradation preserves most of the user's outcome.",
                ("serve stale data or a reduced response instead of an error",),
            ),
            sup(
                "timeouts-derived-from-a-budget",
                "Each call's timeout comes from the overall latency budget rather than being "
                "picked arbitrarily",
                "Timeouts that exceed the caller's patience protect nothing.",
                ("work backwards from how long the user will wait",),
            ),
            bonus(
                "shed-load-at-the-edge",
                "Under extreme load, rejecting early is kinder than queueing work you'll never "
                "finish",
                "Queueing past capacity converts errors into timeouts, which is worse.",
                ("reject early rather than building a queue you can't drain",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "A limit on your callers doesn't limit what you send, so first I'd cap how many "
                "calls I have in flight to them and queue the rest rather than firing everything -- "
                "a bulkhead around that dependency. Second, stop calling it for a bit once it "
                "starts failing, because retrying into something that's down just keeps it down; "
                "fail fast instead of waiting for a timeout every time, then try one request to see "
                "if it's back. Third, add randomness to the backoff, otherwise everyone retries at "
                "the same instant and the retry storm is worse than the original spike, and cap the "
                "number of retries. While the breaker is open I'd serve stale data or a reduced "
                "response instead of an error. And I'd set the timeouts by working backwards from "
                "how long the user will wait, not by picking a number.",
                {
                    "bound-your-own-concurrency": "covered",
                    "stop-calling-when-it-is-failing": "covered",
                    "retries-need-jitter-and-a-budget": "covered",
                    "degrade-rather-than-fail": "covered",
                    "timeouts-derived-from-a-budget": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd tighten the rate limit on our own API, which reduces the number of downstream "
                "calls proportionally. I'd also add retries with a fixed two second delay so "
                "transient failures recover.",
                {
                    "bound-your-own-concurrency": "contradicted",
                    "stop-calling-when-it-is-failing": "missing",
                    "retries-need-jitter-and-a-budget": "contradicted",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # async-concurrency-model
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="async-concurrency-model",
        seniority=MID,
        neutral_wording=(
            "An async web service becomes completely unresponsive under moderate load, even though "
            "it's mostly waiting on IO. What would you look for?"
        ),
        reframe_wording=(
            "Same scenario differently: nothing is CPU-bound, nothing is crashing, and yet requests "
            "stop being served. What would cause that?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "one-loop-shared-by-everything",
                "Async concurrency works by handing control back while waiting, so a single "
                "operation that doesn't yield stalls every other request on that worker",
                "This is the mechanism behind almost every 'async but slow' incident.",
                (
                    "everything shares one loop",
                    "if one thing doesn't give control back nothing else runs",
                    "it's cooperative, so one greedy task blocks the rest",
                    "a blocking call freezes all the other requests",
                ),
                "Think about what has to happen for the next request to get a turn.",
                ("async means the work happens in parallel threads",),
            ),
            core(
                "find-the-blocking-call",
                "You look for synchronous work on the async path -- a blocking driver, file IO, or "
                "a CPU-heavy loop -- and move it off the loop",
                "Naming the culprit class is what makes the fix actionable.",
                (
                    "find the synchronous call that's blocking",
                    "a sync database driver on the async path",
                    "move it to a thread or a worker",
                    "CPU-heavy work needs to go somewhere else",
                ),
                "Think about which line in a request is running without ever awaiting.",
                ("marking a function async makes the code inside it non-blocking",),
            ),
            sup(
                "lazy-io-surprises",
                "In async code, IO triggered implicitly -- like touching an unloaded relationship "
                "-- fails or blocks at runtime on that path only",
                "This is a real trap and it only shows up on the path that touches it.",
                ("touching a relationship you didn't load does IO you didn't expect",),
            ),
            sup(
                "measure-dont-guess",
                "You confirm it with evidence -- loop lag, per-route latency -- rather than "
                "guessing which call is at fault",
                "The blocking call is rarely the one you suspect.",
                ("measure how long the loop is blocked", "look at per-route timings"),
            ),
            bonus(
                "concurrency-is-not-parallelism",
                "More async does not mean more CPU throughput; CPU-bound work needs processes",
                "Prevents the 'add more async' non-fix.",
                ("async doesn't help if the work is CPU-bound",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "Everything shares one loop, and it's cooperative -- if one thing doesn't give "
                "control back nothing else runs, so a blocking call freezes all the other requests "
                "even though they're just waiting on IO. So I'd look for the synchronous call "
                "that's blocking: a sync database driver on the async path, file IO, or a CPU-heavy "
                "loop, and move it to a thread or a worker. A subtle one is touching a relationship "
                "you didn't load, which does IO you didn't expect. I'd confirm it by measuring how "
                "long the loop is blocked and looking at per-route timings rather than guessing. "
                "And async doesn't help if the work is actually CPU-bound.",
                {
                    "one-loop-shared-by-everything": "covered",
                    "find-the-blocking-call": "covered",
                    "lazy-io-surprises": "covered",
                    "measure-dont-guess": "covered",
                    "concurrency-is-not-parallelism": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd increase the number of workers so more requests can run in parallel. Async "
                "code runs on threads so adding workers scales it linearly.",
                {
                    "one-loop-shared-by-everything": "contradicted",
                    "find-the-blocking-call": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="async-concurrency-model",
        seniority=SENIOR,
        neutral_wording=(
            "You're introducing async into a codebase that also has synchronous background workers "
            "sharing the same models. How would you approach that, and what would you watch out "
            "for?"
        ),
        reframe_wording=(
            "Put it another way: half your code has to stay synchronous. How do you avoid ending up "
            "with two of everything?"
        ),
        expected_minutes=7,
        archetype=QuestionArchetype.DECISION,
        concepts=(
            core(
                "two-execution-contexts-one-model-layer",
                "The request path and the workers run differently, so the shared layer has to be "
                "usable from both without forking the domain code",
                "Forking the model layer is the expensive mistake this question is about.",
                (
                    "the workers stay sync and the web path is async",
                    "the models are shared so they can't assume either",
                    "you don't want two copies of the same logic",
                    "keep one domain layer usable from both",
                ),
                "Think about what happens to the shared code if each side gets its own version.",
                ("everything has to be converted to async at once",),
            ),
            core(
                "no-implicit-io-on-the-async-path",
                "Anything the async path touches must be loaded up front, because implicit lazy "
                "loading fails at runtime on exactly the path that does it",
                "The failure is path-specific and therefore easy to ship.",
                (
                    "load everything you'll need eagerly",
                    "lazy loading blows up in async",
                    "it only fails on the code path that touches it, so tests miss it",
                    "the auth dependency reading a role is the classic one",
                ),
                "Think about the attribute nobody loaded, accessed after the await.",
                ("the ORM loads what it needs automatically in async too",),
            ),
            core(
                "make-it-testable",
                "You arrange for async endpoints to run inside the test transaction, rather than "
                "standing up a second engine and losing isolation",
                "Untestable async is how the lazy-IO bugs reach production.",
                (
                    "run the async code inside the test transaction",
                    "otherwise you need a second engine and lose isolation",
                    "present the sync test session behind the async interface",
                    "roll back to a savepoint between tests",
                ),
                "Think about how a test would exercise the async path and still roll back cleanly.",
            ),
            sup(
                "migrate-incrementally",
                "You convert route by route rather than in one change, so each step is reviewable "
                "and revertible",
                "Big-bang conversions can't be reviewed or rolled back.",
                ("do it a route at a time",),
            ),
            sup(
                "commit-then-enqueue-ordering",
                "Work dispatched from the async path must not race the commit, which is what the "
                "outbox exists to solve",
                "Connects the concurrency model to the reliability requirement.",
                ("the worker can race the commit, so use an outbox",),
            ),
            bonus(
                "override-identity-in-tests",
                "Async and sync dependencies are separate objects, so overriding one does not "
                "override the other",
                "A subtle test-infrastructure trap worth knowing.",
                ("overriding the sync dependency doesn't override the async one",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "I'd keep the workers sync and make the web path async, with one domain layer "
                "usable from both -- you don't want two copies of the same logic. The main trap is "
                "that lazy loading blows up in async, and it only fails on the code path that "
                "touches it, so tests miss it; the auth dependency reading a role is the classic "
                "one, so load everything you'll need eagerly. For testing I'd run the async code "
                "inside the test transaction by presenting the sync test session behind the async "
                "interface, otherwise you need a second engine and lose isolation. I'd do it a "
                "route at a time. And anything that dispatches background work has to be careful "
                "because the worker can race the commit, so use an outbox.",
                {
                    "two-execution-contexts-one-model-layer": "covered",
                    "no-implicit-io-on-the-async-path": "covered",
                    "make-it-testable": "covered",
                    "migrate-incrementally": "covered",
                    "commit-then-enqueue-ordering": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd convert everything to async in one pass, including the workers, so there's "
                "only one style in the codebase. The ORM handles loading automatically so the "
                "models don't need changing.",
                {
                    "two-execution-contexts-one-model-layer": "contradicted",
                    "no-implicit-io-on-the-async-path": "contradicted",
                    "make-it-testable": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # rest-api-design
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="rest-api-design",
        seniority=MID,
        neutral_wording=(
            "You're designing the endpoints for a resource that can be created, listed, updated "
            "and cancelled. How would you lay that out, and why?"
        ),
        reframe_wording=(
            "Put it another way: sketch the URLs and methods. What makes one layout better than "
            "another here?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "methods-carry-meaning",
                "The method already tells callers and every intermediary whether a call is safe "
                "to repeat or safe to cache, so it has to match what the call actually does",
                "Getting this wrong breaks retries and caching for everyone downstream.",
                (
                    "a get shouldn't change anything",
                    "put and delete can be repeated safely, post can't",
                    "proxies and clients assume that, so don't lie to them",
                    "if a retry is safe, the method should say so",
                ),
                "Think about what a client library is entitled to assume before it retries a call.",
                ("using post for everything is simpler and works fine",),
            ),
            core(
                "actions-that-are-not-crud",
                "Something like cancel isn't naturally a field update, so it becomes either a "
                "state transition on the resource or its own sub-resource -- not a verb in the URL",
                "This is where most REST designs get muddled, and there is a clean answer.",
                (
                    "cancel is a state change, so patch the status",
                    "or make it its own sub-resource you post to",
                    "keep verbs out of the path",
                    "model it as a thing rather than an action",
                ),
                "Think about how to express 'do this to it' without putting a verb in the URL.",
                ("a verb in the path is the RESTful way to model an action",),
            ),
            core(
                "status-codes-are-part-of-the-contract",
                "The status carries the outcome class -- created, no content, conflict, not found "
                "-- so clients branch on it before reading the body",
                "A 200 with an error inside forces every client to parse before it can react.",
                (
                    "201 with the location when you create something",
                    "409 when it conflicts with the current state",
                    "don't return 200 with an error inside",
                    "the status says what happened, the body says why",
                ),
                "Think about what the client can decide before it has parsed anything.",
            ),
            sup(
                "consistent-collection-conventions",
                "Listing endpoints share one convention for filtering, sorting and pagination "
                "across the whole API",
                "Consistency is what makes the second endpoint free to learn.",
                ("same pagination and filter style everywhere",),
            ),
            sup(
                "design-for-the-caller",
                "The shape follows from what clients actually need to do, not from the table "
                "layout underneath",
                "An API that mirrors your schema leaks your schema.",
                ("don't just expose the tables", "start from what the client is trying to do"),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "I'd use a collection and an item under it, and let the methods carry meaning -- a "
                "get shouldn't change anything, and put and delete can be repeated safely while "
                "post can't. Proxies and clients assume that, so don't lie to them. Cancel is the "
                "interesting one: it's a state change, so I'd patch the status, or make it its own "
                "sub-resource you post to, and keep verbs out of the path. For responses, 201 with "
                "the location when you create something, 409 when it conflicts with the current "
                "state, and don't return 200 with an error inside -- the status says what "
                "happened, the body says why. I'd use the same pagination and filter style "
                "everywhere, and start from what the client is trying to do rather than just "
                "exposing the tables.",
                {
                    "methods-carry-meaning": "covered",
                    "actions-that-are-not-crud": "covered",
                    "status-codes-are-part-of-the-contract": "covered",
                    "consistent-collection-conventions": "covered",
                    "design-for-the-caller": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd have /createThing, /listThings, /updateThing and /cancelThing, all as POST. "
                "Using post for everything is simpler and works fine, and it means you don't have "
                "to think about which method to use. They'd all return 200 with a success flag in "
                "the body.",
                {
                    "methods-carry-meaning": "contradicted",
                    "actions-that-are-not-crud": "contradicted",
                    "status-codes-are-part-of-the-contract": "contradicted",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="rest-api-design",
        seniority=SENIOR,
        neutral_wording=(
            "You need to add a field to an API response and change the meaning of an existing "
            "one. Clients include a mobile app you can't force to update. How do you proceed?"
        ),
        reframe_wording=(
            "Another framing: one change is additive and one isn't. What can you ship today and "
            "what needs a different plan?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.DECISION,
        concepts=(
            core(
                "additive-is-safe-semantic-change-is-not",
                "Adding a field is backwards compatible if clients ignore unknown fields; "
                "changing what an existing field means is a break even though the shape is identical",
                "Distinguishing shape from meaning is the whole judgement here.",
                (
                    "adding a field is fine as long as clients ignore what they don't know",
                    "changing the meaning breaks them even though the type is the same",
                    "the schema looks unchanged but the contract isn't",
                    "old clients will keep reading it the old way",
                ),
                "Think about a client that keeps parsing the field successfully and now draws the "
                "wrong conclusion.",
                ("if the response still validates against the schema it is backwards compatible",),
            ),
            core(
                "add-new-rather-than-redefine",
                "The safe move is a new field with the new meaning, deprecating the old one, "
                "rather than repurposing a name clients already depend on",
                "This converts an impossible change into an ordinary one.",
                (
                    "add a new field with the new meaning and leave the old one alone",
                    "deprecate rather than repurpose",
                    "let old clients keep reading the old field",
                    "never quietly change what a name means",
                ),
                "Think about how to introduce the new meaning without touching the old name.",
                ("a changelog entry is enough notice for a semantic change",),
            ),
            core(
                "you-cannot-force-a-mobile-update",
                "Some clients are permanently out there, so removal is gated on observed usage "
                "dropping rather than on an announcement",
                "This is what makes the mobile constraint a design input, not a communication task.",
                (
                    "there will always be old app versions in the wild",
                    "you can't make people update",
                    "measure who's still calling it before you remove anything",
                    "instrument the old field and watch it drop",
                ),
                "Think about the phone that never gets updated, and how you'd know it exists.",
            ),
            sup(
                "version-when-you-genuinely-must",
                "If a break is unavoidable, a new version lets old and new coexist rather than "
                "forcing a flag day",
                "Versioning is the escape hatch, not the default.",
                ("if it really can't be done additively, add a new version alongside",),
            ),
            sup(
                "generated-types-catch-drift",
                "Generating client types from the published schema turns a mismatch into a "
                "compile error rather than an undefined at runtime",
                "Moves the failure from production to CI.",
                ("generate the client types from the schema so drift is a build failure",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "Those are two different changes. Adding a field is fine as long as clients ignore "
                "what they don't know, so I'd ship that today. Changing the meaning breaks them "
                "even though the type is the same -- the schema looks unchanged but the contract "
                "isn't, and old clients will keep reading it the old way and drawing the wrong "
                "conclusion. So I'd add a new field with the new meaning and leave the old one "
                "alone, and deprecate rather than repurpose. Because there will always be old app "
                "versions in the wild and you can't make people update, I'd instrument the old "
                "field and watch it drop before removing it. If it really can't be done additively, "
                "add a new version alongside. And I'd generate the client types from the schema so "
                "drift is a build failure.",
                {
                    "additive-is-safe-semantic-change-is-not": "covered",
                    "add-new-rather-than-redefine": "covered",
                    "you-cannot-force-a-mobile-update": "covered",
                    "version-when-you-genuinely-must": "covered",
                    "generated-types-catch-drift": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "Both changes are safe because the response still validates against the schema -- "
                "the field types aren't changing. I'd ship them together and put a note in the "
                "changelog so client teams know the field means something different now.",
                {
                    "additive-is-safe-semantic-change-is-not": "contradicted",
                    "add-new-rather-than-redefine": "missing",
                    "you-cannot-force-a-mobile-update": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # api-versioning
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="api-versioning",
        seniority=MID,
        neutral_wording=(
            "Your API has no versioning and you're about to introduce it. What are the options "
            "and what would you pick?"
        ),
        reframe_wording=(
            "Same question differently: where does the version live, and what does that choice "
            "cost you later?"
        ),
        expected_minutes=4,
        concepts=(
            core(
                "version-in-the-path-or-the-header",
                "The version can sit in the URL or in a header, and the trade is between being "
                "obvious in a browser and log versus keeping one URL per resource",
                "Both are defensible; knowing why is the point.",
                (
                    "either put it in the path or negotiate it with a header",
                    "in the path it's visible in logs and easy to curl",
                    "in a header the url stays the same for the same thing",
                    "path versioning is easier for humans to reason about",
                ),
                "Think about where a caller would look to find out which version they got.",
                ("the version belongs in the request body alongside the payload",),
            ),
            core(
                "version-the-contract-not-every-change",
                "Most changes should be additive and need no version at all; a version is for the "
                "breaks you genuinely cannot avoid",
                "Versioning per release produces a maintenance burden with no benefit.",
                (
                    "most changes don't need a new version at all",
                    "only bump it when you actually break something",
                    "adding fields is backwards compatible",
                    "a version per release means supporting a version per release",
                ),
                "Think about how many versions you'll be maintaining in two years under each policy.",
                ("every release should get a new API version",),
            ),
            sup(
                "have-a-deprecation-story",
                "Introducing versions without a policy for retiring them means supporting all of "
                "them forever",
                "The cost of a version is its whole lifetime, not its introduction.",
                ("decide up front how a version gets retired", "announce, measure, then remove"),
            ),
            sup(
                "moving-paths-breaks-hidden-things",
                "Adding a prefix breaks anything that hardcoded the old one -- cookie paths, "
                "redirect URLs, health probes, end-to-end tests",
                "The API client is the obvious one; the others bite later.",
                (
                    "a cookie scoped to the old path stops being sent",
                    "grep for the old prefix everywhere, not just the client",
                ),
            ),
            bonus(
                "one-implementation-many-adapters",
                "Old versions are best served by translating at the edge rather than by "
                "maintaining parallel implementations",
                "Keeps the branching in one thin layer.",
                ("translate the old shape at the edge rather than forking the code",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "You either put it in the path or negotiate it with a header. In the path it's "
                "visible in logs and easy to curl, which I'd usually take; in a header the URL "
                "stays the same for the same thing. But the more important rule is that most "
                "changes don't need a new version at all -- adding fields is backwards compatible, "
                "so only bump it when you actually break something, because a version per release "
                "means supporting a version per release. I'd decide up front how a version gets "
                "retired. One thing to watch when adding the prefix: a cookie scoped to the old "
                "path stops being sent, so grep for the old prefix everywhere, not just the client.",
                {
                    "version-in-the-path-or-the-header": "covered",
                    "version-the-contract-not-every-change": "covered",
                    "have-a-deprecation-story": "covered",
                    "moving-paths-breaks-hidden-things": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "Every release should get a new API version so clients always know exactly what "
                "they're getting. I'd put v1 in the path now and bump to v2 next sprint when we "
                "add the new fields.",
                {
                    "version-in-the-path-or-the-header": "partial",
                    "version-the-contract-not-every-change": "contradicted",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="api-versioning",
        seniority=SENIOR,
        neutral_wording=(
            "You're maintaining three live API versions and the team is spending most of its time "
            "on the older two. How do you get out of that?"
        ),
        reframe_wording=(
            "Put it another way: versioning worked and now it's the problem. What's the way back "
            "to one?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.DECISION,
        concepts=(
            core(
                "find-out-who-is-actually-on-them",
                "Retirement is driven by measured usage per version and per client, because the "
                "answer is usually that almost nobody is on the old ones",
                "Without the data the conversation is about fear rather than facts.",
                (
                    "instrument which version each caller uses",
                    "break it down by client, not just totals",
                    "usually it's two integrations, not the whole world",
                    "you need the list of who to talk to",
                ),
                "Think about what you'd need to know before you could name a shutdown date.",
                ("you can never remove a public API version once it exists",),
            ),
            core(
                "collapse-to-one-implementation",
                "The maintenance cost comes from parallel implementations, so the fix is one "
                "internal model with thin translation layers per version",
                "This removes most of the cost even before any version is retired.",
                (
                    "have one implementation and adapt the old shapes at the edge",
                    "stop maintaining three copies of the logic",
                    "the old version becomes a translation, not a fork",
                    "fix a bug once instead of three times",
                ),
                "Think about where the duplicated work actually lives.",
                ("each version needs its own copy of the business logic",),
            ),
            core(
                "sunset-with-notice-and-signal",
                "Removal is announced, signalled in the responses themselves, and gated on usage "
                "reaching zero -- not on the date alone",
                "A date without a usage gate is how you break someone on a Friday.",
                (
                    "announce a date and send a deprecation header",
                    "warn in the response so it shows up in their logs",
                    "confirm usage is actually zero before you switch it off",
                    "brownouts before the real shutdown",
                ),
                "Think about how a client who never reads your email would find out.",
            ),
            sup(
                "contract-tests-per-version",
                "Each supported version needs tests asserting its shape, or the shared "
                "implementation silently changes it",
                "Consolidation without tests reintroduces the breaks you were avoiding.",
                ("test each version's response shape against its published schema",),
            ),
            sup(
                "stop-adding-versions",
                "The immediate action is a policy that only genuine breaks earn a version, or the "
                "problem regrows",
                "Otherwise you clean up and end up back here.",
                ("agree that only real breaks get a new version from now on",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "First I'd instrument which version each caller uses and break it down by client, "
                "not just totals -- usually it's two integrations, not the whole world, and you "
                "need the list of who to talk to. Then I'd collapse the cost: have one "
                "implementation and adapt the old shapes at the edge, so the old version becomes a "
                "translation, not a fork, and you fix a bug once instead of three times. For "
                "removal I'd announce a date and send a deprecation header so it warns in their "
                "logs, run brownouts before the real shutdown, and confirm usage is actually zero "
                "before switching it off. I'd add tests for each version's response shape against "
                "its published schema, and agree that only real breaks get a new version from now "
                "on.",
                {
                    "find-out-who-is-actually-on-them": "covered",
                    "collapse-to-one-implementation": "covered",
                    "sunset-with-notice-and-signal": "covered",
                    "contract-tests-per-version": "covered",
                    "stop-adding-versions": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "You can never remove a public API version once it exists, so we're stuck "
                "supporting all three. I'd hire another engineer for the maintenance, or freeze "
                "the old versions and only fix critical bugs in them.",
                {
                    "find-out-who-is-actually-on-them": "contradicted",
                    "collapse-to-one-implementation": "missing",
                    "sunset-with-notice-and-signal": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # authentication-mechanisms
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="authentication-mechanisms",
        seniority=MID,
        neutral_wording=(
            "How would you handle sign-in for a web app, from the password arriving to the user "
            "staying signed in across visits?"
        ),
        reframe_wording=(
            "Put it another way: walk me from the login form to a user who is still signed in "
            "tomorrow. What are you storing at each point?"
        ),
        expected_minutes=6,
        concepts=(
            core(
                "never-store-the-password",
                "The password is put through a slow, salted, purpose-built hash, so a database "
                "leak yields nothing usable and guessing is expensive",
                "Speed is the enemy here, which inverts the usual instinct about hashing.",
                (
                    "hash it with something deliberately slow",
                    "each one has its own salt so you can't attack them all at once",
                    "never store it, and never log it",
                    "a fast hash is the wrong tool because guessing gets cheap",
                ),
                "Think about what an attacker with a copy of the table can do, and how long it "
                "takes them.",
                ("sha256 with a salt is appropriate for passwords",),
            ),
            core(
                "short-access-long-refresh",
                "A short-lived credential authorises requests and a longer-lived one obtains new "
                "ones, so a stolen access token expires quickly",
                "This is the shape that makes revocation tractable.",
                (
                    "a short-lived token for requests",
                    "a longer-lived one that gets you new ones",
                    "so a stolen one is only good for a few minutes",
                    "the long-lived one is only sent to the refresh endpoint",
                ),
                "Think about how long a stolen credential stays useful under each design.",
                ("one long-lived token is simpler and equally safe",),
            ),
            core(
                "rotate-and-detect-reuse",
                "Each refresh issues a new credential and invalidates the old one, so seeing an "
                "old one again means it leaked and the whole session should be revoked",
                "Rotation alone protects nothing; the detection is the control.",
                (
                    "give out a new one each time and retire the old",
                    "if an old one comes back, someone has a copy",
                    "kill the whole family when that happens",
                    "rotation is only useful because it makes reuse visible",
                ),
                "Think about what it means when a credential you already replaced is presented "
                "again.",
            ),
            sup(
                "store-it-where-script-cannot-reach",
                "Session credentials belong in cookies the page cannot read, so a script "
                "injection can't walk off with them",
                "Where you store it decides what an XSS bug costs you.",
                ("httponly cookie so javascript can't read it", "not localstorage"),
            ),
            sup(
                "do-not-reveal-which-part-was-wrong",
                "Sign-in failures return one message whether the account exists or not, and take "
                "similar time either way",
                "A distinct 'no such account' is a free user list.",
                ("same error whether the email exists or not",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "The password gets hashed with something deliberately slow, each one with its own "
                "salt so you can't attack them all at once -- a fast hash is the wrong tool "
                "because guessing gets cheap. Then I'd issue a short-lived token for requests and "
                "a longer-lived one that gets you new ones, so a stolen one is only good for a few "
                "minutes, and the long-lived one is only sent to the refresh endpoint. On each "
                "refresh I'd give out a new one and retire the old, and if an old one comes back, "
                "someone has a copy, so kill the whole family. I'd keep them in an httponly cookie "
                "so javascript can't read it, not localstorage. And the same error whether the "
                "email exists or not.",
                {
                    "never-store-the-password": "covered",
                    "short-access-long-refresh": "covered",
                    "rotate-and-detect-reuse": "covered",
                    "store-it-where-script-cannot-reach": "covered",
                    "do-not-reveal-which-part-was-wrong": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd hash the password with sha256 and a salt, which is appropriate for passwords "
                "and fast. Then issue a long-lived token, store it in localStorage so the frontend "
                "can attach it to requests, and check it on each call. If the email isn't found I'd "
                "return 'no such user' so they know to sign up.",
                {
                    "never-store-the-password": "contradicted",
                    "short-access-long-refresh": "contradicted",
                    "rotate-and-detect-reuse": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="authentication-mechanisms",
        seniority=SENIOR,
        neutral_wording=(
            "You're adding third-party sign-in alongside existing password accounts. What are the "
            "risks, and how do you handle a user who has both?"
        ),
        reframe_wording=(
            "Another framing: the same human can now arrive through two doors. What could go "
            "wrong when they do?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.EDGE,
        concepts=(
            core(
                "email-is-not-proof-of-identity",
                "Linking accounts on a matching email address is only safe if the provider has "
                "actually verified it, otherwise anyone who can claim the address takes the account",
                "This is the account-takeover path, and it looks like a convenience feature.",
                (
                    "only link them if the provider says the email is verified",
                    "otherwise someone signs up with your address and gets your account",
                    "the email alone doesn't prove anything",
                    "check the verified flag, don't assume it",
                ),
                "Think about someone signing in with a provider using an address they don't own.",
                ("matching on email address is a safe way to link accounts",),
            ),
            core(
                "link-deliberately-not-silently",
                "When an email matches an existing account, the safe flow proves control of the "
                "existing account before attaching the new sign-in method",
                "Explicit linking turns a silent takeover into a normal confirmation step.",
                (
                    "make them sign in the old way once to link it",
                    "ask before merging, don't just merge",
                    "prove they control the existing account first",
                    "linking is an action the user takes, not something that happens to them",
                ),
                "Think about how you'd confirm the two accounts really belong to the same person.",
                ("silently merging on a matching email is good user experience",),
            ),
            core(
                "the-exchange-must-be-bound-to-the-request",
                "The redirect flow needs state that ties the response back to the request that "
                "started it, and the code must be single-use and bound to this client",
                "Without it, an attacker can graft their own login onto someone else's session.",
                (
                    "a state value you generate and check when they come back",
                    "otherwise someone can feed you a response you didn't ask for",
                    "the code is single use and tied to the client",
                    "pkce so an intercepted code is useless on its own",
                ),
                "Think about what stops someone handing your app a login response you never "
                "initiated.",
            ),
            sup(
                "one-identity-many-methods",
                "The data model separates the person from the ways they can prove who they are, "
                "so adding or removing a method doesn't disturb their data",
                "Modelling it any other way makes every later change painful.",
                ("one user with several linked login methods",),
            ),
            sup(
                "do-not-lock-them-out",
                "Removing a sign-in method has to leave at least one working, and account "
                "recovery has to survive losing the provider",
                "The failure mode is a user who can never get back in.",
                ("make sure they always have at least one way back in",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "The big one is that the email alone doesn't prove anything -- only link them if "
                "the provider says the email is verified, otherwise someone signs up with your "
                "address and gets your account. So when the email matches I'd make them sign in "
                "the old way once to link it: prove they control the existing account first, and "
                "ask before merging rather than just merging. On the flow itself, I'd use a state "
                "value I generate and check when they come back, otherwise someone can feed you a "
                "response you didn't ask for, plus pkce so an intercepted code is useless on its "
                "own. I'd model it as one user with several linked login methods, and make sure "
                "they always have at least one way back in.",
                {
                    "email-is-not-proof-of-identity": "covered",
                    "link-deliberately-not-silently": "covered",
                    "the-exchange-must-be-bound-to-the-request": "covered",
                    "one-identity-many-methods": "covered",
                    "do-not-lock-them-out": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "Matching on email address is a safe way to link accounts, so if the email from "
                "the provider matches an existing user I'd just log them into that account. That's "
                "the smoothest experience and avoids an extra step.",
                {
                    "email-is-not-proof-of-identity": "contradicted",
                    "link-deliberately-not-silently": "contradicted",
                    "the-exchange-must-be-bound-to-the-request": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # session-and-cookie-security
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="session-and-cookie-security",
        seniority=MID,
        neutral_wording=(
            "You're setting a session cookie. Walk me through the attributes you'd set and what "
            "each one is protecting against."
        ),
        reframe_wording=(
            "Put it another way: for each flag on that cookie, what specifically goes wrong if "
            "you leave it off?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "keep-it-away-from-scripts-and-plaintext",
                "Marking it unreadable to scripts limits what an injected script can steal, and "
                "restricting it to HTTPS stops it crossing the network in the clear",
                "These two are what decide the cost of an XSS bug or a coffee-shop network.",
                (
                    "httponly so javascript can't read it",
                    "an xss bug then can't walk off with the session",
                    "secure so it's never sent over plain http",
                    "otherwise anyone on the network sees it",
                ),
                "Think about what an injected script, and then a network observer, could each do "
                "with it.",
                ("httponly prevents cross-site request forgery",),
            ),
            core(
                "control-when-it-is-sent-cross-site",
                "Restricting the cookie on cross-site requests is what stops another site's page "
                "silently making authenticated calls as the user",
                "This is the CSRF control, and it is different from the script-readability one.",
                (
                    "samesite so another site can't make requests as you",
                    "lax still works when you click a link in, but blocks cross-site posts",
                    "that's what stops a form on another domain hitting your api",
                    "strict is safer but breaks arriving from an external link",
                ),
                "Think about a page on someone else's domain submitting a form to your API.",
                ("samesite strict is always the right choice",),
            ),
            sup(
                "scope-it-narrowly",
                "Path and domain decide who receives it, and a broad domain shares it with every "
                "subdomain including ones you don't control",
                "Scope is the difference between one app's problem and everyone's.",
                (
                    "don't set it on the parent domain unless you mean it",
                    "every subdomain will get it",
                ),
            ),
            sup(
                "lifetime-and-invalidation",
                "A session needs an expiry and a way to be revoked server-side, so sign-out and "
                "compromise actually end it",
                "A cookie you can't revoke is a permanent credential.",
                ("give it an expiry and be able to kill it server side",),
            ),
            bonus(
                "rotate-on-privilege-change",
                "Issuing a fresh session on sign-in and on privilege escalation prevents an "
                "attacker-planted session being used later",
                "Closes session fixation.",
                ("issue a new session id when they log in",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "Httponly so javascript can't read it -- an xss bug then can't walk off with the "
                "session. Secure so it's never sent over plain http, otherwise anyone on the "
                "network sees it. Samesite so another site can't make requests as you: lax still "
                "works when you click a link in but blocks cross-site posts, which is what stops a "
                "form on another domain hitting your api. I'd scope the path narrowly and not set "
                "it on the parent domain unless I mean it, because every subdomain will get it. "
                "It needs an expiry and I need to be able to kill it server side. And I'd issue a "
                "new session id when they log in.",
                {
                    "keep-it-away-from-scripts-and-plaintext": "covered",
                    "control-when-it-is-sent-cross-site": "covered",
                    "scope-it-narrowly": "covered",
                    "lifetime-and-invalidation": "covered",
                    "rotate-on-privilege-change": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd set httponly, which prevents cross-site request forgery since other sites "
                "can't read or send the cookie. That's the main one. I'd also set a long expiry so "
                "users don't have to log in again.",
                {
                    "keep-it-away-from-scripts-and-plaintext": "contradicted",
                    "control-when-it-is-sent-cross-site": "contradicted",
                    "lifetime-and-invalidation": "partial",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="session-and-cookie-security",
        seniority=SENIOR,
        neutral_wording=(
            "Your frontend and API are on different origins and you're using cookie auth. What "
            "does that force you to get right?"
        ),
        reframe_wording=(
            "Another framing: the browser now treats your own frontend as a third party to your "
            "API. What has to change?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.EDGE,
        concepts=(
            core(
                "cross-origin-credentials-are-opt-in-on-both-sides",
                "The browser will not send or accept credentialed cross-origin requests unless "
                "the client asks and the server explicitly allows that exact origin",
                "Both halves are required, and the failure is silent on the client.",
                (
                    "the client has to ask to send credentials",
                    "and the server has to allow credentials for that specific origin",
                    "you can't use a wildcard origin with credentials",
                    "if either side is missing, the cookie just isn't sent",
                ),
                "Think about what the browser does by default with a cookie on a cross-origin "
                "request.",
                ("allowing all origins is fine as long as you also allow credentials",),
            ),
            core(
                "samesite-becomes-load-bearing",
                "Cross-site cookie rules now apply to your own frontend, so the SameSite setting "
                "decides whether your app works at all -- and loosening it re-opens CSRF",
                "This is the tension the split origin creates and it needs a deliberate answer.",
                (
                    "your own frontend counts as cross-site now",
                    "strict would break your own app",
                    "loosening it means you need another csrf defence",
                    "the setting that protects you is the one that breaks you",
                ),
                "Think about the browser treating your own frontend the same as any other site.",
                ("a split origin behaves the same as a same-origin setup",),
            ),
            core(
                "state-the-csrf-posture-explicitly",
                "With cookie auth you need a documented answer for CSRF -- SameSite plus origin "
                "checking, or a token -- rather than assuming it's handled",
                "Unstated CSRF posture is how it ends up not being handled at all.",
                (
                    "write down what actually stops csrf here",
                    "samesite plus checking the origin header",
                    "or a token the other site can't read",
                    "don't assume the framework did it",
                ),
                "Think about what specifically would stop a malicious page posting to your API as "
                "the user.",
            ),
            sup(
                "preflight-and-caching",
                "Non-simple cross-origin requests trigger a preflight, so the allowed headers and "
                "methods have to be listed and it's worth caching the answer",
                "Explains the mysterious doubled request count.",
                ("the browser sends an options request first", "list the headers you actually use"),
            ),
            sup(
                "cookie-path-follows-the-api-prefix",
                "A cookie scoped to a path stops being sent when routes move, so the scope has to "
                "track the API prefix",
                "This is a real outage that looks like an auth bug.",
                ("if you move routes under a prefix the cookie path has to move too",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "First, the client has to ask to send credentials and the server has to allow "
                "credentials for that specific origin -- you can't use a wildcard origin with "
                "credentials, and if either side is missing the cookie just isn't sent. Second, "
                "your own frontend counts as cross-site now, so strict would break your own app, "
                "and loosening it means you need another csrf defence -- the setting that protects "
                "you is the one that breaks you. So I'd write down what actually stops csrf here: "
                "samesite plus checking the origin header, or a token the other site can't read. "
                "I'd also remember the browser sends an options request first, so list the headers "
                "you actually use. And if you move routes under a prefix the cookie path has to "
                "move too.",
                {
                    "cross-origin-credentials-are-opt-in-on-both-sides": "covered",
                    "samesite-becomes-load-bearing": "covered",
                    "state-the-csrf-posture-explicitly": "covered",
                    "preflight-and-caching": "covered",
                    "cookie-path-follows-the-api-prefix": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd enable CORS with allow-all origins and allow credentials, which is fine and "
                "means any frontend can talk to it. The cookie will be sent automatically by the "
                "browser so nothing else needs to change.",
                {
                    "cross-origin-credentials-are-opt-in-on-both-sides": "contradicted",
                    "samesite-becomes-load-bearing": "missing",
                    "state-the-csrf-posture-explicitly": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # caching-strategies
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="caching-strategies",
        seniority=MID,
        neutral_wording=(
            "An endpoint is called constantly and the underlying data changes a few times a day. "
            "How would you add caching, and where?"
        ),
        reframe_wording=(
            "Put it differently: the same answer is being recomputed thousands of times. Where do "
            "you put the saved copy, and how do you know when to throw it away?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "decide-tolerable-staleness-first",
                "How out of date the answer may be is a product question, and it determines "
                "everything else about the design",
                "Starting anywhere else means guessing at the requirement.",
                (
                    "how old is the answer allowed to be",
                    "that's a question for the people using it",
                    "a few minutes might be fine, or it might not",
                    "the tolerance decides the design",
                ),
                "Think about what a user would notice if the answer were ten minutes old.",
                ("the shortest TTL you can tolerate is always the safest default",),
            ),
            core(
                "invalidate-on-write-not-just-on-time",
                "Since the data changes rarely and identifiably, clearing the entry when it "
                "changes gives fresh data and a high hit rate at the same time",
                "Time-based expiry alone forces a choice between stale and cold.",
                (
                    "clear the key when the data changes",
                    "then you can keep it much longer",
                    "expiry alone means it's either stale or always cold",
                    "the write path knows exactly what changed",
                ),
                "Think about who already knows the moment the answer became wrong.",
                ("a short ttl is equivalent to invalidating on write",),
            ),
            core(
                "never-cache-per-user-data-in-a-shared-place",
                "A shared cache keyed without the viewer will serve one user's data to another, "
                "which is a data leak rather than a stale-data bug",
                "This is the mistake that turns a performance change into an incident.",
                (
                    "if the response varies by user it can't go in a shared cache",
                    "you'd serve one person's data to someone else",
                    "either key it per user or don't cache it",
                    "mark it private if the body depends on who's asking",
                ),
                "Think about two different users hitting the same cache key.",
            ),
            sup(
                "one-recompute-on-a-miss",
                "When an entry disappears, only one caller should recompute while the rest wait "
                "or get the old value",
                "Otherwise every expiry is a small stampede.",
                ("let one do the work and the others wait",),
            ),
            sup(
                "prove-it-with-the-hit-rate",
                "A cache is justified by its measured hit rate and the drop in origin load, not "
                "by its existence",
                "A cache that never hits is pure risk.",
                ("measure the hit rate and whether the database load actually dropped",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "First, how old is the answer allowed to be -- that's a question for the people "
                "using it, and the tolerance decides the design. Given it changes a few times a "
                "day and we know when, I'd clear the key when the data changes rather than relying "
                "on expiry, because then you can keep it much longer; expiry alone means it's "
                "either stale or always cold. The thing I'd be careful about is that if the "
                "response varies by user it can't go in a shared cache -- you'd serve one person's "
                "data to someone else -- so either key it per user or mark it private. On a miss "
                "I'd let one do the work and the others wait. Then measure the hit rate and "
                "whether the database load actually dropped.",
                {
                    "decide-tolerable-staleness-first": "covered",
                    "invalidate-on-write-not-just-on-time": "covered",
                    "never-cache-per-user-data-in-a-shared-place": "covered",
                    "one-recompute-on-a-miss": "covered",
                    "prove-it-with-the-hit-rate": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd put a cache in front of the endpoint with a thirty second TTL. A short ttl is "
                "equivalent to invalidating on write and it's much simpler, so the data is never "
                "more than thirty seconds old and we don't need to touch the write path.",
                {
                    "decide-tolerable-staleness-first": "missing",
                    "invalidate-on-write-not-just-on-time": "contradicted",
                    "never-cache-per-user-data-in-a-shared-place": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="caching-strategies",
        seniority=SENIOR,
        neutral_wording=(
            "You have caching at several layers -- browser, CDN and application -- and users are "
            "occasionally seeing stale content after a deploy. How do you sort that out?"
        ),
        reframe_wording=(
            "Another framing: something in the chain is holding on to an old copy and you don't "
            "know which. How do you find out and fix it?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.EDGE,
        concepts=(
            core(
                "identify-which-layer-is-holding-it",
                "Each layer can be interrogated separately, and the response headers tell you "
                "which one served the copy",
                "Fixing the wrong layer is the default failure here.",
                (
                    "check the headers to see which layer served it",
                    "bypass each one in turn to narrow it down",
                    "the cdn will tell you hit or miss",
                    "compare a request straight to the origin",
                ),
                "Think about how you'd tell a stale browser copy apart from a stale edge copy.",
                ("purging the cdn clears every layer",),
            ),
            core(
                "you-cannot-recall-a-browser-copy",
                "Anything already cached in a user's browser cannot be purged, so the only "
                "reliable fix is content-addressed URLs that change when the content does",
                "This is why the fix is a naming strategy rather than an invalidation strategy.",
                (
                    "you can't clear a cache on someone else's machine",
                    "give the file a new name when it changes",
                    "hash the content into the filename",
                    "the html points at the new url so the old one is never requested",
                ),
                "Think about a file already sitting on a user's laptop with a year-long expiry.",
                ("a hard refresh is a reliable fix you can ask users for",),
            ),
            core(
                "different-content-different-policy",
                "Immutable assets and mutable documents need opposite policies -- cache the "
                "fingerprinted assets forever, and make the entry document revalidate every time",
                "One blanket policy is what produces this bug.",
                (
                    "cache the hashed assets forever and never cache the html",
                    "the entry point has to revalidate",
                    "one policy for everything is what causes this",
                    "immutable things and changing things get opposite settings",
                ),
                "Think about which single file has to be fresh for everything else to update.",
            ),
            sup(
                "revalidation-over-blind-expiry",
                "Conditional requests let a client keep a copy but confirm it cheaply, which is "
                "usually better than either extreme",
                "Gets most of the benefit without the staleness.",
                ("use an etag so it can ask whether it changed", "304 instead of the whole body"),
            ),
            sup(
                "purge-as-part-of-deploy",
                "The invalidation step belongs in the deploy pipeline rather than in someone's "
                "memory",
                "Manual purges get forgotten exactly when they matter.",
                ("make the purge part of the deploy, not a manual step"),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "First I'd check the headers to see which layer served it and bypass each one in "
                "turn to narrow it down -- the cdn will tell you hit or miss, and I'd compare a "
                "request straight to the origin. The important realisation is you can't clear a "
                "cache on someone else's machine, so the fix is to give the file a new name when "
                "it changes: hash the content into the filename, and the html points at the new "
                "url so the old one is never requested. That means cache the hashed assets forever "
                "and never cache the html -- the entry point has to revalidate. One policy for "
                "everything is what causes this. I'd use an etag so it can ask whether it changed, "
                "and make the purge part of the deploy, not a manual step.",
                {
                    "identify-which-layer-is-holding-it": "covered",
                    "you-cannot-recall-a-browser-copy": "covered",
                    "different-content-different-policy": "covered",
                    "revalidation-over-blind-expiry": "covered",
                    "purge-as-part-of-deploy": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd purge the CDN after each deploy, which clears every layer including the "
                "browser caches. If people still see old content I'd tell them to hard refresh.",
                {
                    "identify-which-layer-is-holding-it": "missing",
                    "you-cannot-recall-a-browser-copy": "contradicted",
                    "different-content-different-policy": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # background-jobs-and-queues
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="background-jobs-and-queues",
        seniority=MID,
        neutral_wording=(
            "A request currently sends an email inline and users complain it's slow. You want to "
            "move it to a background job. What do you have to think about?"
        ),
        reframe_wording=(
            "Put it another way: the work moves off the request. What changes about how it can "
            "fail, and what the user sees?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "the-response-no-longer-means-it-happened",
                "Once the work is deferred, a successful response only means the job was accepted "
                "-- so the user needs to be told that, and failures need somewhere to surface",
                "The semantics of the response change, and that's the part people skip.",
                (
                    "success now means we accepted it, not that it's done",
                    "the user needs to know it's queued rather than finished",
                    "if it fails later nobody is watching the request any more",
                    "you need somewhere for the failure to show up",
                ),
                "Think about what the user has actually been promised when the response returns.",
                ("moving work to a job is purely an implementation detail the user won't notice",),
            ),
            core(
                "jobs-run-at-least-once",
                "A worker can die after doing the work and before recording it, so the job will "
                "run again and must be safe to repeat",
                "Without this the change turns a slow email into two emails.",
                (
                    "it can run twice if the worker dies partway",
                    "so sending twice has to be prevented",
                    "make it safe to re-run",
                    "key it so a repeat is recognised",
                ),
                "Think about a worker that finishes the work and then crashes before saying so.",
                ("a job either runs completely or not at all",),
            ),
            core(
                "pass-an-id-not-the-object",
                "The job should carry a reference and re-read the current state, because the "
                "payload it was queued with may already be out of date",
                "Serialising the whole object bakes in a stale snapshot and a schema dependency.",
                (
                    "send the id and look it up in the worker",
                    "don't serialise the whole object into the message",
                    "the data may have changed by the time it runs",
                    "the message shape becomes a contract if you do",
                ),
                "Think about what might have changed between queueing the job and running it.",
            ),
            sup(
                "retries-need-limits-and-backoff",
                "Failures retry with increasing delay and a cap, then go somewhere a human can "
                "see them",
                "Infinite retries turn one bad job into a permanent load.",
                ("retry with backoff and give up eventually", "put it somewhere someone will look"),
            ),
            sup(
                "the-row-must-exist-before-the-job-runs",
                "The job must not be queued before the data it needs is committed, or the worker "
                "races an invisible row",
                "This is the ordering bug that looks like a flaky worker.",
                ("don't queue it before the transaction commits",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "The main change is that success now means we accepted it, not that it's done, so "
                "the user needs to know it's queued rather than finished, and if it fails later "
                "nobody is watching the request any more -- you need somewhere for the failure to "
                "show up. Then, it can run twice if the worker dies partway, so I'd key it so a "
                "repeat is recognised and sending twice is prevented. I'd send the id and look it "
                "up in the worker rather than serialising the whole object, because the data may "
                "have changed by the time it runs. Retries with backoff, give up eventually, and "
                "put it somewhere someone will look. And don't queue it before the transaction "
                "commits.",
                {
                    "the-response-no-longer-means-it-happened": "covered",
                    "jobs-run-at-least-once": "covered",
                    "pass-an-id-not-the-object": "covered",
                    "retries-need-limits-and-backoff": "covered",
                    "the-row-must-exist-before-the-job-runs": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "Moving work to a job is purely an implementation detail the user won't notice. "
                "I'd serialise the email object into the queue message so the worker has "
                "everything it needs, and retry forever until it succeeds.",
                {
                    "the-response-no-longer-means-it-happened": "contradicted",
                    "jobs-run-at-least-once": "missing",
                    "pass-an-id-not-the-object": "contradicted",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="background-jobs-and-queues",
        seniority=SENIOR,
        neutral_wording=(
            "One type of job has backed up badly and is now delaying every other kind of "
            "background work. How would you fix this, now and structurally?"
        ),
        reframe_wording=(
            "Another framing: one slow job type has taken the whole worker pool hostage. What do "
            "you do today, and what stops it recurring?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.SCENARIO,
        concepts=(
            core(
                "separate-queues-are-the-structural-fix",
                "Different work types need their own queues and capacity, so a backlog in one "
                "cannot consume the workers the others need",
                "This is the bulkhead, and it is the answer to 'stops it recurring'.",
                (
                    "put them on separate queues with their own workers",
                    "so one backlog can't starve the others",
                    "isolate them like bulkheads",
                    "the important work gets its own capacity",
                ),
                "Think about what a slow job type is currently taking away from the others.",
                ("adding more workers to the shared pool solves it properly",),
            ),
            core(
                "find-out-why-it-backed-up",
                "Scaling workers without knowing the cause can make things worse -- a job hammering "
                "a database or a rate-limited API gets slower with more concurrency",
                "This is where the reflexive fix actively backfires.",
                (
                    "work out whether it's volume or each job got slower",
                    "if it's hitting a rate limit, more workers makes it worse",
                    "check whether they're all fighting over the same lock",
                    "more concurrency isn't always more throughput",
                ),
                "Think about what happens when you double the workers on a job that queues behind "
                "a shared resource.",
            ),
            core(
                "shed-or-defer-rather-than-drown",
                "When the backlog can't be cleared, the right move is to prioritise or drop work "
                "deliberately rather than deliver everything very late",
                "Deciding what not to do is the part that requires judgement.",
                (
                    "decide what actually has to run and what can wait",
                    "a notification delivered six hours late is worse than not sent",
                    "drop or downgrade the low-value work on purpose",
                    "process the newest first if the old ones are worthless now",
                ),
                "Think about whether every item in that backlog is still worth doing.",
                ("every queued item must eventually be processed",),
            ),
            sup(
                "alert-on-depth-and-age",
                "Queue depth and the age of the oldest item are the signals that catch this "
                "before users do",
                "Latency alone won't show a backlog forming.",
                ("alert on how deep the queue is and how old the oldest item is",),
            ),
            sup(
                "make-poison-messages-visible",
                "A job that always fails will retry forever and consume capacity, so it needs a "
                "cap and a place to go",
                "One bad message can look exactly like a capacity problem.",
                ("a job that can never succeed will eat the workers", "cap the retries"),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "Structurally, put them on separate queues with their own workers so one backlog "
                "can't starve the others -- bulkheads. But before scaling anything I'd work out "
                "whether it's volume or each job got slower: if it's hitting a rate limit, more "
                "workers makes it worse, and more concurrency isn't always more throughput. For "
                "today, I'd decide what actually has to run and what can wait -- a notification "
                "delivered six hours late is worse than not sent, so I'd drop or downgrade the "
                "low-value work on purpose and process the newest first if the old ones are "
                "worthless now. Going forward I'd alert on how deep the queue is and how old the "
                "oldest item is, and cap the retries, because a job that can never succeed will "
                "eat the workers.",
                {
                    "separate-queues-are-the-structural-fix": "covered",
                    "find-out-why-it-backed-up": "covered",
                    "shed-or-defer-rather-than-drown": "covered",
                    "alert-on-depth-and-age": "covered",
                    "make-poison-messages-visible": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "Adding more workers to the shared pool solves it properly, so I'd scale the "
                "worker deployment up until the queue drains. Once it's caught up we can scale back "
                "down.",
                {
                    "separate-queues-are-the-structural-fix": "contradicted",
                    "find-out-why-it-backed-up": "missing",
                    "shed-or-defer-rather-than-drown": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # at-least-once-and-idempotent-consumers
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="at-least-once-and-idempotent-consumers",
        seniority=MID,
        neutral_wording=(
            "A colleague says the queue they've chosen guarantees exactly-once delivery, so the "
            "consumer doesn't need to handle duplicates. What's your view?"
        ),
        reframe_wording=(
            "Put it another way: is there a place a message can be delivered once and only once, "
            "end to end? Where does that promise break down?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "the-gap-between-doing-and-acknowledging",
                "The consumer does the work and then acknowledges it, and a crash in between "
                "means the message is redelivered -- no broker can close that gap for you",
                "This is the mechanism, and it makes the promise structurally impossible.",
                (
                    "you do the work then say you did it, and you can die in between",
                    "the broker has no idea whether your side effect happened",
                    "the ack and the work aren't in the same transaction",
                    "so it redelivers and the work happens twice",
                ),
                "Think about the moment after the work is done and before the broker has been told.",
                ("a queue can guarantee a message is processed exactly once",),
            ),
            core(
                "make-the-effect-idempotent-instead",
                "The workable version is at-least-once delivery with consumers whose repeat runs "
                "have no additional effect",
                "This is the achievable property that people mistake exactly-once for.",
                (
                    "assume it'll arrive twice and make the second one a no-op",
                    "record what you've processed and skip repeats",
                    "a unique constraint on the message id does it",
                    "make the operation naturally repeatable",
                ),
                "Think about making the second delivery harmless rather than preventing it.",
                ("deduplicating in a cache in front of the consumer is sufficient",),
            ),
            sup(
                "deduplicate-where-the-effect-lands",
                "The check has to live with the side effect, so it commits atomically with it -- "
                "a separate 'seen' cache can drift from reality",
                "Deduplication that isn't atomic with the effect is just a smaller race.",
                ("store the processed id in the same transaction as the write",),
            ),
            sup(
                "ordering-is-a-separate-promise",
                "Redelivery also means messages can arrive out of order, so ordering assumptions "
                "need their own handling",
                "People conflate the two guarantees.",
                ("they can also turn up out of order",),
            ),
            bonus(
                "vendors-mean-something-narrower",
                "Where exactly-once is claimed it usually means deduplication within one system "
                "over a window, not across your side effects",
                "Reading the claim precisely is the useful skill.",
                ("what they mean is dedupe inside their system for a while",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "I'd push back. You do the work then say you did it, and you can die in between -- "
                "the ack and the work aren't in the same transaction, and the broker has no idea "
                "whether your side effect happened, so it redelivers and the work happens twice. "
                "No broker can close that gap. What you can have is at-least-once plus idempotent "
                "consumers: assume it'll arrive twice and make the second one a no-op, record what "
                "you've processed and skip repeats -- a unique constraint on the message id does "
                "it. Crucially I'd store the processed id in the same transaction as the write. "
                "They can also turn up out of order, which is a separate problem. What vendors "
                "usually mean is dedupe inside their system for a while.",
                {
                    "the-gap-between-doing-and-acknowledging": "covered",
                    "make-the-effect-idempotent-instead": "covered",
                    "deduplicate-where-the-effect-lands": "covered",
                    "ordering-is-a-separate-promise": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "If the queue guarantees exactly-once then that's fine, a queue can guarantee a "
                "message is processed exactly once. I'd trust the documentation and keep the "
                "consumer simple.",
                {
                    "the-gap-between-doing-and-acknowledging": "contradicted",
                    "make-the-effect-idempotent-instead": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="at-least-once-and-idempotent-consumers",
        seniority=SENIOR,
        neutral_wording=(
            "You need to make an existing consumer idempotent. It writes to your database and "
            "also calls a third-party API that charges money. How do you approach it?"
        ),
        reframe_wording=(
            "Another framing: half the side effect is yours and half belongs to someone else. How "
            "do you make a redelivery safe across both?"
        ),
        expected_minutes=7,
        archetype=QuestionArchetype.EDGE,
        concepts=(
            core(
                "your-own-writes-are-the-easy-half",
                "Effects inside your database can be made idempotent with a uniqueness "
                "constraint committed alongside the write itself",
                "Establishing the easy half first isolates the genuinely hard one.",
                (
                    "put a unique key on it and commit it with the write",
                    "the second delivery hits the constraint and stops",
                    "one transaction covering both the effect and the marker",
                    "that half is straightforward",
                ),
                "Think about which parts of the side effect you fully control.",
                ("an external call can be rolled back with the transaction",),
            ),
            core(
                "the-external-call-needs-their-idempotency-key",
                "You can't roll back someone else's charge, so the duplicate has to be prevented "
                "on their side using the key they provide for exactly this",
                "This is the correct answer and it depends on a property of their API.",
                (
                    "send them an idempotency key derived from the message",
                    "so their side recognises the retry and doesn't charge twice",
                    "you can't undo a charge, so it must not happen twice",
                    "the key has to be stable across redeliveries",
                ),
                "Think about what stops the *other* system doing the work twice.",
                ("wrapping the external call in your transaction makes it atomic",),
            ),
            core(
                "order-the-steps-so-recovery-is-possible",
                "Record the intent before calling out and the outcome after, so a crash leaves a "
                "state you can reconcile rather than an unknown",
                "Ordering is what makes the ambiguous case recoverable.",
                (
                    "write down that you're about to call before you call",
                    "then you can check afterwards what actually happened",
                    "a crash leaves a record you can reconcile",
                    "query their api for the key to find out",
                ),
                "Think about what evidence you'd want to have written down if you crash mid-call.",
            ),
            sup(
                "what-if-they-have-no-such-key",
                "If the third party offers no idempotency mechanism, you need a reconciliation "
                "process and to accept the residual risk explicitly",
                "Naming an unavoidable risk beats pretending it's solved.",
                ("if they don't support it you need a reconciliation job and to say so out loud",),
            ),
            sup(
                "test-the-duplicate-path",
                "Deliver the same message twice on purpose in a test, because this is exactly the "
                "path production will take and nothing else exercises it",
                "The duplicate path is otherwise never run until it matters.",
                ("write a test that delivers the same message twice",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "The database side is straightforward: put a unique key on it and commit it with "
                "the write, one transaction covering both the effect and the marker, so the second "
                "delivery hits the constraint and stops. The charge is the real problem, because "
                "you can't undo a charge, so it must not happen twice -- I'd send them an "
                "idempotency key derived from the message, stable across redeliveries, so their "
                "side recognises the retry. I'd also write down that I'm about to call before I "
                "call, so a crash leaves a record I can reconcile and I can query their api for "
                "the key to find out what happened. If they don't support it you need a "
                "reconciliation job and to say so out loud. And I'd write a test that delivers the "
                "same message twice.",
                {
                    "your-own-writes-are-the-easy-half": "covered",
                    "the-external-call-needs-their-idempotency-key": "covered",
                    "order-the-steps-so-recovery-is-possible": "covered",
                    "what-if-they-have-no-such-key": "covered",
                    "test-the-duplicate-path": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd wrap the whole consumer in a database transaction, including the external "
                "call, so it's atomic -- if anything fails the whole thing rolls back and nothing "
                "happened. That handles duplicates too.",
                {
                    "your-own-writes-are-the-easy-half": "partial",
                    "the-external-call-needs-their-idempotency-key": "contradicted",
                    "order-the-steps-so-recovery-is-possible": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # outbox-pattern
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="outbox-pattern",
        seniority=MID,
        neutral_wording=(
            "You save a record and then publish an event about it. Sometimes the record exists "
            "with no event, and sometimes an event arrives for a record nobody can find. Why?"
        ),
        reframe_wording=(
            "Put it another way: two things have to happen together and they aren't. What are the "
            "two orderings, and what does each one break?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "two-systems-cannot-commit-together",
                "The database write and the message publish are separate operations, so any crash "
                "between them leaves one done and the other not",
                "Both symptoms come from this single fact, which is why reordering can't fix it.",
                (
                    "they're two different systems and you can't commit both at once",
                    "if it crashes in between you get one without the other",
                    "publish first and the record might never exist",
                    "save first and the event might never be sent",
                ),
                "Think about the instant between the two operations, and a crash landing there.",
                ("doing them in the right order removes the problem",),
            ),
            core(
                "write-the-event-as-a-row",
                "Store the event in the same database, in the same transaction as the record, so "
                "either both exist or neither does",
                "This is the mechanism, and it turns two systems back into one.",
                (
                    "save the event to a table in the same transaction",
                    "then either both are there or neither is",
                    "it's just another row in the same commit",
                    "you've turned two writes into one",
                ),
                "Think about making the fact 'this needs publishing' part of the same all-or-nothing "
                "unit.",
            ),
            core(
                "something-drains-it-afterwards",
                "A separate process reads unpublished rows and sends them, marking them done -- "
                "which means a message can be sent twice but never lost",
                "Completes the picture and names the guarantee you actually get.",
                (
                    "a separate process picks up the unsent rows and publishes them",
                    "it marks them as sent afterwards",
                    "it might send twice if it crashes after sending",
                    "so consumers have to tolerate duplicates",
                ),
                "Think about who reads that table, and what happens if it dies mid-send.",
                ("the relay guarantees each event is published exactly once",),
            ),
            sup(
                "failures-stay-visible",
                "An event that can't be published stays in the table where someone can see and "
                "replay it",
                "A lost message is a mystery; a stuck row is a bug report.",
                ("the failed ones sit there so you can look at them",),
            ),
            sup(
                "small-latency-cost",
                "The relay adds a short delay between commit and publish, which is usually "
                "irrelevant next to not losing events",
                "Naming the cost shows it's a trade, not a free lunch.",
                ("it's a bit slower to publish because something has to poll",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "They're two different systems and you can't commit both at once, so if it crashes "
                "in between you get one without the other -- publish first and the record might "
                "never exist, save first and the event might never be sent. The fix is to save the "
                "event to a table in the same transaction, so either both are there or neither is; "
                "it's just another row in the same commit. Then a separate process picks up the "
                "unsent rows and publishes them and marks them as sent. It might send twice if it "
                "crashes after sending, so consumers have to tolerate duplicates. The failed ones "
                "sit there so you can look at them. It's a bit slower to publish because something "
                "has to poll.",
                {
                    "two-systems-cannot-commit-together": "covered",
                    "write-the-event-as-a-row": "covered",
                    "something-drains-it-afterwards": "covered",
                    "failures-stay-visible": "covered",
                    "small-latency-cost": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "Doing them in the right order removes the problem -- save the record first and "
                "then publish. That way the record always exists by the time the event goes out, "
                "so consumers won't get an event for something missing.",
                {
                    "two-systems-cannot-commit-together": "contradicted",
                    "write-the-event-as-a-row": "missing",
                    "something-drains-it-afterwards": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="outbox-pattern",
        seniority=SENIOR,
        neutral_wording=(
            "You're running an outbox in production. What are the operational concerns, and how "
            "would you run more than one relay safely?"
        ),
        reframe_wording=(
            "Another framing: the pattern is in place and now you have to operate it. What breaks, "
            "and what do you watch?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.EDGE,
        concepts=(
            core(
                "concurrent-relays-need-claiming",
                "Two relays polling the same table will both pick up the same rows unless the "
                "claim locks them and skips anything already taken",
                "This is the specific mechanism that makes horizontal relays safe.",
                (
                    "lock the rows you select and skip the ones already locked",
                    "otherwise both relays send the same event",
                    "select for update skip locked",
                    "each relay takes a disjoint batch",
                ),
                "Think about two relays running the same query at the same moment.",
                ("running two relays is safe because consumers are idempotent anyway",),
            ),
            core(
                "the-table-must-not-grow-forever",
                "Published rows accumulate and will eventually dominate the table, so there needs "
                "to be a retention or archival step",
                "An unbounded table becomes the next incident.",
                (
                    "delete or archive the published ones",
                    "otherwise the table grows without limit",
                    "the polling query gets slower as it fills up",
                    "keep them for a while for debugging, then clear them",
                ),
                "Think about what that table looks like after a year of traffic.",
                ("keeping every event forever is free and useful",),
            ),
            core(
                "watch-lag-not-just-errors",
                "The signal that matters is the age of the oldest unpublished row, because a "
                "stalled relay produces no errors at all",
                "A silent stall is the failure mode this pattern actually has.",
                (
                    "alert on how old the oldest unsent row is",
                    "a stopped relay throws no errors, it just stops",
                    "queue depth alone doesn't tell you it's stuck",
                    "measure the delay from commit to publish",
                ),
                "Think about what your monitoring would show if the relay simply stopped running.",
            ),
            sup(
                "poison-events-need-a-cap",
                "An event that always fails to publish will be retried forever, so attempts are "
                "counted and it eventually parks rather than blocking",
                "One bad row shouldn't hold up the queue.",
                ("count the attempts and park it after a few", "don't let one bad row block the rest"),
            ),
            sup(
                "keep-the-correlation-id",
                "Carrying the originating request id through the event makes the whole chain "
                "traceable from API to worker",
                "This is what makes debugging the async path possible at all.",
                ("carry the request id through so you can trace it end to end",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "For multiple relays, lock the rows you select and skip the ones already locked -- "
                "select for update skip locked -- so each relay takes a disjoint batch; otherwise "
                "both relays send the same event. Operationally, delete or archive the published "
                "ones, because otherwise the table grows without limit and the polling query gets "
                "slower as it fills up. The key signal is to alert on how old the oldest unsent "
                "row is: a stopped relay throws no errors, it just stops, so queue depth alone "
                "doesn't tell you it's stuck. I'd count the attempts and park a bad event after a "
                "few so it doesn't block the rest, and carry the request id through so you can "
                "trace it end to end.",
                {
                    "concurrent-relays-need-claiming": "covered",
                    "the-table-must-not-grow-forever": "covered",
                    "watch-lag-not-just-errors": "covered",
                    "poison-events-need-a-cap": "covered",
                    "keep-the-correlation-id": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "Running two relays is safe because consumers are idempotent anyway, so duplicates "
                "don't matter. I'd monitor the error rate on the publish calls and alert if it goes "
                "up.",
                {
                    "concurrent-relays-need-claiming": "contradicted",
                    "the-table-must-not-grow-forever": "missing",
                    "watch-lag-not-just-errors": "contradicted",
                },
            ),
        ),
    ),
)
