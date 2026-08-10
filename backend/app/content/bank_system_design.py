"""Authored question bank -- domain: system-design.

Same bar as the other two banks (``app/content/types.py``): >= 2 core concepts,
>= 3 acceptable signals per core concept, >= 2 misconceptions overall, a
``why_it_matters`` on every concept, an L2 signpost on every core concept, and
a strong + weak golden answer.

**Why this domain, and why now.** Question count is bounded by how many
competencies the JD names *and* the bank has rubrics for -- so a 45-minute
session was returning three questions not because the budget was small but
because only two domains were authored. Reliability and scaling topics appear
in nearly every backend job description, so authoring them raises the ceiling
for exactly the sessions that were running short.

The signal discipline is the same and matters more here, because this domain
has the densest jargon in the industry. **Nobody has to say "backpressure",
"idempotent" or "quorum".** "Tell the fast one to slow down" is full credit.
"""

from __future__ import annotations

from app.content.types import GoldenSpec, QuestionSpec, bonus, core, sup
from app.domain.enums import QuestionArchetype, Seniority

MID, SENIOR = Seniority.MID, Seniority.SENIOR


QUESTIONS: tuple[QuestionSpec, ...] = (
    # ══════════════════════════════════════════════════════════════════════
    # timeouts-retries-jitter
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="timeouts-retries-jitter",
        seniority=MID,
        neutral_wording=(
            "A service you call starts responding slowly, and soon your own service falls over "
            "too. What would you put in place so that a slow dependency doesn't take you down?"
        ),
        reframe_wording=(
            "Put another way: the thing you depend on is up, just slow. Why does that take your "
            "service down as well, and what would you change?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "unbounded-wait-consumes-capacity",
                "Every request waiting on a slow dependency is holding one of your own workers, "
                "so without a deadline the slow service quietly consumes all your capacity",
                "This is why a slow dependency is more dangerous than a dead one.",
                (
                    "each waiting request is still holding a connection",
                    "you run out of workers because they're all stuck waiting",
                    "nothing is free while it's waiting, it's occupying a slot",
                    "the requests pile up behind the slow one",
                ),
                "Think about what each of your own threads is doing while it waits for a reply.",
                (
                    "a slow dependency only makes you slow, not down",
                    "the default timeout is fine",
                ),
            ),
            core(
                "deadline-must-be-set-explicitly",
                "You put an explicit limit on how long you will wait, and give up when it passes, "
                "so a stuck call fails fast instead of hanging forever",
                "Most defaults are effectively infinite, so this has to be a decision.",
                (
                    "set a limit on how long you'll wait",
                    "give up after a few seconds instead of hanging",
                    "fail fast rather than waiting forever",
                    "decide up front how long is too long",
                ),
                "Think about what happens by default if the other side simply never replies.",
            ),
            core(
                "retries-amplify-load",
                "Retrying a struggling service sends it more traffic than before, so retries have "
                "to be limited and spaced out rather than immediate",
                "This is the part that turns a blip into an outage, and it is usually well meant.",
                (
                    "if you retry straight away you're just hitting it harder",
                    "everyone retrying at once makes it worse",
                    "you should wait longer between each attempt",
                    "cap how many times you try before giving up",
                ),
                "Think about what a struggling service experiences when every client retries at once.",
                ("retrying always improves reliability",),
            ),
            sup(
                "spread-the-retries-out",
                "Adding a random amount to each wait stops every client retrying at the same "
                "instant and hammering the service in waves",
                "Separates knowing about retries from knowing why they synchronise.",
                (
                    "add a bit of randomness so they don't all fire together",
                    "otherwise everyone comes back at exactly the same moment",
                ),
            ),
            sup(
                "only-retry-what-is-safe",
                "Retrying is only safe when repeating the call cannot cause the work to happen "
                "twice",
                "Connects reliability to correctness, which is where retries usually go wrong.",
                (
                    "you can't just retry a payment",
                    "repeating a read is fine, repeating a write might not be",
                ),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "The problem is that every request waiting on the slow service is still holding "
                "one of my own workers, so they all get stuck waiting and I run out of capacity "
                "even though nothing has actually crashed. So the first thing is a deadline: "
                "decide up front how long is too long and give up after that instead of hanging. "
                "The second thing is being careful with retries, because if you retry straight "
                "away you're just hitting a struggling service harder, so I'd cap the number of "
                "attempts and wait longer between each one, with a bit of randomness so every "
                "client doesn't come back at exactly the same moment. And I'd only retry calls "
                "where doing it twice is harmless.",
                {
                    "unbounded-wait-consumes-capacity": "covered",
                    "deadline-must-be-set-explicitly": "covered",
                    "retries-amplify-load": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd add retries so that if it fails we try again, and probably a timeout.",
                {
                    "unbounded-wait-consumes-capacity": "missing",
                    "deadline-must-be-set-explicitly": "partial",
                    "retries-amplify-load": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="timeouts-retries-jitter",
        seniority=SENIOR,
        neutral_wording=(
            "Your service calls three others to answer one request, and each of them retries "
            "internally. Occasionally a small slowdown somewhere turns into a site-wide outage. "
            "Walk me through why, and what you'd change."
        ),
        reframe_wording=(
            "Same question from the other end: what property does a chain of services need so "
            "that one slow hop stays one slow hop?"
        ),
        expected_minutes=6,
        concepts=(
            core(
                "retry-amplification-multiplies-down-the-chain",
                "When every layer retries independently the attempts multiply, so three layers "
                "retrying three times each turns one user request into dozens at the bottom",
                "This is the mechanism behind most retry-induced outages, and it is invisible per layer.",
                (
                    "each layer retrying multiplies the one below it",
                    "three times three times three, not three",
                    "the bottom service sees way more traffic than the user sent",
                    "everyone is retrying everyone else's retries",
                ),
                "Think about how many calls actually reach the bottom service when every layer tries three times.",
                ("retries at each layer are independent and additive",),
            ),
            core(
                "budget-must-shrink-down-the-chain",
                "The time limit has to be passed down and reduced at each hop, so an inner call "
                "cannot still be waiting after the outer caller has already given up",
                "Without this, work continues on requests nobody is waiting for any more.",
                (
                    "pass the remaining time down with the call",
                    "the inner timeout has to be shorter than the outer one",
                    "otherwise you're still working on something the caller abandoned",
                    "each hop gets less time than the one above it",
                ),
                "Think about what the innermost service is doing thirty seconds after the user's browser gave up.",
            ),
            core(
                "shed-load-rather-than-queue-it",
                "Past a certain point the right answer is to reject work quickly rather than "
                "accept it into a queue that only grows",
                "Senior instinct: a fast failure is a better product than an unbounded wait.",
                (
                    "start rejecting instead of queueing",
                    "say no quickly rather than accepting work you can't do",
                    "a growing queue just means everyone waits and then times out anyway",
                    "return an error fast so the caller can do something else",
                ),
                "Think about what a queue that grows faster than it drains eventually does to every request in it.",
                ("a bigger queue absorbs the spike",),
            ),
            sup(
                "retry-at-one-layer-only",
                "Deciding which single layer owns retrying keeps the multiplication from starting "
                "at all",
                "Shows the fix is architectural, not a tuning exercise.",
                (
                    "pick one place to do the retrying",
                    "the layers below shouldn't retry as well",
                ),
            ),
            bonus(
                "adaptive-retry-budget",
                "Capping retries as a fraction of overall traffic keeps them helpful when things "
                "are healthy and harmless when they are not",
                "The mature version of the fix, and rarely reached unprompted.",
                (
                    "only allow retries to be a small percentage of total calls",
                    "turn retrying off when the error rate is already high",
                ),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "The killer is that each layer retrying multiplies the one below it, so three "
                "layers trying three times each means the bottom service sees far more traffic "
                "than the user actually sent, and that arrives exactly when it is already "
                "struggling. Two changes. First, pass the remaining time budget down with each "
                "call and shrink it at every hop, so an inner service isn't still working on "
                "something the browser abandoned twenty seconds ago. Second, pick one layer that "
                "owns retrying and stop the others doing it. Past a certain load I'd also start "
                "rejecting quickly rather than queueing, because a queue growing faster than it "
                "drains just means everyone waits and then times out anyway.",
                {
                    "retry-amplification-multiplies-down-the-chain": "covered",
                    "budget-must-shrink-down-the-chain": "covered",
                    "shed-load-rather-than-queue-it": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd tune the timeouts and make sure we have retries with backoff everywhere.",
                {
                    "retry-amplification-multiplies-down-the-chain": "missing",
                    "budget-must-shrink-down-the-chain": "missing",
                    "shed-load-rather-than-queue-it": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # circuit-breakers
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="circuit-breakers",
        seniority=MID,
        neutral_wording=(
            "One of your dependencies is completely down and every call to it fails after a long "
            "wait. Retrying isn't helping. What would you do differently?"
        ),
        reframe_wording=(
            "Put differently: you already know the next call will fail. Why send it, and what "
            "would you do instead?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "stop-calling-what-is-known-broken",
                "After enough consecutive failures you stop sending calls at all for a while, "
                "because you already know the answer and the attempt costs you time and capacity",
                "This is the whole idea: the cheapest call is the one you don't make.",
                (
                    "stop trying for a bit once you know it's down",
                    "don't send a request you're confident will fail",
                    "trip a switch and fail immediately instead of waiting",
                    "after enough failures in a row, just stop",
                ),
                "Think about what you gain by not making a call you already know the outcome of.",
                ("keep retrying until it comes back",),
            ),
            core(
                "fail-fast-protects-the-caller",
                "While it is stopped you return an error straight away, which keeps your own "
                "workers free instead of parked on a call that will time out",
                "The protection is for *you*, which is the part people miss.",
                (
                    "you return an error immediately instead of waiting",
                    "your own threads stay free",
                    "it protects us, not just them",
                    "the user gets a fast no instead of a slow no",
                ),
                "Think about who is actually being protected while the switch is open.",
            ),
            core(
                "let-one-call-through-to-test",
                "After a cooldown you let a single call through to see whether it recovered, "
                "rather than resuming full traffic and knocking it over again",
                "Without this it either never recovers or recovers into a stampede.",
                (
                    "after a while let one through and see",
                    "test the water with a single request",
                    "if that one works, go back to normal",
                    "don't send everything at once the moment it comes back",
                ),
                "Think about how you find out it recovered without sending all your traffic to check.",
                ("resume all traffic as soon as the cooldown ends",),
            ),
            sup(
                "have-a-fallback-answer",
                "Deciding what to return while the switch is open -- cached data, a partial "
                "response, a clear error -- is part of the design",
                "Turns a reliability mechanism into a product decision.",
                (
                    "serve something stale rather than nothing",
                    "degrade the feature instead of failing the whole page",
                ),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "Once it has failed enough times in a row I'd stop sending requests at all for a "
                "while, because I already know what the answer will be and every attempt is "
                "costing me a worker parked on a call that will time out. So during that period "
                "I return an error immediately, which keeps my own threads free -- the point is "
                "really protecting us rather than them. Then after a cooldown I'd let one request "
                "through to test the water, and only go back to normal traffic if it succeeds, "
                "because sending everything the moment it comes back would just knock it over "
                "again. Where we can, I'd serve something stale instead of nothing.",
                {
                    "stop-calling-what-is-known-broken": "covered",
                    "fail-fast-protects-the-caller": "covered",
                    "let-one-call-through-to-test": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd add a circuit breaker library and configure the thresholds.",
                {
                    "stop-calling-what-is-known-broken": "partial",
                    "fail-fast-protects-the-caller": "missing",
                    "let-one-call-through-to-test": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="circuit-breakers",
        seniority=SENIOR,
        neutral_wording=(
            "You add the stop-calling-when-it's-failing pattern to a service, and during the next "
            "incident it makes things worse rather than better. What are the ways that can happen?"
        ),
        reframe_wording=(
            "Same question inverted: what does this pattern assume about failures, and what "
            "happens when those assumptions don't hold?"
        ),
        expected_minutes=6,
        concepts=(
            core(
                "wrong-scope-fails-healthy-traffic",
                "If the counter covers everything rather than one dependency or one shard, a "
                "problem with a small slice of traffic cuts off calls that were working fine",
                "Scope is the single most common way this pattern backfires.",
                (
                    "one bad endpoint trips it for everything",
                    "you need a separate one per dependency",
                    "traffic that was fine gets blocked too",
                    "it shouldn't be one big switch for the whole service",
                ),
                "Think about what else stops working when the switch covers more than the broken thing.",
                ("one breaker for the whole service is simpler and fine",),
            ),
            core(
                "synchronised-recovery-restampedes",
                "If every instance opens and closes on the same schedule, they all resume together "
                "and the recovering service is hit by the full load at once",
                "The recovery path is where this pattern most often causes the second outage.",
                (
                    "everyone comes back at the same moment",
                    "it gets slammed the instant it recovers",
                    "you need to ramp traffic back up gradually",
                    "all the instances unblock together",
                ),
                "Think about what the recovering service sees at the exact moment the cooldown ends everywhere.",
            ),
            core(
                "thresholds-need-rate-not-count",
                "Counting raw failures behaves differently at different traffic levels, so the "
                "trigger should be a proportion of requests over a window with a minimum volume",
                "This is why a breaker tuned in staging misbehaves in production.",
                (
                    "use a percentage rather than a raw count",
                    "five failures means nothing if you're doing ten thousand requests",
                    "you need a minimum number of samples before deciding",
                    "it should be failures out of total, over a time window",
                ),
                "Think about what five failures means at ten requests a minute versus ten thousand.",
                ("a fixed failure count works at any scale",),
            ),
            sup(
                "distinguish-failure-kinds",
                "A slow response, a refused connection and a validation error are different "
                "signals, and treating a client error as a dependency failure trips the switch "
                "on your own bug",
                "Shows they thought about what actually counts as a failure.",
                (
                    "a 400 is our fault, it shouldn't count",
                    "timeouts and refusals mean different things",
                ),
            ),
            bonus(
                "observability-of-the-breaker",
                "The state has to be visible, because an open switch looks identical to an outage "
                "from the outside",
                "Senior operational instinct.",
                (
                    "you need to see when it's open or you'll debug the wrong thing",
                    "alert on it changing state",
                ),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "The most common one is scope: if it's one big switch for the whole service then "
                "one bad endpoint trips it for everything, and traffic that was perfectly fine "
                "gets blocked too, so it needs to be per dependency at least. The second is "
                "recovery -- if every instance uses the same cooldown they all unblock at the "
                "same moment and the recovering service gets slammed, so you want to ramp back "
                "up rather than resume everything at once. The third is the threshold itself: "
                "five failures means nothing at ten thousand requests a minute, so it should be "
                "a proportion over a window with a minimum sample size. And I'd be careful that "
                "client errors don't count, or our own bad request trips it.",
                {
                    "wrong-scope-fails-healthy-traffic": "covered",
                    "synchronised-recovery-restampedes": "covered",
                    "thresholds-need-rate-not-count": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "If the thresholds are set too low it will open when it shouldn't.",
                {
                    "wrong-scope-fails-healthy-traffic": "missing",
                    "synchronised-recovery-restampedes": "missing",
                    "thresholds-need-rate-not-count": "partial",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # replication-and-read-replicas
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="replication-and-read-replicas",
        seniority=MID,
        neutral_wording=(
            "Reads are overwhelming your database, so someone suggests adding copies to read "
            "from. What does that fix, and what new problem does it introduce?"
        ),
        reframe_wording=(
            "Same setup: a user saves a change, then immediately reloads the page and their "
            "change isn't there. How did adding read copies cause that?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "copies-spread-read-load-only",
                "Extra copies take read traffic off the main database, but every write still has "
                "to go to one place, so writes are not helped at all",
                "Names exactly what the technique buys, which bounds when to reach for it.",
                (
                    "reads go to the copies, writes still go to the one",
                    "it only helps if the problem is reads",
                    "you haven't made writing any faster",
                    "the main one still handles every change",
                ),
                "Think about which half of the traffic actually moved off the original.",
                ("read copies increase write capacity too",),
            ),
            core(
                "copies-lag-behind",
                "A copy is updated slightly after the original, so a read from it can return data "
                "that is a moment out of date",
                "This is the cost, and it shows up as a user-visible bug rather than an error.",
                (
                    "the copy is always a little behind",
                    "you might read something before the change arrives",
                    "it catches up, but not instantly",
                    "there's a delay between writing and it showing up over there",
                ),
                "Think about the gap in time between the write landing and the copy hearing about it.",
            ),
            core(
                "read-your-own-writes",
                "The visible symptom is a user not seeing their own change, so the fix is to send "
                "that user's reads to the main database for a short window after they write",
                "Turns an abstract consistency point into the concrete thing you must handle.",
                (
                    "send them to the main one right after they save",
                    "the person who made the change should read from the original",
                    "stick them to the primary for a few seconds",
                    "otherwise they refresh and their edit is gone",
                ),
                "Think about which specific user notices the delay, and where their next read should go.",
                ("lag is fine because it's only milliseconds",),
            ),
            sup(
                "tolerance-varies-by-read",
                "Some reads can happily be stale and some cannot, so the routing decision belongs "
                "per query rather than globally",
                "Shows judgement rather than a blanket rule.",
                (
                    "a dashboard can be a bit behind, a checkout can't",
                    "decide per query how fresh it needs to be",
                ),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "It fixes read load: reads go to the copies while writes still all go to the one "
                "main database, so it only helps if reads are actually the bottleneck -- you "
                "haven't made writing any faster. The new problem is that a copy is always a "
                "little behind, so you can read something before the change has arrived there. "
                "The way that shows up is a user saving something, reloading, and their edit "
                "appears to be gone. So right after someone writes I'd send that user's reads to "
                "the main database for a short window. Beyond that it depends on the query -- a "
                "dashboard can be a bit behind, a checkout can't.",
                {
                    "copies-spread-read-load-only": "covered",
                    "copies-lag-behind": "covered",
                    "read-your-own-writes": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "It scales the database horizontally so you can handle more traffic.",
                {
                    "copies-spread-read-load-only": "partial",
                    "copies-lag-behind": "missing",
                    "read-your-own-writes": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="replication-and-read-replicas",
        seniority=SENIOR,
        neutral_wording=(
            "Your main database fails and a copy is promoted to take over. What can you lose in "
            "that switch, and what would you have decided in advance to control it?"
        ),
        reframe_wording=(
            "Same event, framed as a trade: what do you give up to make the failover fast, and "
            "what do you give up to make it lossless?"
        ),
        expected_minutes=6,
        concepts=(
            core(
                "unreplicated-writes-are-lost",
                "Anything written to the original but not yet copied across is gone when a copy "
                "is promoted, and those writes were already acknowledged to users",
                "This is the actual data-loss window, and it is invisible until it happens.",
                (
                    "whatever hadn't been copied yet is lost",
                    "we told the user it saved and then it wasn't there",
                    "the gap between writing and copying is what you lose",
                    "the promoted copy simply never heard about those",
                ),
                "Think about the writes that were in flight at the exact moment the original died.",
            ),
            core(
                "waiting-for-copies-trades-latency-for-safety",
                "You can make writes wait until a copy confirms them, which removes the loss but "
                "makes every write slower and couples you to the copy's availability",
                "This is the decision, stated as a trade rather than a best practice.",
                (
                    "you can make it wait until the copy confirms",
                    "that makes every write slower",
                    "if the copy is down, writes stop too",
                    "you're choosing between losing data and being slower",
                ),
                "Think about what has to happen before you tell the user their write succeeded.",
                ("synchronous copying is strictly better",),
            ),
            core(
                "two-primaries-is-the-worse-failure",
                "If the original is only unreachable rather than dead, promoting a copy can leave "
                "two databases both accepting writes, which is harder to recover from than the "
                "outage was",
                "Senior instinct: the dangerous failure is the ambiguous one.",
                (
                    "you can end up with two of them both taking writes",
                    "it might not be dead, just unreachable",
                    "then you have to merge two divergent histories",
                    "you need something that guarantees the old one stops",
                ),
                "Think about what happens if the original was healthy the whole time and only the network broke.",
                ("promoting a replica is always safe if the primary stops responding",),
            ),
            sup(
                "failover-must-be-rehearsed",
                "A failover path that has never been executed is a plan, not a capability",
                "Distinguishes people who have done this from people who have read about it.",
                (
                    "practise it before you need it",
                    "you find out what's broken by doing it deliberately",
                ),
            ),
            bonus(
                "clients-must-follow-the-promotion",
                "Everything that holds a connection has to learn about the new primary, or it "
                "keeps talking to a database that is no longer in charge",
                "The step that turns a successful failover into a still-broken application.",
                (
                    "the apps need to reconnect to the new one",
                    "connection pools keep pointing at the old address",
                ),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "You lose whatever had been written but not yet copied across -- and those are "
                "writes we already told users had succeeded, which is the worst kind. The lever "
                "is whether writes wait for a copy to confirm before we acknowledge them: that "
                "removes the loss but makes every write slower and means writes stop if the copy "
                "is down, so it's a straight trade rather than a best practice. The failure I'd "
                "worry about more is the ambiguous one, where the original isn't dead but "
                "unreachable, and you end up with two databases both accepting writes and two "
                "histories to merge. So you need something that guarantees the old one is really "
                "stopped, and you need to have rehearsed the whole thing.",
                {
                    "unreplicated-writes-are-lost": "covered",
                    "waiting-for-copies-trades-latency-for-safety": "covered",
                    "two-primaries-is-the-worse-failure": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "The replica gets promoted automatically so there's failover and we stay up.",
                {
                    "unreplicated-writes-are-lost": "missing",
                    "waiting-for-copies-trades-latency-for-safety": "missing",
                    "two-primaries-is-the-worse-failure": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # partitioning-and-sharding
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="partitioning-and-sharding",
        seniority=MID,
        neutral_wording=(
            "One table has grown far too big for a single machine. You decide to split it across "
            "several. How do you decide what to split it on, and what gets harder afterwards?"
        ),
        reframe_wording=(
            "Same situation: the data now lives on four machines instead of one. What does a "
            "query have to do differently, and when does that hurt?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "the-split-key-decides-everything",
                "The column you split on determines which machine any given row lives on, so it "
                "has to be something your common queries already know",
                "Everything else about the design follows from this one choice.",
                (
                    "you pick something the queries already filter by",
                    "it decides which machine the row is on",
                    "if you don't know it you can't find the row",
                    "choose it so a normal lookup only touches one machine",
                ),
                "Think about how a query works out which machine to even ask.",
                ("you can change the split key later without a migration",),
            ),
            core(
                "queries-without-the-key-hit-everything",
                "Any query that doesn't include the split key has to ask every machine and combine "
                "the results, which is slower than the single machine was",
                "This is the cost, and it is why the key choice is not reversible in practice.",
                (
                    "you have to ask all of them and merge the answers",
                    "it fans out to every machine",
                    "that's slower than it was before you split",
                    "you can't tell which one has it so you check them all",
                ),
                "Think about a search that filters on something other than what you split by.",
            ),
            core(
                "uneven-split-recreates-the-problem",
                "If the values are not evenly spread, one machine ends up with most of the data "
                "or most of the traffic and you are back where you started",
                "The failure mode that makes a technically correct split useless.",
                (
                    "one machine ends up with most of it",
                    "if one customer is huge they swamp their shard",
                    "the load has to spread evenly or there's no point",
                    "a popular value makes one machine hot",
                ),
                "Think about what happens when one customer is a hundred times bigger than the rest.",
                ("splitting always spreads load evenly",),
            ),
            sup(
                "cross-machine-joins-and-transactions",
                "Joins and all-or-nothing updates across machines stop being simple, so the design "
                "tries to keep related rows together",
                "Shows awareness of what the database stops doing for you.",
                (
                    "you can't easily join across them any more",
                    "keep the related rows on the same machine",
                ),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "The choice of column is the whole design, because it decides which machine a row "
                "lives on -- so it has to be something the common queries already filter by, "
                "otherwise you can't tell which machine to ask. What gets harder is any query "
                "that doesn't include that column: it has to fan out to every machine and merge "
                "the results, which is slower than the single machine was. The other thing I'd "
                "check is whether the values spread evenly, because if one customer is a hundred "
                "times bigger than everyone else, that machine ends up with most of the data and "
                "you're back where you started. And joins across machines stop being simple, so "
                "I'd try to keep related rows together.",
                {
                    "the-split-key-decides-everything": "covered",
                    "queries-without-the-key-hit-everything": "covered",
                    "uneven-split-recreates-the-problem": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd shard it by id using a hash so the data is distributed across the nodes.",
                {
                    "the-split-key-decides-everything": "partial",
                    "queries-without-the-key-hit-everything": "missing",
                    "uneven-split-recreates-the-problem": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="partitioning-and-sharding",
        seniority=SENIOR,
        neutral_wording=(
            "You already split your data across eight machines and now you need sixteen. How do "
            "you get there without an outage, and what did the original design need to have "
            "anticipated?"
        ),
        reframe_wording=(
            "Same problem stated as a property: what makes adding capacity cheap, and what makes "
            "it a rewrite?"
        ),
        expected_minutes=7,
        concepts=(
            core(
                "naive-mapping-moves-everything",
                "If the machine is chosen by dividing by the number of machines, changing that "
                "number reassigns nearly every row at once",
                "This is why the growth path has to be designed before the first split.",
                (
                    "changing the count moves almost all the data",
                    "everything gets a different machine at the same time",
                    "you can't add one without reshuffling the lot",
                    "the mapping depends on how many there are",
                ),
                "Think about how many rows change machine when the divisor goes from eight to nine.",
                ("adding a shard only moves a fraction of the data",),
            ),
            core(
                "indirection-lets-you-move-a-slice",
                "Splitting into many more logical buckets than machines, and keeping a lookup of "
                "bucket to machine, means growing is moving some buckets rather than remapping "
                "every row",
                "The actual technique, expressed as a mechanism rather than a name.",
                (
                    "have far more buckets than machines and move buckets around",
                    "keep a table of which bucket is where",
                    "then adding a machine just moves a few buckets",
                    "the row's bucket never changes, only where the bucket lives",
                ),
                "Think about adding a layer between the row and the machine, so one can move without the other.",
            ),
            core(
                "migration-must-be-online-and-reversible",
                "The move happens while traffic is live, so you copy, then read from both and "
                "compare, then switch, keeping the ability to go back at each step",
                "Distinguishes people who have done a live migration from people who have planned one.",
                (
                    "copy it across while still serving from the old place",
                    "run both and check they agree before switching",
                    "cut over gradually, not all at once",
                    "make sure you can roll back at each step",
                ),
                "Think about what you would need in place to abandon the move halfway through.",
                ("take a maintenance window and copy everything",),
            ),
            sup(
                "routing-must-be-a-lookup-not-a-formula",
                "Clients ask where a bucket lives rather than computing it, so the answer can "
                "change without redeploying every client",
                "Shows the operational consequence of the design choice.",
                (
                    "the app looks up where it is rather than calculating",
                    "otherwise every client needs redeploying to move data",
                ),
            ),
            bonus(
                "isolate-the-outlier",
                "A single tenant large enough to swamp a machine gets its own, rather than "
                "distorting the whole scheme",
                "The pragmatic escape hatch that keeps the general design simple.",
                (
                    "give the huge customer their own machine",
                    "don't design the whole scheme around one outlier",
                ),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "If the machine is chosen by dividing by how many there are, going from eight to "
                "sixteen reassigns nearly every row at once, which is why the growth path has to "
                "be in the original design. What I'd want is far more logical buckets than "
                "machines, with a lookup table saying which bucket lives where -- then a row's "
                "bucket never changes and growing means moving some buckets, not remapping "
                "everything. The clients have to consult that lookup rather than calculating, or "
                "moving data means redeploying every client. The move itself is online: copy "
                "while still serving from the old place, read from both and compare, then cut "
                "over gradually with a way back at every step.",
                {
                    "naive-mapping-moves-everything": "covered",
                    "indirection-lets-you-move-a-slice": "covered",
                    "migration-must-be-online-and-reversible": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "We'd rebalance the cluster and let it redistribute the data to the new nodes.",
                {
                    "naive-mapping-moves-everything": "missing",
                    "indirection-lets-you-move-a-slice": "missing",
                    "migration-must-be-online-and-reversible": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # statelessness-and-session-affinity
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="statelessness-and-session-affinity",
        seniority=MID,
        neutral_wording=(
            "Your app works on one server. You add a second behind a load balancer and users "
            "start getting logged out at random. What's going on, and how would you fix it?"
        ),
        reframe_wording=(
            "Same symptom, different angle: why would the same request succeed or fail depending "
            "on which machine answered it?"
        ),
        expected_minutes=4,
        archetype=QuestionArchetype.SCENARIO,
        concepts=(
            core(
                "per-machine-memory-is-not-shared",
                "The session was held in one server's memory, so when the load balancer sends the "
                "next request to the other server, that server has never heard of the user",
                "This is the mechanism, and it generalises to every kind of in-process state.",
                (
                    "the session only exists on the machine that made it",
                    "the other server has no idea who they are",
                    "it's in memory, and that memory isn't shared",
                    "each request might land somewhere different",
                ),
                "Think about where the login was actually stored, and who else can see it.",
                ("the load balancer should copy memory between servers",),
            ),
            core(
                "move-the-state-out-or-carry-it",
                "The fix is to keep the session somewhere both servers can reach, or to carry it "
                "with the request so no server has to remember anything",
                "Names both real options rather than just the one they happen to know.",
                (
                    "put the session in a shared store both can read",
                    "or give the client something it sends every time",
                    "keep it in a database or cache instead of memory",
                    "then it doesn't matter which server answers",
                ),
                "Think about what would make it not matter which machine got the request.",
                (
                    "storing sessions in a file on the server fixes it",
                    "a bigger server would avoid the problem",
                ),
            ),
            sup(
                "affinity-works-but-costs-you",
                "Pinning a user to one server also fixes it, at the price of uneven load and "
                "everyone on that server losing their session when it restarts",
                "Shows they can evaluate the tempting shortcut rather than just reject it.",
                (
                    "you can pin them to the same server",
                    "but then a deploy logs those users out",
                    "and the load stops spreading evenly",
                ),
            ),
            sup(
                "generalises-beyond-sessions",
                "Anything else kept in one process -- uploaded files, in-memory caches, scheduled "
                "jobs -- has the same problem",
                "Separates fixing this bug from understanding the class.",
                (
                    "same thing happens with uploaded files on local disk",
                    "in-memory caches drift apart between servers",
                ),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "The session was kept in the first server's memory, so when the load balancer "
                "sends the next request to the second one, that server has never heard of the "
                "user and treats them as logged out. The fix is to stop keeping it in one "
                "process: either put the session somewhere both servers can read, like a shared "
                "cache, or give the client something it sends with every request so no server "
                "needs to remember anything. You can also pin each user to one server, but then "
                "a deploy logs all of them out and the load stops spreading evenly. The same "
                "problem applies to anything else held locally, like uploaded files on disk.",
                {
                    "per-machine-memory-is-not-shared": "covered",
                    "move-the-state-out-or-carry-it": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd turn on sticky sessions in the load balancer so it keeps working.",
                {
                    "per-machine-memory-is-not-shared": "missing",
                    "move-the-state-out-or-carry-it": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="statelessness-and-session-affinity",
        seniority=SENIOR,
        neutral_wording=(
            "A team argues that carrying all session data with the request is strictly better "
            "than keeping it server-side. Where does that argument break down?"
        ),
        reframe_wording=(
            "Same debate, concrete version: a user is banned at 10:00. When do they actually stop "
            "having access, under each approach?"
        ),
        expected_minutes=6,
        concepts=(
            core(
                "self-contained-tokens-cannot-be-withdrawn",
                "If everything needed is inside the token, nothing needs to be looked up -- which "
                "also means nothing can be checked, so revoking access does not take effect until "
                "it expires",
                "The trade is the whole answer, and it is a security property, not a performance one.",
                (
                    "you can't take it back once you've issued it",
                    "they stay logged in until it runs out",
                    "there's nothing to check against, that's the point of it",
                    "banning someone doesn't kick them out immediately",
                ),
                "Think about what you would have to look up to deny a request, and what happens when you look nothing up.",
                ("you can revoke a self-contained token by deleting it",),
            ),
            core(
                "short-life-plus-renewal-recovers-control",
                "Making the token short-lived and renewing it against something checkable puts the "
                "revocation point back, at the cost of a lookup on renewal rather than every call",
                "This is the actual resolution, and it is a middle position rather than a side.",
                (
                    "keep it short-lived and refresh it often",
                    "check them when they renew rather than every request",
                    "the window of being wrong is however long the token lasts",
                    "you trade a small delay for not checking every time",
                ),
                "Think about where you could put a single check that limits how long a stale decision survives.",
            ),
            core(
                "stale-claims-not-just-revocation",
                "Anything baked into the token -- roles, plan, permissions -- is a snapshot, so a "
                "change of role also takes effect late",
                "Generalises the problem past logout, which is where teams get caught.",
                (
                    "their permissions are frozen at the moment it was issued",
                    "if you demote someone they keep the old access for a while",
                    "the roles inside it can be out of date",
                    "it's a snapshot, not a live answer",
                ),
                "Think about what else besides 'are they logged in' is copied into the token.",
                ("only logout is affected by staleness",),
            ),
            sup(
                "size-and-exposure-cost",
                "The token travels on every request and is readable by anyone holding it, so it "
                "is both bandwidth and a disclosure surface",
                "Practical detail that shows real use rather than theory.",
                (
                    "it's sent on every single request so keep it small",
                    "anyone who has it can read what's inside",
                ),
            ),
            bonus(
                "hybrid-by-sensitivity",
                "Low-risk endpoints can trust the token while sensitive actions re-check against "
                "the source of truth",
                "The judgement call rather than a doctrine.",
                (
                    "check properly for the dangerous operations only",
                    "not every endpoint needs the same rigour",
                ),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "It breaks down on revocation. The appeal is that nothing needs looking up, but "
                "that also means nothing can be checked, so if you ban someone at ten they keep "
                "working until their token expires. And it isn't only logout -- anything baked "
                "in, like their role or plan, is a snapshot, so demoting someone leaves them with "
                "the old access for a while. The usual resolution is to keep the token "
                "short-lived and renew it against something you can actually check, so you pay a "
                "lookup on renewal instead of on every request and the window of being wrong is "
                "bounded. For genuinely sensitive actions I'd re-check against the source of "
                "truth regardless.",
                {
                    "self-contained-tokens-cannot-be-withdrawn": "covered",
                    "short-life-plus-renewal-recovers-control": "covered",
                    "stale-claims-not-just-revocation": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "Stateless tokens scale better because you don't need a session store.",
                {
                    "self-contained-tokens-cannot-be-withdrawn": "missing",
                    "short-life-plus-renewal-recovers-control": "missing",
                    "stale-claims-not-just-revocation": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # backpressure
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="backpressure",
        seniority=MID,
        neutral_wording=(
            "Work arrives faster than your system can process it. The queue just keeps growing. "
            "What should happen instead?"
        ),
        reframe_wording=(
            "Same situation: the queue is at two million items and climbing. What has gone wrong "
            "with the design, not the capacity?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "a-growing-queue-is-a-hidden-failure",
                "A queue that grows faster than it drains never catches up, so it is not "
                "absorbing a spike, it is delaying an outage while memory or disk fills",
                "Reframes the queue from a solution to a symptom, which is the whole insight.",
                (
                    "it's never going to catch up",
                    "the queue is just hiding that we're too slow",
                    "eventually it runs out of memory or disk",
                    "it looks fine right up until it isn't",
                ),
                "Think about whether the queue will ever be empty again at these rates.",
                ("a bigger queue absorbs more load",),
            ),
            core(
                "tell-the-producer-to-slow-down",
                "The sender has to find out it is going too fast -- by being blocked, rejected, or "
                "explicitly told to wait -- so the pressure travels back to the source",
                "This is the mechanism, and the plain-language version is the point.",
                (
                    "tell the fast one to slow down",
                    "the sender needs to feel it, not just the queue",
                    "block them or reject them so they back off",
                    "push the problem back to where the work comes from",
                ),
                "Think about how the thing producing the work could ever learn that it should stop.",
            ),
            core(
                "bounded-queues-force-the-decision",
                "Giving the queue a fixed maximum turns 'grow forever' into an explicit choice "
                "about what to do when it is full: reject, drop, or block",
                "Without a bound there is no moment at which anyone has to decide.",
                (
                    "put a limit on how big it can get",
                    "then you have to decide what happens when it's full",
                    "reject new work rather than accept it",
                    "an unbounded queue means never having to choose",
                ),
                "Think about what a maximum size forces you to decide that no maximum lets you avoid.",
                ("dropping work is always unacceptable",),
            ),
            sup(
                "latency-is-the-early-signal",
                "Time spent waiting in the queue rises long before anything breaks, so it is the "
                "metric that warns you",
                "Connects the design to how you would actually notice.",
                (
                    "watch how long things sit in the queue",
                    "queue depth going up is the early warning",
                ),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "If it's growing faster than it drains then it's never going to catch up, so the "
                "queue isn't absorbing a spike, it's just hiding the fact that we're too slow "
                "until memory or disk runs out. What needs to happen is that the thing producing "
                "the work finds out it's going too fast -- you tell the fast one to slow down, by "
                "blocking or rejecting it, so the pressure reaches the source rather than piling "
                "up in the middle. Practically that means giving the queue a fixed maximum, which "
                "forces an explicit decision about what to do when it's full, instead of letting "
                "it grow forever and never having to choose. I'd watch how long items sit in the "
                "queue as the early warning.",
                {
                    "a-growing-queue-is-a-hidden-failure": "covered",
                    "tell-the-producer-to-slow-down": "covered",
                    "bounded-queues-force-the-decision": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd add more consumers to process the queue faster and scale up the workers.",
                {
                    "a-growing-queue-is-a-hidden-failure": "missing",
                    "tell-the-producer-to-slow-down": "missing",
                    "bounded-queues-force-the-decision": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="backpressure",
        seniority=SENIOR,
        neutral_wording=(
            "You have to shed load, but not all requests are equally important. How would you "
            "decide what to drop, and how do you avoid making the outage worse by dropping the "
            "wrong things?"
        ),
        reframe_wording=(
            "Same constraint: you can serve sixty percent of traffic. Which sixty, and how does "
            "the system know?"
        ),
        expected_minutes=7,
        concepts=(
            core(
                "shed-by-value-not-arrival-order",
                "Dropping whatever happens to arrive when you are full discards paying and "
                "trivial traffic at the same rate, so requests need a priority the system can act on",
                "The difference between load shedding and simply failing.",
                (
                    "drop the cheap stuff and keep the important stuff",
                    "not everything is worth the same",
                    "you need to know which request matters before you can choose",
                    "first come first served is the wrong rule when you're full",
                ),
                "Think about which requests you would most regret dropping, and how the server would know.",
                ("shedding randomly is fair",),
            ),
            core(
                "drop-early-and-cheaply",
                "Rejecting after the expensive work is already done costs the same as serving it, "
                "so the decision has to happen at the edge before resources are committed",
                "Where the rejection happens decides whether shedding helps at all.",
                (
                    "reject it before you've done the work",
                    "no point failing after you've already queried the database",
                    "decide at the front door",
                    "otherwise you pay the cost and get nothing",
                ),
                "Think about how much a rejected request costs if you reject it at the last step.",
            ),
            core(
                "retries-of-shed-work-must-not-return-immediately",
                "Rejected clients that retry straight away turn shedding into a loop, so the "
                "rejection has to tell them to wait and they have to obey it",
                "The failure mode that makes shedding actively harmful.",
                (
                    "if they all retry instantly you've gained nothing",
                    "tell them how long to wait before coming back",
                    "the rejection needs to slow them down, not just say no",
                    "otherwise the dropped traffic comes straight back",
                ),
                "Think about what the rejected clients do one second later.",
                ("rejecting a request removes its load",),
            ),
            sup(
                "protect-the-recovery-path",
                "Health checks, admin endpoints and anything needed to fix the incident must be "
                "exempt, or shedding locks you out of your own system",
                "Hard-won operational detail.",
                (
                    "don't shed the health checks",
                    "keep the admin tools working or you can't fix it",
                ),
            ),
            bonus(
                "measure-what-you-dropped",
                "Shed traffic has to be counted and attributed, or the system looks healthy "
                "precisely because it is refusing work",
                "Senior instinct: the dashboard lies if it only measures what you served.",
                (
                    "your latency looks great because you dropped the slow ones",
                    "count the rejections or you can't see the incident",
                ),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "First come first served is the wrong rule when you're full, so requests need a "
                "priority the system can act on -- checkout over analytics, logged-in over "
                "anonymous -- otherwise you drop the valuable and trivial at the same rate. The "
                "rejection has to happen at the front door, before you've queried anything, "
                "because failing after the expensive work costs the same as succeeding. The trap "
                "is that rejected clients retry immediately and the shed traffic comes straight "
                "back, so the response has to tell them how long to wait and they have to honour "
                "it. I'd exempt health checks and admin endpoints, or shedding locks us out of "
                "fixing it, and I'd count what was dropped, because otherwise latency looks great "
                "precisely because we refused the hard requests.",
                {
                    "shed-by-value-not-arrival-order": "covered",
                    "drop-early-and-cheaply": "covered",
                    "retries-of-shed-work-must-not-return-immediately": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd rate limit the endpoints so we return 429 once we hit the threshold.",
                {
                    "shed-by-value-not-arrival-order": "missing",
                    "drop-early-and-cheaply": "missing",
                    "retries-of-shed-work-must-not-return-immediately": "missing",
                },
            ),
        ),
    ),
)
