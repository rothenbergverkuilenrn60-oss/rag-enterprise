# =============================================================================
# config/settings.py
# 企业级 RAG 全局配置 — Pydantic V2 BaseSettings
# 路径基准: /mnt/f/  (WSL2 镜像模式 + F盘物理隔离)
# =============================================================================
from __future__ import annotations
import os
from pathlib import Path
from typing import Literal
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# BASE_DIR 优先从环境变量读取，回退到文件所在目录的上一级（项目根目录）
# Docker 部署时设置 APP_BASE_DIR=/app 即可，无需修改代码
BASE_DIR: Path = Path(os.getenv("APP_BASE_DIR", str(Path(__file__).parent.parent)))

# OPS-01: APP_MODEL_DIR is required — no hardcoded fallback
_model_dir_raw = os.getenv("APP_MODEL_DIR")
if _model_dir_raw is None:
    raise RuntimeError(
        "APP_MODEL_DIR environment variable is required. "
        "Set it to the directory containing model files (e.g., /models). "
        "Server will not start."
    )
MODEL_DIR: Path = Path(_model_dir_raw)

# SEC-01: Known-weak JWT secrets that must be rejected at startup
_JWT_DENYLIST: frozenset[str] = frozenset({
    "CHANGE-ME-IN-PRODUCTION-USE-256BIT-KEY",
    "secret",
    "password",
    "changeme",
    "dev",
    "test",
    "insecure",
    "12345678901234567890123456789012",
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "00000000000000000000000000000000",
    "11111111111111111111111111111111",
    "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "yoursecretkey",
    "mysecretkey",
    "supersecretkey",
})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ══════════════════════════════════════════════════════════════════════════
    # 应用元数据
    # ══════════════════════════════════════════════════════════════════════════
    app_name:    str = "EnterpriseRAG"
    app_version: str = "3.0.0"
    environment: Literal["development", "staging", "production"] = "development"
    debug:       bool = False
    log_level:   str  = "INFO"

    # ══════════════════════════════════════════════════════════════════════════
    # 路径
    # ══════════════════════════════════════════════════════════════════════════
    data_dir:      Path = BASE_DIR / "data" / "raw"
    processed_dir: Path = BASE_DIR / "data" / "processed"
    index_dir:     Path = BASE_DIR / "data" / "index"
    log_dir:       Path = BASE_DIR / "logs"
    cache_dir:     Path = BASE_DIR / "cache"

    # ══════════════════════════════════════════════════════════════════════════
    # FastAPI
    # ══════════════════════════════════════════════════════════════════════════
    api_host:           str       = "0.0.0.0"
    api_port:           int       = 8000
    api_prefix:         str       = "/api/v1"
    cors_origins:       list[str] = []
    rate_limit_rpm:     int       = 60       # 每 IP 每分钟最大请求数
    rate_limit_burst:   int       = 20       # 令牌桶突发余量
    rate_limit_auth_rpm:   int    = 5        # per-route: auth endpoints (login, token)
    rate_limit_ingest_rpm: int    = 10       # per-route: ingest endpoints
    rate_limit_query_rpm:  int    = 30       # per-route: query endpoints
    rate_limit_redis:   bool      = True     # True=Redis 分布式限流；False=进程内（单节点）
    request_timeout_sec: int      = 120
    uvicorn_workers:    int       = 1        # uvicorn worker 进程数（生产建议 CPU*2+1）

    # ── Reranker 微服务 ───────────────────────────────────────────────────────
    reranker_service_url: str     = ""       # 设置后优先走远端微服务（e.g. http://reranker:8001）
    reranker_sla_ms:      float   = 45.0    # Reranker SLA 阈值（超时自动降级）

    # ── 检索增强 ──────────────────────────────────────────────────────────────
    similarity_correction_enabled: bool  = True
    similarity_correction_alpha:   float = 0.3   # 0=纯rerank分数，1=纯余弦相似度

    # ── NER & 实体知识库 ──────────────────────────────────────────────────────
    ner_model_path: str = ""  # 空=纯规则；设置后加载 HuggingFace NER 模型

    # ── Embedding Ensemble ────────────────────────────────────────────────────
    # 单模型时保持为空列表；多模型时配置：
    # [{"provider": "ollama", "weight": 0.6}, {"provider": "openai", "weight": 0.4}]
    embedding_ensemble: list[dict] = []
    embedding_ensemble_strategy: str = "average"  # average | concat

    # ── JWT ───────────────────────────────────────────────────────────────────
    secret_key: str = Field(
        default="CHANGE-ME-IN-PRODUCTION-USE-256BIT-KEY",
        description="JWT 签名密钥，生产环境必须用 openssl rand -hex 32 替换",
    )
    jwt_algorithm:      Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_expire_minutes: int = 60

    # ══════════════════════════════════════════════════════════════════════════
    # STAGE 1 — 预处理
    # ══════════════════════════════════════════════════════════════════════════
    preprocess_clean_html:       bool = True
    preprocess_remove_headers:   bool = True   # 去除页眉页脚模板文字
    preprocess_deduplicate:      bool = True   # SHA256 内容去重
    preprocess_language_detect:  bool = True   # 自动检测中/英文
    preprocess_min_chars:        int  = 50     # 低于此字符数的段落丢弃
    preprocess_max_chars:        int  = 100_000

    # ══════════════════════════════════════════════════════════════════════════
    # STAGE 2 — 文档提取
    #
    # 说明：PDF 提取使用 PyMuPDF + pdfplumber 双引擎，代码自动选择，
    # 不需要手动指定引擎，这里的配置项控制的是提取行为开关。
    # ══════════════════════════════════════════════════════════════════════════
    # OCR 相关
    # ─────────────────────────────────────────────────────────────────────────
    # 代码会自动检测 PDF 是否为扫描件（通过字符密度判断）。
    # ocr_engine 决定检测到扫描件时用哪个引擎，不影响数字 PDF 的处理。
    # 可选：
    #   "auto"      → 优先尝试 PaddleOCR，未安装则自动降级到 Tesseract
    #   "paddle"    → 强制用 PaddleOCR（需要 pip install paddlepaddle paddleocr）
    #   "tesseract" → 强制用 Tesseract（需要 apt install tesseract-ocr）
    #   "none"      → 禁用 OCR，扫描件跳过不处理（返回空文本）
    ocr_engine:          Literal["auto", "paddle", "tesseract", "none"] = "auto"
    extractor_ocr_lang:  str  = "chi_sim+eng"   # Tesseract 语言包
    extractor_table_extract:  bool = True        # 用 pdfplumber 单独提取表格结构
    extractor_image_extract:  bool = False       # 提取图片（暂未实现，留作扩展）
    extractor_max_workers:    int  = 4           # PDF 并行解析线程数

    # ══════════════════════════════════════════════════════════════════════════
    # STAGE 3 — 分块
    #
    # 分块是一个流水线，不是单选题。各层配置相互叠加：
    #
    #  第一层（必选，决定按什么边界切）：
    #    chunk_primary_strategy 控制主切法
    #      "auto"        → 代码自动判断：文档有章节结构用 structure，否则用 recursive
    #      "structure"   → 按文档自然结构切（章节/条款/表格行），推荐企业制度文档
    #      "recursive"   → 按字符数递归切，通用兜底
    #      "semantic"    → 按句子嵌入相似度找语义断点切（慢，精度高）
    #      "sentence"    → 每块包含目标句 ± N 句上下文
    #
    #  第二层（可选，决定块的大小层次）：
    #    parent_child_enabled = true 时，在第一层切出的块基础上再做父子分层：
    #      子块（chunk_size）用于检索，父块（parent_chunk_size）送给 LLM
    #
    #  第三层（可选，决定嵌入的内容质量）：
    #    contextual_retrieval_enabled = true 时，对每个块调用 LLM 生成上下文说明，
    #    拼在块前面再做向量化（Anthropic 实测降低 67% 检索失败率）
    #    contextual_retrieval_enabled = false 时，用静态元数据头（来源+章节拼接）
    #
    #  第四层（可选，针对精确条款查询）：
    #    proposition_on_articles = true 时，对识别出的「条款」节点额外做命题化拆解
    #    其他节点（章节标题、表格、普通段落）仍走常规流程，避免全量命题化的高成本
    # ══════════════════════════════════════════════════════════════════════════
    chunk_primary_strategy: Literal[
        "auto", "structure", "recursive", "semantic", "sentence"
    ] = "auto"

    # 切块尺寸参数
    chunk_size:        int  = 512    # 子块 token 数上限
    chunk_overlap:     int  = 64     # 相邻块重叠 token 数
    chunk_min_size:    int  = 100    # 低于此 token 数的块丢弃
    parent_chunk_size: int  = 2048   # 父块 token 数上限（parent_child_enabled 时生效）
    sentence_window_size: int = 3    # sentence 策略：目标句前后各保留几句

    # 第二层：父子块
    parent_child_enabled:      bool = False  # True 时启用父子块，子块检索、父块送 LLM
    qdrant_parent_collection:  str  = ""     # 父块 collection，空时自动加 _parent 后缀

    # 第三层：Contextual Retrieval
    chunk_add_metadata_header:         bool = True   # False 时完全不加任何头部
    contextual_retrieval_enabled:      bool = False  # True 时用 LLM 动态生成上下文头
    contextual_retrieval_concurrency:  int  = 3      # 并发调用 LLM 的协程数上限

    # 第四层：命题化（仅对条款节点）
    proposition_on_articles:  bool = False  # True 时对 article 类型节点做命题化拆解
    proposition_concurrency:  int  = 3
    proposition_max_retries:  int  = 2

    # ══════════════════════════════════════════════════════════════════════════
    # STAGE 4 — 向量化 & 存储
    # ══════════════════════════════════════════════════════════════════════════
    # Embedding 模型
    # ─────────────────────────────────────────────────────────────────────────
    # 三个 provider 使用同一套接口，切换只需改 embedding_provider：
    #   "ollama"       → 本地 Ollama 服务（推荐，数据不出本机）
    #   "huggingface"  → 本地 HuggingFace 模型（需要提前下载到 embedding_model_path）
    #   "openai"       → OpenAI API（需要 openai_api_key，有网络费用）
    embedding_provider:   Literal["ollama", "openai", "huggingface"] = "huggingface"
    embedding_model:      str  = "bge-m3"
    embedding_model_path: Path = MODEL_DIR / "embedding_models" / "bge-m3"
    embedding_dim:        int  = 1024    # BGE-M3 输出维度，换模型时必须同步修改
    embedding_batch_size: int  = 32      # 每次调用发送的文本条数
    embedding_normalize:  bool = True    # 归一化向量（余弦相似度必须为 True）

    # 稀疏检索（BM25 关键词索引，与密集检索互补）
    sparse_enabled: bool = True
    sparse_method:  Literal["bm25", "splade"] = "bm25"

    # 向量数据库
    # ─────────────────────────────────────────────────────────────────────────
    # 三个 backend 使用同一套接口，切换只需改 vector_store：
    #   "qdrant"   → 已移除（Phase 1 起），QdrantVectorStore 已删除
    #   "pgvector" → 默认（Phase 1 起），PostgreSQL + pgvector，无需额外服务
    #   "chroma"   → 本地开发/PoC（不适合生产，无持久化分布式）
    vector_store:           Literal["qdrant", "milvus", "pgvector", "chroma"] = "pgvector"
    qdrant_url:             str  = "http://localhost:6333"
    qdrant_collection:      str  = "rag_enterprise_v3"
    qdrant_api_key:         str  = ""
    qdrant_on_disk_payload: bool = True   # payload 存磁盘（节省 RAM，建议开启）
    milvus_uri:             str  = "http://localhost:19530"
    pg_dsn:                 str  = "postgresql+asyncpg://rag:rag@localhost:5432/ragdb"

    # ══════════════════════════════════════════════════════════════════════════
    # STAGE 5 — 检索
    # ══════════════════════════════════════════════════════════════════════════
    top_k_dense:  int   = 20    # 向量检索返回候选数
    top_k_sparse: int   = 20    # BM25 返回候选数
    top_k_rerank: int   = 6     # Cross-Encoder 精排后最终返回数（送给 LLM 的块数）
    rrf_k:        int   = 60    # RRF 融合参数，行业默认值，无需修改

    # HyDE：先让 LLM 生成假设答案，用答案向量检索（解决短查询语义弱问题）
    hyde_enabled: bool = True

    # Multi-Query：生成 N 个问题变体分别检索后合并（提升召回率）
    query_rewrite_enabled: bool = True
    multi_query_count:     int  = 3
    sparse_query_limit:    int  = 2      # Multi-query: BM25 只对前 N 个查询生效（减少噪声）

    # Reranker：Cross-Encoder 精排（比 Bi-Encoder 向量相似度更精准，但更慢）
    reranker_enabled:    bool = True
    reranker_model_path: Path = MODEL_DIR / "embedding_models" / "bge-m3-rerank"
    reranker_batch_size: int  = 32

    # ══════════════════════════════════════════════════════════════════════════
    # STAGE 6 — 生成
    # ══════════════════════════════════════════════════════════════════════════
    # 三个 provider 使用同一套接口，切换只需改 llm_provider：
    #   "ollama"    → 本地部署（推荐，数据不出本机，支持 Qwen/LLaMA 等）
    #   "openai"    → OpenAI API（GPT-4o，效果最好，有网络费用）
    #   "anthropic" → Anthropic API（Claude，可选）
    llm_provider:       Literal["ollama", "openai", "anthropic", "azure"] = "openai"
    ollama_base_url:    str   = "http://localhost:11434"
    ollama_model:       str   = "qwen2.5:14b"
    ollama_model_path:  Path  = MODEL_DIR / "ollama_model"
    openai_api_key:     str   = ""
    openai_model:       str   = "gpt-4o"
    anthropic_api_key:  str   = ""
    anthropic_model:    str   = "claude-sonnet-4-6"
    # Azure OpenAI（llm_provider="azure" 时生效）
    azure_openai_endpoint:    str = ""   # e.g. https://your-resource.openai.azure.com/
    azure_openai_api_version: str = "2024-02-01"
    azure_openai_deployment:  str = ""   # e.g. gpt-4o（Azure 部署名）
    llm_temperature:    float = 0.1
    llm_max_tokens:     int   = 2048
    llm_context_window: int   = 8192   # 粗略估算上下文窗口，超出时截断输入
    llm_stream:         bool  = True

    # ══════════════════════════════════════════════════════════════════════════
    # 缓存（Redis）
    # ══════════════════════════════════════════════════════════════════════════
    redis_url:      str  = "redis://localhost:6379/0"
    cache_ttl_sec:  int  = 3600
    cache_enabled:  bool = True
    arq_keep_result_sec: int  = 86400   # ASYNC-02: 24h TTL for job results
    arq_job_timeout:     int  = 300     # ASYNC-01/02: max seconds per worker job

    # ══════════════════════════════════════════════════════════════════════════
    # 可观测性
    # ══════════════════════════════════════════════════════════════════════════
    langfuse_enabled:    bool = False
    langfuse_public_key: str  = ""
    langfuse_secret_key: str  = ""
    langfuse_host:       str  = "https://cloud.langfuse.com"
    otel_enabled:        bool = False
    otel_endpoint:       str  = "http://localhost:4317"

    # ══════════════════════════════════════════════════════════════════════════
    # NLU — 自然语言理解
    # ══════════════════════════════════════════════════════════════════════════
    # nlu_llm_enabled: True 时意图分类/实体识别使用 LLM 深度解析（慢但准）
    # False 时仅用规则引擎（快，覆盖常见查询）
    nlu_llm_enabled: bool = True

    # ══════════════════════════════════════════════════════════════════════════
    # 记忆系统
    # ══════════════════════════════════════════════════════════════════════════
    session_ttl_sec:    int  = 7200    # 短期记忆（Redis）会话超时，默认 2 小时
    # 长期记忆使用 pg_dsn 中配置的 PostgreSQL 连接

    # ══════════════════════════════════════════════════════════════════════════
    # 事件总线 / Kafka
    # ══════════════════════════════════════════════════════════════════════════
    # 空字符串 = 禁用 Kafka，使用进程内内存事件总线（开发/单机部署）
    # 填写地址 = 启用 Kafka（如 "localhost:9092"）
    kafka_bootstrap_servers: str = ""
    kafka_topic_prefix:      str = "rag"

    # ══════════════════════════════════════════════════════════════════════════
    # 知识库自动更新
    # ══════════════════════════════════════════════════════════════════════════
    # 是否在启动时自动扫描 data_dir 做增量更新
    auto_update_on_startup: bool = False
    # 定时扫描间隔（秒），0 = 禁用定时扫描
    auto_update_interval_sec: int = 0

    # ══════════════════════════════════════════════════════════════════════════
    # PII 检测
    # ══════════════════════════════════════════════════════════════════════════
    pii_detection_enabled: bool = True     # 文档入库前自动检测并脱敏 PII
    pii_block_on_detect:   bool = True     # True 时检测到 block_entities 中的 PII 阻止入库
    pii_block_entities: list[str] = [      # SEC-03: entity types that trigger hard block
        "US_SSN", "CREDIT_CARD", "US_BANK_NUMBER", "US_DRIVER_LICENSE", "US_PASSPORT",
    ]

    # ══════════════════════════════════════════════════════════════════════════
    # 摘要索引
    # ══════════════════════════════════════════════════════════════════════════
    summary_index_enabled:  bool = False   # True 时入库时额外构建三层摘要索引
    summary_search_enabled: bool = False   # True 时检索时先走摘要层定位候选 chunk

    # ══════════════════════════════════════════════════════════════════════════
    # 实体消歧
    # ══════════════════════════════════════════════════════════════════════════
    entity_disambiguation_enabled: bool = True   # True 时 NLU 实体识别后自动消歧

    # ══════════════════════════════════════════════════════════════════════════
    # 动态 top_k（根据意图自动调整检索宽度）
    # ══════════════════════════════════════════════════════════════════════════
    dynamic_top_k_enabled: bool = True
    top_k_factual:     int = 3    # 事实查询：精准，少量 chunk 即可
    top_k_procedural:  int = 5    # 流程查询：需要完整步骤
    top_k_comparison:  int = 8    # 对比查询：需要多来源
    top_k_multi_hop:   int = 12   # 多跳查询：宽泛召回后过滤
    top_k_calculation: int = 5    # 计算查询
    top_k_definition:  int = 4    # 定义查询

    # ══════════════════════════════════════════════════════════════════════════
    # 动态 chunk 切分（按内容节点类型调整 chunk_size）
    # ══════════════════════════════════════════════════════════════════════════
    dynamic_chunk_size_enabled: bool = True
    chunk_size_table:      int = 256   # 表格行：结构紧凑，小块
    chunk_size_article:    int = 384   # 法规条款：中小块，保持条款完整性
    chunk_size_paragraph:  int = 512   # 普通段落：默认大小
    chunk_size_chapter:    int = 768   # 章节导言：允许稍大，保留上下文

    # ══════════════════════════════════════════════════════════════════════════
    # 审计日志
    # ══════════════════════════════════════════════════════════════════════════
    audit_enabled:    bool = True    # 审计日志总开关
    audit_db_enabled: bool = False   # True 时同时写入 PostgreSQL audit_log 表

    # ══════════════════════════════════════════════════════════════════════════
    # OIDC / SSO 企业身份认证
    # ══════════════════════════════════════════════════════════════════════════
    oidc_enabled:    bool = False
    oidc_issuer:     str  = ""   # e.g. https://login.microsoftonline.com/{tid}/v2.0
    oidc_client_id:  str  = ""
    oidc_audience:   str  = ""   # e.g. api://your-app-id

    # ══════════════════════════════════════════════════════════════════════════
    # Prometheus 监控
    # ══════════════════════════════════════════════════════════════════════════
    metrics_enabled: bool = True
    metrics_path:    str  = "/metrics"

    @field_validator("data_dir", "processed_dir", "index_dir", "log_dir", "cache_dir", mode="before")
    @classmethod
    def ensure_path(cls, v: str | Path) -> Path:
        p = Path(v)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @model_validator(mode="after")
    def _validate_security(self) -> "Settings":
        # ── SEC-01: JWT secret denylist + minimum length ──────────────────────
        secret = self.secret_key
        if len(secret) < 32:
            raise ValueError(
                f"secret_key must be at least 32 characters. "
                f"Run: python -c \"import secrets; print(secrets.token_hex(32))\" "
                f"and set SECRET_KEY env var. Server will not start."
            )
        # Repeated-character check: all same char = weak regardless of denylist
        if len(set(secret)) == 1:
            raise ValueError(
                "secret_key consists of a single repeated character and is not secure. "
                "Generate a strong key with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if secret in _JWT_DENYLIST:
            raise ValueError(
                "secret_key matches a known-weak value and cannot be used. "
                "Generate a strong key with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )

        # ── SEC-04: CORS origins validation ──────────────────────────────────
        if self.environment == "production":
            if not self.cors_origins:
                raise ValueError(
                    "cors_origins must be set in production. "
                    "Set the CORS_ORIGINS environment variable to a comma-separated list "
                    "of allowed origins (e.g., https://app.example.com). Server will not start."
                )
            _localhost_patterns = ("localhost", "127.0.0.1", "0.0.0.0", "::1")
            bad = [o for o in self.cors_origins if any(p in o for p in _localhost_patterns)]
            if bad:
                raise ValueError(
                    f"cors_origins contains localhost/loopback entries in production: {bad}. "
                    f"Remove all localhost/127.0.0.1 entries before starting in production mode."
                )

        return self

    @property
    def active_model(self) -> str:
        """当前生效的 LLM 模型名称，随 llm_provider 自动切换。"""
        return {
            "ollama":    self.ollama_model,
            "openai":    self.openai_model,
            "anthropic": self.anthropic_model,
            "azure":     self.azure_openai_deployment or self.openai_model,
        }.get(self.llm_provider, self.ollama_model)

    @property
    def effective_context_window(self) -> int:
        """根据当前 provider + model 返回实际可用的上下文窗口大小（tokens）。

        参考 claude-code context.ts：getContextWindowForModel()
        使用固定的 llm_context_window 配置（8192）会大幅浪费 Claude 200k 的上下文窗口，
        导致 RAG 只能向 LLM 传递 ~5600 token 的文档片段，丢弃大量可用信息。

        优先级：
          1. llm_context_window != 8192（用户明确配置过）→ 使用配置值
          2. provider=anthropic → 按模型名查表（claude-sonnet-4-6 / opus-4-6: 200k）
          3. provider=openai   → 按模型名查表（gpt-4o / gpt-4o-mini: 128k）
          4. 其余 → 使用配置值（ollama 等本地模型，窗口大小取决于部署配置）
        """
        # 用户明确配置了非默认值 → 尊重用户设置
        if self.llm_context_window != 8192:
            return self.llm_context_window

        model = self.active_model.lower()

        # Anthropic: claude-sonnet-4-6 / claude-opus-4-6 → 200k
        if self.llm_provider == "anthropic":
            if "sonnet-4" in model or "opus-4" in model:
                return 200_000
            if "haiku" in model:
                return 200_000  # Haiku 4.5 也支持 200k
            return 100_000  # 旧版 Claude 3 系列保守估计

        # OpenAI
        if self.llm_provider in ("openai", "azure"):
            if "gpt-4o" in model or "gpt-4-turbo" in model or "o1" in model or "o3" in model:
                return 128_000
            if "gpt-4o-mini" in model:
                return 128_000
            return 16_000  # 旧版 GPT-3.5 等

        # Ollama 等本地模型：默认按配置值（用户需手动调整）
        return self.llm_context_window


settings = Settings()
