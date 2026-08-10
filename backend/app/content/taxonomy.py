"""The closed competency taxonomy (Appendix C.1).

This is the vocabulary IR-4 validates against: reduction may only emit ids from
this list, which is precisely what bounds the damage a hostile document can do
and what makes two candidates comparable.

Deliberately deep on computer engineering and software development, and covers
nothing else (§1.3). Breadth into other industries is a non-goal, not an
oversight.
"""

from __future__ import annotations

from app.content.types import CompetencySpec

D = "databases"
B = "backend-engineering"


def _c(competency_id: str, domain: str, label: str, description: str = "") -> CompetencySpec:
    return CompetencySpec(competency_id, domain, label, description or None)


TAXONOMY: tuple[CompetencySpec, ...] = (
    # ── cs-fundamentals ────────────────────────────────────────────────────
    _c("data-structure-choice", "cs-fundamentals", "Choosing the right data structure"),
    _c("complexity-reasoning", "cs-fundamentals", "Reasoning about complexity"),
    _c("recursion-and-dp", "cs-fundamentals", "Recursion and dynamic programming"),
    _c("sorting-searching-tradeoffs", "cs-fundamentals", "Sorting and searching trade-offs"),
    _c("hashing-and-collisions", "cs-fundamentals", "Hashing and collision handling"),
    # ── os-and-systems ─────────────────────────────────────────────────────
    _c("process-vs-thread", "os-and-systems", "Processes vs threads"),
    _c("concurrency-primitives", "os-and-systems", "Concurrency primitives"),
    _c("deadlock-and-contention", "os-and-systems", "Deadlock and contention"),
    _c("memory-model-stack-heap", "os-and-systems", "Stack, heap, and the memory model"),
    _c("virtual-memory-paging", "os-and-systems", "Virtual memory and paging"),
    _c("garbage-collection", "os-and-systems", "Garbage collection"),
    _c("scheduling", "os-and-systems", "Process scheduling"),
    _c("syscalls-and-io", "os-and-systems", "Syscalls and IO"),
    # ── computer-architecture ──────────────────────────────────────────────
    _c("cache-hierarchy-and-locality", "computer-architecture", "Cache hierarchy and locality"),
    _c("pipelining-and-hazards", "computer-architecture", "Pipelining and hazards"),
    _c("memory-bandwidth-vs-latency", "computer-architecture", "Bandwidth vs latency"),
    _c("endianness-and-representation", "computer-architecture", "Endianness and representation"),
    # ── networking ─────────────────────────────────────────────────────────
    _c("tcp-vs-udp", "networking", "TCP vs UDP"),
    _c("tcp-connection-lifecycle", "networking", "TCP connection lifecycle"),
    _c("http-semantics-and-versions", "networking", "HTTP semantics and versions"),
    _c("dns-resolution", "networking", "DNS resolution"),
    _c("tls-handshake", "networking", "The TLS handshake"),
    _c("load-balancing", "networking", "Load balancing"),
    _c("websockets-vs-sse-vs-polling", "networking", "WebSockets vs SSE vs polling"),
    _c("idempotency-of-http-methods", "networking", "Idempotency of HTTP methods"),
    # ── databases ──────────────────────────────────────────────────────────
    _c("relational-modelling", D, "Relational modelling"),
    _c("normalisation-tradeoffs", D, "Normalisation trade-offs"),
    _c("indexing-strategy", D, "Indexing strategy"),
    _c("when-indexes-dont-help", D, "When indexes don't help"),
    _c("query-planning-and-explain", D, "Query planning and EXPLAIN"),
    _c("transactions-and-acid", D, "Transactions and ACID"),
    _c("isolation-levels-and-anomalies", D, "Isolation levels and anomalies"),
    _c("pessimistic-vs-optimistic-locking", D, "Pessimistic vs optimistic locking"),
    _c("offset-vs-keyset-pagination", D, "Offset vs keyset pagination"),
    _c("sql-vs-nosql-tradeoffs", D, "SQL vs NoSQL trade-offs"),
    _c("connection-pooling", D, "Connection pooling"),
    _c("schema-migration-safety", D, "Safe schema migration"),
    # ── backend-engineering ────────────────────────────────────────────────
    _c("rest-api-design", B, "REST API design"),
    _c("api-versioning", B, "API versioning"),
    _c("idempotency-keys", B, "Idempotency keys"),
    _c("error-contract-design", B, "Error contract design"),
    _c("authentication-mechanisms", B, "Authentication mechanisms"),
    _c("authorization-models", B, "Authorization models"),
    _c("session-and-cookie-security", B, "Session and cookie security"),
    _c("caching-strategies", B, "Caching strategies"),
    _c("cache-invalidation-and-stampede", B, "Cache invalidation and stampede"),
    _c("background-jobs-and-queues", B, "Background jobs and queues"),
    _c("at-least-once-and-idempotent-consumers", B, "At-least-once and idempotent consumers"),
    _c("outbox-pattern", B, "The transactional outbox"),
    _c("rate-limiting", B, "Rate limiting"),
    _c("async-concurrency-model", B, "Async concurrency model"),
    # ── frontend-engineering ───────────────────────────────────────────────
    _c("rendering-strategies-csr-ssr-ssg-isr", "frontend-engineering", "Rendering strategies"),
    _c("server-components", "frontend-engineering", "Server components"),
    _c("react-render-model", "frontend-engineering", "The React render model"),
    _c("hooks-rules-and-pitfalls", "frontend-engineering", "Hooks rules and pitfalls"),
    _c("server-vs-client-state", "frontend-engineering", "Server vs client state"),
    _c("data-fetching-and-invalidation", "frontend-engineering", "Data fetching and invalidation"),
    _c("browser-event-loop", "frontend-engineering", "The browser event loop"),
    _c("bundle-size-and-code-splitting", "frontend-engineering", "Bundle size and code splitting"),
    _c("core-web-vitals", "frontend-engineering", "Core Web Vitals"),
    _c("list-virtualisation", "frontend-engineering", "List virtualisation"),
    _c("accessibility-fundamentals", "frontend-engineering", "Accessibility fundamentals"),
    _c("type-safety-at-api-boundary", "frontend-engineering", "Type safety at the API boundary"),
    # ── system-design ──────────────────────────────────────────────────────
    _c("requirement-clarification", "system-design", "Clarifying requirements"),
    _c("capacity-estimation", "system-design", "Capacity estimation"),
    _c("horizontal-vs-vertical-scaling", "system-design", "Horizontal vs vertical scaling"),
    _c("statelessness-and-session-affinity", "system-design", "Statelessness and session affinity"),
    _c("consistency-models", "system-design", "Consistency models"),
    _c("cap-tradeoffs", "system-design", "CAP trade-offs"),
    _c("partitioning-and-sharding", "system-design", "Partitioning and sharding"),
    _c("replication-and-read-replicas", "system-design", "Replication and read replicas"),
    _c("event-driven-design", "system-design", "Event-driven design"),
    _c("backpressure", "system-design", "Backpressure"),
    _c("timeouts-retries-jitter", "system-design", "Timeouts, retries and jitter"),
    _c("circuit-breakers", "system-design", "Circuit breakers"),
    _c("exactly-once-myth", "system-design", "The exactly-once myth"),
    _c("observability-by-design", "system-design", "Observability by design"),
    # ── devops-cloud ───────────────────────────────────────────────────────
    _c("container-images-and-layers", "devops-cloud", "Container images and layers"),
    _c("container-security-nonroot", "devops-cloud", "Non-root containers"),
    _c("ci-cd-pipeline-design", "devops-cloud", "CI/CD pipeline design"),
    _c("deployment-strategies", "devops-cloud", "Deployment strategies"),
    _c("graceful-shutdown-sigterm", "devops-cloud", "Graceful shutdown on SIGTERM"),
    _c("logs-metrics-traces", "devops-cloud", "Logs, metrics and traces"),
    _c("secrets-management", "devops-cloud", "Secrets management"),
    _c("iac-concepts", "devops-cloud", "Infrastructure as code"),
    _c("serverless-vs-containers", "devops-cloud", "Serverless vs containers"),
    _c("cold-starts", "devops-cloud", "Cold starts"),
    _c("cost-model-reasoning", "devops-cloud", "Cost model reasoning"),
    # ── security ───────────────────────────────────────────────────────────
    _c("injection-classes", "security", "Injection classes"),
    _c("xss-and-output-encoding", "security", "XSS and output encoding"),
    _c("csrf-and-samesite", "security", "CSRF and SameSite"),
    _c("ssrf", "security", "SSRF"),
    _c("broken-access-control-idor", "security", "Broken access control / IDOR"),
    _c("password-storage-hashing", "security", "Password storage and hashing"),
    _c("jwt-pitfalls", "security", "JWT pitfalls"),
    _c("transport-security", "security", "Transport security"),
    _c("dependency-and-supply-chain", "security", "Dependency and supply-chain risk"),
    _c("secret-rotation", "security", "Secret rotation"),
    _c("prompt-injection", "security", "Prompt injection"),
    # ── testing-and-practice ───────────────────────────────────────────────
    _c("test-pyramid-and-boundaries", "testing-and-practice", "Test pyramid and boundaries"),
    _c("test-isolation-and-fixtures", "testing-and-practice", "Test isolation and fixtures"),
    _c("flakiness-diagnosis", "testing-and-practice", "Diagnosing flaky tests"),
    _c("property-based-testing", "testing-and-practice", "Property-based testing"),
    _c("mocking-boundaries", "testing-and-practice", "Mocking boundaries"),
    _c("debugging-methodology", "testing-and-practice", "Debugging methodology"),
    _c("git-branching-model", "testing-and-practice", "Git branching model"),
    _c("rebase-vs-merge", "testing-and-practice", "Rebase vs merge"),
    _c("code-review-practice", "testing-and-practice", "Code review practice"),
    # ── language-runtime (python / js-ts subset) ───────────────────────────
    _c("gil-and-threads", "language-runtime", "Python: the GIL and threads"),
    _c("async-await-model", "language-runtime", "Python: the async/await model"),
    _c("generators-and-iterators", "language-runtime", "Python: generators and iterators"),
    _c("mutable-default-args", "language-runtime", "Python: mutable default arguments"),
    _c("event-loop-microtasks", "language-runtime", "JS/TS: event loop and microtasks"),
    _c("closures-and-scope", "language-runtime", "JS/TS: closures and scope"),
    _c("promise-semantics", "language-runtime", "JS/TS: promise semantics"),
    # ── ai-llm-engineering ─────────────────────────────────────────────────
    _c("prompt-design", "ai-llm-engineering", "Prompt design"),
    _c("context-window-management", "ai-llm-engineering", "Context window management"),
    _c("rag-and-chunking", "ai-llm-engineering", "RAG and chunking"),
    _c("embeddings-and-similarity", "ai-llm-engineering", "Embeddings and similarity"),
    _c("tool-calling", "ai-llm-engineering", "Tool calling"),
    _c("llm-output-evaluation", "ai-llm-engineering", "Evaluating LLM output"),
    _c("cost-latency-tradeoffs", "ai-llm-engineering", "Cost and latency trade-offs"),
    _c("llm-prompt-injection-defence", "ai-llm-engineering", "Prompt-injection defence"),
    # ── behavioural (separate rubric family, C.4) ──────────────────────────
    _c("ownership-and-impact", "behavioural", "Ownership and impact"),
    _c("conflict-and-disagreement", "behavioural", "Conflict and disagreement"),
    _c("failure-and-learning", "behavioural", "Failure and learning"),
    _c("prioritisation-under-constraint", "behavioural", "Prioritisation under constraint"),
    _c("collaboration-and-mentoring", "behavioural", "Collaboration and mentoring"),
    _c("role-motivation-and-fit", "behavioural", "Role motivation and fit"),
)

TAXONOMY_IDS = frozenset(spec.competency_id for spec in TAXONOMY)
