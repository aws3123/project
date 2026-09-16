# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

AI Code Review Sentinel — a three-tier code review automation system. The Java backend is the API gateway; the Python service runs an LLM-powered LangGraph analysis pipeline; the React frontend provides the review submission UI and task dashboard.

## Layer commands

All commands run from the repository root.

### Frontend (`frontend/`)

```bash
pnpm --dir frontend install        # install dependencies (pnpm + pnpm-workspace.yaml)
pnpm --dir frontend dev            # Vite dev server with HMR (proxies /api → localhost:8080)
pnpm --dir frontend build          # type-check (tsc -b) then bundle (vite build)
pnpm --dir frontend lint           # ESLint (flat config: eslint.config.js)
pnpm --dir frontend test           # vitest in watch mode
pnpm --dir frontend test:run       # vitest single run (uses jsdom, globals: true, setup: src/tests/setup.ts)
pnpm --dir frontend test:ci        # lint + test:run + build
pnpm --dir frontend e2e:smoke:chrome  # Playwright E2E (system Chrome)
```

Run a single test file:
```bash
pnpm --dir frontend vitest run src/pages/TaskDashboardPage.test.tsx
```

### Python (`python/`)

Package manager is `uv`. Config: `pyproject.toml` (not pip/poetry).

```bash
cd python && uv sync                              # install deps (including dev: black, ruff, mypy)
cd python && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000  # dev server (omit --reload on Windows, multiprocessing breaks venv inheritance)
cd python && uv run pytest                        # all tests
cd python && uv run ruff check .                  # lint
cd python && uv run black .                       # format
cd python && uv run mypy .                        # type-check (no watch/daemon)
# Kafka async consumer / callback producer start with the app when KAFKA_ENABLED=true
# (no standalone consumer process anymore)
```

Health: `GET http://localhost:8000/ai/health`

If imports fail with ModuleNotFoundError (especially after `uv sync`), the reloader subprocess may be using a wrong interpreter. Run without `--reload`, or use the venv Python directly:
```bash
cd python && .venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Run a specific test file/subset:
```bash
cd python && uv run pytest tests/app/test_health_route.py -q
cd python && uv run pytest tests/graph -q
cd python && uv run pytest tests/repositories -q
```

Env switches (set inline or in `.env`):
- `KAFKA_ENABLED=true|false` — Kafka async link (consumer + callback producer), default false; topics `ai.review.tasks` / `ai.review.callbacks`, see `kafka_*` settings in `config/settings.py`
- `PERSISTENCE_BACKEND=sql|inmemory` — task/result persistence backend (default: inmemory; use `sql` with MySQL in production)
- `TELEMETRY_BACKEND=logging|prometheus|noop` — telemetry output (default: logging)
- `VECTOR_BACKEND=pgvector|chromadb|stub` — legacy variable (referenced only by README/tests; RAG is wired to ChromaDB + Elasticsearch dual-path in code)

### Backend (`backend/`)

Maven project, Spring Boot 3.2.5, Java 17. Group: `com.acme`, artifact: `review-backend`.
No Maven wrapper checked in — use system `mvn` (at `/d/develop/apache-maven-3.9.4/bin/mvn`).

```bash
cd backend && mvn spring-boot:run -Dmaven.test.skip=true  # dev server on port 8080 (skip test compile: tests may lag behind source)
cd backend && mvn test -Dtest="ReviewControllerTest"      # single test class
cd backend && mvn clean package -Dmaven.test.skip=true     # build JAR
```

Active profile defaults to `dev` (SPRING_PROFILES_ACTIVE=dev). Dev config uses H2; prod uses MySQL.

Health: `GET http://localhost:8080/actuator/health`

## Architecture

### Request flow

Three review entry points (sync / async / auto-routing dispatch):

```
Browser (React SPA)

  POST /api/review/sync  (direct sync — blocks until Python returns)
    → SyncStrategy.executeSync()
      → ReviewTask (PROCESSING) persisted to DB
      → PythonComputeClient.computeSync() — blocking HTTP → Python POST /ai/review/sync
      → on success: task→SUCCESS, upsert ReviewResult, push SSE, return ReviewSyncResponse
      → on failure: task→FAILED, save error result, rethrow

  POST /api/review/async  (explicit async — returns 202 + taskId immediately)
    → AsyncStrategy: persist ReviewTask (PENDING) + Outbox event in one transaction
    → publish to Kafka ai.review.tasks → see async path below

  POST /api/review/dispatch  (auto-routing via DispatchStrategy)
    → 1. Webhook dedup (Redisson distributed lock on projectId+prUrl)
    → 2. System load check (queue>70% or active>80% → force ASYNC)
    → 3. FeatureExtractor: diffChars, fileCount, moduleCount, riskSignals, quickIntent, deepIntent
    → 4. Direct rules:
         SYNC: ≤4000 chars, ≤2 files, single module, no risk signals, quick intent
         ASYNC: ≥12000 chars, ≥6 files, multi-module, risk signals, or deep intent
    → 5. HeuristicLightweightRouteClassifier (borderline cases; confidence<0.80 → ASYNC)
    → if SYNC: delegate to SyncStrategy.executeSync() (same path as /sync above)
    → if ASYNC: publish to MQ, return immediately

Async path (from /dispatch when routed ASYNC, or explicit POST /api/review/async):
  backend persists Outbox event in the same transaction → Kafka ai.review.tasks (partition-key=taskId)
    → Python review_consumer (aiokafka) consumes and runs the pipeline
    → callback_producer publishes ai.review.callbacks → Java ReviewCallbackConsumer persists result + pushes SSE
    (state machine: PENDING → PROCESSING → SUCCESS / FAILED / HUMAN_REVIEW)
```

