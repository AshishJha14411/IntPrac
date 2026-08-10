"""Authored question bank -- domain: databases.

Every rubric here obeys the authoring bar in ``app/content/types.py``:
>= 2 core concepts, >= 3 acceptable signals per core concept, >= 2
misconceptions overall, a ``why_it_matters`` line on every concept (shown
verbatim to the candidate), an L2 signpost on every core concept, and a
strong + weak golden answer for the drift gate.

Note what the ``acceptable_signals`` look like. They are the *plain-language*
ways someone explains the mechanism -- "it has to walk past all those rows
first" -- not the vocabulary. **No candidate ever needs to say the word
"keyset".** That is the entire product thesis, encoded as data.
"""

from __future__ import annotations

from app.content.types import GoldenSpec, QuestionSpec, bonus, core, sup
from app.domain.enums import QuestionArchetype, Seniority

MID, SENIOR = Seniority.MID, Seniority.SENIOR


QUESTIONS: tuple[QuestionSpec, ...] = (
    # ══════════════════════════════════════════════════════════════════════
    # offset-vs-keyset-pagination  (the worked example from Appendix C.3)
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="offset-vs-keyset-pagination",
        seniority=MID,
        neutral_wording=(
            "An endpoint lists newest-first records and gets slow when users page deep into "
            "the results. What's happening, and how would you fix it?"
        ),
        reframe_wording=(
            "Same situation, put differently: page 2 of that list is fast and page 500 is slow, "
            "even though both return the same number of rows. Why would that be, and what would "
            "you change?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "offset-scans-and-discards",
                "Skipping rows still costs work: the database walks past every skipped row before "
                "returning any, so the cost grows with how deep you page",
                "This is the actual mechanism; without it the fix is cargo-culted.",
                (
                    "it has to walk past all those rows first",
                    "it counts through everything it's skipping",
                    "the database still reads them, it just throws them away",
                    "page 500 means reading 500 pages worth of rows",
                ),
                "Think about what the database physically has to do before it can hand you row 5001.",
                (
                    "adding an index makes deep paging fast",
                    "LIMIT is the slow part",
                ),
            ),
            core(
                "seek-by-last-seen-key",
                "The fix is to remember where the last page ended and start from there, instead of "
                "counting rows from the beginning every time",
                "This is the core idea; everything else is implementation detail.",
                (
                    "remember where you stopped and start there next time",
                    "like a bookmark instead of counting pages",
                    "pass back the last id and ask for rows after it",
                    "you tell it 'give me the next ones after this one'",
                ),
                "Think about how you'd resume reading a book without counting pages from the start.",
            ),
            core(
                "total-ordering-tiebreaker",
                "The column you order by has to be unique, or you need a tiebreaker -- otherwise "
                "rows with identical values repeat or get skipped across pages",
                "This is the subtle correctness bug most candidates miss, and it silently loses data.",
                (
                    "if two rows have the same timestamp you can't tell them apart",
                    "you need something to break ties or rows repeat",
                    "add the id as a second sort key",
                    "the ordering has to be unique or the boundary is ambiguous",
                ),
                "Think about two records created in the same millisecond, and which page each lands on.",
                ("ordering by a non-unique timestamp is fine as long as it's indexed",),
            ),
            sup(
                "index-must-match-sort",
                "The seek is only cheap if an index exists in the same order as the sort",
                "Separates knowing the trick from knowing why it's fast.",
                (
                    "you need an index on what you're sorting by",
                    "otherwise it still has to sort everything",
                ),
            ),
            sup(
                "loses-random-page-access",
                "You give up jumping to an arbitrary page -- there's no 'page 50' any more, only "
                "next and previous",
                "Shows they understand what they're trading away, not just what they're gaining.",
                ("you can't jump to page 50 any more", "only next and previous"),
            ),
            bonus(
                "opaque-validated-cursor",
                "The cursor handed to clients should be opaque and validated, so tampering "
                "produces a clean error rather than a crash or a leak",
                "Senior-flavoured API-design instinct.",
                ("encode it so people don't depend on the format", "validate it when it comes back"),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "The problem is that skipping rows isn't free. When you ask for the 10 rows "
                "starting at 5000, the database still has to walk past all those rows first and "
                "throw them away, so it gets slower the deeper you go. The fix is to remember "
                "where you stopped and start there next time -- you pass back the last id you saw "
                "and ask for rows after it, like a bookmark instead of counting pages. The catch "
                "is that if two rows have the same timestamp you can't tell them apart, so you "
                "need something to break ties, usually the id as a second sort key, or rows "
                "repeat across pages. You also need an index on what you're sorting by, otherwise "
                "it still has to sort everything. The trade-off is you can't jump to page 50 any "
                "more, only next and previous.",
                {
                    "offset-scans-and-discards": "covered",
                    "seek-by-last-seen-key": "covered",
                    "total-ordering-tiebreaker": "covered",
                    "index-must-match-sort": "covered",
                    "loses-random-page-access": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "You should add an index on the created_at column. Then OFFSET will be fast "
                "because the index makes lookups quick. LIMIT is what slows it down when the "
                "number gets big.",
                {
                    "offset-scans-and-discards": "contradicted",
                    "seek-by-last-seen-key": "missing",
                    "total-ordering-tiebreaker": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="offset-vs-keyset-pagination",
        seniority=SENIOR,
        neutral_wording=(
            "You need to change a heavily-used, deeply-paginated listing endpoint to a cursor "
            "scheme without breaking existing clients. Walk me through how you'd roll that out "
            "and what you'd watch."
        ),
        reframe_wording=(
            "Put another way: the fix is understood, the risk is the migration. How do you ship "
            "it to live traffic safely?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.DECISION,
        concepts=(
            core(
                "mechanism-still-understood",
                "Deep paging is slow because skipped rows are still read and discarded; seeking "
                "from the last-seen key removes that work",
                "The rollout only makes sense if the underlying mechanism is understood.",
                (
                    "it reads and throws away everything it skips",
                    "start from where the last page ended",
                    "resume from the last row instead of counting",
                ),
                "Start from what the database is doing before it returns the first row of page 500.",
                ("an index removes the cost of skipping rows",),
            ),
            core(
                "dual-support-rollout",
                "Both schemes run side by side for a period, so existing clients keep working "
                "while new ones migrate, and you can roll back without a deploy",
                "Migration safety is what separates a senior answer from a correct one.",
                (
                    "support both for a while",
                    "keep the old parameter working and add the new one",
                    "clients move over gradually, nothing breaks at once",
                    "so you can turn it off again if it goes wrong",
                ),
                "Think about what happens to the mobile app version someone installed last year.",
            ),
            core(
                "what-to-measure",
                "You decide it worked from evidence: latency at the tail rather than the average, "
                "and which clients are still on the old path",
                "Senior work is measured, not asserted.",
                (
                    "look at p95 or p99, not the average",
                    "the average hides the slow deep pages",
                    "track how many clients still use the old parameter",
                    "measure before and after on the same query",
                ),
                "Think about which number would actually move if only deep pages got faster.",
                ("if the average response time drops, the fix worked",),
            ),
            sup(
                "index-and-plan-verification",
                "You confirm the new query actually uses the intended index rather than assuming it",
                "The plan is the evidence; the index existing is not.",
                ("check the query plan", "make sure it's not still sorting everything"),
            ),
            sup(
                "cost-and-ops-consequence",
                "Deep paging is often a symptom -- an export or a scraper -- and the right fix may "
                "be a different endpoint entirely",
                "Reframing the requirement is frequently the highest-value move.",
                ("if they're paging to page 500 they probably want an export", "give them a bulk endpoint"),
            ),
            bonus(
                "cursor-stability-under-writes",
                "Rows inserted or deleted mid-pagination shift what 'next' means, and the scheme "
                "should make that behaviour explicit rather than accidental",
                "Shows they've thought past the happy path.",
                ("new rows arriving change what the next page is",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "First, why it's slow: it reads and throws away everything it skips, so the cost "
                "grows with depth. The fix is to start from where the last page ended. For "
                "rollout I'd support both for a while -- keep the old parameter working and add "
                "the new one, so clients move over gradually and nothing breaks at once, and I "
                "can turn it off again if it goes wrong. To know it worked I'd look at p95 or p99, "
                "not the average, because the average hides the slow deep pages, and I'd track how "
                "many clients still use the old parameter so I know when I can remove it. I'd also "
                "check the query plan to make sure it's not still sorting everything. Honestly, if "
                "they're paging to page 500 they probably want an export, so I'd ask whether a bulk "
                "endpoint is the real fix.",
                {
                    "mechanism-still-understood": "covered",
                    "dual-support-rollout": "covered",
                    "what-to-measure": "covered",
                    "index-and-plan-verification": "covered",
                    "cost-and-ops-consequence": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd switch the endpoint to cursor pagination and deploy it. Clients would need to "
                "update. Then I'd check that the average response time went down.",
                {
                    "mechanism-still-understood": "missing",
                    "dual-support-rollout": "missing",
                    "what-to-measure": "contradicted",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # indexing-strategy
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="indexing-strategy",
        seniority=MID,
        neutral_wording=(
            "A query filters on two columns and sorts by a third, and it's slow. How do you decide "
            "what index to add, and how do you know it helped?"
        ),
        reframe_wording=(
            "Another way in: you can add one index to make this query fast. How do you pick which "
            "one, and what tells you it worked?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "index-is-ordered-lookup-structure",
                "An index is a separate, ordered copy of some columns, so the database can jump "
                "to matching rows instead of reading the whole table",
                "Without this, index choice is guesswork dressed up as a rule.",
                (
                    "it's a sorted structure it can jump into",
                    "so it doesn't have to read every row",
                    "like the index at the back of a book",
                    "it keeps the values in order so lookups are cheap",
                ),
                "Think about what physically lets the database avoid reading every row.",
                ("an index makes the whole table faster",),
            ),
            core(
                "column-order-matters",
                "In a multi-column index the order of the columns decides which queries it can "
                "serve -- it can be used left to right, not from the middle",
                "This is the difference between an index that helps and one that just costs writes.",
                (
                    "the order of the columns matters",
                    "it can only use it from the left",
                    "if you skip the first column it can't use the rest",
                    "equality columns first, then the one you sort by",
                ),
                "Think about a phone book sorted by surname then first name, and looking someone "
                "up by first name only.",
                ("the database reorders index columns for you as needed",),
            ),
            core(
                "verify-with-the-plan",
                "You confirm from the query plan that the index is actually being used, rather "
                "than assuming it because you created it",
                "Creating an index and measuring nothing is how unused indexes accumulate.",
                (
                    "look at the query plan",
                    "check whether it's actually using it",
                    "run explain before and after",
                    "compare rows read, not just wall-clock time",
                ),
                "Think about how you'd prove the database changed its mind, not just that the "
                "query felt faster.",
            ),
            sup(
                "writes-pay-for-reads",
                "Every index has to be maintained on insert and update, so indexes are a read "
                "speedup bought with write cost and storage",
                "Explains why 'index everything' is not a strategy.",
                ("every write has to update the index too", "they're not free"),
            ),
            sup(
                "selectivity-matters",
                "An index on a column with very few distinct values often isn't worth using, "
                "because it doesn't narrow anything down",
                "Selectivity is why some 'obvious' indexes never get used.",
                ("if almost every row matches it doesn't help", "a boolean column barely narrows it"),
            ),
            bonus(
                "covering-index",
                "If the index contains every column the query needs, the database can answer "
                "without touching the table at all",
                "Shows depth beyond 'add an index on the filter column'.",
                ("if everything it needs is in the index it never reads the table",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "An index is a sorted structure it can jump into, so it doesn't have to read every "
                "row. For this query I'd put the two equality columns first, then the one you sort "
                "by, because the order of the columns matters -- it can only use it from the left, "
                "and if you skip the first column it can't use the rest. Then I'd run explain "
                "before and after and check whether it's actually using it, comparing rows read "
                "rather than just wall-clock time. I'd keep it to one index rather than adding "
                "three, because every write has to update the index too, so they're not free. And "
                "if one of those columns is nearly always the same value it doesn't help much -- "
                "if almost every row matches, it doesn't narrow anything down.",
                {
                    "index-is-ordered-lookup-structure": "covered",
                    "column-order-matters": "covered",
                    "verify-with-the-plan": "covered",
                    "writes-pay-for-reads": "covered",
                    "selectivity-matters": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd add an index on each of the three columns. Indexes make queries faster, so "
                "more indexes means the table is faster overall. The database will pick the right "
                "one automatically.",
                {
                    "index-is-ordered-lookup-structure": "contradicted",
                    "column-order-matters": "missing",
                    "verify-with-the-plan": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="indexing-strategy",
        seniority=SENIOR,
        neutral_wording=(
            "You need to add an index to a large, busy production table. What could go wrong, and "
            "how do you do it safely?"
        ),
        reframe_wording=(
            "Put differently: the index is the right index. The risk is creating it on a table "
            "that's serving traffic right now. How do you handle that?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.EDGE,
        concepts=(
            core(
                "build-can-block-writes",
                "Building an index normally holds a lock that blocks writes for the whole build, "
                "which on a large table means an outage rather than a slowdown",
                "This is the failure mode that turns a routine change into an incident.",
                (
                    "it locks the table while it builds",
                    "writes queue up behind it",
                    "on a big table that's minutes of downtime",
                    "everything trying to insert just stops",
                ),
                "Think about what other queries are allowed to do to that table while the index is "
                "being built.",
                ("index creation is always online and safe",),
            ),
            core(
                "concurrent-build-tradeoffs",
                "There's a non-blocking way to build it that takes longer, does more passes, and "
                "can leave a broken index behind if it fails -- which then has to be cleaned up",
                "Knowing the escape hatch *and* its failure mode is the senior part.",
                (
                    "there's a concurrent option that doesn't block",
                    "it takes longer because it makes more passes",
                    "if it fails it leaves an invalid index you have to drop",
                    "it can't run inside a transaction",
                ),
                "Think about what the safer option costs you, and what it leaves behind if it fails "
                "halfway.",
                ("the concurrent build is strictly better with no downsides",),
            ),
            core(
                "what-to-measure-and-rollback",
                "You decide it worked from evidence -- plan changes, write latency, replication "
                "lag -- and dropping an index is a cheap, fast rollback",
                "Rollout without a rollback plan is a hope, not a plan.",
                (
                    "watch write latency while it builds",
                    "check replication lag",
                    "you can just drop it if it's wrong",
                    "confirm the plan actually changed",
                ),
                "Think about what you'd be staring at while it runs, and what you'd do if it "
                "looked wrong.",
            ),
            sup(
                "migration-tooling-caveat",
                "The non-blocking build can't run inside a normal migration transaction, so the "
                "migration tool needs an explicit escape hatch",
                "This is the detail that turns a good plan into a working one.",
                ("the migration runs in a transaction so you have to opt out",),
            ),
            sup(
                "replica-impact",
                "Index builds replay on replicas too, so the cost isn't confined to the primary",
                "Shows they think past a single machine.",
                ("the replicas have to build it as well", "it can cause lag"),
            ),
            bonus(
                "backfill-and-bloat",
                "Large index builds consume IO and can leave behind bloat that needs maintenance",
                "Operational awareness beyond the change itself.",
                ("it hammers IO while it runs",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "The default problem is that it locks the table while it builds, so writes queue "
                "up behind it and on a big table that's minutes of downtime. So I'd use the "
                "concurrent option that doesn't block -- it takes longer because it makes more "
                "passes, and it can't run inside a transaction, which matters because the "
                "migration runs in a transaction so you have to opt out. The other catch is that "
                "if it fails it leaves an invalid index you have to drop. While it runs I'd watch "
                "write latency and check replication lag, since the replicas have to build it as "
                "well and it can cause lag. Afterwards I'd confirm the plan actually changed, and "
                "if any of it looks wrong you can just drop it, which is fast.",
                {
                    "build-can-block-writes": "covered",
                    "concurrent-build-tradeoffs": "covered",
                    "what-to-measure-and-rollback": "covered",
                    "migration-tooling-caveat": "covered",
                    "replica-impact": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd write a migration that creates the index and run it during the day. Creating "
                "an index is an online operation so it doesn't affect anyone. Then I'd check the "
                "query is faster.",
                {
                    "build-can-block-writes": "contradicted",
                    "concurrent-build-tradeoffs": "missing",
                    "what-to-measure-and-rollback": "partial",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # transactions-and-acid
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="transactions-and-acid",
        seniority=MID,
        neutral_wording=(
            "Two parts of a request each write to the database, and the second one fails. What "
            "should happen, and what makes that guarantee actually hold?"
        ),
        reframe_wording=(
            "Another angle: a request half-succeeded. What stops the database from being left in "
            "that half state?"
        ),
        expected_minutes=4,
        concepts=(
            core(
                "all-or-nothing-unit",
                "The two writes are one unit: either both take effect or neither does, and a "
                "failure part-way undoes what already happened",
                "This is the guarantee everything else in the answer rests on.",
                (
                    "either both happen or neither does",
                    "it rolls back what it already did",
                    "it's one unit of work, not two",
                    "the half state never becomes visible",
                ),
                "Think about what the database does with the first write once the second one fails.",
                ("the first write stays and you clean it up afterwards",),
            ),
            core(
                "one-owner-of-commit",
                "Something has to own the boundary -- one place decides to commit or roll back, "
                "rather than each piece of code committing as it goes",
                "Scattered commits are how partial writes get shipped despite 'using transactions'.",
                (
                    "one place decides when to commit",
                    "the individual functions shouldn't commit themselves",
                    "commit at the edge, not in the middle",
                    "if each part commits separately you've got two transactions, not one",
                ),
                "Think about who is allowed to say 'we're done' -- and what happens if several "
                "people can say it.",
                ("each service method should commit its own work",),
            ),
            sup(
                "durability-after-commit",
                "Once it commits, the change survives a crash -- that's what commit means",
                "Distinguishes 'written' from 'acknowledged'.",
                ("after it says yes, it's safe even if the box dies",),
            ),
            sup(
                "keep-transactions-short",
                "Long transactions hold locks and resources, so external calls don't belong inside "
                "one",
                "Explains a large class of production stalls.",
                ("don't call an external API inside a transaction", "it holds locks the whole time"),
            ),
            bonus(
                "constraint-as-arbiter",
                "Uniqueness is enforced by the database constraint and the violation is caught, "
                "rather than checked first and hoped for",
                "Check-then-insert is a race, and the constraint is the only real arbiter.",
                ("checking first doesn't help, two requests can both pass the check",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "It should be one unit of work, not two -- either both happen or neither does, so "
                "if the second fails it rolls back what it already did and the half state never "
                "becomes visible. What makes that hold in practice is that one place decides when "
                "to commit; the individual functions shouldn't commit themselves, because if each "
                "part commits separately you've got two transactions, not one. Once it does "
                "commit, it's safe even if the box dies. I'd also keep it short and not call an "
                "external API inside a transaction, because it holds locks the whole time.",
                {
                    "all-or-nothing-unit": "covered",
                    "one-owner-of-commit": "covered",
                    "durability-after-commit": "covered",
                    "keep-transactions-short": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "The second write would fail and return an error to the user. Each service method "
                "should commit its own work so the successful part is saved. That way you don't "
                "lose the first write.",
                {
                    "all-or-nothing-unit": "contradicted",
                    "one-owner-of-commit": "contradicted",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="transactions-and-acid",
        seniority=SENIOR,
        neutral_wording=(
            "A request writes a row and then needs to trigger background work based on it. The "
            "background worker sometimes runs and finds nothing. What's happening, and how do you "
            "fix it properly?"
        ),
        reframe_wording=(
            "Put another way: the job fires, but the data it needs isn't there yet. What is "
            "actually racing what?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.EDGE,
        concepts=(
            core(
                "commit-then-enqueue-race",
                "The job was queued before the write became visible, so the worker looked for a "
                "row that hadn't been committed yet",
                "Naming the race correctly is what makes the right fix obvious.",
                (
                    "the job started before the transaction committed",
                    "the worker can't see uncommitted data",
                    "it queued the work too early",
                    "the row isn't visible to anyone else until commit",
                ),
                "Think about the exact moment the other process is able to see that row.",
                ("the worker is just slow, adding a delay fixes it",),
            ),
            core(
                "write-the-intent-transactionally",
                "The fix is to record the intent to do the work in the same transaction as the "
                "data, then have something dispatch it afterwards",
                "This is the actual mechanism, and it survives crashes that a reordering does not.",
                (
                    "write the job as a row in the same transaction",
                    "then something reads that table and dispatches it",
                    "the event and the data commit together",
                    "so either both exist or neither does",
                ),
                "Think about making the fact 'this work needs doing' part of the same all-or-nothing "
                "unit as the data.",
            ),
            core(
                "at-least-once-and-idempotency",
                "Dispatch is at-least-once, so the same job can arrive twice and the consumer has "
                "to be safe to run repeatedly",
                "Duplicate delivery is guaranteed; safe consumers are what make it a non-event.",
                (
                    "the same job might get delivered twice",
                    "so it has to be safe to run again",
                    "make the second run a no-op",
                    "you can't get exactly-once, you get at-least-once plus idempotency",
                ),
                "Think about what happens if the dispatcher crashes right after sending but before "
                "recording that it sent.",
                ("a queue can guarantee exactly-once delivery",),
            ),
            sup(
                "why-reordering-is-not-enough",
                "Simply committing before enqueuing narrows the window but still loses jobs if the "
                "process dies in between",
                "Rules out the tempting almost-fix.",
                ("if it crashes between the commit and the enqueue, the job is just gone",),
            ),
            sup(
                "failure-visibility",
                "Failed dispatches stay visible and retryable rather than disappearing",
                "A dead job you can see is a bug; one you can't is a mystery.",
                ("keep the failed ones so you can look at them",),
            ),
            bonus(
                "ordering-and-concurrency",
                "Multiple dispatchers can run without double-sending if claiming is done carefully",
                "Shows they've thought about running more than one relay.",
                ("lock the rows you claim so two dispatchers don't send the same one",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "The job started before the transaction committed, so the worker looked for a row "
                "that isn't visible to anyone else until commit. Reordering isn't enough on its "
                "own -- if it crashes between the commit and the enqueue, the job is just gone. "
                "The proper fix is to write the job as a row in the same transaction, so the event "
                "and the data commit together and either both exist or neither does, then "
                "something reads that table and dispatches it. Because the dispatcher can crash "
                "after sending, the same job might get delivered twice, so it has to be safe to "
                "run again -- you can't get exactly-once, you get at-least-once plus idempotency. "
                "I'd keep the failed ones so you can look at them, and lock the rows you claim so "
                "two dispatchers don't send the same one.",
                {
                    "commit-then-enqueue-race": "covered",
                    "write-the-intent-transactionally": "covered",
                    "at-least-once-and-idempotency": "covered",
                    "why-reordering-is-not-enough": "covered",
                    "failure-visibility": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "The worker is just slow to pick it up. I'd add a short delay before queueing the "
                "job so the database has time to catch up. Most queues guarantee exactly-once "
                "delivery so it'll only run once.",
                {
                    "commit-then-enqueue-race": "contradicted",
                    "write-the-intent-transactionally": "missing",
                    "at-least-once-and-idempotency": "contradicted",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # isolation-levels-and-anomalies
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="isolation-levels-and-anomalies",
        seniority=MID,
        neutral_wording=(
            "Two requests read the same counter, add one, and write it back. Sometimes an increment "
            "goes missing. Why, and what would you change?"
        ),
        reframe_wording=(
            "Same thing differently: two people press the button at the same instant and the total "
            "only goes up by one. What happened in between?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "read-modify-write-race",
                "Both requests read the same starting value before either wrote, so the second "
                "write overwrites the first instead of building on it",
                "This is the mechanism; every fix follows from seeing the interleaving.",
                (
                    "they both read the old value first",
                    "the second one overwrites the first",
                    "the update is based on a value that's already stale",
                    "one of the increments is just lost",
                ),
                "Think about the order the two requests actually did their reads and writes, "
                "interleaved.",
                ("the database serialises writes so this can't happen",),
            ),
            core(
                "make-the-update-atomic",
                "Either let the database do the arithmetic in one statement, or make the write "
                "conditional on the value not having changed since you read it",
                "Two legitimate fixes; either shows the right model.",
                (
                    "let the database do the increment itself",
                    "update it in one statement instead of read-then-write",
                    "check it hasn't changed since you read it",
                    "take a lock on the row while you work on it",
                ),
                "Think about how to remove the gap between reading the value and writing it back.",
                ("wrapping the two statements in a transaction is enough on its own",),
            ),
            sup(
                "isolation-level-is-a-choice",
                "The default isolation level allows this; stricter levels prevent more anomalies "
                "at a cost",
                "Isolation is a dial, not a fixed property, and defaults are chosen for throughput.",
                ("the default doesn't stop this", "a stricter level would, but it costs you"),
            ),
            sup(
                "retry-on-conflict",
                "With optimistic approaches the loser gets a conflict and retries, so the caller "
                "needs to handle that",
                "The strategy isn't complete without the failure path.",
                ("one of them fails and has to try again",),
            ),
            bonus(
                "contention-shapes-choice",
                "Which approach is right depends on how often the conflict actually happens",
                "Shows the trade-off is empirical, not dogmatic.",
                ("if it collides constantly, locking beats retrying",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "They both read the old value first, so the update is based on a value that's "
                "already stale and the second one overwrites the first -- one of the increments is "
                "just lost. The fix is to remove the gap: let the database do the increment itself "
                "in one statement instead of read-then-write, or check it hasn't changed since you "
                "read it before writing. The default isolation level doesn't stop this; a stricter "
                "level would, but it costs you. If I go the optimistic route then one of them fails "
                "and has to try again, so the caller has to handle that -- and if it collides "
                "constantly, locking beats retrying.",
                {
                    "read-modify-write-race": "covered",
                    "make-the-update-atomic": "covered",
                    "isolation-level-is-a-choice": "covered",
                    "retry-on-conflict": "covered",
                    "contention-shapes-choice": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "They need to be in a transaction. Once both statements are inside a transaction "
                "the database handles the ordering and the increments won't be lost.",
                {
                    "read-modify-write-race": "partial",
                    "make-the-update-atomic": "contradicted",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="isolation-levels-and-anomalies",
        seniority=SENIOR,
        neutral_wording=(
            "A booking system occasionally double-books a slot even though there's a check before "
            "insert. How do you make it correct, and how would you prove it stays correct?"
        ),
        reframe_wording=(
            "Put it this way: the check passes for two requests at once. What guarantee is missing, "
            "and how do you demonstrate you've added it?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.EDGE,
        concepts=(
            core(
                "check-then-act-is-a-race",
                "The check and the insert aren't atomic, so two requests can both pass the check "
                "before either inserts",
                "Pre-checks feel safe and are not; this is the whole bug.",
                (
                    "both requests pass the check before either writes",
                    "there's a gap between checking and inserting",
                    "the check tells you about a moment that's already gone",
                    "nothing stops the other one in between",
                ),
                "Think about two requests running the check at the same microsecond.",
                ("checking for an existing booking first prevents duplicates",),
            ),
            core(
                "database-is-the-arbiter",
                "Correctness has to come from the database -- a constraint, or a lock held across "
                "the check and the write -- and the violation is caught and translated",
                "Only the database sees all concurrent writers; application code does not.",
                (
                    "put a unique constraint on it and catch the error",
                    "let the insert fail and handle that",
                    "lock the row or the range while you decide",
                    "the database is the only thing that sees both requests",
                ),
                "Think about which component is in a position to see both requests at once.",
            ),
            core(
                "prove-it-with-a-race-test",
                "You demonstrate it with a test that genuinely runs the two paths concurrently, "
                "not one that simulates them sequentially",
                "A concurrency fix without a concurrency test is an assertion.",
                (
                    "write a test that actually runs them at the same time",
                    "two threads lined up on a barrier",
                    "a sequential test would pass either way, so it proves nothing",
                    "assert exactly one succeeds and the other gets a conflict",
                ),
                "Think about what a test would have to do differently to fail against the broken "
                "version.",
                ("mocking the second request is enough to test the race",),
            ),
            sup(
                "translate-to-a-clean-error",
                "The constraint violation becomes a meaningful conflict response rather than a 500",
                "The user experience of the correct behaviour still matters.",
                ("turn it into a 409 rather than an unhandled error",),
            ),
            sup(
                "isolation-level-alternative",
                "A stricter isolation level can also prevent it, at a throughput and retry cost",
                "Shows awareness of the other lever and its price.",
                ("serializable would catch it but you pay in retries",),
            ),
            bonus(
                "range-constraints",
                "Overlapping-range bookings need a constraint that understands ranges, not just "
                "equality",
                "Recognises when a plain unique index isn't sufficient.",
                ("a plain unique index doesn't catch overlapping times",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "The check and the insert aren't atomic, so both requests pass the check before "
                "either writes -- the check tells you about a moment that's already gone. The fix "
                "has to come from the database, because it's the only thing that sees both "
                "requests: put a unique constraint on it and catch the error, or lock the range "
                "while you decide. I'd turn the violation into a 409 rather than an unhandled "
                "error. To prove it, I'd write a test that actually runs them at the same time -- "
                "two threads lined up on a barrier -- and assert exactly one succeeds and the "
                "other gets a conflict, because a sequential test would pass either way, so it "
                "proves nothing. Serializable would also catch it but you pay in retries. And if "
                "bookings are time ranges, a plain unique index doesn't catch overlapping times.",
                {
                    "check-then-act-is-a-race": "covered",
                    "database-is-the-arbiter": "covered",
                    "prove-it-with-a-race-test": "covered",
                    "translate-to-a-clean-error": "covered",
                    "isolation-level-alternative": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd make sure the code checks for an existing booking before inserting, and add a "
                "test that calls the endpoint twice in a row and asserts the second one fails.",
                {
                    "check-then-act-is-a-race": "contradicted",
                    "database-is-the-arbiter": "missing",
                    "prove-it-with-a-race-test": "contradicted",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # connection-pooling
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="connection-pooling",
        seniority=MID,
        neutral_wording=(
            "Under load your service starts failing with 'too many connections' from the database, "
            "even though CPU on both sides is low. What's going on and how do you fix it?"
        ),
        reframe_wording=(
            "Another way to look at it: nothing is busy, but the database is refusing new work. "
            "What resource has actually run out?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "connections-are-a-scarce-server-resource",
                "Each database connection costs the server memory and a process or thread, so "
                "there's a hard ceiling well below 'as many as clients want'",
                "Explains why the limit exists rather than treating it as an arbitrary setting.",
                (
                    "each connection costs the database memory",
                    "it's not free to hold one open",
                    "there's a hard cap on the server side",
                    "the database has a fixed number it can serve",
                ),
                "Think about what the database has to allocate for each connection it accepts.",
                ("raising max_connections is the fix",),
            ),
            core(
                "pool-bounds-and-reuses",
                "A pool keeps a bounded set of connections open and hands them out, so requests "
                "wait for a connection instead of the database being overwhelmed",
                "The pool moves the queue to a place you control.",
                (
                    "keep a fixed set open and share them",
                    "reuse them instead of opening one per request",
                    "requests wait in line for a free one",
                    "it puts a ceiling on how many you ever open",
                ),
                "Think about where you'd rather the queue form: in your app, or at the database.",
                ("a pool exists to make individual queries faster",),
            ),
            sup(
                "pool-size-is-not-max-throughput",
                "A bigger pool is not automatically faster -- past a point more concurrency just "
                "adds contention",
                "Counters the reflex to raise the number until the error stops.",
                ("a bigger pool isn't automatically better", "past a point it just thrashes"),
            ),
            sup(
                "total-connections-across-instances",
                "The real number is pool size times instances, which is what actually hits the "
                "server limit",
                "The multiplication is where most incidents come from.",
                ("multiply by the number of app instances", "ten pods times twenty each is two hundred"),
            ),
            bonus(
                "leaks-and-long-holds",
                "Connections held across slow external calls, or never returned, exhaust the pool "
                "just as effectively",
                "A leak looks exactly like undersizing until you look closer.",
                ("if you hold one while calling an API you've taken it out of circulation",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "Each connection costs the database memory, so there's a hard cap on the server "
                "side -- it's not a CPU problem, you've run out of that. The fix is a pool: keep a "
                "fixed set open and share them, reuse them instead of opening one per request, so "
                "requests wait in line for a free one and it puts a ceiling on how many you ever "
                "open. The number that matters is pool size times the number of app instances -- "
                "ten pods times twenty each is two hundred, which is probably what blew the limit. "
                "I wouldn't just make the pool bigger, because past a point it just thrashes. I'd "
                "also check we're not holding one while calling an API, because that takes it out "
                "of circulation.",
                {
                    "connections-are-a-scarce-server-resource": "covered",
                    "pool-bounds-and-reuses": "covered",
                    "pool-size-is-not-max-throughput": "covered",
                    "total-connections-across-instances": "covered",
                    "leaks-and-long-holds": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd raise max_connections on the database since it's clearly set too low, and "
                "increase the pool size in the app so more requests can be served at once.",
                {
                    "connections-are-a-scarce-server-resource": "contradicted",
                    "pool-bounds-and-reuses": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="connection-pooling",
        seniority=SENIOR,
        neutral_wording=(
            "You're moving a service to an autoscaling platform that can run many short-lived "
            "instances. What does that do to your database connections, and how do you handle it?"
        ),
        reframe_wording=(
            "Put another way: the platform will happily run fifty copies of your app. What does "
            "that do downstream, and what do you put in the way?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.DECISION,
        concepts=(
            core(
                "instance-count-multiplies-connections",
                "Every instance brings its own pool, so an autoscaler quietly multiplies the "
                "connection count until the database refuses new ones",
                "This is the classic serverless-meets-database incident, and it's arithmetic.",
                (
                    "each instance opens its own pool",
                    "scaling out multiplies the connections",
                    "fifty instances times ten connections is five hundred",
                    "the autoscaler doesn't know about the database limit",
                ),
                "Think about what happens to the total when the platform doubles your instance "
                "count at 3am.",
                ("the platform manages database connections for you",),
            ),
            core(
                "external-pooler-in-front",
                "You put a pooler between the app and the database so many client connections map "
                "onto few server ones",
                "The fix is architectural, not a config tweak.",
                (
                    "put a pooler in front of the database",
                    "many app connections share a few real ones",
                    "use the pooled connection string, not the direct one",
                    "it multiplexes them down to a smaller number",
                ),
                "Think about adding something in the middle whose whole job is to be the ceiling.",
            ),
            core(
                "pooling-mode-changes-semantics",
                "Aggressive pooling modes break things that assume a stable session -- prepared "
                "statements, session settings, some transaction patterns",
                "The gotcha that turns the fix into a new outage if unknown.",
                (
                    "transaction pooling breaks prepared statements",
                    "you don't get the same connection back",
                    "anything that relies on session state stops working",
                    "you have to turn off statement caching",
                ),
                "Think about what your driver assumes is still true between two statements.",
                ("a pooler is a transparent drop-in with no behaviour change",),
            ),
            sup(
                "small-pools-per-instance",
                "With many instances each pool should be small; the aggregate is what matters",
                "Right-sizing follows from the multiplication, not from per-instance intuition.",
                ("keep each instance's pool tiny",),
            ),
            sup(
                "what-to-measure",
                "You watch connection count, wait time for a connection, and refusals -- not just "
                "app latency",
                "Names the signal that would have caught it early.",
                ("graph active connections against the limit", "alert before you hit the ceiling"),
            ),
            bonus(
                "cold-start-interaction",
                "Short-lived instances pay connection setup repeatedly, which shows up as latency "
                "rather than errors",
                "Connects the pooling story to the cold-start story.",
                ("new instances pay the handshake every time",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "Each instance opens its own pool, so scaling out multiplies the connections -- "
                "fifty instances times ten connections is five hundred, and the autoscaler doesn't "
                "know about the database limit. So I'd put a pooler in front of the database and "
                "use the pooled connection string, not the direct one, so many app connections "
                "share a few real ones. The catch is that transaction pooling breaks prepared "
                "statements -- you don't get the same connection back, so anything that relies on "
                "session state stops working and you have to turn off statement caching. I'd keep "
                "each instance's pool tiny since the aggregate is what matters, and graph active "
                "connections against the limit so we alert before we hit the ceiling.",
                {
                    "instance-count-multiplies-connections": "covered",
                    "external-pooler-in-front": "covered",
                    "pooling-mode-changes-semantics": "covered",
                    "small-pools-per-instance": "covered",
                    "what-to-measure": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "The platform handles scaling so it should be fine. If we see connection errors I'd "
                "add a pooler, which is a transparent drop-in, and everything keeps working the "
                "same way.",
                {
                    "instance-count-multiplies-connections": "contradicted",
                    "external-pooler-in-front": "partial",
                    "pooling-mode-changes-semantics": "contradicted",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # schema-migration-safety
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="schema-migration-safety",
        seniority=MID,
        neutral_wording=(
            "You need to rename a column that live code reads and writes. How do you do it without "
            "downtime?"
        ),
        reframe_wording=(
            "Same problem from another side: the old code and the new schema have to coexist for a "
            "while. How do you arrange that?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "old-and-new-code-overlap",
                "During a rollout both old and new versions of the code run at once, so the schema "
                "has to satisfy both simultaneously",
                "Every expand/contract rule follows from this one observation.",
                (
                    "both versions of the code are running during the deploy",
                    "the old pods are still up while the new ones start",
                    "the schema has to work for both at the same time",
                    "you can't change the code and the schema in one instant",
                ),
                "Think about what's actually running in the thirty seconds mid-deploy.",
                ("the migration and the deploy happen atomically together",),
            ),
            core(
                "add-backfill-switch-drop",
                "You add the new column, write to both, backfill, move reads over, and only then "
                "remove the old one -- each step safe on its own",
                "The sequence is the answer; skipping a step is where outages come from.",
                (
                    "add the new one first and write to both",
                    "backfill the old rows",
                    "then switch reads over",
                    "drop the old column in a later deploy",
                ),
                "Think about breaking it into steps where each one is safe to stop at.",
                ("you can rename it and update the code in the same release",),
            ),
            sup(
                "each-step-is-reversible",
                "Every step can be rolled back on its own, which is what makes the sequence safe "
                "rather than just long",
                "The point of the steps is the rollback, not the ceremony.",
                ("you can stop after any step and still be fine",),
            ),
            sup(
                "backfill-in-batches",
                "Backfilling in one statement locks or bloats; doing it in batches keeps the table "
                "usable",
                "A correct plan that takes the table down is still an outage.",
                ("do the backfill in chunks", "one big update would lock it"),
            ),
            bonus(
                "verify-before-drop",
                "Before dropping, you confirm nothing still reads the old column",
                "The last step is the one people ship blind.",
                ("check nothing is still using it before you drop it",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "The core problem is that both versions of the code are running during the deploy "
                "-- the old pods are still up while the new ones start -- so the schema has to work "
                "for both at the same time. I'd add the new one first and write to both, backfill "
                "the old rows in chunks because one big update would lock it, then switch reads "
                "over, and drop the old column in a later deploy. Each step is separately safe, so "
                "you can stop after any step and still be fine. Before dropping I'd check nothing "
                "is still using it.",
                {
                    "old-and-new-code-overlap": "covered",
                    "add-backfill-switch-drop": "covered",
                    "each-step-is-reversible": "covered",
                    "backfill-in-batches": "covered",
                    "verify-before-drop": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd write a migration that renames the column and deploy it together with the code "
                "change so they happen at the same time. That way there's no window where they "
                "disagree.",
                {
                    "old-and-new-code-overlap": "contradicted",
                    "add-backfill-switch-drop": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="schema-migration-safety",
        seniority=SENIOR,
        neutral_wording=(
            "Your team runs migrations from several places -- local machines, CI, and the deploy "
            "job. What can go wrong with that, and how would you make it safe?"
        ),
        reframe_wording=(
            "Put it another way: several people and systems can all apply schema changes. What's "
            "the worst realistic outcome, and what prevents it?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.EDGE,
        concepts=(
            core(
                "wrong-target-database",
                "The most dangerous failure isn't a bad migration, it's a correct migration applied "
                "to the wrong database because the connection setting fell through to a default",
                "This is a near-miss most teams have actually had, and it is silent.",
                (
                    "someone runs it against production by accident",
                    "the config falls back to whatever's in the environment",
                    "it picks up the wrong URL and you don't find out until later",
                    "the migration itself is fine, it just ran in the wrong place",
                ),
                "Think about where the connection string comes from when nobody set one explicitly.",
                ("the migration tool always knows which database is which",),
            ),
            core(
                "pin-the-target-explicitly",
                "Each environment pins its own migration target explicitly, and the tool refuses to "
                "run rather than guessing",
                "Failing closed is the whole control; a default is what caused the problem.",
                (
                    "give the migration its own explicit setting",
                    "make it fail if it isn't set instead of defaulting",
                    "pin it per environment, don't share one variable",
                    "print which database it's about to touch",
                ),
                "Think about what the tool should do when it can't tell which database it's pointed "
                "at.",
            ),
            core(
                "serialise-and-record",
                "Only one thing applies migrations at a time, and the applied set is recorded, so "
                "concurrent or repeated runs don't interleave",
                "Ordering matters as much as targeting once more than one runner exists.",
                (
                    "one place owns applying them",
                    "take a lock so two deploys don't run them at once",
                    "the tool records which ones already ran",
                    "make it idempotent to re-run",
                ),
                "Think about two deploys starting thirty seconds apart.",
                ("the version table alone makes concurrent runs safe",),
            ),
            sup(
                "review-generated-migrations",
                "Auto-generated migrations get read before they ship, because a generated drop is "
                "still a drop",
                "Autogenerate is a draft, not an artefact.",
                ("read what it generated before merging", "it'll happily write a drop table"),
            ),
            sup(
                "test-schema-parity",
                "The test schema has to match the real one, or migration-only objects are silently "
                "untestable",
                "This is how a feature ships that no test could ever have exercised.",
                ("if the tests build the schema differently you're not testing the real thing",),
            ),
            bonus(
                "restore-drill",
                "A rehearsed restore is what makes 'we have backups' a true sentence",
                "Backups nobody has restored are a belief, not a control.",
                ("actually practise a restore and time it",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "The scariest one isn't a bad migration, it's a correct one that ran in the wrong "
                "place -- the config falls back to whatever's in the environment and someone runs "
                "it against production by accident, and you don't find out until later. So I'd "
                "give the migration its own explicit setting, pin it per environment rather than "
                "sharing one variable, make it fail if it isn't set instead of defaulting, and "
                "print which database it's about to touch. Then ordering: one place owns applying "
                "them, take a lock so two deploys don't run them at once, and the tool records "
                "which ones already ran. I'd also read what it generated before merging, because "
                "it'll happily write a drop table, and make sure the tests don't build the schema "
                "differently, or you're not testing the real thing.",
                {
                    "wrong-target-database": "covered",
                    "pin-the-target-explicitly": "covered",
                    "serialise-and-record": "covered",
                    "review-generated-migrations": "covered",
                    "test-schema-parity": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "It's fine as long as everyone is careful. The migration tool tracks which "
                "migrations have run so it won't apply them twice, and it knows which database to "
                "connect to from the config.",
                {
                    "wrong-target-database": "contradicted",
                    "pin-the-target-explicitly": "missing",
                    "serialise-and-record": "partial",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # relational-modelling
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="relational-modelling",
        seniority=MID,
        neutral_wording=(
            "You're modelling orders, customers and products for a shop. Walk me through the "
            "tables you'd create and how they relate."
        ),
        reframe_wording=(
            "Put it another way: sketch the shape of the data. What is a row in each table, and "
            "how does one table point at another?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "one-fact-in-one-place",
                "Each fact lives in exactly one row in one table, and other tables point at it "
                "rather than repeating it",
                "This is what makes an update a single write instead of a hunt.",
                (
                    "you store the customer once and reference it",
                    "don't copy the same information into every order",
                    "otherwise you have to update it in ten places",
                    "each thing has one home",
                ),
                "Think about what happens when a customer changes their address.",
                ("copying the data into each table is fine if you keep it in sync",),
            ),
            core(
                "relationships-need-a-join-table",
                "A many-to-many relationship can't be expressed with a column on either side, so "
                "it needs its own table holding the pair",
                "The line item table is where most of the interesting data actually lives.",
                (
                    "an order has many products and a product is in many orders",
                    "you need a table in between holding both ids",
                    "the line items table",
                    "one row per product per order",
                ),
                "Think about where you'd put the quantity of a product on a particular order.",
            ),
            core(
                "snapshot-what-must-not-change",
                "Some values must be frozen at the time of the event -- the price on an order is "
                "the price it was sold at, not today's price",
                "Getting this wrong silently rewrites financial history the next time a price changes.",
                (
                    "store the price on the line item, not just a link to the product",
                    "otherwise old orders change when you change the price",
                    "you need what it cost at the time",
                    "copy the value in deliberately because it's a historical fact",
                ),
                "Think about opening a two-year-old invoice after a price rise.",
                ("always reference rather than copy; duplication is always wrong",),
            ),
            sup(
                "constraints-express-the-rules",
                "Foreign keys, not-null and unique constraints put the rules in the database "
                "rather than hoping every writer remembers them",
                "The database is the only writer that sees every other writer.",
                ("put a foreign key on it", "the database enforces it, not just the app"),
            ),
            sup(
                "surrogate-vs-natural-key",
                "An internal id that never changes is safer as a primary key than a business "
                "value that might",
                "Business values change; primary keys shouldn't have to.",
                ("don't use the email as the key, people change it",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "I'd have customers, products and orders, and you store the customer once and "
                "reference it from the order rather than copying it in -- otherwise you have to "
                "update it in ten places. An order has many products and a product is in many "
                "orders, so I need a table in between holding both ids, the line items table, one "
                "row per product per order, and that's where quantity lives. Importantly I'd "
                "store the price on the line item, not just a link to the product, otherwise old "
                "orders change when you change the price -- you need what it cost at the time. "
                "I'd put a foreign key on it so the database enforces it, not just the app, and "
                "I wouldn't use the email as the key, people change it.",
                {
                    "one-fact-in-one-place": "covered",
                    "relationships-need-a-join-table": "covered",
                    "snapshot-what-must-not-change": "covered",
                    "constraints-express-the-rules": "covered",
                    "surrogate-vs-natural-key": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd have an orders table with the customer name, address and the product names "
                "and prices in columns. That keeps it simple and fast because you don't need "
                "joins. If the customer changes address we update all their orders.",
                {
                    "one-fact-in-one-place": "contradicted",
                    "relationships-need-a-join-table": "missing",
                    "snapshot-what-must-not-change": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="relational-modelling",
        seniority=SENIOR,
        neutral_wording=(
            "A table in production has grown a dozen nullable columns that only apply to some "
            "rows, and nobody is sure which combinations are valid. How would you fix it?"
        ),
        reframe_wording=(
            "Another way in: the table is modelling several different things at once and the "
            "nulls are the evidence. What do you do about it, on live data?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.DECISION,
        concepts=(
            core(
                "nulls-signal-conflated-entities",
                "Columns that only apply to some rows usually mean several different things are "
                "sharing one table, and the nulls are the seam showing",
                "Naming the smell correctly is what makes the fix obvious rather than cosmetic.",
                (
                    "the table is doing more than one job",
                    "those rows are actually different kinds of thing",
                    "the nulls tell you where the split is",
                    "it's two entities crammed into one table",
                ),
                "Think about what the empty columns have in common across the rows that have them.",
                ("nullable columns are just a normal way to model optional data",),
            ),
            core(
                "make-invalid-states-unrepresentable",
                "Once split, the constraints can express which combinations are legal, so bad "
                "rows become impossible rather than merely discouraged",
                "A rule the database can't enforce is a rule that will be broken.",
                (
                    "then you can add constraints that actually hold",
                    "the invalid combination can't be written at all",
                    "a check constraint instead of a convention",
                    "make the bad state impossible rather than documented",
                ),
                "Think about the difference between a rule in a wiki and a rule the database enforces.",
                ("documenting the valid combinations is equivalent to enforcing them",),
            ),
            core(
                "migrate-without-downtime",
                "The change ships in expand/contract steps -- write both, backfill, move reads, "
                "then drop -- because old and new code run at the same time",
                "The model change is easy; doing it to a live table is the actual work.",
                (
                    "add the new tables and write to both for a while",
                    "backfill in batches",
                    "move reads over, then stop writing the old ones",
                    "both versions of the code are live during the deploy",
                ),
                "Think about the thirty seconds mid-deploy when both versions are serving.",
            ),
            sup(
                "views-keep-callers-working",
                "A view in the old shape lets existing queries keep working while callers migrate",
                "Reduces the blast radius from every caller to one.",
                ("put a view over it with the old column names",),
            ),
            sup(
                "when-not-to-split",
                "If the columns genuinely are optional attributes of one thing, splitting adds "
                "joins for no gain -- the test is whether the rules differ, not whether nulls exist",
                "Knowing when *not* to normalise is the senior half of the answer.",
                ("if it's really one thing with optional fields, leave it alone",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "A dozen nullable columns usually means the table is doing more than one job -- "
                "those rows are actually different kinds of thing, and the nulls tell you where "
                "the split is. Once you split it you can add constraints that actually hold, so "
                "the invalid combination can't be written at all rather than being documented "
                "somewhere. For the migration I'd add the new tables and write to both for a "
                "while, backfill in batches, then move reads over and stop writing the old ones, "
                "because both versions of the code are live during the deploy. I'd put a view over "
                "it with the old column names so existing queries keep working. That said, if it's "
                "really one thing with optional fields, leave it alone -- the test is whether the "
                "rules differ.",
                {
                    "nulls-signal-conflated-entities": "covered",
                    "make-invalid-states-unrepresentable": "covered",
                    "migrate-without-downtime": "covered",
                    "views-keep-callers-working": "covered",
                    "when-not-to-split": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "Nullable columns are a normal way to model optional data, so I'd document which "
                "combinations are valid in the wiki and add validation in the application layer. "
                "If we did want to change it I'd write a migration that splits the table and "
                "deploy it with the code change.",
                {
                    "nulls-signal-conflated-entities": "contradicted",
                    "make-invalid-states-unrepresentable": "contradicted",
                    "migrate-without-downtime": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # normalisation-tradeoffs
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="normalisation-tradeoffs",
        seniority=MID,
        neutral_wording=(
            "Someone proposes copying the customer's name onto the orders table so the list page "
            "doesn't need a join. What would you say?"
        ),
        reframe_wording=(
            "Same question differently: what do you gain and what do you take on by storing the "
            "same value in two places?"
        ),
        expected_minutes=4,
        concepts=(
            core(
                "duplication-buys-reads-costs-writes",
                "Copying a value makes the read cheaper and makes every future write responsible "
                "for keeping both copies in step",
                "This is the trade, and naming both halves is the whole answer.",
                (
                    "you save the join but now you have two copies to keep in sync",
                    "reads get faster, writes get more complicated",
                    "someone has to update both when it changes",
                    "you're trading correctness risk for speed",
                ),
                "Think about what has to happen the next time that value changes.",
                ("duplicating data is always wrong",),
            ),
            core(
                "drift-is-the-real-failure",
                "The copies eventually disagree, and the bug shows up as one screen saying "
                "something different from another with no error anywhere",
                "Silent divergence is worse than a slow query because nobody gets paged.",
                (
                    "they drift apart and nothing tells you",
                    "one page shows the old name and another the new one",
                    "there's no error, just wrong data",
                    "you find out from a support ticket",
                ),
                "Think about how you would first learn that the two copies disagree.",
                ("a nightly job that re-syncs the copies makes duplication safe",),
            ),
            sup(
                "measure-before-denormalising",
                "Find out whether the join is actually the problem before paying for duplication",
                "Most 'slow because of the join' claims don't survive an EXPLAIN.",
                ("check whether the join is really the bottleneck first", "look at the plan"),
            ),
            sup(
                "sometimes-it-is-a-snapshot",
                "If the value must be frozen at that moment -- a price, an address on a shipped "
                "order -- it isn't duplication at all, it's a different fact",
                "Distinguishing a cache from a historical record is the useful line.",
                ("if it's what it was at the time, that's a different thing entirely",),
            ),
            bonus(
                "keep-it-in-sync-mechanically",
                "If you do duplicate, the synchronisation should be mechanical rather than "
                "remembered -- a trigger, or a single writer",
                "Discipline decays; mechanism doesn't.",
                ("have one place that owns writing both",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "You save the join but now you have two copies to keep in sync, so reads get "
                "faster and writes get more complicated -- someone has to update both when it "
                "changes. The failure mode is that they drift apart and nothing tells you: one "
                "page shows the old name and another the new one, there's no error, just wrong "
                "data, and you find out from a support ticket. So first I'd check whether the "
                "join is really the bottleneck by looking at the plan. The exception is if it's "
                "what it was at the time -- that's a different thing entirely, not a copy. And if "
                "we do it, I'd have one place that owns writing both.",
                {
                    "duplication-buys-reads-costs-writes": "covered",
                    "drift-is-the-real-failure": "covered",
                    "measure-before-denormalising": "covered",
                    "sometimes-it-is-a-snapshot": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "Duplicating data is always wrong, it breaks normalisation. I'd tell them no and "
                "keep the join. Databases are good at joins so it will be fine.",
                {
                    "duplication-buys-reads-costs-writes": "contradicted",
                    "drift-is-the-real-failure": "missing",
                    "measure-before-denormalising": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="normalisation-tradeoffs",
        seniority=SENIOR,
        neutral_wording=(
            "A reporting page aggregates across several large tables and takes eight seconds. "
            "What are your options, and how would you choose between them?"
        ),
        reframe_wording=(
            "Another angle: the query is correct but too slow to serve. What are the ways out, "
            "and what does each one cost you?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.DECISION,
        concepts=(
            core(
                "understand-the-plan-first",
                "Before changing the data model, find out where the eight seconds actually go -- "
                "the fix for a bad plan is different from the fix for genuine volume",
                "Restructuring data to fix a missing index is expensive and doesn't help.",
                (
                    "run explain analyze and see where the time goes",
                    "is it scanning something it shouldn't",
                    "find out if it's the volume or the plan",
                    "measure before you restructure",
                ),
                "Think about the difference between a query doing too much work and a query doing "
                "the right work slowly.",
                ("an aggregate over large tables is inherently slow, so caching is the only option",),
            ),
            core(
                "precompute-the-answer",
                "If the numbers genuinely take that long to compute, compute them ahead of time "
                "into a table the page reads directly",
                "This is the option that actually scales with data volume rather than hiding it.",
                (
                    "maintain a summary table",
                    "compute it on a schedule or as the data changes",
                    "the page reads one small table instead of aggregating",
                    "a materialised view",
                ),
                "Think about doing the work before the user arrives rather than while they wait.",
                ("a materialised view stays perfectly up to date automatically",),
            ),
            core(
                "staleness-is-the-price",
                "Any precomputed answer is out of date by some amount, and how much is a product "
                "decision rather than a technical one",
                "Choosing the refresh interval without asking is how you ship wrong numbers.",
                (
                    "it's going to be a few minutes behind",
                    "you have to agree how stale is acceptable",
                    "that's a question for the people using the report",
                    "real-time and precomputed are a trade, not a ranking",
                ),
                "Think about who gets to decide whether a number that's ten minutes old is fine.",
            ),
            sup(
                "incremental-beats-full-rebuild",
                "Updating the summary as data changes scales better than periodically "
                "recomputing everything",
                "Full rebuilds get slower exactly as the problem gets worse.",
                ("update it as things change rather than rebuilding the whole thing",),
            ),
            sup(
                "keep-the-source-of-truth-normalised",
                "The precomputed table is a derived read model; the normalised tables stay "
                "authoritative so it can always be rebuilt",
                "A derived value you can't regenerate is a liability.",
                ("you can always throw it away and rebuild from the real tables",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "First I'd run explain analyze and see where the time goes -- is it scanning "
                "something it shouldn't, or is it genuinely the volume? Measure before you "
                "restructure. If it really is the volume, I'd maintain a summary table computed "
                "on a schedule or as the data changes, so the page reads one small table instead "
                "of aggregating. The price is that it's going to be a few minutes behind, and you "
                "have to agree how stale is acceptable -- that's a question for the people using "
                "the report, not for me. I'd update it as things change rather than rebuilding the "
                "whole thing, and keep the normalised tables authoritative so you can always throw "
                "the summary away and rebuild from the real tables.",
                {
                    "understand-the-plan-first": "covered",
                    "precompute-the-answer": "covered",
                    "staleness-is-the-price": "covered",
                    "incremental-beats-full-rebuild": "covered",
                    "keep-the-source-of-truth-normalised": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "Aggregating over large tables is inherently slow, so I'd put a cache in front of "
                "the endpoint with a long TTL. That makes the page fast without changing the "
                "database.",
                {
                    "understand-the-plan-first": "contradicted",
                    "precompute-the-answer": "partial",
                    "staleness-is-the-price": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # when-indexes-dont-help
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="when-indexes-dont-help",
        seniority=MID,
        neutral_wording=(
            "You added an index for a slow query and the query is exactly as slow as before. "
            "What are the possible reasons?"
        ),
        reframe_wording=(
            "Put it another way: the index exists, the query still crawls. Where would you look?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "the-planner-may-be-ignoring-it",
                "The database chooses whether to use an index, and if it expects most rows to "
                "match it will read the table directly instead -- which is usually the right call",
                "Understanding that it's a choice, not a command, redirects the whole investigation.",
                (
                    "the database decided not to use it",
                    "if most rows match, reading the table is cheaper",
                    "it's a cost decision, not an instruction",
                    "the plan shows a scan even though the index exists",
                ),
                "Think about who actually decides whether that index gets used.",
                ("creating an index guarantees the query will use it",),
            ),
            core(
                "the-expression-must-match",
                "Wrapping the column in a function, or comparing it to a different type, means "
                "the index on the raw column no longer applies",
                "This is the most common reason a perfectly good index sits unused.",
                (
                    "you're calling a function on the column",
                    "lower(email) can't use an index on email",
                    "the types don't match so it casts and gives up",
                    "the index is on the column, not on the expression",
                ),
                "Think about whether the thing you're searching for is literally what's stored in "
                "the index.",
                ("an index on the column also covers functions applied to it",),
            ),
            core(
                "the-index-may-be-the-wrong-shape",
                "A multi-column index only serves queries that use its leading columns, so an "
                "index in the wrong order doesn't apply",
                "Right columns, wrong order, no benefit.",
                (
                    "the column order is wrong for this query",
                    "it can only be used from the left",
                    "the filter isn't on the first column",
                    "the sort direction doesn't match",
                ),
                "Think about a phone book sorted by surname when you only know the first name.",
            ),
            sup(
                "stale-statistics",
                "The planner decides from statistics about the data, and if those are out of date "
                "it makes the decision on stale information",
                "A perfectly good index loses to a bad estimate.",
                ("the stats are out of date so it's guessing wrong", "run analyze"),
            ),
            sup(
                "the-time-is-somewhere-else",
                "The lookup may never have been the slow part -- sorting, returning a huge result "
                "set, or the network can dominate",
                "You can only speed up the part that's actually slow.",
                ("maybe the index lookup was never the bottleneck",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "First possibility is the database decided not to use it -- it's a cost decision, "
                "not an instruction, and if most rows match then reading the table is cheaper. "
                "Second, you might be calling a function on the column: lower(email) can't use an "
                "index on email, because the index is on the column, not on the expression. Third, "
                "the column order is wrong for this query -- it can only be used from the left, so "
                "if the filter isn't on the first column it won't apply. It's also worth checking "
                "the stats are out of date so it's guessing wrong, and honestly, maybe the index "
                "lookup was never the bottleneck. The plan tells you which of these it is.",
                {
                    "the-planner-may-be-ignoring-it": "covered",
                    "the-expression-must-match": "covered",
                    "the-index-may-be-the-wrong-shape": "covered",
                    "stale-statistics": "covered",
                    "the-time-is-somewhere-else": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "Creating an index guarantees the query will use it, so the index must be wrong. "
                "I'd add indexes on the other columns too and see if that helps.",
                {
                    "the-planner-may-be-ignoring-it": "contradicted",
                    "the-expression-must-match": "missing",
                    "the-index-may-be-the-wrong-shape": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="when-indexes-dont-help",
        seniority=SENIOR,
        neutral_wording=(
            "A table has fourteen indexes and writes have become slow. How would you decide "
            "which ones to remove, and how would you do it safely?"
        ),
        reframe_wording=(
            "Another way in: someone has been adding an index per slow query for two years. How "
            "do you unwind that without breaking anything?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.EDGE,
        concepts=(
            core(
                "every-index-is-a-write-tax",
                "Each index has to be maintained on every insert, update and delete, so indexes "
                "trade write throughput and storage for read speed",
                "Explains the symptom and why 'just add one more' has a limit.",
                (
                    "every write has to update all of them",
                    "fourteen indexes means fourteen extra bits of work per insert",
                    "you're paying for them on every write",
                    "they cost storage and cache too",
                ),
                "Think about what an INSERT has to do beyond writing the row itself.",
                ("unused indexes are harmless because nothing reads them",),
            ),
            core(
                "measure-usage-before-dropping",
                "The database records which indexes are actually used, so the decision comes from "
                "usage statistics rather than from reading the code",
                "Guessing which index matters is how you drop the one that holds production up.",
                (
                    "check the usage stats to see which ones are never scanned",
                    "the database tracks how often each is used",
                    "look at real traffic, not the code",
                    "watch it over a full cycle including weekly and monthly jobs",
                ),
                "Think about where you'd find evidence that an index has never been read.",
                ("reading the codebase tells you which indexes are used",),
            ),
            core(
                "redundant-prefixes-can-go",
                "An index whose columns are a leading subset of another can usually be dropped, "
                "because the wider one already serves those queries",
                "This is the safest class of removal and often the biggest win.",
                (
                    "if one is the left-hand part of another it's redundant",
                    "the wider index already covers those queries",
                    "an index on a is covered by an index on a and b",
                    "look for overlapping prefixes first",
                ),
                "Think about which queries an index on (a, b) can already answer.",
            ),
            sup(
                "make-it-reversible",
                "Dropping is fast to reverse in principle, but rebuilding a large index takes "
                "time, so the rollback plan is 'invisible first, dropped later'",
                "The safe move is to disable before deleting.",
                ("mark it invisible or unused first and watch, then drop it",),
            ),
            sup(
                "constraints-are-not-just-indexes",
                "Some indexes back a unique or foreign-key constraint, and dropping those changes "
                "correctness, not just performance",
                "A performance change that quietly removes a guarantee is a bad trade.",
                ("check none of them are backing a constraint",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "Every write has to update all of them, so fourteen indexes means fourteen extra "
                "bits of work per insert, plus storage and cache. To decide, I'd check the usage "
                "stats to see which ones are never scanned and watch it over a full cycle "
                "including weekly and monthly jobs, because a report that runs on the first of the "
                "month will look unused for four weeks. The easiest wins are overlapping prefixes: "
                "if one is the left-hand part of another it's redundant, since the wider index "
                "already covers those queries. I'd check none of them are backing a constraint "
                "first, and mark them invisible or unused first and watch, then drop.",
                {
                    "every-index-is-a-write-tax": "covered",
                    "measure-usage-before-dropping": "covered",
                    "redundant-prefixes-can-go": "covered",
                    "make-it-reversible": "covered",
                    "constraints-are-not-just-indexes": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "Unused indexes are harmless because nothing reads them, so the write slowness is "
                "probably something else. I'd look at the server resources. If we did want to "
                "clean up I'd read through the queries in the codebase and drop anything not "
                "mentioned.",
                {
                    "every-index-is-a-write-tax": "contradicted",
                    "measure-usage-before-dropping": "contradicted",
                    "redundant-prefixes-can-go": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # query-planning-and-explain
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="query-planning-and-explain",
        seniority=MID,
        neutral_wording=(
            "You run EXPLAIN on a slow query. What are you actually looking for in the output?"
        ),
        reframe_wording=(
            "Put it differently: the plan is on your screen. What tells you where the problem is?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "the-plan-is-a-tree-of-work",
                "The output describes how the database intends to get the rows -- which tables it "
                "touches, in what order, and how it combines them",
                "Without this framing the output is noise rather than a diagnosis.",
                (
                    "it's showing you the steps it's going to take",
                    "which table it reads first and how it joins the next one",
                    "you read it from the inside out",
                    "each node feeds rows to the one above it",
                ),
                "Think about what the database has to decide before it can run anything.",
                ("the plan is a fixed property of the query text",),
            ),
            core(
                "estimates-versus-reality",
                "The important signal is where the expected row count and the actual row count "
                "diverge, because a wrong estimate produces a wrong plan",
                "This single comparison finds most bad plans, and it needs the analyze variant.",
                (
                    "compare what it expected with what it actually got",
                    "if it thought ten rows and got a million, that's the problem",
                    "you need explain analyze to see the real numbers",
                    "a bad estimate leads it to pick the wrong join strategy",
                ),
                "Think about what happens downstream when the database guesses the size wrong.",
                ("explain shows you how long the query actually took",),
            ),
            core(
                "rows-examined-not-wall-clock",
                "Judge by how much work is being done -- rows read versus rows returned -- rather "
                "than by the timing, which moves with cache state",
                "Timings are noisy; work done is stable and comparable.",
                (
                    "look at how many rows it reads versus how many it returns",
                    "the time changes depending on what's cached",
                    "reading a million to return ten is the smell",
                    "work done is the stable number",
                ),
                "Think about why running the same query twice can give very different timings.",
            ),
            sup(
                "scan-is-not-automatically-bad",
                "Reading the whole table is the right choice when most of it matches; the problem "
                "is a scan where a lookup would do",
                "Prevents the reflex of treating every sequential scan as a defect.",
                ("a full scan is fine if you're reading most of the table",),
            ),
            sup(
                "reproduce-on-real-data",
                "Plans depend on data volume and distribution, so a plan from a small dev database "
                "tells you very little",
                "The plan you need is the one production would choose.",
                ("the plan on your laptop isn't the plan in production",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "It's showing you the steps it's going to take -- which table it reads first and "
                "how it joins the next one -- and you read it from the inside out. The main thing "
                "I look for is comparing what it expected with what it actually got: if it thought "
                "ten rows and got a million, that's the problem, because a bad estimate leads it "
                "to pick the wrong join strategy. You need explain analyze to see the real "
                "numbers. I judge by how many rows it reads versus how many it returns rather than "
                "the timing, because the time changes depending on what's cached. A full scan is "
                "fine if you're reading most of the table. And the plan on your laptop isn't the "
                "plan in production.",
                {
                    "the-plan-is-a-tree-of-work": "covered",
                    "estimates-versus-reality": "covered",
                    "rows-examined-not-wall-clock": "covered",
                    "scan-is-not-automatically-bad": "covered",
                    "reproduce-on-real-data": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "Explain shows you how long the query actually took, so I look at the total time "
                "and find the slowest step. If I see a sequential scan I add an index to get rid "
                "of it.",
                {
                    "the-plan-is-a-tree-of-work": "partial",
                    "estimates-versus-reality": "contradicted",
                    "rows-examined-not-wall-clock": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="query-planning-and-explain",
        seniority=SENIOR,
        neutral_wording=(
            "The same query is fast for most users and very slow for a handful. The plan looks "
            "fine when you run it yourself. How do you investigate?"
        ),
        reframe_wording=(
            "Another framing: it's not slow, it's slow *sometimes*, for particular inputs. Where "
            "does that come from?"
        ),
        expected_minutes=6,
        archetype=QuestionArchetype.EDGE,
        concepts=(
            core(
                "data-skew-changes-the-right-plan",
                "The best plan depends on how many rows the parameter matches, so a value that "
                "matches a hundred rows and one that matches a million want different plans",
                "This is the mechanism behind almost every 'slow for some users' report.",
                (
                    "some values match way more rows than others",
                    "one customer has a million records and everyone else has ten",
                    "the right plan depends on the parameter",
                    "the distribution is uneven",
                ),
                "Think about what is different about the rows those particular users touch.",
                ("if the plan is fine for one input it's fine for all of them",),
            ),
            core(
                "reproduce-with-their-parameters",
                "You have to run the plan with the actual slow values, not with a convenient one, "
                "and ideally capture the plan the server chose in production",
                "Testing with a fast input proves nothing about the slow one.",
                (
                    "run explain with the values that are actually slow",
                    "log the parameters from the slow requests",
                    "capture the plan the server really used",
                    "don't test with a value you picked",
                ),
                "Think about which input you would have to use to see the problem at all.",
                ("any representative parameter will reproduce the plan",),
            ),
            core(
                "cached-plans-can-be-wrong-for-some-inputs",
                "A plan chosen once and reused for different parameters can be badly wrong for "
                "the outliers, even though it was right when it was made",
                "Explains why the same statement is fast and slow with no code change.",
                (
                    "it reuses the plan it made the first time",
                    "the generic plan doesn't suit every parameter",
                    "it was planned for a typical value and this one isn't typical",
                    "forcing a re-plan for those cases can fix it",
                ),
                "Think about what happens when the database decides not to plan the same statement "
                "twice.",
            ),
            sup(
                "statistics-targets-for-skewed-columns",
                "More detailed statistics on a skewed column let the planner see the outliers "
                "instead of assuming an average",
                "Often the smallest change that fixes the whole class.",
                ("increase the statistics detail on that column",),
            ),
            sup(
                "measure-the-tail-not-the-mean",
                "This never shows up in an average; it needs latency percentiles segmented by the "
                "parameter that varies",
                "The dashboard that shows the problem is not the default one.",
                ("look at p99 and break it down per tenant",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "Almost certainly some values match way more rows than others -- one customer has "
                "a million records and everyone else has ten -- so the right plan depends on the "
                "parameter. That means I need to run explain with the values that are actually "
                "slow, so I'd log the parameters from the slow requests and capture the plan the "
                "server really used, because testing with a value I picked proves nothing. The "
                "other thing to check is that it reuses the plan it made the first time: the "
                "generic plan doesn't suit every parameter, and forcing a re-plan for those cases "
                "can fix it. Increasing the statistics detail on that column often helps. And I'd "
                "look at p99 and break it down per tenant, because the average hides this "
                "entirely.",
                {
                    "data-skew-changes-the-right-plan": "covered",
                    "reproduce-with-their-parameters": "covered",
                    "cached-plans-can-be-wrong-for-some-inputs": "covered",
                    "statistics-targets-for-skewed-columns": "covered",
                    "measure-the-tail-not-the-mean": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "If the plan is fine for one input it's fine for all of them, so it's probably not "
                "the query. I'd check whether those users are on a slow network or whether the "
                "server was busy at the time.",
                {
                    "data-skew-changes-the-right-plan": "contradicted",
                    "reproduce-with-their-parameters": "missing",
                    "cached-plans-can-be-wrong-for-some-inputs": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # pessimistic-vs-optimistic-locking
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="pessimistic-vs-optimistic-locking",
        seniority=MID,
        neutral_wording=(
            "Two people have the same record open in two tabs and both press save. What are your "
            "options for handling that, and what does each one feel like to the user?"
        ),
        reframe_wording=(
            "Put it another way: the second save is based on a version of the record that is "
            "already out of date. What can you do about it?"
        ),
        expected_minutes=5,
        concepts=(
            core(
                "the-second-write-is-based-on-stale-data",
                "Without something in the way, the later save overwrites the earlier one and the "
                "first person's change disappears with no error",
                "Naming the lost update is what makes both strategies make sense.",
                (
                    "the second save wipes out the first",
                    "whoever saves last wins and the other change is gone",
                    "nobody gets told anything went wrong",
                    "they both loaded the same starting values",
                ),
                "Think about what happens to the first person's edit, and who finds out.",
                ("the database detects and reports the conflicting update by itself",),
            ),
            core(
                "detect-the-conflict-and-tell-them",
                "The optimistic approach lets both proceed and checks on write whether the record "
                "changed since it was read, rejecting the loser so they can retry",
                "This is the approach that fits a web form, and the rejection is a feature.",
                (
                    "keep a version number and check it hasn't changed",
                    "if it changed since you loaded it, reject the save",
                    "tell them someone else edited it and show the difference",
                    "let them both try and catch the clash at write time",
                ),
                "Think about how the save could know that the record moved underneath it.",
                ("wrapping the update in a transaction prevents the lost update",),
            ),
            core(
                "or-prevent-it-by-holding-a-lock",
                "The pessimistic approach takes a lock while one person edits, so the second is "
                "blocked or told the record is in use",
                "The right choice when a conflict is expensive or common.",
                (
                    "lock the row while they're editing",
                    "the second person is told it's checked out",
                    "nobody can start conflicting work in the first place",
                    "you stop it happening instead of detecting it after",
                ),
                "Think about stopping the second person before they do the work, rather than after.",
            ),
            sup(
                "contention-decides-which",
                "Optimistic suits rare conflicts; pessimistic suits frequent ones, because "
                "constant retries are worse than waiting",
                "The choice is empirical, not ideological.",
                ("if they clash all the time, retrying is worse than waiting",),
            ),
            sup(
                "holding-locks-across-think-time-is-dangerous",
                "A lock held while a human decides can be held for hours, so pessimistic locking "
                "over a web form needs a timeout or a lease",
                "This is how pessimistic locking goes wrong in practice.",
                ("you can't hold a database lock while someone goes to lunch",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "By default the second save wipes out the first -- whoever saves last wins and the "
                "other change is gone, and nobody gets told anything went wrong. The option I'd "
                "usually pick is to keep a version number and check it hasn't changed: if it "
                "changed since you loaded it, reject the save and tell them someone else edited "
                "it. The alternative is to lock the row while they're editing so the second person "
                "is told it's checked out, which stops it happening instead of detecting it after. "
                "Which one depends on how often they clash -- if they clash all the time, retrying "
                "is worse than waiting. But you can't hold a database lock while someone goes to "
                "lunch, so that needs a lease.",
                {
                    "the-second-write-is-based-on-stale-data": "covered",
                    "detect-the-conflict-and-tell-them": "covered",
                    "or-prevent-it-by-holding-a-lock": "covered",
                    "contention-decides-which": "covered",
                    "holding-locks-across-think-time-is-dangerous": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "Wrapping the update in a transaction prevents the lost update, because "
                "transactions are atomic. So as long as both saves are in transactions the data "
                "will be consistent.",
                {
                    "the-second-write-is-based-on-stale-data": "partial",
                    "detect-the-conflict-and-tell-them": "contradicted",
                    "or-prevent-it-by-holding-a-lock": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="pessimistic-vs-optimistic-locking",
        seniority=SENIOR,
        neutral_wording=(
            "You're adding concurrency control to a long-running multi-step workflow where each "
            "step can be retried. How would you approach it, and what would you watch for?"
        ),
        reframe_wording=(
            "Another framing: the work spans minutes and several requests, and any step can be "
            "replayed. Where does the concurrency control live?"
        ),
        expected_minutes=7,
        archetype=QuestionArchetype.SCENARIO,
        concepts=(
            core(
                "locks-do-not-span-requests",
                "A database lock lives for a transaction, so it cannot protect work that spans "
                "several requests or minutes of waiting",
                "Trying to stretch a lock across a workflow is the mistake this question probes.",
                (
                    "the lock ends when the transaction ends",
                    "you can't hold one across multiple requests",
                    "a long transaction just holds resources and blocks everyone",
                    "the workflow outlives the connection",
                ),
                "Think about how long a database lock can actually last, and what it costs while "
                "it does.",
                ("hold a transaction open for the duration of the workflow",),
            ),
            core(
                "make-each-step-idempotent",
                "Because steps are retried, each one has to be safe to run twice -- the second "
                "run either does nothing or produces the same result",
                "Retry safety replaces mutual exclusion for most of the workflow.",
                (
                    "each step has to be safe to run again",
                    "the second attempt should be a no-op",
                    "key it so a repeat is recognised",
                    "you get at-least-once, so build for it",
                ),
                "Think about what the second run of a step should do differently from the first.",
                ("if steps are retried the queue guarantees they run exactly once",),
            ),
            core(
                "guard-the-state-transition",
                "Concurrency is controlled by making the *transition* atomic -- move the row from "
                "one state to the next in a single conditional update, and let the loser lose",
                "This is the mechanism that replaces a long lock, and it's a single statement.",
                (
                    "update the row only if it's still in the previous state",
                    "one statement that changes the status, and check it affected a row",
                    "whoever doesn't get the update just stops",
                    "the state column is the lock",
                ),
                "Think about how one worker can claim a job so that a second worker can tell it "
                "has been claimed.",
            ),
            sup(
                "leases-for-stuck-work",
                "A claim needs an expiry, or a worker that dies leaves the item claimed forever",
                "Every claim mechanism needs an answer for the crash case.",
                ("give the claim a timeout so a dead worker doesn't block it forever",),
            ),
            sup(
                "compensate-rather-than-roll-back",
                "Work already committed in an earlier step can't be rolled back by a later "
                "failure, so failures are handled by compensating actions",
                "Distributed work has no global rollback; naming that is the senior signal.",
                ("you can't undo the earlier steps, you have to compensate for them",),
            ),
            bonus(
                "observability-of-stuck-items",
                "Anything that can be claimed can be stuck, so the states need to be visible and "
                "queryable",
                "You will need to find the wedged items at 3am.",
                ("you need to be able to query what's stuck and for how long",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "The first thing is that the lock ends when the transaction ends -- you can't hold "
                "one across multiple requests, and a long transaction just holds resources and "
                "blocks everyone. So instead I'd make each step safe to run again, keyed so a "
                "repeat is recognised, because you get at-least-once and should build for it. For "
                "the actual concurrency I'd guard the transition: update the row only if it's "
                "still in the previous state, one statement, and check it affected a row -- "
                "whoever doesn't get the update just stops. The state column is the lock. I'd give "
                "the claim a timeout so a dead worker doesn't block it forever, and accept that you "
                "can't undo the earlier steps, you have to compensate for them. And you need to be "
                "able to query what's stuck and for how long.",
                {
                    "locks-do-not-span-requests": "covered",
                    "make-each-step-idempotent": "covered",
                    "guard-the-state-transition": "covered",
                    "leases-for-stuck-work": "covered",
                    "compensate-rather-than-roll-back": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "I'd hold a transaction open for the duration of the workflow and take a row lock "
                "at the start, so nothing else can touch it until we're done. If a step fails the "
                "whole thing rolls back cleanly.",
                {
                    "locks-do-not-span-requests": "contradicted",
                    "make-each-step-idempotent": "missing",
                    "guard-the-state-transition": "missing",
                },
            ),
        ),
    ),
    # ══════════════════════════════════════════════════════════════════════
    # sql-vs-nosql-tradeoffs
    # ══════════════════════════════════════════════════════════════════════
    QuestionSpec(
        competency_id="sql-vs-nosql-tradeoffs",
        seniority=MID,
        neutral_wording=(
            "Someone on your team wants to use a document database for a new feature instead of "
            "the relational one you already run. How would you think about that?"
        ),
        reframe_wording=(
            "Put it differently: what would actually have to be true about this feature for a "
            "different kind of database to be the right call?"
        ),
        expected_minutes=5,
        archetype=QuestionArchetype.DECISION,
        concepts=(
            core(
                "access-pattern-drives-the-choice",
                "The question is how the data will be read and written -- always fetched as one "
                "whole object, or queried and combined in ways you can't predict",
                "This is the actual decision criterion; everything else is downstream of it.",
                (
                    "how are you going to read it",
                    "if you always fetch the whole document as one thing, that fits",
                    "if you need to query across it in ways you can't predict, it doesn't",
                    "the shape of the queries decides, not the shape of the data",
                ),
                "Think about the queries you'll need in a year, not the object you're storing today.",
                ("document databases are faster, so they're the better default",),
            ),
            core(
                "you-give-up-cross-entity-guarantees",
                "Relational databases give you joins and constraints across entities; giving "
                "those up means the application has to maintain the relationships itself",
                "Naming what you lose is what makes this a trade rather than a preference.",
                (
                    "you lose joins and have to do it in the application",
                    "no foreign keys, so nothing stops an orphan",
                    "the database won't enforce the relationship for you",
                    "consistency across documents becomes your problem",
                ),
                "Think about what stops a record pointing at something that no longer exists.",
                ("application-level checks give the same guarantee as a foreign key",),
            ),
            core(
                "a-second-datastore-has-a-fixed-cost",
                "Adding a database means another thing to operate, back up, restore, monitor and "
                "secure, and that cost is paid forever regardless of the feature's size",
                "At small scale this cost usually dominates the technical argument.",
                (
                    "now there's another thing to back up and monitor",
                    "someone has to learn to operate it",
                    "you can't do a transaction across the two",
                    "the operational cost doesn't scale down",
                ),
                "Think about who restores it at 3am, and whether they've done it before.",
            ),
            sup(
                "json-in-a-relational-database",
                "Modern relational databases store and index semi-structured columns, which often "
                "gets the flexibility without a second system",
                "Frequently the answer that resolves the disagreement.",
                ("you can store json in postgres and index it",),
            ),
            sup(
                "hard-to-reverse",
                "Choosing a datastore is expensive to undo once data lives in it, so it deserves "
                "more scrutiny than a reversible choice",
                "Weighting decisions by reversibility is the useful instinct.",
                ("this is hard to walk back once there's data in it",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "I'd start with how are you going to read it -- if you always fetch the whole "
                "document as one thing, that fits, but if you need to query across it in ways you "
                "can't predict, it doesn't. The shape of the queries decides, not the shape of the "
                "data. The thing you give up is joins, so you have to do it in the application, "
                "and there are no foreign keys, so nothing stops an orphan. And now there's "
                "another thing to back up and monitor, someone has to learn to operate it, and you "
                "can't do a transaction across the two. Usually I'd point out you can store json "
                "in postgres and index it, which gets the flexibility without a second system. "
                "This is hard to walk back once there's data in it.",
                {
                    "access-pattern-drives-the-choice": "covered",
                    "you-give-up-cross-entity-guarantees": "covered",
                    "a-second-datastore-has-a-fixed-cost": "covered",
                    "json-in-a-relational-database": "covered",
                    "hard-to-reverse": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "Document databases are faster and scale better, so they're the better default for "
                "anything new. I'd say yes, since the schema flexibility means we can move quicker "
                "and won't need migrations.",
                {
                    "access-pattern-drives-the-choice": "contradicted",
                    "you-give-up-cross-entity-guarantees": "missing",
                    "a-second-datastore-has-a-fixed-cost": "missing",
                },
            ),
        ),
    ),
    QuestionSpec(
        competency_id="sql-vs-nosql-tradeoffs",
        seniority=SENIOR,
        neutral_wording=(
            "A team wants to move one high-traffic table out of the main database into a separate "
            "key-value store. What would you want to know first, and how would you de-risk it?"
        ),
        reframe_wording=(
            "Another angle: the extraction might be right. What has to be established before you'd "
            "agree, and how would you do it without a big-bang cutover?"
        ),
        expected_minutes=7,
        archetype=QuestionArchetype.DECISION,
        concepts=(
            core(
                "establish-what-problem-it-solves",
                "Find out which measured limit is being hit -- write throughput, storage, "
                "contention, latency -- because different limits have different, often cheaper, fixes",
                "Extraction is an expensive answer, so the question deserves evidence first.",
                (
                    "what exactly are we hitting, in numbers",
                    "is it writes, size, or lock contention",
                    "the cheaper fix might be an index or a partition",
                    "show me the graph before we move anything",
                ),
                "Think about which measurement would distinguish 'we need a new datastore' from "
                "'we need a different index'.",
                ("moving a hot table out is a standard scaling step and doesn't need justifying",),
            ),
            core(
                "losing-the-transaction-boundary",
                "Once the table lives elsewhere, writes that used to be atomic with the rest are "
                "no longer, so partial failure becomes a real state the code must handle",
                "This is the correctness cost, and it is usually underestimated.",
                (
                    "you can't write both in one transaction any more",
                    "one can succeed and the other fail",
                    "you need an outbox or a compensating action",
                    "partial state becomes something you have to handle",
                ),
                "Think about a request that writes to both stores and fails halfway.",
                ("a distributed transaction across the two stores is the normal fix",),
            ),
            core(
                "migrate-with-dual-writes-and-shadow-reads",
                "You write to both for a period, read from the old one while comparing against "
                "the new, then flip reads once they agree -- with the flip reversible",
                "This is what makes the change safe rather than brave.",
                (
                    "write to both for a while",
                    "read from the old and compare against the new in the background",
                    "flip reads behind a flag you can turn off",
                    "backfill the history before you trust it",
                ),
                "Think about how you'd get confidence the new store is right *before* depending on "
                "it.",
            ),
            sup(
                "queries-you-will-lose",
                "Enumerate the queries that currently join against that table, because those are "
                "the ones that stop being possible",
                "The list is usually longer than anyone expects.",
                ("list everything that currently joins to it",),
            ),
            sup(
                "measure-the-flip",
                "Decide up front which numbers say it worked and which say roll back",
                "A cutover without a rollback criterion is a hope.",
                ("agree in advance what would make us turn it back off",),
            ),
        ),
        goldens=(
            GoldenSpec(
                "strong",
                "First, what exactly are we hitting, in numbers -- is it writes, size, or lock "
                "contention? Show me the graph before we move anything, because the cheaper fix "
                "might be an index or a partition. If it is justified, the big cost is that you "
                "can't write both in one transaction any more: one can succeed and the other fail, "
                "so you need an outbox or a compensating action. I'd also list everything that "
                "currently joins to it, because those queries stop being possible. For the "
                "migration I'd write to both for a while, read from the old and compare against the "
                "new in the background, backfill the history, then flip reads behind a flag you can "
                "turn off. And I'd agree in advance what would make us turn it back off.",
                {
                    "establish-what-problem-it-solves": "covered",
                    "losing-the-transaction-boundary": "covered",
                    "migrate-with-dual-writes-and-shadow-reads": "covered",
                    "queries-you-will-lose": "covered",
                    "measure-the-flip": "covered",
                },
            ),
            GoldenSpec(
                "weak",
                "Moving a hot table out is a standard scaling step and doesn't need justifying. "
                "I'd write a migration script to copy the data over, switch the code to the new "
                "store, and deploy. The key-value store will handle the load much better.",
                {
                    "establish-what-problem-it-solves": "contradicted",
                    "losing-the-transaction-boundary": "missing",
                    "migrate-with-dual-writes-and-shadow-reads": "missing",
                },
            ),
        ),
    ),
)
