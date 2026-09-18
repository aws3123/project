# Production Docker Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fragmented Docker configuration with a secure, single-host production Compose stack that preserves business source code.

**Architecture:** A root Compose file owns the complete dependency graph and exposes only the frontend on loopback for the host Nginx. Service secrets come from an untracked deployment environment file; application and infrastructure communication stays on private Docker networks.

**Tech Stack:** Docker Compose, Maven/Temurin 17, Python 3.12/uv, Node 22/pnpm, Nginx, MySQL 8.4, Redis 7, Kafka KRaft, MinIO, Elasticsearch, Prometheus, Grafana.

**Spec:** `docs/superpowers/specs/2026-09-18-production-docker-design.md`

## Global Constraints

- Do not modify `backend/src`, `python/app`, or `frontend/src`.
- Do not commit real secrets; use `deploy/production/.env` locally and commit only its example file.
- Bind only the frontend and optional observability interfaces to `127.0.0.1`.
- Keep `python-ai` at one replica because its Chroma client is local-file based.
- All Compose service-to-service URLs use Docker DNS names, never `host-gateway` or host ports.

---

### Task 1: Define production deployment inputs and host gateway contract

**Files:**
- Create: `deploy/production/.env.example`
- Create: `deploy/production/nginx-sentinel.conf.example`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `APP_HOST_PORT`, `MYSQL_*`, `MINIO_*`, `API_KEY`, `CALLBACK_TOKEN`, `LLM_*` values from `deploy/production/.env`.
- Produces: a private Compose variable contract and a host Nginx upstream at `127.0.0.1:${APP_HOST_PORT}`.

- [ ] **Step 1: Write the deployment input template**

Create an example that contains empty secret placeholders and explicit non-secret defaults, including `APP_HOST_PORT=8088`, `MYSQL_DATABASE=review`, `MYSQL_USER=review`, and `GRAFANA_HOST_PORT=3001`.

- [ ] **Step 2: Verify secrets cannot be accidentally committed**

Run: `git check-ignore deploy/production/.env`

Expected: exit code `0` after adding the exact ignore rule while `.env.example` remains tracked.

- [ ] **Step 3: Add the host Nginx example**

Provide a `server` block that redirects HTTP to HTTPS and proxies the TLS virtual host to `http://127.0.0.1:8088`, with WebSocket/SSE-safe HTTP/1.1 headers and 300-second read timeout.

### Task 2: Replace the production Compose topology

**Files:**
- Create: `compose.yaml`
- Delete: `docker-compose.yml`
- Delete: `docker-compose.infra.yml`
- Delete: `docker-compose.python-scale.yml`
- Delete: `python/docker-compose.yml`

**Interfaces:**
- Consumes: `deploy/production/.env` and the three service Dockerfiles.
- Produces: `frontend`, `java-backend`, `python-ai`, `mysql`, `redis`, `minio`, `minio-init`, `kafka`, `kafka-init`, `elasticsearch`, `prometheus`, and `grafana` services.

- [ ] **Step 1: Write a failing Compose structural check**

Run: `docker compose --env-file deploy/production/.env.example -f compose.yaml config`

Expected before creation: failure because `compose.yaml` does not exist.

- [ ] **Step 2: Implement the complete private topology**

Define internal `app-net` and `observability-net` networks, named data volumes, health checks for dependencies, one-shot MinIO/Kafka initializers, `restart: unless-stopped`, log rotation, and dependency conditions. Publish only `127.0.0.1:${APP_HOST_PORT}:80`, `127.0.0.1:${PROMETHEUS_HOST_PORT}:9090`, and `127.0.0.1:${GRAFANA_HOST_PORT}:3000`.

- [ ] **Step 3: Configure production application environment**

Use `SPRING_PROFILES_ACTIVE=prod`, SQL persistence for Python, Redis SSE persistence for Java, and internal hostnames such as `mysql:3306`, `redis:6379`, `kafka:9092`, `minio:9000`, `elasticsearch:9200`, `java-backend:8080`, and `python-ai:8000`.

- [ ] **Step 4: Run the structural check**

Run: `docker compose --env-file deploy/production/.env.example -f compose.yaml config --quiet`

Expected: exit code `0` with no unresolved interpolation warnings.

### Task 3: Harden service images and container Nginx

**Files:**
- Modify: `backend/Dockerfile`
- Modify: `backend/.dockerignore`
- Modify: `python/Dockerfile`
- Modify: `python/.dockerignore`
- Modify: `frontend/Dockerfile`
- Modify: `frontend/.dockerignore`
- Modify: `frontend/deploy/nginx/default.conf.template`

**Interfaces:**
- Consumes: per-service manifests and the Compose internal service names.
- Produces: non-root, multi-stage Java/Python images and a frontend Nginx proxy to `java-backend:8080` that supports SSE.

- [ ] **Step 1: Write build checks**

Run: `docker build -f backend/Dockerfile backend`, `docker build -f python/Dockerfile python`, and `docker build -f frontend/Dockerfile frontend`.

Expected before hardening: builds may succeed, but runtime image inspection does not guarantee non-root ownership or the production entrypoint contract.

- [ ] **Step 2: Implement hardened Dockerfiles**

Use explicit stage names, dependency-first copy order for cacheability, no development dependencies in production images, non-root runtime users, and `COPY --chown` for application files. Keep the existing application entrypoints and do not add code dependencies.

- [ ] **Step 3: Implement proxy and static-serving policy**

Keep SPA fallback, restrict API proxying to `java-backend`, disable buffering for SSE, preserve forwarded headers, add conservative security headers, and cache immutable Vite assets.

- [ ] **Step 4: Re-run build checks**

Run the three `docker build` commands from Step 1.

Expected: all complete with exit code `0`.

### Task 4: Validate, document operations, and review scope

**Files:**
- Modify: `README.md`
- Test: Compose render and Docker builds

**Interfaces:**
- Consumes: final Compose stack and deployment templates.
- Produces: concise production deployment, backup, startup, scaling-boundary, and host Nginx instructions.

- [ ] **Step 1: Document exact commands**

Add a production deployment section covering copying `.env.example` to `.env`, setting required secrets, `docker compose --env-file deploy/production/.env up -d --build`, the host Nginx config location, `docker compose ps`, and named-volume backup guidance.

- [ ] **Step 2: Verify no business source changed**

Run: `git diff --name-only -- backend/src python/app frontend/src`

Expected: no output.

- [ ] **Step 3: Verify final Compose configuration**

Run: `docker compose --env-file deploy/production/.env.example -f compose.yaml config --quiet`

Expected: exit code `0`.

- [ ] **Step 4: Review and commit**

Run: `git diff --check` followed by `git status --short`; stage only deployment-related files and commit with `build: replace production Docker deployment`.
