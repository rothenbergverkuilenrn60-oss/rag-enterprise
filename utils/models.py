# =============================================================================
# utils/models.py
# 企业级 RAG — 全局 Pydantic V2 数据模型
# 所有 Stage 之间传递的数据结构都定义在这里，保证类型安全和单一数据源
# =============================================================================
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ══════════════════════════════════════════════════════════════════════════════
# 枚举类型
# ══════════════════════════════════════════════════════════════════════════════

class DocType(str, Enum):
    """文档类型枚举，继承 str 使其可直接用作字符串比较。"""
    PDF     = "pdf"
    DOCX    = "docx"
    XLSX    = "xlsx"
    CSV     = "csv"
    HTML    = "html"
    JSON    = "json"
    TXT     = "txt"
    MD      = "md"
    IMAGE   = "image"
    UNKNOWN = "unknown"


class ChunkStrategy(str, Enum):
    """分块策略枚举。"""
    RECURSIVE = "recursive"
    SEMANTIC  = "semantic"
    SENTENCE  = "sentence"
    TOKEN     = "token"


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 1 — 预处理 (Preprocessor)
# ══════════════════════════════════════════════════════════════════════════════

class RawDocument(BaseModel):
    """原始文档入口模型，流水线的起点。"""
    raw_id:    str               = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    file_path: str               = Field(..., description="文件绝对路径")
    doc_type:  DocType           = Field(default=DocType.UNKNOWN)
    metadata:  dict[str, Any]   = Field(default_factory=dict)
    created_at: float            = Field(default_factory=time.time)


class PreprocessResult(BaseModel):
    """STAGE 1 输出：清洗后的文本及质量元数据。"""
    raw_id:       str
    cleaned_text: str             = ""
    language:     str             = "zh"
    char_count:   int             = 0
    is_duplicate: bool            = False
    duplicate_of: str | None      = None
    warnings:     list[str]       = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        # 自动计算字符数
        if self.cleaned_text and self.char_count == 0:
            self.char_count = len(self.cleaned_text)


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 2 — 提取 (Extractor)
# ══════════════════════════════════════════════════════════════════════════════

class ExtractedImage(BaseModel):
    """An image extracted from a PDF page or standalone image file."""
    raw_bytes:   bytes = Field(..., description="Raw image bytes before base64 encoding")
    width:       int   = 0
    height:      int   = 0
    page_number: int   = 0    # 0 for standalone image files
    image_index: int   = 0    # position within the page (0-based)
    ext:         str   = "png"


class ExtractedContent(BaseModel):
    """STAGE 2 输出：从各种格式文件中提取的结构化内容。"""
    raw_id:            str
    doc_type:          DocType           = DocType.UNKNOWN
    title:             str               = ""
    author:            str               = ""
    created_date:      str               = ""
    pages:             int               = 0
    body_text:         str               = ""
    tables:            list[dict]        = Field(default_factory=list)
    images_count:      int               = 0
    images:            list[ExtractedImage] = Field(default_factory=list)
    language:          str               = "zh"
    metadata:          dict[str, Any]    = Field(default_factory=dict)
    extraction_engine: str               = "unknown"
    extraction_errors: list[str]         = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if self.images and self.images_count == 0:
            self.images_count = len(self.images)


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 3 — 文档处理 (DocProcessor / Chunker)
# ══════════════════════════════════════════════════════════════════════════════

# ── 文档结构节点（Structure-Aware Chunking 用）───────────────────────────────
class StructureNode(BaseModel):
    """
    文档的一个结构单元（章节 / 条款 / 表格行 / 列表项）。
    StructureAwareChunker 先把文档解析成节点树，再生成块。
    """
    node_type:   str             = "paragraph"  # chapter|article|table_row|list_item|paragraph
    level:       int             = 0            # 层级深度（0=顶层章节，1=条款，2=子条款）
    heading:     str             = ""           # 本节标题，如「第十五条 年假」
    content:     str             = ""           # 正文内容
    parent_heading: str          = ""           # 上级标题，如「第三章 考勤管理」
    page_number: int | None      = None
    table_header: str            = ""           # 表格行专用：所属表格的表头行


