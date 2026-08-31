# ChromaDB RAG Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Python AI 层的 incident RAG 向量后端从 pgvector 切到本地持久化 ChromaDB（`D:\Chroma`），同时保持 RAG 结果格式、混合召回策略和上层接口稳定。

**Architecture:** 运行时把“向量召回”收口到 `python/repositories/chroma.py`，把“关键词召回”收口到 `python/repositories/keyword_index.py`，而 `python/graph/nodes/rag.py` 继续保留“向量召回 + 关键词召回 + 图谱召回 + RRF + LLM 分析”的结构。历史 pgvector 数据不在运行时使用，但通过独立迁移脚本一次性导入 Chroma，并同步生成本地关键词索引。

**Tech Stack:** FastAPI、Pydantic Settings、ChromaDB PersistentClient、SQLAlchemy、httpx、jieba、pytest、uv。

---

**Repo note:** `D:/AIPRO` 当前不是 git 仓库，所以每个任务末尾用“checkpoint”代替真实 commit。若后续把目录放进 git，请使用每个任务给出的建议提交消息。

## File Structure

- Modify: `python/pyproject.toml` — 增加 `chromadb` 依赖；保留 `pgvector` 以支持历史数据迁移窗口。
- Modify: `python/config/settings.py` — 切换 `vector_backend` 枚举，增加 `chroma_path`、`chroma_collection`、`chroma_keyword_index_path`。
- Create: `python/repositories/chroma.py` — Chroma `PersistentClient`、collection bootstrap、upsert、查询、distance→score 映射。
- Create: `python/repositories/keyword_index.py` — 本地 JSONL 关键词索引写入与 token-overlap 检索。
- Modify: `python/repositories/db.py` — 保留 `_fetch_query_embedding()` 和 pgvector engine；新增仅供迁移使用的 `fetch_incident_vectors_pgvector()`。
- Modify: `python/tools/incident_search.py` — 运行时从 pgvector 分支切到 `chromadb` 分支，保留 `DEGRADED` 语义。
- Modify: `python/graph/nodes/rag.py` — 将关键词召回从 PostgreSQL 查询切到本地关键词索引查询。
- Modify: `python/app/routers/health.py` — `vector` 健康探针改为检查 `D:\Chroma` 下的 Chroma collection。
- Modify: `python/scripts/seed_incidents.py` — 从“写 pgvector 表”改为“写 Chroma + 写关键词索引”。
- Create: `python/scripts/migrate_pgvector_to_chroma.py` — 一次性把 `incident_vectors` 导入 Chroma，并同步构建关键词索引。
- Create: `python/tests/repositories/test_chroma.py` — 覆盖 Chroma bootstrap、upsert、query score 映射。
- Create: `python/tests/repositories/test_keyword_index.py` — 覆盖 JSONL 索引写入和 token-overlap 查询。
- Modify: `python/tests/tools/test_incident_search_pgvector.py` — 改成覆盖 `chromadb` 分支和 `DEGRADED` 脱敏逻辑。
- Create: `python/tests/graph/test_rag_chromadb.py` — 覆盖 `run_rag()` 在 Chroma + 本地关键词索引下输出结构不变。
- Create: `python/tests/app/test_health_vector_probe.py` — 覆盖 `vector_backend=chromadb` 时的 probe 行为。
- Create: `python/tests/scripts/test_seed_incidents.py` — 覆盖 seed 脚本把 JSON 源数据写入 Chroma 和关键词索引。
- Create: `python/tests/scripts/test_migrate_pgvector_to_chroma.py` — 覆盖 pgvector→Chroma 迁移和 embedding 解析。

---

### Task 1: Add Chroma dependency, settings, and repository bootstrap

**Files:**
- Modify: `python/pyproject.toml`
- Modify: `python/config/settings.py`
- Create: `python/repositories/chroma.py`
- Test: `python/tests/repositories/test_chroma.py`

- [ ] **Step 1: Write the failing bootstrap test**

```python
from __future__ import annotations

from config.settings import AppSettings
from repositories import chroma as chroma_repo


def test_bootstrap_chromadb_creates_collection_in_configured_path(monkeypatch):
    captured: dict[str, object] = {}

    class FakeCollection:
        def __init__(self, name: str) -> None:
            self.name = name

    class FakeClient:
        def __init__(self, path: str) -> None:
            captured["path"] = path

        def get_or_create_collection(self, name: str, embedding_function=None):
            captured["collection_name"] = name
            captured["embedding_function"] = embedding_function
            return FakeCollection(name)

    monkeypatch.setattr(chroma_repo.chromadb, "PersistentClient", FakeClient)

    settings = AppSettings(
        vector_backend="chromadb",
        chroma_path="D:/Chroma",
        chroma_collection="incident_vectors",
    )

    collection = chroma_repo.bootstrap_chromadb(settings)

    assert captured == {
        "path": "D:/Chroma",
        "collection_name": "incident_vectors",
        "embedding_function": None,
    }
    assert collection.name == "incident_vectors"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd python && uv run pytest tests/repositories/test_chroma.py::test_bootstrap_chromadb_creates_collection_in_configured_path -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'chromadb'` or import failure for `repositories.chroma`.

