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
pnpm --dir frontend vitest run src/pages/TaskDetailPage.test.tsx
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
cd python && uv run python mq/consumer.py --interval 1.0  # start async task consumer
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
cd python && uv run pytest tests/mq/test_bus.py tests/mq/test_producer.py tests/mq/test_consumer.py -q
```

Env switches (set inline or in `.env`):
- `MQ_BACKEND=inmemory|kafka|rabbitmq` — message queue backend (default: inmemory)
- `PERSISTENCE_BACKEND=sql|inmemory` — database backend (default: sql, uses MySQL)
- `VECTOR_BACKEND=pgvector|chromadb|stub` — vector DB for incident RAG (default: chromadb)
- `TELEMETRY_BACKEND=logging|noop` — telemetry dispatch

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

Two sync entry points and one auto-routing dispatch endpoint:

```
Browser (React SPA)

  POST /api/review/sync  (direct sync — blocks until Python returns)
    → SyncStrategy.executeSync()
      → ReviewTask (PROCESSING) persisted to DB
      → PythonComputeClient.computeSync() — blocking HTTP → Python POST /ai/review/sync
      → on success: task→SUCCESS, upsert ReviewResult, push SSE, return ReviewSyncResponse
      → on failure: task→FAILED, save error result, rethrow

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

Async path (from /dispatch when routed ASYNC):
  backend publishes to MQ → Python consumer polls → POST /ai/review/async
    → Python calls back Java POST /api/internal/review/callback when done
```

The frontend dev server proxies `/api` to `localhost:8080`, so all API calls go through the Java gateway.

### Java backend (`backend/src/main/java/com/acme/review/`)

| Package | Role |
|---------|------|
| `controller/` | REST endpoints: `ReviewController` (sync/async/dispatch), `TaskController` (task CRUD), `HandoffController` (human review decisions), `InternalCallbackController` (callback from Python) |
| `service/` | `ReviewDispatchFeatureExtractor` (extract diff stats + intent signals), `HeuristicLightweightRouteClassifier` (score-based routing for borderline cases), `ConcurrentMetricsService`, `SseRegistry`, `WebhookDedupService` |
| `service/strategy/` | Strategy pattern — `ReviewStrategyFactory` (bean lookup), `DispatchStrategy` (auto-routing: dedup → load check → features → direct rules → classifier → execute), `SyncStrategy` (task persist → blocking Python HTTP → result persist → SSE), `AsyncStrategy` (MQ publish), `AbstractReviewExecutionStrategy` (template method: Python call lifecycle + error handling) |
| `client/` | `PythonComputeClient` — WebClient-based HTTP calls to Python AI service (`computeSync` with configurable timeout, default 5s) |
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

**LangGraph pipeline** (defined in `app/dependencies.py` → `_build_graph_runner`):

```
diff → classifier → rules → rag → scoring → report
```

Each node is a function in `graph/nodes/` that receives `(GraphState, NodeContext)` and returns `GraphState`. The `GraphRunner` executes nodes sequentially, logs each via `LogService`, and telemetry hooks record success/failure.

**Dependency injection** (`app/dependencies.py`): all singletons use module-level globals + `threading.RLock`. Repositories and MQ backends are swappable via `PERSISTENCE_BACKEND` / `MQ_BACKEND` env vars.

**Repository pattern** (`repositories/`): abstract protocol classes (e.g., `TaskRepository`) with dual implementations — in-memory (`InMemoryTaskRepository`) and SQL via SQLAlchemy/aiosqlite (`SQLTaskRepository`). The `dependencies.py` module picks the right one at startup.

**MQ abstraction** (`mq/`): `ProducerProtocol` with three adapters — `InMemoryProducer`, `KafkaProducerAdapter`, `RabbitMQProducerAdapter`. The consumer (`mq/consumer.py`) polls the queue and invokes `AIService.run()`.

**Tool system** (`tools/`): typed `ToolRegistry` with default tools: `diff_analyzer`, `sql_risk_checker`, `api_breaking_checker`, `incident_search`, `test_coverage_checker`, `config_change_checker`. Tools are injected into `GraphBuilder` and accessible to nodes via `NodeContext.registry`.

### Frontend (`frontend/src/`)

| Path | Role |
|------|------|
| `router/index.tsx` | React Router v7 — `/` (SubmitPage), `/tasks` (TaskDashboardPage), `/tasks/:taskId` (TaskDetailPage), `/results/:taskId` (ResultDetailPage) |
| `api/client.ts` | Generic `http<T>()` wrapper: adds API-key header, trace-id, timeout via AbortController |
| `api/review.ts`, `task.ts`, `logs.ts` | Typed API functions built on `http<T>()` |
| `store/` | Zustand stores with immer middleware: `taskStore`, `resultStore`, `logStore`, `status` |
| `hooks/` | `useTaskPolling` (polls GET /api/review/tasks on interval), `useReviewSubmission` |
| `components/` | Reusable: `ReviewSubmitForm`, `TaskStatusBadge`, `ReviewResultCard`, `LogsPanel`, `ReportDownloadButton` |
| `pages/` | Route-level page components with co-located `*.test.tsx` files |

State management: Zustand + immer for local state (tasks, results, logs); TanStack React Query for server-state and cache invalidation.

### Testing layers

- **Frontend unit**: Vitest + jsdom + `@testing-library/react`. MSW (`src/tests/msw/handlers.ts`) mocks API.
- **Frontend E2E**: Playwright (`e2e/`), `playwright.config.ts` starts production build + preview server on port 4173.
- **Python**: pytest + pytest-asyncio. Fixtures in `tests/conftest.py`. Testcontainers used for integration tests against real DBs.
- **Backend**: JUnit + Mockito + WireMock (for stubbing Python HTTP calls).

## Key design decisions

- **Swappable backends**: MQ supports inmemory (dev/test), Kafka, and RabbitMQ. Persistence supports inmemory and SQL. Controlled via env vars, not code changes.
- **Trace propagation**: `X-Trace-Id` header flows from frontend → Java → Python and back, set at each layer if missing.
- **Health probes**: Both Java and Python expose health endpoints with real dependency checks (not just ping). Python returns `503` if any required dependency is down; skipped backends (e.g., Kafka when `MQ_BACKEND=inmemory`) don't affect health.
- **Async task lifecycle**: Tasks transition `PENDING → IN_PROGRESS → SUCCEEDED | NEED_REVIEW | FAILED`. `NEED_REVIEW` tasks require a human handoff decision (APPROVED/REJECTED) via the handoff endpoint.