class ChunkMetadata(BaseModel):
    """附加在每个文档块上的元数据，随块一起存入向量数据库。"""
    source:          str           = ""
    doc_id:          str           = ""
    title:           str           = ""
    author:          str           = ""
    section:         str           = ""           # 顶层章节标题
    sub_section:     str           = ""           # 子章节/条款标题
    section_id:      str           = ""           # GB标准章节号，例如 "3.10" (META-01)
    section_title:   str           = ""           # 章节标题文本，例如 "定义的透光面" (META-01)
    page_number:     int | None    = None
    chunk_index:     int           = 0
    total_chunks:    int           = 0
    doc_type:        DocType       = DocType.UNKNOWN
    language:        str           = "zh"
    tags:            list[str]     = Field(default_factory=list)
    # 父子块关联
    parent_chunk_id: str           = ""           # 非空时表示本块有对应父块
    chunk_level:     str           = "child"      # "child" | "parent" | "proposition"
    node_type:       str           = "paragraph"  # 来自 StructureNode.node_type
    # 图像块字段
    chunk_type:      str           = "text"       # "text" | "image"
    image_b64:       str           = ""           # base64 str; non-empty only for chunk_type="image" chunks


class DocumentChunk(BaseModel):
    """STAGE 3 输出：一个文档块，包含内容、元数据和（可选的）向量。"""
    chunk_id:            str
    doc_id:              str
    content:             str                   # 原始内容（存入向量库、返回给用户）
    content_with_header: str                   # 富化内容（用于嵌入）
    metadata:            ChunkMetadata
    token_count:         int                   = 0
    embedding:           list[float] | None    = None   # STAGE 4 填充
    # 父块内容（父子块策略时填充，检索后替换 content 送给 LLM）
    parent_content:      str | None            = None


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 4 — 向量化存储 (Vectorizer)
# ══════════════════════════════════════════════════════════════════════════════

class VectorizeResult(BaseModel):
    """STAGE 4 输出：向量化并存储的汇总结果。"""
    doc_id:         str
    total_chunks:   int   = 0
    embedded_chunks: int  = 0
    vector_store:   str   = ""
    collection:     str   = ""
    elapsed_ms:     float = 0.0


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 5 — 检索 (Retriever)
# ══════════════════════════════════════════════════════════════════════════════

class RetrievedChunk(BaseModel):
    """STAGE 5 输出：检索到的文档块，含多路评分信息。"""
    chunk_id:         str
    doc_id:           str
    content:          str            # 子块原文（用于来源展示和忠实度评估）
    metadata:         ChunkMetadata

    # 各阶段得分（由检索流程依次填充）
    dense_score:      float = 0.0
    sparse_score:     float = 0.0
    rrf_score:        float = 0.0
    rerank_score:     float = 0.0
    final_score:      float = 0.0

    retrieval_method: str   = "dense"

    # 父块回溯（parent_child 策略专用）
    # 非空时 Generator 优先用此内容构建 Prompt，content 仍用于来源标注
    parent_content:   str | None = None


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 6 — 生成 (Generator)
# ══════════════════════════════════════════════════════════════════════════════