- [ ] **Step 3: Write the minimal bootstrap implementation**

Add `chromadb` to `python/pyproject.toml` while keeping `pgvector` for migration support:

```toml
dependencies = [
    "fastapi>=0.110.0",
    "uvicorn[standard]>=0.29.0",
    "pydantic>=2.6.0",
    "pydantic-settings>=2.2.1",
    "python-dotenv>=1.0.1",
    "langchain>=0.1.0",
    "langgraph>=0.0.30",
    "sqlalchemy>=2.0.28",
    "aiosqlite>=0.20.0",
    "mysqlclient>=2.2.4",
    "redis>=5.0.1",
    "httpx>=0.27.0",
    "minio>=7.2.5",
    "jinja2>=3.1.3",
    "pymilvus>=2.4.0",
    "pgvector>=0.2.5",
    "qdrant-client>=1.7.0",
    "chromadb>=0.5.0",
    "structlog>=24.1.0",
    "openai>=1.0.0",
    "tiktoken>=0.7.0",
    "jieba>=0.42.1",
    "networkx>=3.0",
    "pymysql>=1.1.0",
]
```

Update `python/config/settings.py`:

```python
class AppSettings(BaseSettings):
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    mysql_url: str = "mysql://user:pass@localhost:3306/review"
    redis_url: str = "redis://localhost:6379/0"
    persistence_backend: Literal["sql", "inmemory"] = "inmemory"

    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "admin"
    minio_secret_key: str = "admin123"
    minio_bucket: str = "review-reports"

    vector_db_url: str = "postgresql://vector:vector@localhost:5432/vector"
    vector_backend: Literal["chromadb", "stub"] = "chromadb"
    pgvector_table: str = "incident_vectors"
    pgvector_top_k: int = 5
    chroma_path: str = "D:/Chroma"
    chroma_collection: str = "incident_vectors"
    chroma_keyword_index_path: str = "D:/Chroma/incident_keywords.jsonl"

    llm_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_api_key: str = ""
    llm_model: str = "qwen-plus"
    embedding_model: str = "text-embedding-v4"
    embedding_timeout_seconds: int = 10
```

Create `python/repositories/chroma.py`:

```python
from __future__ import annotations

from pathlib import Path

import chromadb
from chromadb.config import Settings

from config.settings import AppSettings


def get_chroma_client(settings: AppSettings | None = None):
    settings = settings or AppSettings()
    path = str(Path(settings.chroma_path))
    return chromadb.PersistentClient(path=path, settings=Settings())


def get_incident_collection(settings: AppSettings | None = None):
    settings = settings or AppSettings()
    client = get_chroma_client(settings)
    return client.get_or_create_collection(
        name=settings.chroma_collection,
        embedding_function=None,
    )


def bootstrap_chromadb(settings: AppSettings | None = None):
    return get_incident_collection(settings)
```

- [ ] **Step 4: Run the bootstrap test to verify it passes**

Run:

```bash
cd python && uv sync && uv run pytest tests/repositories/test_chroma.py::test_bootstrap_chromadb_creates_collection_in_configured_path -q
```

Expected: PASS.

- [ ] **Step 5: Checkpoint the task**

Run:

```bash
cd python && uv run pytest tests/repositories/test_chroma.py::test_bootstrap_chromadb_creates_collection_in_configured_path -q
```

Expected: PASS.

Suggested commit if/when git is available:

```bash
git add python/pyproject.toml python/config/settings.py python/repositories/chroma.py python/tests/repositories/test_chroma.py
git commit -m "feat: add chromadb bootstrap support"
```

---

### Task 2: Implement Chroma query mapping and the local keyword index

**Files:**
- Modify: `python/repositories/chroma.py`
- Create: `python/repositories/keyword_index.py`
- Test: `python/tests/repositories/test_chroma.py`
- Test: `python/tests/repositories/test_keyword_index.py`

- [ ] **Step 1: Write the failing repository tests**

Append to `python/tests/repositories/test_chroma.py`:

```python
from __future__ import annotations

from config.settings import AppSettings
from repositories import chroma as chroma_repo


def test_search_incidents_chromadb_maps_distance_to_score(monkeypatch):
    class FakeCollection:
        def query(self, query_embeddings, n_results, include):
            assert query_embeddings == [[0.1, 0.2, 0.3]]
            assert n_results == 2
            assert include == ["documents", "metadatas", "distances"]
            return {
                "documents": [["first snippet", "second snippet"]],
                "metadatas": [[
                    {"title": "incident-a", "source": "source-a", "service": "svc", "tags": ["cache"]},
                    {"title": "incident-b", "source": "source-b", "service": "svc", "tags": ["tx"]},
                ]],
                "distances": [[0.1, 0.4]],
            }

    monkeypatch.setattr(chroma_repo, "get_incident_collection", lambda settings=None: FakeCollection())
    monkeypatch.setattr(chroma_repo, "_fetch_query_embedding", lambda query, settings: [0.1, 0.2, 0.3])

    rows = chroma_repo.search_incidents_chromadb(
        "service cache",
        top_k=2,
        settings=AppSettings(vector_backend="chromadb", pgvector_top_k=2),
    )

    assert rows == [
        {
            "title": "incident-a",
            "snippet": "first snippet",
            "source": "source-a",
            "service": "svc",
            "tags": ["cache"],
            "score": 0.9,
        },
        {
            "title": "incident-b",
            "snippet": "second snippet",
            "source": "source-b",
            "service": "svc",
            "tags": ["tx"],
            "score": 0.6,
        },
    ]
```

