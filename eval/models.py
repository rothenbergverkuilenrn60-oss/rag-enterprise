# =============================================================================
# eval/models.py
# RAGAS 评测 Pydantic 数据模型
# =============================================================================
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 配置
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class EvalSettings(BaseSettings):
    """RAGAS 评测配置（从环境变量或 .env 读取）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Judge LLM
    ragas_judge_provider: Literal["openai", "anthropic", "ollama"] = "openai"
    ragas_judge_model: str = "gpt-4o"
    ragas_judge_api_key: str = Field(default="", alias="openai_api_key")
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # 评测数据集
    ragas_eval_dataset: Path = Path("/app/eval/datasets/qa_pairs.json")
    ragas_report_dir: Path = Path("/app/eval_reports")
    ragas_batch_size: int = 5

    # RAG API
    rag_api_base_url: str = "http://localhost:8000/api/v1"
    request_timeout_sec: int = 120

    # 评测指标开关
    eval_faithfulness: bool = True
    eval_answer_relevancy: bool = True
    eval_context_precision: bool = True
    eval_context_recall: bool = True
    eval_answer_correctness: bool = False  # 需要 ground_truth，按需开启

    @field_validator("ragas_report_dir", mode="before")
    @classmethod
    def ensure_report_dir(cls, v: str | Path) -> Path:
        p = Path(v)
        p.mkdir(parents=True, exist_ok=True)
        return p


eval_settings = EvalSettings()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 输入数据模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class QAPair(BaseModel):
    """单条评测问答对。"""

    question: str = Field(..., description="评测问题")
    ground_truth: str | None = Field(None, description="参考答案（可选，用于 answer_correctness）")
    doc_type: Literal[
        "policy_factual", "procedural", "comparison",
        "definition", "multi_hop"
    ] | None = Field(None, description="doc_type — 问题类型，用于分层统计")
    topic: str | None = Field(None, description="主题标签，如 leave_policy / reimbursement")
    source_doc: str | None = Field(None, description="来源文档路径（仅 holdout 文档）")
    # source_doc must reference a path listed in holdout_manifest.json (anti-contamination)
    metadata: dict[str, Any] = Field(default_factory=dict, description="附加元数据")

    @field_validator("question")
    @classmethod
    def question_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be empty")
        return v.strip()


class EvalDataset(BaseModel):
    """评测数据集（JSON 文件根对象）。"""

    name: str = Field(default="RAG Eval Dataset", description="数据集名称")
    version: str = Field(default="1.0.0")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    description: str = Field(default="", description="数据集说明")
    pairs: list[QAPair] = Field(..., min_length=1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RAG API 调用结果
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class RAGResponse(BaseModel):
    """从 /query 端点返回的完整结果。"""

    question: str
    answer: str
    contexts: list[str]          # 检索到的文本段列表
    ground_truth: str | None = None
    latency_ms: float = 0.0
    trace_id: str = ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 单条评测结果
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class SingleEvalResult(BaseModel):
    """每个问题的 RAGAS 指标评分。"""

    question: str
    answer: str
    context_count: int
    latency_ms: float
    trace_id: str

    # RAGAS 指标（None = 未开启或评测失败）
    faithfulness: float | None = None
    answer_relevancy: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None
    answer_correctness: float | None = None

    error: str | None = None   # 评测异常信息

    @property
    def passed(self) -> bool:
        """至少一个指标成功评测则视为通过。"""
        scores = [
            self.faithfulness, self.answer_relevancy,
            self.context_precision, self.context_recall,
        ]
        return any(s is not None for s in scores)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 聚合报告
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class EvalReport(BaseModel):
    """完整评测报告（写入 JSON + HTML）。"""

    run_id: str
    dataset_name: str
    judge_model: str
    started_at: datetime
    finished_at: datetime
    total_questions: int
    successful_evals: int
    failed_evals: int

    # 平均分（None = 全部失败）
    avg_faithfulness: float | None = None
    avg_answer_relevancy: float | None = None
    avg_context_precision: float | None = None
    avg_context_recall: float | None = None
    avg_answer_correctness: float | None = None
    avg_latency_ms: float | None = None

    # 明细
    results: list[SingleEvalResult] = Field(default_factory=list)

    @property
    def overall_score(self) -> float | None:
        """四项主要指标的宏平均（Macro-average）。"""
        scores = [
            s for s in [
                self.avg_faithfulness,
                self.avg_answer_relevancy,
                self.avg_context_precision,
                self.avg_context_recall,
            ] if s is not None
        ]
        return round(sum(scores) / len(scores), 4) if scores else None

    def summary_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "overall_score": self.overall_score,
            "faithfulness": self.avg_faithfulness,
            "answer_relevancy": self.avg_answer_relevancy,
            "context_precision": self.avg_context_precision,
            "context_recall": self.avg_context_recall,
            "answer_correctness": self.avg_answer_correctness,
            "avg_latency_ms": self.avg_latency_ms,
            "total": self.total_questions,
            "success": self.successful_evals,
            "failed": self.failed_evals,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
        }
