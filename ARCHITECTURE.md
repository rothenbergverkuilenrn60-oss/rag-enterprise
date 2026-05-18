# EnterpriseRAG 架构与文件指南

> 本文档面向**新加入工程师**与**架构评审**。覆盖三层抽象、运行时数据流、每个目录的职责、关键代码文件的职责与对外契约。
>
> 配套阅读：[README.md](README.md)（用户手册） · [docs/agent-architecture.md](docs/agent-architecture.md)（Planner/Executor 心智模型） · [SECURITY.md](SECURITY.md)（安全策略） · [CHANGELOG.md](CHANGELOG.md)（版本演进）。

---

## 1. 项目定位

**EnterpriseRAG** 是一个 Planner → Executor → Synthesizer 三段式 Agent 框架，**RAG 只是它能调用的众多工具之一**。

- **多租户**：PostgreSQL Row-Level Security 在数据库层强隔离每个 tenant 的向量与元数据。
- **Provider 中立**：Anthropic / OpenAI / Azure / Ollama 同一接口（`BaseLLMClient.call_agentic_turn`）。
- **结构化事件流**：Agent 运行时通过 SSE 实时发出 6 种事件（`planner.plan` / `tool.span.start` / `tool.span.end` / `tool.span.error` / `executor.parallel` / `synthesizer.final`），每帧带 `trace_id` + `seq` + `ts_ms`。
- **生产级硬性要求**：mypy --strict、ruff、Pydantic V2、tenacity 重试边界、narrow exception、结构化日志。

当前版本：**v1.5**（Web Search via Tavily + AGENT-05 Verifier + 每模块 70% 覆盖率门）。

---

## 2. 顶层架构

```
                ┌──────────────────────────────────────────┐
HTTP/SSE ──▶    │   FastAPI Routes (controllers/api.py)    │
                └─────────────────┬────────────────────────┘
                                  │
                                  ▼
              ┌───────────────────────────────────────────────┐
              │   Pipelines (services/pipeline.py)            │
              │                                                │
              │   - IngestionPipeline    (6 阶段写入)         │
              │   - QueryPipeline        (10 阶段固定流水线)  │
              │   - AgentQueryPipeline   (Planner→Exec→Synth) │
              │   - SwarmQueryPipeline   (Fork-Swarm 多智能体)│
              └────────────┬────────────────────┬─────────────┘
                           │                    │
                           ▼                    ▼
                ┌────────────────────┐ ┌──────────────────┐
                │  services/agent/   │ │  services/*      │
                │  Planner / Exec /  │ │  preprocessor    │
                │  Verifier / Tools  │ │  extractor       │
                │                    │ │  doc_processor   │
                │  RetrieveTool      │ │  vectorizer      │
                │  RefinedRetrieve   │ │  retriever       │
                │  WebSearchTool     │ │  generator       │
                │                    │ │  nlu / memory    │
                │                    │ │  auth / audit    │
                │                    │ │  knowledge / etc │
                └─────────┬──────────┘ └────────┬─────────┘
                          │                     │
                          ▼                     ▼
                  ┌─────────────────────────────────────┐
                  │  utils/      models / cache / log   │
                  │  config/     settings.py            │
                  └─────────────────────────────────────┘
                                   │
                                   ▼
        ┌─────────────────────────────────────────────────────┐
        │  PostgreSQL+pgvector(HNSW) │ Redis │ Ollama/外部LLM  │
        └─────────────────────────────────────────────────────┘
```

**三层规则**：
- `controllers/` 只做 HTTP 入参出参 + 鉴权 + 速率限制 + SSE 编码；不能调底层服务。
- `services/` 编排业务流程（Pipeline），调用细分领域服务（Retriever / Generator 等）。
- `utils/` 跨模块通用工具（数据模型、缓存、日志、指标），无业务语义。

---

## 3. 运行时数据流

### 3.1 摄取流（Ingestion）