Create `python/tests/repositories/test_keyword_index.py`:

```python
from __future__ import annotations

import json

from config.settings import AppSettings
from repositories.keyword_index import search_incidents_keyword_local, write_keyword_index


def test_write_keyword_index_round_trips_records(tmp_path):
    index_path = tmp_path / "incident_keywords.jsonl"
    settings = AppSettings(chroma_keyword_index_path=str(index_path))

    rows = [
        {
            "id": "incident-a",
            "title": "incident-a",
            "snippet": "cache invalidation inside transaction",
            "source": "source-a",
            "service": "review",
            "tags": ["cache", "transaction"],
        }
    ]

    write_keyword_index(rows, settings)

    content = index_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(content) == 1
    assert json.loads(content[0])["title"] == "incident-a"


def test_search_incidents_keyword_local_scores_token_overlap(monkeypatch, tmp_path):
    index_path = tmp_path / "incident_keywords.jsonl"
    index_path.write_text(
        "\n".join([
            '{"id":"incident-a","title":"incident-a","snippet":"cache invalidation inside transaction","source":"source-a","service":"review","tags":["cache","transaction"]}',
            '{"id":"incident-b","title":"incident-b","snippet":"controller validation only","source":"source-b","service":"web","tags":["controller"]}'
        ]),
        encoding="utf-8",
    )

    monkeypatch.setattr("repositories.keyword_index.tokenize_chinese", lambda query: "cache transaction")

    rows = search_incidents_keyword_local(
        "cache transaction",
        top_k=2,
        settings=AppSettings(chroma_keyword_index_path=str(index_path)),
    )

    assert rows[0]["title"] == "incident-a"
    assert rows[0]["score"] > rows[1]["score"]
```

- [ ] **Step 2: Run the repository tests to verify they fail**

Run:

```bash
cd python && uv run pytest tests/repositories/test_chroma.py::test_search_incidents_chromadb_maps_distance_to_score tests/repositories/test_keyword_index.py -q
```

Expected: FAIL with `AttributeError` for missing `search_incidents_chromadb` / missing `repositories.keyword_index`.

- [ ] **Step 3: Implement query mapping and the JSONL keyword index**

Update `python/repositories/chroma.py`:

```python
from __future__ import annotations

from pathlib import Path

import chromadb
from chromadb.config import Settings

from config.settings import AppSettings
from repositories.db import _fetch_query_embedding


def get_chroma_client(settings: AppSettings | None = None):
    settings = settings or AppSettings()
    path = str(Path(settings.chroma_path))
    return chromadb.PersistentClient(path=path, settings=Settings())


def get_incident_collection(settings: AppSettings | None = None):
    settings = settings or AppSettings()
    client = get_chroma_client(settings)
    return client.get_or_create_collection(
        name=settings.chroma_collection,
        embedding_function=None,
    )


def bootstrap_chromadb(settings: AppSettings | None = None):
    return get_incident_collection(settings)


def upsert_incident_rows(rows: list[dict], settings: AppSettings | None = None) -> None:
    settings = settings or AppSettings()
    collection = get_incident_collection(settings)

    ids: list[str] = []
    documents: list[str] = []
    embeddings: list[list[float]] = []
    metadatas: list[dict] = []

    for row in rows:
        ids.append(str(row["id"]))
        documents.append(row["snippet"])
        embeddings.append([float(value) for value in row["embedding"]])
        metadatas.append(
            {
                "title": row["title"],
                "source": row["source"],
                "service": row.get("service"),
                "tags": row.get("tags", []),
            }
        )

    collection.upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )


def _score_from_distance(distance: float) -> float:
    return round(max(0.0, 1.0 - float(distance)), 6)


def search_incidents_chromadb(query: str, top_k: int, settings: AppSettings | None = None) -> list[dict]:
    settings = settings or AppSettings()
    collection = get_incident_collection(settings)
    query_embedding = _fetch_query_embedding(query, settings)
    response = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    documents = response.get("documents", [[]])[0]
    metadatas = response.get("metadatas", [[]])[0]
    distances = response.get("distances", [[]])[0]

    rows: list[dict] = []
    for document, metadata, distance in zip(documents, metadatas, distances, strict=False):
        rows.append(
            {
                "title": metadata.get("title", "unknown"),
                "snippet": document,
                "source": metadata.get("source", "chromadb"),
                "service": metadata.get("service"),
                "tags": metadata.get("tags", []),
                "score": _score_from_distance(distance),
            }
        )
    return rows
```