The frontend dev server proxies `/api` to `localhost:8080`, so all API calls go through the Java gateway.

### Java backend (`backend/src/main/java/com/acme/review/`)

| Package | Role |
|---------|------|
| `controller/` | 11 REST controllers: `ReviewController` (sync/async/dispatch), `TaskController` (task CRUD), `FeedbackController`, `HandoffController` (human review decisions), `ChunkController` (BFF AST chunking for Python), `NotificationController`, `BusinessRiskController` / `BusinessRiskSseController` (business risk + SSE), and internals: `InternalReviewPayloadController` (large-payload fetch by Python), `InternalBusinessRiskCallbackController` (Python callback), `InternalBusinessRiskWorkerHeartbeatController` (worker heartbeat) |
| `service/` | `ReviewDispatchFeatureExtractor` (extract diff stats + intent signals), `HeuristicLightweightRouteClassifier` (score-based routing for borderline cases), `ConcurrentMetricsService`, `SseRegistry`, `WebhookDedupService` |
| `service/strategy/` | Strategy pattern — `ReviewStrategyFactory` (bean lookup), `DispatchStrategy` (auto-routing: dedup → load check → features → direct rules → classifier → execute), `SyncStrategy` (task persist → blocking Python HTTP → result persist → SSE), `AsyncStrategy` (MQ publish), `AbstractReviewExecutionStrategy` (template method: Python call lifecycle + error handling) |
| `client/` | `PythonComputeClient` — WebClient calls to Python (connect timeout 3s; sync total budget `orchestrator.sync-timeout-ms`, default 120s, enforced by `SyncStrategy`; SSE stream idle timeout 60s) · `BusinessRiskPythonClient` · `PythonServiceRegistry` (multi-instance Python registry) |
| `mq/` | `OutboxPoller` (delivers Outbox events, SKIP LOCKED + 10 retries), `ReviewCallbackConsumer` (consumes `ai.review.callbacks`), `FeedbackEventConsumer` |
| `ast/` | Tree-Sitter JNI parsing + code chunking (`TreeSitterNativeParser`, `AstChunker`) — CPU-heavy AST work offloaded from Python |
| `job/` | `ReconciliationJob` — 60s reconciliation sweep (rebuilds events for stale PENDING tasks) |
| `aop/` | `BillingAspect` — token metering / billing |
| `config/` | Spring Security (API-key auth via `ApiKeyAuthenticationFilter`), MyBatis-Plus, WebClient, trace-id propagation |
| `entity/` + `repository/` | MyBatis-Plus entities (`ReviewTask`, `ReviewResult`) with type-safe enums via a custom `ReviewTaskStatusTypeHandler` |
| `dto/` | Request/response DTOs: `ReviewSyncRequest/Response`, `ReviewDispatchRequest/Response`, `ReviewDispatchDecision`, `ReviewDispatchFeatures` (record), `DispatchRoute` enum (SYNC/ASYNC), `ReviewMode` enum |
| `health/` | Custom health indicators for `python`, `redisPing`, `mq` |

**Dispatch heuristics** (configurable via `application.yml` `review.dispatch.*` properties):
- Small+simple diffs (≤4000 chars, ≤2 files, single module, no risk signals, quick intent) → SYNC
- Large/risky diffs (≥12000 chars, ≥6 files, multi-module, risk signals, deep intent) → ASYNC
- Borderline cases → heuristic classifier (score-based); confidence < 0.80 degrades to ASYNC
- System under load (queue > 70% or active threads > 80% of max) → force ASYNC regardless of features

### Python AI layer (`python/`)

**Two pipelines** (assembled in `app/dependencies.py` via `GraphBuilder`; nodes live in `graph/nodes/` and receive `(GraphState, NodeContext)` → return `GraphState`):

Code review pipeline (`_build_graph_runner`):

```
diff → classifier → impact → rag (pre-retrieval) → [rules ∥ security ∥ performance] → scoring → report
```

Business risk pipeline (`_build_business_risk_runner`):