```
data/raw/*.{pdf,docx,xlsx,html,md,txt} 
    │
    ▼   POST /ingest 或 /ingest/async
┌───────────────────────────────────────┐
│ IngestionPipeline                      │
│   1. preprocessor/cleaner   去噪、归一化 │
│   2. extractor/extractor    PDF→文本+图│
│   3. doc_processor/chunker  父子分块    │
│   4. preprocessor/pii       PII 检测   │
│   5. vectorizer/embedder    BGE-M3 向量│
│   6. vectorizer/indexer     pgvector 入库│
└───────────────────┬───────────────────┘
                    ▼
           PostgreSQL+pgvector
              (HNSW 索引)
```

### 3.2 查询流（Agent）

```
POST /api/v1/agent/v1/run/stream  (SSE)
    │
    ▼
AgentQueryPipeline.run_streaming()
    │
    │  ┌─────────────────── for iteration in range(MAX_ITERATIONS=5) ───────────────┐
    │  │                                                                              │
    ▼  │
  Planner.plan_from_messages(messages, tools=ALLOWLIST, system=_AGENT_SYSTEM)        │
    │                                                                                 │
    ▼  emit planner.plan                                                              │
  ToolPlan(steps, parallel_groups, raw_assistant_msg)                                 │
    │                                                                                 │
    ▼                                                                                 │
  Executor.execute_plan_streaming(plan, tf, req)                                      │
    │  emit tool.span.start  (一对多 fan-out, asyncio.as_completed)                   │
    │  emit tool.span.end / tool.span.error                                            │
    │  emit executor.parallel                                                          │
    ▼                                                                                  │
  raw_outputs: list[ToolResult | BaseException]                                       │
    │                                                                                  │
    ▼                                                                                  │
  _build_tool_results → 喂回 messages → 下一轮 Planner                                  │
    └──────────────────────────────────────────────────────────────────────────────┘
    │
    ▼ (终止条件：plan.steps==[] OR MAX_ITERATIONS 用完→force_final_answer)
  emit synthesizer.final(answer, sources_count)
    │
    ▼
  _persist_turn → memory_service + audit_service（v1.7：memory_service 走批量 save_facts，audit_service pool 单例自启）
```

**为什么是这样**：
- `parallel_groups` 让 planner 显式声明哪些工具调用可以并行（`asyncio.as_completed` 真并行）。
- `BaseException isolation`：单个工具失败不影响并行组里的其他工具。
- `MAX_ITERATIONS=5` 兜底：planner 循环跑空时强制 `force_final_answer`（v1.5 修复）。

---

## 4. 顶层文件清单

| 文件 | 作用 |
|------|------|
| `main.py` | FastAPI 入口；`lifespan` 中预热 vectorstore、启动 EventBus、注册事件 handler、可选启动时扫描；安装中间件（CORS、AuthN/Z、rate limit、observability）。 |
| `pyproject.toml` | uv-managed 项目元数据 + dev dependencies。 |
| `requirements.txt` | 运行时依赖锁定（产物来自 uv）。 |
| `requirements-dev.txt` | 开发期 / 测试依赖。 |
| `requirements-eval.txt` | RAGAS 评测依赖（`make eval` 单独安装）。 |
| `uv.lock` | uv 锁文件 — 所有 transitive 依赖精确版本。 |
| `Dockerfile` | 多阶段构建（builder + runtime），基础镜像 `python:3.11-slim`。 |
| `docker-compose.yml` | 8 个服务编排：rag-api、ingest-worker、postgres、redis、ollama、ollama-init、ragas-eval、nginx。 |
| `Makefile` | `build` / `up` / `down` / `logs-all` / `health` / `ingest` / `eval` / `coverage-*` / `demo-agent` 等。 |
| `.env` | 本地开发环境变量（**已 gitignore**，含密钥）。 |
| `.env.docker` | 容器部署环境变量模板（**已 gitignore**）。 |
| `.dockerignore` | 排除 `.venv`、缓存、planning 等非运行时文件。 |
| `pytest.ini` | 测试配置 — 标记、覆盖率、超时。 |
| `mempalace.yaml` | MemPalace（决策记忆）配置。 |
| `entities.json` | NLU 实体词典（小型 seed）。 |
| `README.md` | 用户级指南：架构概览 + 五分钟启动 + 工具列表 + API 示例。 |
| `ARCHITECTURE.md` | **本文件**：开发者级深度 — 每文件职责。 |
| `CHANGELOG.md` | keep-a-changelog 1.1.0 格式 — v1.0 → v1.5。 |
| `CLAUDE.md` | GSD（Get Shit Done）项目流程契约 — 给 AI 协作者读的项目守则。 |
| `SECURITY.md` | 威胁模型 + 报告渠道 + 已知 CVE 跟踪。 |