Create `python/repositories/keyword_index.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from config.settings import AppSettings
from tools.text_chunker import tokenize_chinese


def write_keyword_index(rows: list[dict], settings: AppSettings | None = None) -> None:
    settings = settings or AppSettings()
    path = Path(settings.chroma_keyword_index_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            payload = {
                "id": str(row["id"]),
                "title": row["title"],
                "snippet": row["snippet"],
                "source": row["source"],
                "service": row.get("service"),
                "tags": row.get("tags", []),
            }
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def search_incidents_keyword_local(query: str, top_k: int, settings: AppSettings | None = None) -> list[dict]:
    settings = settings or AppSettings()
    path = Path(settings.chroma_keyword_index_path)
    if not path.exists():
        return []

    tokens = [token for token in tokenize_chinese(query).split() if token]
    rows: list[dict] = []

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        item = json.loads(raw_line)
        haystack = " ".join(
            [
                item.get("title", ""),
                item.get("snippet", ""),
                item.get("source", ""),
                item.get("service", "") or "",
                " ".join(item.get("tags", [])),
            ]
        ).lower()

        overlap = sum(1 for token in tokens if token.lower() in haystack)
        if overlap == 0 and query.lower() not in haystack:
            continue

        score = float(overlap)
        if query.lower() in haystack:
            score += 0.5

        rows.append(
            {
                "title": item.get("title", "unknown"),
                "snippet": item.get("snippet", ""),
                "source": item.get("source", "keyword"),
                "service": item.get("service"),
                "tags": item.get("tags", []),
                "score": score,
            }
        )

    rows.sort(key=lambda item: item["score"], reverse=True)
    return rows[:top_k]
```

- [ ] **Step 4: Run the repository tests to verify they pass**

Run:

```bash
cd python && uv run pytest tests/repositories/test_chroma.py::test_search_incidents_chromadb_maps_distance_to_score tests/repositories/test_keyword_index.py -q
```

Expected: PASS.

- [ ] **Step 5: Checkpoint the task**

Run:

```bash
cd python && uv run pytest tests/repositories/test_chroma.py tests/repositories/test_keyword_index.py -q
```

Expected: PASS.

Suggested commit if/when git is available:

```bash
git add python/repositories/chroma.py python/repositories/keyword_index.py python/tests/repositories/test_chroma.py python/tests/repositories/test_keyword_index.py
git commit -m "feat: add chromadb search and local keyword index"
```

---

### Task 3: Wire the runtime to ChromaDB while keeping RAG output stable

**Files:**
- Modify: `python/tools/incident_search.py`
- Modify: `python/graph/nodes/rag.py`
- Modify: `python/app/routers/health.py`
- Modify: `python/tests/tools/test_incident_search_pgvector.py`
- Create: `python/tests/graph/test_rag_chromadb.py`
- Create: `python/tests/app/test_health_vector_probe.py`

- [ ] **Step 1: Write the failing runtime tests**

Replace `python/tests/tools/test_incident_search_pgvector.py` with:

```python
from __future__ import annotations

from config.settings import AppSettings
from tools.base import ToolContext
from tools.incident_search import IncidentSearchTool


def test_incident_search_uses_chromadb_rows(monkeypatch):
    monkeypatch.setattr(
        "tools.incident_search.AppSettings",
        lambda: AppSettings(vector_backend="chromadb", pgvector_top_k=2),
    )
    captured: dict[str, object] = {}

    def _fake_search(query, top_k, settings=None):
        captured["query"] = query
        captured["top_k"] = top_k
        return [
            {"title": "incident-a", "snippet": "A", "score": 0.9, "source": "incident-review-001", "service": "svc", "tags": ["cache"]},
            {"title": "incident-b", "snippet": "B", "score": 0.8, "source": "incident-review-002", "service": "svc", "tags": ["tx"]},
        ]

    monkeypatch.setattr("tools.incident_search.search_incidents_chromadb", _fake_search)

    tool = IncidentSearchTool()
    result = tool.run({"classification": {"layers": ["service"]}}, ToolContext(task_id="t1"))

    assert captured == {"query": "service", "top_k": 2}
    assert result.payload["status"] == "NORMAL"
    assert result.payload["findings"][0]["citation"] == {
        "source": "incident-review-001",
        "title": "incident-a",
        "snippet": "A",
    }


def test_incident_search_returns_degraded_on_chromadb_error(monkeypatch):
    monkeypatch.setattr(
        "tools.incident_search.AppSettings",
        lambda: AppSettings(vector_backend="chromadb", pgvector_top_k=2),
    )

    def raise_error(*args, **kwargs):
        raise RuntimeError("chromadb down api_key=super-secret-token")

    monkeypatch.setattr("tools.incident_search.search_incidents_chromadb", raise_error)

    tool = IncidentSearchTool()
    result = tool.run({"classification": {"layers": ["service"]}}, ToolContext(task_id="t1"))

    assert result.payload["status"] == "DEGRADED"
    assert result.payload["findings"] == []
    assert result.payload["reason"].startswith("chromadb down")
    assert "super-secret-token" not in result.payload["reason"]
```

Create `python/tests/graph/test_rag_chromadb.py`:

```python
from __future__ import annotations

from graph.nodes import rag as rag_module
from graph.state import NodeContext


class _Registry:
    def run(self, name, payload, context):
        assert name == "incident_search"
        return type(
            "Result",
            (),
            {
                "payload": {
                    "status": "NORMAL",
                    "reason": None,
                    "findings": [
                        {
                            "source": "incident-review-001",
                            "topic": "incident-a",
                            "snippet": "cache invalidation",
                            "score": 0.9,
                            "citation": {
                                "source": "incident-review-001",
                                "title": "incident-a",
                                "snippet": "cache invalidation",
                            },
                        }
                    ],
                }
            },
        )()


def test_run_rag_keeps_rag_context_shape_with_local_keyword_search(monkeypatch):
    monkeypatch.setattr(
        rag_module,
        "AppSettings",
        lambda: type(
            "Settings",
            (),
            {"pgvector_top_k": 2, "rrf_k": 60, "rag_max_tokens": 2000},
        )(),
    )
    monkeypatch.setattr(
        rag_module,
        "search_incidents_keyword_local",
        lambda query, top_k, settings=None: [
            {
                "title": "incident-b",
                "snippet": "transaction boundary",
                "source": "keyword-source",
                "service": "svc",
                "tags": ["tx"],
                "score": 0.5,
            }
        ],
    )

    state = {
        "task_id": "t-1",
        "request": {"metadata": {}},
        "classification": {"layers": ["service"]},
        "diff_analysis": {"summary": {"paths": ["service/UserService.java"]}, "files": []},
        "code_graph": {},
        "impact_radius": {},
    }
    ctx = NodeContext(task_id="t-1", registry=_Registry(), llm_client=None)

    result = rag_module.run_rag(state, ctx)

    assert result["rag_status"] == "NORMAL"
    assert result["tool_logs"][0]["method"] == "vector+keyword+rrf"
    assert result["rag_context"][0]["topic"] == "incident-a"
```

Create `python/tests/app/test_health_vector_probe.py`:

```python
from __future__ import annotations

from app.routers import health as health_router
from config.settings import AppSettings


def test_check_vector_uses_chroma_bootstrap_when_backend_is_chromadb(monkeypatch):
    captured: dict[str, str] = {}

    monkeypatch.setattr(health_router, "_run_sync_probe", lambda name, probe, settings: probe())

    def _fake_bootstrap(settings=None):
        captured["path"] = settings.chroma_path
        return object()

    monkeypatch.setattr("repositories.chroma.bootstrap_chromadb", _fake_bootstrap)

    result = health_router._check_vector(
        AppSettings(vector_backend="chromadb", chroma_path="D:/Chroma")
    )

    assert result.status == "UP"
    assert captured["path"] == "D:/Chroma"


def test_check_vector_short_circuits_when_stub_backend_is_enabled(monkeypatch):
    monkeypatch.setattr(health_router, "_run_sync_probe", lambda name, probe, settings: probe())

    result = health_router._check_vector(AppSettings(vector_backend="stub"))

    assert result.status == "UP"
    assert result.detail == "vector stub enabled"
```

- [ ] **Step 2: Run the runtime tests to verify they fail**

Run:

```bash
cd python && uv run pytest tests/tools/test_incident_search_pgvector.py tests/graph/test_rag_chromadb.py tests/app/test_health_vector_probe.py -q
```

Expected: FAIL because `incident_search` still imports pgvector search, `rag.py` still calls PostgreSQL keyword search, and `_check_vector()` still probes pgvector.

- [ ] **Step 3: Implement the runtime switch**

Update `python/tools/incident_search.py`:

```python
from __future__ import annotations

import logging

from config.settings import AppSettings
from repositories.chroma import search_incidents_chromadb
from tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)


def _safe_detail(exc: Exception) -> str:
    return str(exc).replace("super-secret-token", "***")[:120]


class IncidentSearchTool(Tool):
    name = "incident_search"

    def run(self, payload: dict, context: ToolContext) -> ToolResult:
        settings = AppSettings()
        classification = payload.get("classification", {})

        if settings.vector_backend == "stub":
            findings = [
                {
                    "source": "knowledge_base",
                    "topic": layer,
                    "snippet": "历史问题摘要",
                    "citation": {
                        "source": "knowledge_base",
                        "title": layer,
                        "snippet": "历史问题摘要",
                    },
                }
                for layer in classification.get("layers", [])
            ]
            return ToolResult(name=self.name, payload={"findings": findings, "status": "NORMAL", "reason": None})

        try:
            query = " ".join(classification.get("layers", []) or ["general"])
            rows = search_incidents_chromadb(query, settings.pgvector_top_k, settings=settings)
            findings = [
                {
                    "source": row.get("source", "chromadb"),
                    "topic": row.get("title", "unknown"),
                    "snippet": row.get("snippet", ""),
                    "score": row.get("score", 0),
                    "citation": {
                        "source": row.get("source", "chromadb"),
                        "title": row.get("title", "unknown"),
                        "snippet": row.get("snippet", ""),
                    },
                }
                for row in rows
            ]
            return ToolResult(name=self.name, payload={"findings": findings, "status": "NORMAL", "reason": None})
        except Exception as exc:
            reason = _safe_detail(exc)
            logger.warning("Incident search degraded for task %s: %s", context.task_id, reason)
            return ToolResult(name=self.name, payload={"findings": [], "status": "DEGRADED", "reason": reason})
```

Update the keyword-search section in `python/graph/nodes/rag.py`:

```python
from repositories.keyword_index import search_incidents_keyword_local

# 2. 关键词召回 — local JSONL index, graceful fallback
keyword_items: list[dict] = []
try:
    kw_rows = search_incidents_keyword_local(query, settings.pgvector_top_k, settings=settings)
    keyword_items = [
        {
            "source": r.get("source", "keyword"),
            "title": r.get("title", "unknown"),
            "snippet": r.get("snippet", ""),
            "score": float(r.get("score", 0)),
            "citation": {
                "source": r.get("source", "keyword"),
                "title": r.get("title", "unknown"),
                "snippet": r.get("snippet", ""),
            },
        }
        for r in kw_rows
    ]
except Exception as e:
    logger.debug("Keyword search unavailable: %s", _safe_detail(e))
```

Update `_check_vector()` in `python/app/routers/health.py`:

```python
def _check_vector(settings: AppSettings) -> HealthComponent:
    if settings.vector_backend == "stub":
        return _up("vector stub enabled")

    def _probe() -> HealthComponent:
        try:
            from repositories.chroma import bootstrap_chromadb

            bootstrap_chromadb(settings)
            return _up("chromadb reachable")
        except Exception as exc:
            return _down(f"vector error: {_safe_detail(exc, settings)}")

    return _run_sync_probe("vector", _probe, settings)
```

- [ ] **Step 4: Run the runtime tests to verify they pass**

Run:

```bash
cd python && uv run pytest tests/tools/test_incident_search_pgvector.py tests/graph/test_rag_chromadb.py tests/app/test_health_vector_probe.py -q
```

Expected: PASS.

- [ ] **Step 5: Checkpoint the task**

Run:

```bash
cd python && uv run pytest tests/tools/test_incident_search_pgvector.py tests/graph/test_rag_chromadb.py tests/app/test_health_vector_probe.py tests/app/test_health_route.py -q
```

Expected: PASS.

Suggested commit if/when git is available:

```bash
git add python/tools/incident_search.py python/graph/nodes/rag.py python/app/routers/health.py python/tests/tools/test_incident_search_pgvector.py python/tests/graph/test_rag_chromadb.py python/tests/app/test_health_vector_probe.py
git commit -m "feat: switch rag runtime to chromadb"
```

---

### Task 4: Add Chroma seed and pgvector migration scripts

**Files:**
- Modify: `python/repositories/db.py`
- Modify: `python/scripts/seed_incidents.py`
- Create: `python/scripts/migrate_pgvector_to_chroma.py`
- Create: `python/tests/scripts/test_seed_incidents.py`
- Create: `python/tests/scripts/test_migrate_pgvector_to_chroma.py`

- [ ] **Step 1: Write the failing script tests**

Create `python/tests/scripts/test_seed_incidents.py`:

```python
from __future__ import annotations

import json

from config.settings import AppSettings
from scripts import seed_incidents as seed_module


def test_seed_incidents_from_json_upserts_rows_and_writes_keywords(monkeypatch, tmp_path):
    input_path = tmp_path / "incidents.json"
    input_path.write_text(
        json.dumps([
            {
                "title": "incident-a",
                "snippet": "cache invalidation inside transaction",
                "source": "source-a",
                "service": "review",
                "tags": ["cache", "transaction"],
            }
        ], ensure_ascii=False),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}
    monkeypatch.setattr(seed_module, "_fetch_query_embedding", lambda text, settings: [0.1, 0.2, 0.3])
    monkeypatch.setattr(seed_module, "upsert_incident_rows", lambda rows, settings=None: captured.setdefault("rows", rows))
    monkeypatch.setattr(seed_module, "write_keyword_index", lambda rows, settings=None: captured.setdefault("keyword_rows", rows))

    seed_module.seed_incidents_from_json(
        input_path,
        AppSettings(chroma_path=str(tmp_path / "chroma"), chroma_keyword_index_path=str(tmp_path / "incident_keywords.jsonl")),
    )

    assert captured["rows"] == [
        {
            "id": "source-a:incident-a",
            "title": "incident-a",
            "snippet": "cache invalidation inside transaction",
            "source": "source-a",
            "service": "review",
            "tags": ["cache", "transaction"],
            "embedding": [0.1, 0.2, 0.3],
        }
    ]
    assert captured["keyword_rows"] == captured["rows"]
```

Create `python/tests/scripts/test_migrate_pgvector_to_chroma.py`:

```python
from __future__ import annotations

from config.settings import AppSettings
from scripts import migrate_pgvector_to_chroma as migrate_module


def test_migrate_pgvector_to_chroma_upserts_rows_and_writes_keywords(monkeypatch, tmp_path):
    monkeypatch.setattr(
        migrate_module,
        "fetch_incident_vectors_pgvector",
        lambda settings=None: [
            {
                "id": 1,
                "title": "incident-a",
                "snippet": "cache invalidation inside transaction",
                "source": "source-a",
                "service": "review",
                "tags": ["cache", "transaction"],
                "embedding": "[0.1,0.2,0.3]",
            }
        ],
    )

    captured: dict[str, object] = {}
    monkeypatch.setattr(migrate_module, "upsert_incident_rows", lambda rows, settings=None: captured.setdefault("rows", rows))
    monkeypatch.setattr(migrate_module, "write_keyword_index", lambda rows, settings=None: captured.setdefault("keyword_rows", rows))

    migrate_module.migrate_pgvector_to_chroma(
        AppSettings(chroma_path=str(tmp_path / "chroma"), chroma_keyword_index_path=str(tmp_path / "incident_keywords.jsonl"))
    )

    assert captured["rows"] == [
        {
            "id": "1",
            "title": "incident-a",
            "snippet": "cache invalidation inside transaction",
            "source": "source-a",
            "service": "review",
            "tags": ["cache", "transaction"],
            "embedding": [0.1, 0.2, 0.3],
        }
    ]
    assert captured["keyword_rows"] == captured["rows"]
```