```
extract_business_invariants → trace_data_flow → [check_invariants ∥ deep_read_methods ∥ semantic_hotspot_scan] → assess_business_risk → business_risk_rag → verify_business_risks
```

`GraphRunner` runs single-node phases sequentially and multi-node phases in parallel (`as_completed` + per-agent timeout + `CircuitBreaker`), with `agent_selector` dynamically pruning agents, `CheckpointService` for resume, `LogService` logging, and telemetry hooks recording success/failure.

**Dependency injection** (`app/dependencies.py`): all singletons use module-level globals + `threading.RLock`. Repositories are swappable via `PERSISTENCE_BACKEND`; both pipeline runners (code review / business risk) are assembled here.

**Repository pattern** (`repositories/`): abstract protocol classes (e.g., `TaskRepository`) with dual implementations — in-memory (`InMemoryTaskRepository`) and SQL via SQLAlchemy/aiosqlite (`SQLTaskRepository`). The `dependencies.py` module picks the right one at startup.

**MQ** (`mq/`): Kafka-native via aiokafka — `review_consumer.py` consumes `ai.review.tasks` and runs the review pipeline (Redis SETNX dedup + in-process transient retries); `callback_producer.py` publishes state callbacks to `ai.review.callbacks`; `payload_client.py` fetches large payloads from Java. All start with the FastAPI lifespan when `KAFKA_ENABLED=true`.

**Tool system** (`tools/`): typed `ToolRegistry` with 8 default tools: `diff_analyzer`, `sql_risk_checker`, `api_breaking_checker`, `incident_search`, `test_coverage_checker`, `config_change_checker`, plus `ASTParserTool` and `CodeKnowledgeGraphTool` (AST parsing + code knowledge graph, NetworkX weighted BFS impact radius). Tools are injected into `GraphBuilder` and accessible to nodes via `NodeContext.registry`.

### Frontend (`frontend/src/`)

| Path | Role |
|------|------|
| `router/index.tsx` | React Router v7 — `/` (SubmitPage), `/tasks` (TaskDashboardPage), `/code-review/:taskId` (CodeReviewDetailPage), `/business-risk/:taskId` (BusinessRiskDetailPage), `/business-risk/source` (BusinessRiskSourcePage), `/feedback` (FeedbackDashboardPage) |
| `api/client.ts` | Generic `http<T>()` wrapper: adds API-key header, trace-id, timeout via AbortController |
| `api/review.ts`, `task.ts`, `logs.ts`, `stream.ts`, `feedback.ts`, `businessRisk.ts` | Typed API functions built on `http<T>()` (`stream.ts` wraps SSE) |
| `store/` | Zustand stores with immer middleware: `taskStore`, `resultStore`, `logStore`, `status` |
| `hooks/` | `useTaskPolling` (polls GET /api/review/tasks on interval), `useReviewSubmission`, `useBusinessRiskSse` (SSE + Last-Event-ID reconnect), `useInterval` |
| `components/` | Reusable: `ReviewSubmitForm`, `TaskStatusBadge`, `TaskStatusTimeline`, `TaskSummarySidebar`, `ReviewResultCard`, `ReviewProgressPanel`, `LogsPanel`, `ReportDownloadButton`, `FeedbackWidget` |
| `pages/` | Route-level page components with co-located `*.test.tsx` files |

State management: Zustand + immer for local state (tasks, results, logs); TanStack React Query for server-state and cache invalidation.

### Testing layers

- **Frontend unit**: Vitest + jsdom + `@testing-library/react`. MSW (`src/tests/msw/handlers.ts`) mocks API.
- **Frontend E2E**: Playwright (`e2e/`), `playwright.config.ts` starts production build + preview server on port 4173.
- **Python**: pytest + pytest-asyncio. Fixtures in `tests/conftest.py`. Testcontainers used for integration tests against real DBs.
- **Backend**: JUnit + Mockito + WireMock (for stubbing Python HTTP calls).

## Key design decisions

- **Swappable backends**: Persistence supports inmemory and SQL (`PERSISTENCE_BACKEND`, default inmemory). The async link is Kafka-native: Java Spring Cloud Stream publishes, Python aiokafka consumes/produces callbacks, toggled by `KAFKA_ENABLED`. Controlled via env vars, not code changes.
- **Trace propagation**: `X-Trace-Id` header flows from frontend → Java → Python and back, set at each layer if missing.
- **Health probes**: Both Java and Python expose health endpoints with real dependency checks (not just ping). Python returns `503` if any required dependency is down; skipped backends (e.g., Kafka when `KAFKA_ENABLED=false`) don't affect health.
- **Async task lifecycle**: Tasks transition `PENDING → PROCESSING → SUCCESS | FAILED | HUMAN_REVIEW`. `HUMAN_REVIEW` tasks require a human handoff decision (APPROVE/REJECT/MODIFY) via the handoff endpoint.