class GenerationRequest(BaseModel):
    """用户查询请求，通过 POST /query 接收。"""
    query:        str                           = Field(..., min_length=1, max_length=2000)
    top_k:        int                           = Field(default=6, ge=1, le=20)
    filters:      dict[str, Any] | None         = None
    session_id:   str                           = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    chat_history: list[dict[str, str]]          = Field(default_factory=list)
    temperature:  float                         = Field(default=0.1, ge=0.0, le=2.0)
    stream:       bool                          = False
    agent_mode:   bool                          = False   # True 时使用 Agentic 工具循环
    swarm_mode:   bool                          = False   # True 时使用 Fork-Agent Swarm（AGENT-03）
    debate:       bool                          = False   # AGENT-14 — opt-in verifier hop after peer fan-out (CF-02)
    include_images: bool                        = False   # True 时响应保留 image_b64（默认剥离以减小响应体）
    # 多租户 & 用户身份
    tenant_id:    str                           = ""
    user_id:      str                           = ""

    @field_validator("query")
    @classmethod
    def strip_query(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _check_debate_requires_swarm(self) -> "GenerationRequest":
        """D-10: debate=True requires swarm_mode=True (verifier runs after peer fan-out)."""
        if self.debate and not self.swarm_mode:
            raise ValueError(
                "debate=True requires swarm_mode=True (verifier runs after peer fan-out)"
            )
        return self


class GenerationResponse(BaseModel):
    """STAGE 6 输出：最终答案及来源信息。"""
    answer:            str
    sources:           list[RetrievedChunk]     = Field(default_factory=list)
    session_id:        str                       = ""
    query:             str                       = ""
    latency_ms:        float                     = 0.0
    stage_latencies:   dict[str, float]          = Field(default_factory=dict)
    faithfulness_score: float                    = 0.0
    trace_id:          str                       = ""
    model:             str                       = ""


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 6 — Agentic Tool Use (provider-neutral; AGENT-01)
# ══════════════════════════════════════════════════════════════════════════════

class ToolCall(BaseModel):
    """A single tool invocation requested by the LLM in one assistant turn.

    Provider-neutral: Anthropic's ``tool_use`` content block and OpenAI's
    ``tool_calls[i]`` array element both normalize to this shape inside the
    adapter's ``call_agentic_turn``.

    ``id`` correlates the call to its result on the next turn (Anthropic
    ``tool_use_id``, OpenAI ``tool_call_id``). Frozen — adapters never mutate.
    """
    model_config = ConfigDict(frozen=True)

    id:        str
    name:      str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgenticTurn(BaseModel):
    """One LLM turn in the agentic tool-use loop, normalized across providers.

    Adapters (``AnthropicLLMClient.call_agentic_turn``,
    ``OpenAILLMClient.call_agentic_turn``) parse provider-specific wire formats
    and return this. ``AgentQueryPipeline`` consumes only this — it does NOT
    branch on provider type.

    ``raw_assistant_msg`` is the provider-shaped dict the pipeline appends to
    the next-turn ``messages`` list verbatim (Anthropic:
    ``{"role": "assistant", "content": [...blocks...]}``; OpenAI:
    ``{"role": "assistant", "content": ..., "tool_calls": [...]}``). The
    adapter is the only thing that knows the wire shape.

    ``stop_reason`` literals:
      - ``"text_only"``  → Anthropic ``end_turn`` / ``stop_sequence``; OpenAI ``stop``
      - ``"tool_use"``   → Anthropic ``tool_use``; OpenAI ``tool_calls``
      - ``"max_tokens"`` → Anthropic ``max_tokens``; OpenAI ``length``
      - ``"error"``      → reserved for adapter-side normalization failures
    """
    model_config = ConfigDict(frozen=True)

    text:                str                                                  = ""
    tool_calls:          list[ToolCall]                                       = Field(default_factory=list)
    stop_reason:         Literal["text_only", "tool_use", "max_tokens", "error"]
    raw_assistant_msg:   dict[str, Any]                                       = Field(default_factory=dict)
    usage_input_tokens:  int                                                  = 0
    usage_output_tokens: int                                                  = 0


class ToolPlan(BaseModel):
    """Planner output: an ordered list of ToolCalls plus their parallel-group
    assignment and a human-readable rationale (AGENT-06, Phase 16).

    ``parallel_groups`` is the canonical execution shape: each inner list is
    a wave of step indices that the Executor dispatches concurrently via
    ``asyncio.gather``. Every step index in ``range(len(steps))`` MUST appear
    in exactly one group; ``parallel_groups`` is never empty for a non-empty
    plan. Phase 16 CONTEXT.md D-01, D-02 freeze this shape.

    ``rationale`` is surfaced verbatim in the Phase 18 ``planner.plan`` SSE
    trace event. Planner system prompt instructs the LLM to write
    ``rationale`` in the same language as the user query (CONTEXT.md D-03).
    """
    model_config = ConfigDict(frozen=True)

    steps:             list[ToolCall]  = Field(default_factory=list)
    parallel_groups:   list[list[int]] = Field(default_factory=list)
    rationale:         str             = ""
    # Carried from AgenticTurn so the orchestrator can append it to messages
    # before appending tool_results (provider wire-format requirement).
    raw_assistant_msg: dict[str, Any]  = Field(default_factory=dict)
    # Mirrored from AgenticTurn.stop_reason so the orchestrator can log
    # max_tokens warnings without a second LLM call.
    stop_reason:       str             = "text_only"

    @field_validator("parallel_groups")
    @classmethod
    def _validate_parallel_groups(
        cls,
        v: list[list[int]],
        info: Any,
    ) -> list[list[int]]:
        steps = info.data.get("steps", [])
        n = len(steps)

        if n == 0:
            if v:
                raise ValueError("parallel_groups must be empty when steps is empty")
            return v

        if not v:
            raise ValueError("parallel_groups must not be empty when steps is non-empty")

        seen: set[int] = set()
        for group in v:
            if not group:
                raise ValueError("parallel_groups must not contain empty groups")
            for idx in group:
                if idx < 0 or idx >= n:
                    raise ValueError(
                        f"parallel_groups index {idx} out of range for {n} steps"
                    )
                if idx in seen:
                    raise ValueError(
                        f"parallel_groups index {idx} appears in multiple groups"
                    )
                seen.add(idx)

        if seen != set(range(n)):
            missing = sorted(set(range(n)) - seen)
            raise ValueError(
                f"parallel_groups missing step indices: {missing}"
            )

        return v


class ToolResult(BaseModel):
    """A single tool's output, normalized across tool implementations (AGENT-07).

    The orchestrator builds provider tool_results from ``content``; ``chunks``
    is consumed only on the RetrieveTool path; ``metadata`` carries free-form
    per-tool diagnostic data surfaced to Phase 18 ``tool.span`` SSE events.

    Frozen — adapters never mutate.

    Metadata key convention (Phase 18 SSE forward-compat):
      - ``latency_ms: int``    — wall-clock ms for the tool run (0 for errors/placeholders)
      - ``query: str``         — effective query string (RetrieveTool family)
      - ``placeholder: bool``  — True for skeletal/stub tools (WebSearchTool v1.4)
      - ``chunk_count: int``   — number of chunks returned (RetrieveTool family)
      - ``provider: str``      — tool-specific provider tag (future web search tools)
    """
    model_config = ConfigDict(frozen=True)

    content:  str
    chunks:   list[Any]       = Field(default_factory=list)
    metadata: dict[str, Any]  = Field(default_factory=dict)
    is_error: bool             = False


class ToolContext(BaseModel):
    """Per-tool-dispatch context (AGENT-07).

    Mirrors v1.3's positional ``execute_tool_call(tc, tf, req, retriever, llm)``
    signature: ``Executor`` constructs a ``ToolContext`` per dispatch from
    its bound retriever + llm and the orchestrator's ``tf`` + ``req``.

    ``arbitrary_types_allowed=True`` is REQUIRED — ``retriever`` and ``llm``
    hold concrete adapter instances (HybridRetrieverService,
    AnthropicLLMClient) that are not Pydantic models. Without this flag,
    Pydantic V2 raises ``PydanticUserError`` at construction.
    Frozen — tools never mutate ctx.
    """
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    req:       GenerationRequest
    tf:        dict[str, Any]
    retriever: Any
    llm:       Any


# ══════════════════════════════════════════════════════════════════════════════
# API 层通用模型
# ══════════════════════════════════════════════════════════════════════════════

class IngestionRequest(BaseModel):
    """POST /ingest 的请求体。"""
    file_path: str                      = Field(..., description="服务器上文件的绝对路径")
    doc_id:    str | None               = None
    metadata:  dict[str, Any]           = Field(default_factory=dict)
    force:     bool                     = False   # True 时跳过去重检查，强制重新摄取


class AsyncIngestRequest(BaseModel):
    """POST /ingest/async request body — sends content directly instead of file_path.

    Async ingest receives raw document content in the request body (ASYNC-01/02).
    The worker reconstructs this to call the pipeline. Unlike the sync /ingest route
    (which takes file_path on the server), this model is designed for API clients
    that send content over the wire.
    """
    doc_id: str
    content: str
    tenant_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    force: bool = False


class IngestionResponse(BaseModel):
    """POST /ingest 的响应体。"""
    doc_id:            str
    total_chunks:      int        = 0
    success:           bool       = True
    elapsed_ms:        float      = 0.0
    error:             str | None = None
    extraction_errors: list[str]  = Field(default_factory=list)


class APIResponse(BaseModel):
    """所有 API 接口的统一响应包装器。"""
    success:  bool                                      = True
    data:     dict[str, object] | list[object] | None   = None   # object 替代 Any，保持 mypy strict 兼容
    error:    str | None                                = None
    trace_id: str                                       = Field(default_factory=lambda: uuid.uuid4().hex[:8])


class FeedbackRequest(BaseModel):
    """POST /feedback 的请求体。单一数据源：从 utils/models 统一定义和导出。"""
    session_id: str
    feedback:   int   = Field(..., description="1=positive, -1=negative")
    comment:    str   = ""
    user_id:    str   = ""
    tenant_id:  str   = ""


# ══════════════════════════════════════════════════════════════════════════════
# 文档版本控制
# ══════════════════════════════════════════════════════════════════════════════

class DocumentVersion(BaseModel):
    """单个文档的一个历史版本记录。"""
    doc_id:      str
    version:     int                           # 从 1 开始递增
    checksum:    str                           = ""   # SHA-256，用于去重
    file_path:   str                           = ""
    chunk_count: int                           = 0
    ingested_at: float                         = Field(default_factory=time.time)
    note:        str                           = ""   # 入库备注（如"修订版"）
    tenant_id:   str                           = ""
    user_id:     str                           = ""
    is_current:  bool                          = True


class VersionListResponse(BaseModel):
    """GET /docs/{doc_id}/versions 的响应体。"""
    doc_id:   str
    versions: list[DocumentVersion]            = Field(default_factory=list)
    total:    int                              = 0


# ══════════════════════════════════════════════════════════════════════════════
# 人工标注
# ══════════════════════════════════════════════════════════════════════════════

class AnnotationTask(BaseModel):
    """需要人工标注的单条任务（来自 RAGAS 低分结果或随机抽样）。"""
    task_id:       str   = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    question:      str
    answer:        str
    contexts:      list[str]                   = Field(default_factory=list)
    ground_truth:  str                         = ""   # 标准答案（可选）
    source:        str                         = "ragas"   # ragas | manual | feedback
    created_at:    float                       = Field(default_factory=time.time)
    status:        str                         = "pending"  # pending | annotating | done | skip
    ragas_score:   float | None                = None   # 触发标注的 RAGAS 低分
    tenant_id:     str                         = ""
    priority:      int                         = 0    # 越高越优先（负面反馈触发的优先级高）
    user_comment:  str                         = ""   # 用户在反馈时填写的备注（feedback 来源任务才有）


class AnnotationResult(BaseModel):
    """人工标注员提交的评分结果。"""
    task_id:          str
    annotator_id:     str
    faithfulness:     float  = Field(..., ge=0.0, le=1.0)
    answer_quality:   float  = Field(..., ge=0.0, le=1.0)
    corrected_answer: str    = ""   # 若回答有误，标注员提供正确答案
    comment:          str    = ""
    annotated_at:     float  = Field(default_factory=time.time)


class AnnotationStats(BaseModel):
    """标注服务统计数据。"""
    total_tasks:       int   = 0
    pending:           int   = 0
    done:              int   = 0
    skipped:           int   = 0
    avg_faithfulness:  float | None = None
    avg_answer_quality: float | None = None


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 7 — SSE Trace Events (AGENT-04, Phase 18)
# ══════════════════════════════════════════════════════════════════════════════
#
# AgentEvent + 6 concrete subclasses serialized to SSE
# ``event: <type>\ndata: <json>\n\n`` named-event lines by
# ``controllers/api.py::/agent/v1/run/stream`` (Phase 18 D-01, D-10).
#
# Frozen Pydantic V2 models — match Phase 16/17 D-01 placement convention.
# ``event_type: ClassVar[str]`` is the discriminator; ClassVar fields are
# excluded from ``model_dump()`` / ``model_dump_json()`` automatically
# (Pydantic V2 default behavior). The base class declares no ``event_type``
# so concrete subclasses each carry their own canonical wire-name.

class AgentEvent(BaseModel):
    """Abstract-by-convention base for all Phase 18 SSE event payloads.

    Concrete subclasses each declare a unique ``event_type: ClassVar[str]``
    discriminator and add their own payload fields. Common fields live here.

    Frozen — emitters never mutate; SSE serialization is one-way.
    """
    model_config = ConfigDict(frozen=True)

    trace_id: str
    seq:      int
    ts_ms:    int


class PlannerPlanEvent(AgentEvent):
    """Emitted once per planner turn — carries the full ToolPlan the planner
    just produced (D-09)."""
    event_type: ClassVar[str] = "planner.plan"
    model_config = ConfigDict(frozen=True)

    plan: ToolPlan


class ToolSpanStartEvent(AgentEvent):
    """Emitted ONCE per tool dispatch BEFORE the coroutine awaits (D-05).

    ``args`` is verbatim from ``ToolCall.arguments`` — the model performs no
    scrubbing (D-11). Multi-tenant safety is preserved by JWT + RLS at the
    route layer; this model is a structural carrier only.
    """
    event_type: ClassVar[str] = "tool.span.start"
    model_config = ConfigDict(frozen=True)

    span_id: str
    name:    str
    args:    dict[str, Any] = Field(default_factory=dict)


class ToolSpanEndEvent(AgentEvent):
    """Emitted when a tool dispatch resolves to a ``ToolResult`` (D-09).

    ``content_preview`` is first 200 chars of ``ToolResult.content`` — the
    emitter truncates. ``chunk_count`` and ``latency_ms`` come from
    ``ToolResult.metadata`` per Phase 17 D-02 (with ``len(result.chunks)``
    fallback for ``chunk_count``).
    """
    event_type: ClassVar[str] = "tool.span.end"
    model_config = ConfigDict(frozen=True)

    span_id:         str
    latency_ms:      int
    chunk_count:     int
    is_error:        bool
    content_preview: str


class ToolSpanErrorEvent(AgentEvent):
    """Emitted INSTEAD OF ``tool.span.end`` when a tool dispatch raises
    ``BaseException`` (D-12).

    ``error_message`` is ``str(exc)[:200]`` — the emitter truncates. Full
    traceback is logged at ``logger.error`` only; not in the stream.
    """
    event_type: ClassVar[str] = "tool.span.error"
    model_config = ConfigDict(frozen=True)

    span_id:       str
    latency_ms:    int
    error_type:    str
    error_message: str


class ExecutorParallelEvent(AgentEvent):
    """Emitted ONCE per parallel group — at group END with both ``fan_out``
    and ``group_latency_ms`` populated (D-09).

    Plan 18-01 ``planner_decision`` (D-09 / D-15 reconciliation, option c):
    emit at group END (not start) so ``group_latency_ms`` is always populated.
    Plan 18-03's smoke test (D-15) updates the expected sequence accordingly.
    """
    event_type: ClassVar[str] = "executor.parallel"
    model_config = ConfigDict(frozen=True)

    fan_out:          int
    group_latency_ms: int


class SynthesizerFinalEvent(AgentEvent):
    """Emitted ONCE at end of stream — carries the synthesizer's final answer
    text verbatim (D-07)."""
    event_type: ClassVar[str] = "synthesizer.final"
    model_config = ConfigDict(frozen=True)

    answer:        str
    sources_count: int


# ══════════════════════════════════════════════════════════════════════════════
# Phase 21 — AGENT-05 Multi-Agent Debate / Sub-Agent Verifier
# ══════════════════════════════════════════════════════════════════════════════
#
# VerifierVerdict — Verifier sub-agent return type (D-01).
# 3 AgentEvent subclasses — verifier.start / verifier.complete / verifier.disagreement
# (D-08, D-09). Frozen Pydantic V2 models matching the existing AgentEvent
# subclass convention (each subclass redeclares ``model_config = ConfigDict(frozen=True)``).

class VerifierVerdict(BaseModel):
    """Verifier sub-agent verdict (AGENT-05).

    Frozen — Verifier emits once; SwarmQueryPipeline reads (and may
    ``.model_copy(update=...)`` for CF-04 forced-disagree override per
    21-RESEARCH.md Pitfall P-02).

    Per CONTEXT D-02, ``proposed_answer`` is ALWAYS populated (both verdicts).
    """
    model_config = ConfigDict(frozen=True)

    verdict:            Literal["agree", "disagree"]
    evidence_chunk_ids: list[str]
    reasoning:          str
    proposed_answer:    str
    latency_ms:         int


class VerifierStartEvent(AgentEvent):
    """Emitted ONCE before Verifier.verify() awaits (D-09)."""
    event_type: ClassVar[str] = "verifier.start"
    model_config = ConfigDict(frozen=True)

    peer_count: int
    model:      str                       # resolved per D-05


class VerifierCompleteEvent(AgentEvent):
    """Emitted ONCE after Verifier.verify() returns successfully (D-09).

    No ``proposed_answer_preview`` field — kept off the wire to avoid PII echo
    and frame bloat (full text reaches users only via SynthesizerFinalEvent).
    """
    event_type: ClassVar[str] = "verifier.complete"
    model_config = ConfigDict(frozen=True)

    verdict:              Literal["agree", "disagree"]
    evidence_chunk_count: int
    latency_ms:           int


class VerifierDisagreementEvent(AgentEvent):
    """Emitted on the three disagree paths (D-08).

    ``summary`` is truncated to 200 chars at the emitter, mirroring
    ``ToolSpanErrorEvent.error_message`` (utils/models.py ~594-607).
    ``error_type`` is populated only when ``reason="verifier_failed"`` (D-06).
    """
    event_type: ClassVar[str] = "verifier.disagreement"
    model_config = ConfigDict(frozen=True)

    reason:             Literal["peers_diverge", "forced_no_evidence", "verifier_failed"]
    summary:            str
    evidence_chunk_ids: list[str]
    peer_count:         int
    error_type:         str | None = None