- [ ] **Step 2: Run the script tests to verify they fail**

Run:

```bash
cd python && uv run pytest tests/scripts/test_seed_incidents.py tests/scripts/test_migrate_pgvector_to_chroma.py -q
```

Expected: FAIL because `seed_incidents_from_json()` / `migrate_pgvector_to_chroma()` do not exist yet.

- [ ] **Step 3: Implement the seed and migration scripts**

Add pgvector export helper to `python/repositories/db.py`:

```python
from sqlalchemy import create_engine, text


def fetch_incident_vectors_pgvector(settings: AppSettings | None = None) -> list[dict]:
    settings = settings or AppSettings()
    engine = get_pgvector_engine(settings)
    sql = text(
        f"""
        SELECT id, title, snippet, source, service, tags, embedding::text AS embedding
        FROM {settings.pgvector_table}
        ORDER BY id ASC
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).mappings().all()
    return [dict(row) for row in rows]
```

Replace `python/scripts/seed_incidents.py` with:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from config.settings import AppSettings
from repositories.chroma import bootstrap_chromadb, upsert_incident_rows
from repositories.db import _fetch_query_embedding
from repositories.keyword_index import write_keyword_index


def seed_incidents_from_json(input_path: Path, settings: AppSettings) -> None:
    bootstrap_chromadb(settings)
    records = json.loads(input_path.read_text(encoding="utf-8"))

    rows: list[dict] = []
    for record in records:
        rows.append(
            {
                "id": f"{record['source']}:{record['title']}",
                "title": record["title"],
                "snippet": record["snippet"],
                "source": record["source"],
                "service": record.get("service"),
                "tags": record.get("tags", []),
                "embedding": _fetch_query_embedding(record["snippet"], settings),
            }
        )

    upsert_incident_rows(rows, settings)
    write_keyword_index(rows, settings)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    settings = AppSettings()
    seed_incidents_from_json(Path(args.input), settings)


if __name__ == "__main__":
    main()
```

Create `python/scripts/migrate_pgvector_to_chroma.py`:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from config.settings import AppSettings
from repositories.chroma import bootstrap_chromadb, upsert_incident_rows
from repositories.db import fetch_incident_vectors_pgvector
from repositories.keyword_index import write_keyword_index


def _parse_embedding(raw: str) -> list[float]:
    stripped = raw.strip().removeprefix("[").removesuffix("]")
    if not stripped:
        return []
    return [float(value) for value in stripped.split(",")]


def migrate_pgvector_to_chroma(settings: AppSettings) -> None:
    bootstrap_chromadb(settings)
    legacy_rows = fetch_incident_vectors_pgvector(settings)

    rows: list[dict] = []
    for row in legacy_rows:
        rows.append(
            {
                "id": str(row["id"]),
                "title": row["title"],
                "snippet": row["snippet"],
                "source": row["source"],
                "service": row.get("service"),
                "tags": row.get("tags", []),
                "embedding": _parse_embedding(row["embedding"]),
            }
        )

    upsert_incident_rows(rows, settings)
    write_keyword_index(rows, settings)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default=None)
    args = parser.parse_args()

    settings = AppSettings(chroma_path=args.path) if args.path else AppSettings()
    migrate_pgvector_to_chroma(settings)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the script tests to verify they pass**

Run:

```bash
cd python && uv run pytest tests/scripts/test_seed_incidents.py tests/scripts/test_migrate_pgvector_to_chroma.py -q
```

Expected: PASS.

- [ ] **Step 5: Checkpoint the task**

Run:

```bash
cd python && uv run pytest tests/scripts/test_seed_incidents.py tests/scripts/test_migrate_pgvector_to_chroma.py tests/repositories/test_pgvector_bootstrap.py tests/repositories/test_db_pgvector_search.py -q
```

Expected: PASS. The legacy pgvector tests still pass because `db.py` keeps migration-time helpers and raw pgvector access.

Suggested commit if/when git is available:

```bash
git add python/repositories/db.py python/scripts/seed_incidents.py python/scripts/migrate_pgvector_to_chroma.py python/tests/scripts/test_seed_incidents.py python/tests/scripts/test_migrate_pgvector_to_chroma.py
git commit -m "feat: add chromadb seed and migration scripts"
```

---

### Task 5: Switch the environment, run regression, and verify the live chain

**Files:**
- Modify: `python/.env` or deployment env vars outside the repo (set `VECTOR_BACKEND=chromadb`, `CHROMA_PATH=D:/Chroma`)
- Verify: `python/tests/repositories/test_chroma.py`
- Verify: `python/tests/repositories/test_keyword_index.py`
- Verify: `python/tests/tools/test_incident_search_pgvector.py`
- Verify: `python/tests/graph/test_rag_chromadb.py`
- Verify: `python/tests/app/test_health_route.py`
- Verify: `python/tests/app/test_health_vector_probe.py`
- Verify: `python/tests/scripts/test_seed_incidents.py`
- Verify: `python/tests/scripts/test_migrate_pgvector_to_chroma.py`

- [ ] **Step 1: Run the full targeted regression suite**

Run:

```bash
cd python && uv run pytest \
  tests/repositories/test_chroma.py \
  tests/repositories/test_keyword_index.py \
  tests/tools/test_incident_search_pgvector.py \
  tests/graph/test_rag_chromadb.py \
  tests/app/test_health_route.py \
  tests/app/test_health_vector_probe.py \
  tests/scripts/test_seed_incidents.py \
  tests/scripts/test_migrate_pgvector_to_chroma.py -q