---

## 5. 目录与文件详解

### 5.1 `controllers/` — HTTP 表层

| 文件 | 作用 |
|------|------|
| `controllers/__init__.py` | 暴露 `router`，被 `main.py` 通过 `include_router` 装载。 |
| `controllers/api.py` | **唯一的 HTTP 路由文件（~570 行）**。覆盖：health/readiness、/query 同步与流式、/agent/v1/run/stream（SSE）、/ingest 同步与异步、/ingest/status/{task_id}、/feedback、/knowledge/scan、/docs/{doc_id}/versions（版本控制）、/annotation/*（人工标注）、/ab/experiments/*（A/B 测试）、/cache、/stats、/metrics。每个路由依赖注入对应 service，不写业务逻辑。 |

### 5.2 `services/` — 业务编排与领域服务（v1.5 共 23 个子模块）

#### 5.2.1 `services/pipeline.py`（**核心编排层，~1630 行**）

包含四个 Pipeline 类：

- `IngestionPipeline` — 6 阶段写入流水线（preprocessor → extractor → pii → chunker → embedder → indexer）；同步入口 + ARQ 异步入口。
- `QueryPipeline` — 10 阶段固定流水线（NLU → memory load → 查询改写 → HyDE → 多查询展开 → hybrid retrieval → 重排 → rules engine → generator → audit + memory save）；保留 v1.3 行为，作为 `RetrieveTool` 的 wrapper。
- `AgentQueryPipeline` — Planner→Executor→Synthesizer 三段式 Agent。`run` 同步入口、`run_streaming` 流式 SSE 入口；`_AGENT_SYSTEM` 系统提示语；`_build_tool_results` 把 tool output 喂回 planner；`_force_final_answer` 在 MAX_ITERATIONS 耗尽时强制无工具合成（v1.5 新增）。
- `SwarmQueryPipeline`（`AgentQueryPipeline` 子类）— 多智能体 Fork-Swarm，把复杂查询拆为多个并行子查询，每个子查询独立跑一次 Agent，最后融合答案。

工厂函数 `get_ingest_pipeline()` / `get_query_pipeline()` / `get_agent_pipeline()` 提供进程级单例。

#### 5.2.2 `services/agent/` — Agent 核心（v1.4 起的"灵魂"）

| 文件 | 作用 |
|------|------|
| `agent/__init__.py` | 暴露 `get_planner()` / `get_executor()` / `get_verifier()` 工厂。 |
| `agent/planner.py` | `Planner` 类：单次 LLM 调用，把 messages + tools schema 转换为 `ToolPlan`（含 steps、parallel_groups、raw_assistant_msg、stop_reason）。 |
| `agent/executor.py` | `Executor.execute_plan_streaming` 与 `execute_plan`：按 `parallel_groups` 用 `asyncio.as_completed` 并行调度工具；逐工具发 SSE 事件；`BaseException` 隔离单点失败；流量控制 `max_concurrent`。 |
| `agent/verifier.py` | `Verifier`（AGENT-05，v1.5）：Synthesizer 之后做事实校验，对 final answer 与检索 chunks 的一致性打分，分低则触发 retry/重新检索。 |
| `agent/_demo_runner.py` | 独立可执行 demo（`make demo-agent`）：4-tool 并行 RetrieveTool 的 stub 跑通，写 SSE 帧到 stdout，~1.5s 退出。 |
| `agent/_demo_stubs.py` | demo 的 fixture/stub LLM 实现。 |

##### `services/agent/tools/` — 工具注册表

| 文件 | 作用 |
|------|------|
| `tools/__init__.py` | 触发各工具模块装饰器注册（`@get_tool_registry().register`）。 |
| `tools/registry.py` | `ToolRegistry`：进程级单例，`register(tool_cls)` 装饰器、`schemas_for(provider, names)` 输出 Anthropic/OpenAI 形态的 tool schema。 |
| `tools/base.py` | `BaseTool` ABC + `ToolContext`、`ToolResult` 数据契约（D-XX 编号契约）。 |
| `tools/retrieve.py` | `RetrieveTool`（标准检索）+ `RefinedRetrieveTool`（先 LLM 改写查询再检索）。两者都包装 `QueryPipeline.run()`，把检索结果格式化为 `<search_results>` XML 注入 `ToolResult.content`。 |
| `tools/web_search.py` | `WebSearchTool`（v1.5）— Tavily 实时联网搜索；async-throughout、tenacity 3 重试、3 类 typed error（tavily_disabled / quota_exhausted / web_search_failed）；D-15 redaction 策略不向 LLM 泄露 auth header；`_format_results_content` 把 chunks 渲染为 `[N] title — url\n<snippet>` 注入 planner 视野（v1.5.1 修复）。 |

#### 5.2.3 `services/preprocessor/` — Stage 1 去噪

| 文件 | 作用 |
|------|------|
| `preprocessor/cleaner.py` | 文本归一化：去 HTML 标签、空白折叠、Unicode normalization、语言检测。 |
| `preprocessor/pii_detector.py` | PII 检测：身份证、银行卡、手机号、Email；命中默认拦截或脱敏（按租户策略）。 |

#### 5.2.4 `services/extractor/` — Stage 2 抽取

| 文件 | 作用 |
|------|------|
| `extractor/extractor.py` | 路由分发：根据扩展名分派 PDF/DOCX/XLSX/HTML 抽取器。 |
| `extractor/image_extractor.py` | PyMuPDF 抽取 PDF 内嵌图片；LLM 多模态 caption；输出 `chunk_type="image"` chunk。⚠️ PyMuPDF AGPL-3.0 — 商业部署需另购授权。 |
| `extractor/ocr_engine.py` | Tesseract OCR 引擎 wrapper（v1.4.2 启用），处理扫描型 PDF。 |

#### 5.2.5 `services/doc_processor/` — Stage 3/4 分块

| 文件 | 作用 |
|------|------|
| `doc_processor/chunker.py` | 父子分块策略：父块语义完整保留作为生成上下文；子块小窗（~256 token）用于 dense 检索。支持 GB 标准章节号识别（`section_id` 元数据）。 |

#### 5.2.6 `services/vectorizer/` — Stage 5 向量化

| 文件 | 作用 |
|------|------|
| `vectorizer/embedder.py` | `BaseEmbedder` ABC + BGE-M3 / OpenAI / Ollama 适配器；async embedding；批量并行（`max_concurrent`）。 |
| `vectorizer/vector_store.py` | `BaseVectorStore` ABC + `PgVectorStore`（asyncpg + pgvector HNSW、`ef_construction=200 m=16`）+ `QdrantStore`（旧实现，v1.5 已被 pgvector 替换）。 |
| `vectorizer/indexer.py` | `Vectorizer`：编排 embedder + vector_store；`upsert_parent_chunks` / `fetch_parent_chunks` 处理父子分块映射。 |

#### 5.2.7 `services/retriever/` — 检索

| 文件 | 作用 |
|------|------|
| `retriever/retriever.py` | `Retriever.retrieve()`：dense (pgvector HNSW) + sparse (BM25 via Postgres tsvector) → RRF fusion → cross-encoder reranker（top-K 重排）。返回 `RetrievedChunk` 列表 + 调试元数据。 |

#### 5.2.8 `services/reranker_service/` — 独立重排服务（可选）

| 文件 | 作用 |
|------|------|
| `reranker_service/app.py` | 独立 FastAPI 服务（默认进程内但可拆分），加载 BGE-Reranker-Large；POST `/rerank` 输入 query + candidates 输出分数。 |

#### 5.2.9 `services/generator/` — LLM 客户端

| 文件 | 作用 |
|------|------|
| `generator/llm_client.py` | `BaseLLMClient` ABC + `AnthropicLLMClient` / `OpenAILLMClient` / `AzureLLMClient` / `OllamaLLMClient`。统一 `call_agentic_turn(messages, tools, system, max_tokens)` → `AgenticTurn(text, tool_calls, stop_reason, usage_*)`；OpenAI 适配器 v1.5.1 修复了 `tools=[]` 兼容（Groq/DashScope 等严格 host）。 |
| `generator/generator.py` | `Generator.generate()`：非 agent 路径下的最终生成器；prompt template 拼装（带 `[来源N]` 引用占位）；流式 token 输出。 |

#### 5.2.10 `services/nlu/` — 自然语言理解

| 文件 | 作用 |
|------|------|
| `nlu/nlu_service.py` | `NLUService`：意图分类 + 槽位填充；v1.4 起 Agent 路径下意图判定移交 Planner，本服务仍服务 `QueryPipeline`。 |
| `nlu/filter_extractor.py` | `FilterExtractor`：从用户问句抽取 metadata filter（doc_type、date range、author 等），合入 tenant filter。 |
| `nlu/entity_disambiguator.py` | `EntityDisambiguator`：实体歧义消解，配合 `entities.json` 词典与上下文。 |

#### 5.2.11 `services/memory/` — 对话记忆

| 文件 | 作用 |
|------|------|
| `memory/memory_service.py` | 短期：Redis（每 session 最近 N 轮）；长期：PostgreSQL（user_id + tenant_id 维度）。`load_context` 与 `save_turn` 接口，被所有 Pipeline 调用。 |
| `memory_service.py::LongTermMemory.save_facts` | v1.7 批量写入路径 — 1× embed_batch + 1× bulk dedupe SELECT + 1× executemany；近重复触发 `MEMORY_NEAR_DUPLICATE_SKIPPED` 审计行后 INSERT 仍执行（D-09 审计模式，v1.8 → 静默跳过 SK-01）。 |
| `memory_service.py::LongTermMemory._is_near_duplicate` | v1.7 余弦距离预检（`<=> $vec < 0.05`，由 `memory_near_duplicate_threshold` 设置控制）。 |
| `memory_service.py::LongTermMemory._get_pool` / `close` | v1.7 通过 `utils/asyncpg_helper.prepare_dsn(...)` 统一处理 `?ssl=disable` URL 参数（TD-03 集中化）。 |

#### 5.2.12 `services/auth/` — 认证

| 文件 | 作用 |
|------|------|
| `auth/oidc_auth.py` | OIDC/JWT 验证：JWKS 拉取 + 缓存；JWT 解码 + 签名校验；启动期校验 SECRET_KEY 强度（拒 SEC-01 弱密钥列表）。 |

#### 5.2.13 `services/audit/` — 审计

| 文件 | 作用 |
|------|------|
| `audit/audit_service.py` | 缓冲式审计日志：每条查询记录 user/tenant/query/trace_id/result/latency_ms/sources_count；定时 flush 到 PostgreSQL。 |
| `audit/audit_service.py::AuditService._create_tables` | v1.7 冷启动 `audit_log` 自动创建（DDL + REVOKE UPDATE/DELETE 保留 INSERT-ONLY 不变式）；首个 `_get_pool` 调用触发，不需手工 DDL（TD-01）。 |
| `audit/audit_service.py::AuditService._get_pool` / `close` | v1.7 单例 asyncpg pool；通过 `utils/asyncpg_helper.prepare_dsn(...)` 处理 DSN（TD-03）。 |
| `audit/audit_service.py::AuditAction.MEMORY_NEAR_DUPLICATE_SKIPPED` | v1.7 新增审计动作枚举（near-duplicate 预检命中后写入；INSERT 仍执行，审计模式优先于强制执行）。 |

#### 5.2.14 `services/rules/` — 业务规则引擎

| 文件 | 作用 |
|------|------|
| `rules/rules_engine.py` | ABC（Always-Block-Conditions）规则：基于检索结果命中规则时阻断生成（如 PII 命中、政策禁词）；规则可热更新。 |

#### 5.2.15 `services/knowledge/` — 知识库管理

| 文件 | 作用 |
|------|------|
| `knowledge/knowledge_service.py` | 知识库元数据：文档列表、来源、tenant 归属、ingest 状态。 |
| `knowledge/summary_indexer.py` | 文档级摘要索引（用于"找文档"而非"找片段"）。 |
| `knowledge/version_service.py` | 文档版本控制：rollback、diff、版本列表。 |

#### 5.2.16 `services/feedback/` — 反馈循环

| 文件 | 作用 |
|------|------|
| `feedback/feedback_service.py` | `/feedback` 接口的实现：记录用户对答案的点赞/踩、修正建议；触发 `REINDEX_REQUESTED` 事件。 |

#### 5.2.17 `services/annotation/` — 人工标注

| 文件 | 作用 |
|------|------|
| `annotation/annotation_service.py` | 标注任务的 CRUD + 队列：召回 hard cases，分发给标注员，结果回流训练集。 |

#### 5.2.18 `services/ab_test/` — A/B 实验

| 文件 | 作用 |
|------|------|
| `ab_test/ab_test_service.py` | 实验创建/启停、流量分配、统计显著性、winner 决策。配合 `/ab/experiments/*` 路由。 |

#### 5.2.19 `services/tenant/` — 租户

| 文件 | 作用 |
|------|------|
| `tenant/tenant_service.py` | tenant filter 拼装；与 PostgreSQL RLS 配合在 SQL 层强隔离。 |

#### 5.2.20 `services/events/` — 事件总线

| 文件 | 作用 |
|------|------|
| `events/event_bus.py` | 进程内 InMemoryEventBus（默认）+ 可选 Kafka 适配器；`EventType.REINDEX_REQUESTED` 等事件由 feedback 触发，knowledge 监听。 |

#### 5.2.21 `services/ingest_worker.py` — ARQ Worker

ARQ + Redis 后台 worker；`POST /ingest/async` 入队后由本 worker 跑实际摄取。`WorkerSettings` 决定并发度、超时、重试策略。

#### 5.2.22 `services/mcp_server.py` — MCP 服务

通过 Model Context Protocol 暴露内部工具给外部 MCP client（v1.5 探索性）。

### 5.3 `utils/` — 跨模块通用

| 文件 | 作用 |
|------|------|
| `utils/__init__.py` | 仅 import，无逻辑。 |
| `utils/models.py` | **数据模型唯一来源（~700 行）**：`GenerationRequest` / `GenerationResponse`、`ConversationTurn`、`RetrievedChunk` + `ChunkMetadata`、`DocumentChunk`、`StructureNode`、`AuditResult`、`ToolPlan` / `ToolCall` / `ToolResult` / `ToolContext`、`AgentEvent` 6 子类（PlannerPlanEvent / ToolSpanStart/End/ErrorEvent / ExecutorParallelEvent / SynthesizerFinalEvent）等。所有跨模块通信类型在这里定义为 Pydantic V2 frozen models。 |
| `utils/logger.py` | `setup_logger()`：loguru 结构化日志，级别由 `LOG_LEVEL` 控制。 |
| `utils/cache.py` | Redis 缓存装饰器、key 命名规范、TTL 策略。 |
| `utils/metrics.py` | Prometheus counter/histogram/gauge：query latency、tool latency、token usage、retrieval recall。 |
| `utils/observability.py` | Langfuse + OpenTelemetry 集成：`setup_observability()` 在 `lifespan` 启动期可选初始化。 |
| `utils/tasks.py` | ARQ 任务函数：`enqueue_ingest`、`enqueue_reindex` 等。 |

### 5.4 `config/` — 配置

| 文件 | 作用 |
|------|------|
| `config/__init__.py` | 暴露 `settings` 单例。 |
| `config/settings.py` | `Settings(BaseSettings)`：所有运行时配置（数据库 DSN、LLM provider、API key、模型路径、CORS、JWT、tenant、特性开关）。`SECRET_KEY` 强度校验、`JWT_DENYLIST` 弱密钥拦截、`APP_MODEL_DIR` 必填校验（OPS-01）。 |

### 5.5 `static/` — 前端 UI

| 文件 | 作用 |
|------|------|
| `static/index.html` | 项目主页（链接到两个 UI）。 |
| `static/ui.html` / `ui.css` / `ui.js` | 经典查询 UI：表单提交 → 单次响应。 |
| `static/agent.html` / `agent.css` / `agent.js` | **流式 Agent UI（v1.5 新增）**：消费 `/agent/v1/run/stream` 的 SSE 事件流，实时渲染 planner 决策、tool 调用进度、并行度、最终答案。 |

### 5.6 `docker/` — 容器初始化资源

| 子目录 | 作用 |
|--------|------|
| `docker/postgres/` | pgvector 扩展安装脚本 + RLS 初始化 SQL。 |
| `docker/redis/` | redis.conf。 |
| `docker/nginx/` | nginx.conf + conf.d/* 反向代理 + TLS 占位。 |
| `docker/ollama/` | Modelfile + ollama-init 拉取模型脚本。 |
| `docker/qdrant/` | （已废弃，留作回滚预案。） |
| `docker/grafana/` | 仪表盘 JSON。 |
| `docker/prometheus/` | scrape 配置。 |
| `docker/eval/` | RAGAS 评测 Dockerfile + 入口脚本。 |

### 5.7 `k8s/` — 生产部署

| 文件 | 作用 |
|--------|------|
| `k8s/namespace.yaml` | rag-prod namespace。 |
| `k8s/configmap.yaml` | 非密配置。 |
| `k8s/rag-api/` | Deployment + Service + HPA（基于 CPU + 自定义 metric）。 |
| `k8s/redis/` | Redis Deployment（生产建议外部托管）。 |
| `k8s/qdrant/` | Qdrant StatefulSet（已废弃，v1.5 切换到 pgvector）。 |
| `k8s/blue-green/` | 蓝绿部署的两套 Deployment + Service 选择器切换。 |
| `k8s/ingress.yaml` | TLS termination + path routing。 |

### 5.8 `tests/` — 测试

| 子目录 | 作用 |
|--------|------|
| `tests/unit/` | 单元测试（~70 文件，1011 用例）：每个 service 独立 mock；目标 ≥70% 单文件覆盖；CI 强制门。 |
| `tests/integration/` | 集成测试：真实 PostgreSQL + Redis + LLM stub；agent demo 端到端、SSE 帧序断言、RAGAS 评测。 |

### 5.9 `eval/` — 评测

| 子目录 | 作用 |
|--------|------|
| `eval/datasets/` | 200 条分层 QA pairs（多 doc_type、多语言）。 |
| `eval/reports/` | RAGAS 报告输出（gitignore，CI artifact）。 |

### 5.10 `scripts/` — 一次性工具脚本

| 文件 | 作用 |
|------|------|
| `scripts/ingest_batch.py` | 本地批量摄取：`--dir --recursive --concurrency`。 |
| `scripts/eval_ci_gate.py` | CI 评测门：RAGAS 分数对比阈值，不通过返回非零。 |
| `scripts/generate_qa_pairs.py` | 用 LLM 生成 QA pairs 到 eval/datasets。 |
| `scripts/check_pgvector_version.sh` | 部署前校验 pgvector 扩展版本。 |
| `scripts/verify_ocr_bake.sh` | 校验镜像里的 Tesseract OCR 模型已 bake。 |

### 5.11 `docs/` — 文档

| 文件 | 作用 |
|--------|------|
| `docs/agent-architecture.md` | Planner/Executor/Synthesizer 心智模型、签名、SSE 事件契约。 |
| `docs/v1.4-design.md` | Agent-First 反转的设计文档。 |
| `docs/demo.cast` | asciinema v2 录像，`make demo-agent` 的回放。 |

### 5.12 `.planning/` — GSD 流程产物（非运行时）

`STATE.md` / `ROADMAP.md` / `REQUIREMENTS.md` / `PROJECT.md` / `phases/<NN>-*` 各 phase 的 `PLAN.md` / `RESEARCH.md` / `VERIFICATION.md` 等。仅供 AI 协作流程使用，**不参与运行时**。

---

## 6. 关键技术决策（v1.5 状态）

| 维度 | 选择 | 备选 | 理由 |
|------|------|------|------|
| Web 框架 | FastAPI | Flask, Django | async 原生 + Pydantic 自动文档 |
| 向量库 | PostgreSQL+pgvector (HNSW) | Qdrant (旧), Milvus, Weaviate | RLS 多租户 + 单库简化运维（Phase 1 切换） |
| 后台队列 | ARQ + Redis | Celery, RQ | async-native + 极简协议 |
| LLM 抽象 | 自研 BaseLLMClient | LangChain, LlamaIndex | 锁定中立 + 透明代价 + 不绑生态 |
| Agent 抽象 | 自研 Planner/Executor/Synthesizer | LangGraph, AutoGen | 完全可控、可序列化、SSE 友好 |
| Embedding | BGE-M3 | OpenAI text-embedding-3 | 中文友好 + 本地部署 |
| Reranker | BGE-Reranker-Large | Cohere Rerank | 私有部署 + 长文档 |
| 鉴权 | OIDC/JWT | Session, API Key | 多租户 + SSO 友好 |
| 可观测性 | Prometheus + Langfuse + OTel | Datadog | 开源栈 + 自托管 |
| 容器编排 | Docker Compose（开发） + Kubernetes（生产） | Nomad | 行业标准 |

---

## 7. 关键事件契约（SSE）

**端点**：`POST /api/v1/agent/v1/run/stream`，`Content-Type: text/event-stream`。

| event_type | 何时发 | 关键字段 |
|------------|---------|----------|
| `planner.plan` | Planner 给出非空 ToolPlan | `plan.steps` / `plan.parallel_groups` / `plan.raw_assistant_msg` / `plan.stop_reason` |
| `tool.span.start` | 单个工具开始执行 | `span_id` / `name` / `args` |
| `tool.span.end` | 单个工具成功结束 | `span_id` / `latency_ms` / `chunk_count` / `is_error=false` / `content_preview`（前 200 字符） |
| `tool.span.error` | 单个工具异常 | `span_id` / `latency_ms` / `error_kind` |
| `executor.parallel` | 一个并行组结束 | `fan_out` / `group_latency_ms` |
| `synthesizer.final` | 终止：planner 出空 plan 或 max-iter 强制合成 | `answer` / `sources_count` |

每帧统一带 `trace_id`（uuid hex8）+ `seq`（递增）+ `ts_ms`。

---

## 8. 安全契约

- **JWT 启动校验**：`SECRET_KEY` <32 字符或命中 `_JWT_DENYLIST` 时拒启动（SEC-01）。
- **CORS**：生产模式禁止 `localhost`，必须显式列举 origin。
- **PII 默认拦截**：`PIIDetector` 命中即阻断生成，可按 tenant 策略改为脱敏。
- **D-15 redaction**：`WebSearchTool` 等外部工具的异常文本不进 LLM 上下文（防代理回显 Authorization header）。
- **RLS**：每条 SQL 自动带 tenant 谓词，物理上不可越权。
- **Rate limiting**：每路由 token bucket（`utils/cache.py` + Redis）。

---

## 9. 当前状态（v1.5）

- ✅ pgvector 替代 Qdrant 完成（Phase 1）
- ✅ Tavily Web Search 工具上线（Phase 20，AGENT-10/11/12）
- ✅ AGENT-05 Verifier 落地
- ✅ 5 个高流量模块每模块 ≥70% 覆盖率（Phase 22）
- ✅ Streaming Agent UI（`static/agent.*`，本次 milestone）
- ✅ MAX_ITERATIONS 兜底 + Web Search content surface（v1.5.1 修复，commit `39c3d34`）

---

## 10. 推荐阅读顺序

1. `README.md` — 用户视角
2. **本文件** — 开发者视角
3. `docs/agent-architecture.md` — Agent 心智模型
4. `services/pipeline.py` — 编排层源码
5. `services/agent/planner.py` + `executor.py` + `tools/` — Agent 内核
6. `utils/models.py` — 数据契约
7. `controllers/api.py` — HTTP 表面