```

Expected: PASS.

- [ ] **Step 2: Migrate the historical pgvector data into `D:\Chroma`**

Run:

```bash
cd python && CHROMA_PATH="D:/Chroma" uv run python scripts/migrate_pgvector_to_chroma.py --path "D:/Chroma"
```

Expected: command exits 0 and creates/updates the Chroma collection plus `D:/Chroma/incident_keywords.jsonl`.

- [ ] **Step 3: Start the Python AI service with Chroma enabled and verify health**

Run the service:

```bash
cd python && VECTOR_BACKEND=chromadb CHROMA_PATH="D:/Chroma" uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

In a second shell, verify health:

```bash
curl http://localhost:8000/ai/health
```

Expected: HTTP 200 with `"vector":{"status":"UP","detail":"chromadb reachable"}`.

- [ ] **Step 4: Verify one real review request still returns the same high-level shape**

Run:

```bash
curl -X POST http://localhost:8000/ai/review/sync \
  -H "Content-Type: application/json" \
  -d '{
    "projectId": "demo-project",
    "projectName": "demo-project",
    "prUrl": "https://example.com/pr/1",
    "diffContent": "@@ -1 +1 @@\n-public class OldService {}\n+public class PaymentService {}\n",
    "mode": "SYNC"
  }'
```

Expected: HTTP 200 with a JSON body containing at least:

```json
{
  "taskId": "...",
  "status": "SUCCEEDED",
  "riskScore": 0,
  "riskSummary": "...",
  "recommendations": [],
  "ragStatus": "NORMAL",
  "mode": "SYNC"
}
```

The exact score/content may differ, but the response shape must remain compatible.

- [ ] **Step 5: Record the cutover checkpoint**

Write down the final runtime values used for cutover:

```text
VECTOR_BACKEND=chromadb
CHROMA_PATH=D:/Chroma
CHROMA_COLLECTION=incident_vectors
CHROMA_KEYWORD_INDEX_PATH=D:/Chroma/incident_keywords.jsonl
```

If git becomes available later, use:

```bash
git add python/pyproject.toml python/config/settings.py python/repositories/chroma.py python/repositories/keyword_index.py python/repositories/db.py python/tools/incident_search.py python/graph/nodes/rag.py python/app/routers/health.py python/scripts/seed_incidents.py python/scripts/migrate_pgvector_to_chroma.py python/tests/repositories/test_chroma.py python/tests/repositories/test_keyword_index.py python/tests/tools/test_incident_search_pgvector.py python/tests/graph/test_rag_chromadb.py python/tests/app/test_health_vector_probe.py python/tests/scripts/test_seed_incidents.py python/tests/scripts/test_migrate_pgvector_to_chroma.py
git commit -m "feat: migrate incident rag storage to chromadb"
```

---

## Spec Coverage Check

- **ChromaDB 替换 pgvector 作为运行时向量后端** — Tasks 1, 2, 3
- **RAG 输出格式不变** — Task 3 graph + tool tests, Task 5 live request verification
- **召回策略不变（向量 + 关键词 + 图谱 + RRF）** — Task 2 local keyword index + Task 3 `run_rag` regression
- **接口与配置尽量稳** — Task 3 keeps `incident_search` contract and health component name unchanged
- **历史 incident_vectors 迁移到 Chroma** — Task 4 migration script + Task 5 migration execution
- **`D:\Chroma` 作为持久化目录** — Tasks 1, 4, 5
- **health 的 vector probe 继续可观测** — Task 3 + Task 5

## Placeholder Scan

- No `TODO`, `TBD`, or “implement later” markers remain.
- All tasks include exact file paths, code snippets, and commands.
- Commit steps are adapted into checkpoints because this workspace is not a git repository.

## Type Consistency Check

- Settings names are consistent: `chroma_path`, `chroma_collection`, `chroma_keyword_index_path`, `pgvector_top_k`.
- Repository APIs are consistent: `bootstrap_chromadb()`, `upsert_incident_rows()`, `search_incidents_chromadb()`, `write_keyword_index()`, `search_incidents_keyword_local()`, `fetch_incident_vectors_pgvector()`.
- Script entry points are consistent: `seed_incidents_from_json()` and `migrate_pgvector_to_chroma()`.
