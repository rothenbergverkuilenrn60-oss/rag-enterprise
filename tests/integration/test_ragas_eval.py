# =============================================================================
# tests/integration/test_ragas_eval.py
# RAGAS 评测集成测试 — 验证评测流程可正常执行（使用 Mock RAG API）
# 运行：conda run -n torch_env pytest tests/integration/test_ragas_eval.py -v
# =============================================================================
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval.models import (
    EvalDataset,
    EvalReport,
    EvalSettings,
    QAPair,
    RAGResponse,
    SingleEvalResult,
)
from eval.report_renderer import render_html_report


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Fixtures
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@pytest.fixture()
def sample_qa_pair() -> QAPair:
    return QAPair(
        question="什么是RAG？",
        ground_truth="RAG是检索增强生成技术。",
    )


@pytest.fixture()
def sample_dataset(tmp_path: Path) -> Path:
    data = {
        "name": "Test Dataset",
        "version": "1.0.0",
        "created_at": "2025-01-01T00:00:00",
        "pairs": [
            {
                "question": "什么是向量数据库？",
                "ground_truth": "向量数据库是专门存储和检索高维向量的数据库系统。",
                "metadata": {"category": "test"},
            },
            {
                "question": "BGE-M3 模型支持多少种语言？",
                "ground_truth": "BGE-M3 支持超过100种语言。",
                "metadata": {"category": "test"},
            },
        ],
    }
    dataset_path = tmp_path / "test_qa_pairs.json"
    dataset_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return dataset_path


@pytest.fixture()
def eval_cfg(tmp_path: Path, sample_dataset: Path) -> EvalSettings:
    """覆盖配置为测试值，避免依赖真实 API。"""
    cfg = EvalSettings(
        ragas_judge_provider="openai",
        ragas_judge_model="gpt-4o-mini",
        ragas_judge_api_key="sk-test-fake-key",
        ragas_eval_dataset=sample_dataset,
        ragas_report_dir=tmp_path / "reports",
        ragas_batch_size=2,
        rag_api_base_url="http://localhost:8000/api/v1",
        eval_faithfulness=True,
        eval_answer_relevancy=True,
        eval_context_precision=True,
        eval_context_recall=False,
        eval_answer_correctness=False,
    )
    return cfg


@pytest.fixture()
def mock_rag_response() -> RAGResponse:
    return RAGResponse(
        question="什么是向量数据库？",
        answer="向量数据库是专门存储高维向量的数据库，支持语义相似度搜索。",
        contexts=[
            "向量数据库（Vector Database）是专为存储和检索高维向量数据设计的数据库系统。",
            "常见的向量数据库包括 Qdrant、Milvus、Chroma、Pinecone 等。",
        ],
        ground_truth="向量数据库是专门存储和检索高维向量的数据库系统。",
        latency_ms=342.5,
        trace_id="abc12345",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 模型验证测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestEvalModels:
    def test_qa_pair_valid(self, sample_qa_pair: QAPair) -> None:
        assert sample_qa_pair.question == "什么是RAG？"
        assert sample_qa_pair.ground_truth == "RAG是检索增强生成技术。"

    def test_qa_pair_empty_question_raises(self) -> None:
        with pytest.raises(Exception):
            QAPair(question="   ", ground_truth=None)

    def test_eval_dataset_validates_pairs(self, sample_dataset: Path) -> None:
        raw = json.loads(sample_dataset.read_text())
        dataset = EvalDataset.model_validate(raw)
        assert len(dataset.pairs) == 2
        assert dataset.pairs[0].question == "什么是向量数据库？"

    def test_single_eval_result_passed(self, mock_rag_response: RAGResponse) -> None:
        result = SingleEvalResult(
            question=mock_rag_response.question,
            answer=mock_rag_response.answer,
            context_count=len(mock_rag_response.contexts),
            latency_ms=mock_rag_response.latency_ms,
            trace_id=mock_rag_response.trace_id,
            faithfulness=0.92,
            answer_relevancy=0.87,
            context_precision=0.78,
        )
        assert result.passed is True

    def test_single_eval_result_all_none_not_passed(self) -> None:
        result = SingleEvalResult(
            question="q", answer="a", context_count=0,
            latency_ms=0, trace_id="",
        )
        assert result.passed is False

    def test_eval_report_overall_score(self) -> None:
        from datetime import datetime
        report = EvalReport(
            run_id="test01",
            dataset_name="Test",
            judge_model="openai/gpt-4o",
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            total_questions=2,
            successful_evals=2,
            failed_evals=0,
            avg_faithfulness=0.90,
            avg_answer_relevancy=0.85,
            avg_context_precision=0.80,
            avg_context_recall=0.75,
        )
        overall = report.overall_score
        assert overall is not None
        assert abs(overall - round((0.90 + 0.85 + 0.80 + 0.75) / 4, 4)) < 1e-6

    def test_eval_report_overall_score_partial_metrics(self) -> None:
        from datetime import datetime
        report = EvalReport(
            run_id="test02",
            dataset_name="Test",
            judge_model="openai/gpt-4o",
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            total_questions=1,
            successful_evals=1,
            failed_evals=0,
            avg_faithfulness=0.88,
            avg_answer_relevancy=None,  # 未开启
            avg_context_precision=0.72,
            avg_context_recall=None,
        )
        overall = report.overall_score
        assert overall is not None
        assert abs(overall - round((0.88 + 0.72) / 2, 4)) < 1e-6


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RAG API 客户端测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestRAGAPIClient:
    @pytest.mark.asyncio
    async def test_query_parses_response_correctly(
        self, eval_cfg: EvalSettings, sample_qa_pair: QAPair
    ) -> None:
        from eval.ragas_runner import RAGAPIClient

        mock_resp_body = {
            "success": True,
            "trace_id": "abc12345",
            "data": {
                "answer": "RAG即检索增强生成，结合了信息检索与LLM生成。",
                "sources": [
                    {"content": "RAG是一种将检索与生成结合的AI技术。"},
                    {"content": "RAG通过检索相关文档来增强LLM的生成质量。"},
                ],
                "latency_ms": 512.3,
                "trace_id": "abc12345",
            },
        }

        mock_http_response = MagicMock()
        mock_http_response.raise_for_status = MagicMock()
        mock_http_response.json = MagicMock(return_value=mock_resp_body)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_http_response
            async with RAGAPIClient(eval_cfg) as client:
                result = await client.query(sample_qa_pair)

        assert result.question == sample_qa_pair.question
        assert result.answer == "RAG即检索增强生成，结合了信息检索与LLM生成。"
        assert len(result.contexts) == 2
        assert result.latency_ms == 512.3
        assert result.trace_id == "abc12345"

    @pytest.mark.asyncio
    async def test_query_handles_empty_contexts(
        self, eval_cfg: EvalSettings, sample_qa_pair: QAPair
    ) -> None:
        from eval.ragas_runner import RAGAPIClient

        mock_resp_body = {
            "success": True,
            "trace_id": "xyz99",
            "data": {
                "answer": "暂无相关信息。",
                "sources": [],
                "latency_ms": 100.0,
                "trace_id": "xyz99",
            },
        }
        mock_http_response = MagicMock()
        mock_http_response.raise_for_status = MagicMock()
        mock_http_response.json = MagicMock(return_value=mock_resp_body)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_http_response
            async with RAGAPIClient(eval_cfg) as client:
                result = await client.query(sample_qa_pair)

        assert result.contexts == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 报告渲染测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestReportRenderer:
    def _make_report(self) -> EvalReport:
        from datetime import datetime
        return EvalReport(
            run_id="render01",
            dataset_name="Render Test",
            judge_model="openai/gpt-4o",
            started_at=datetime(2025, 6, 1, 12, 0, 0),
            finished_at=datetime(2025, 6, 1, 12, 5, 30),
            total_questions=2,
            successful_evals=2,
            failed_evals=0,
            avg_faithfulness=0.91,
            avg_answer_relevancy=0.84,
            avg_context_precision=0.77,
            avg_context_recall=0.69,
            avg_latency_ms=425.0,
            results=[
                SingleEvalResult(
                    question="什么是向量数据库？",
                    answer="向量数据库是存储高维向量的专用数据库。",
                    context_count=3,
                    latency_ms=380.0,
                    trace_id="t001",
                    faithfulness=0.93,
                    answer_relevancy=0.88,
                    context_precision=0.80,
                    context_recall=0.72,
                ),
                SingleEvalResult(
                    question="BGE-M3 支持多少语言？",
                    answer="BGE-M3 支持超过 100 种语言。",
                    context_count=2,
                    latency_ms=470.0,
                    trace_id="t002",
                    faithfulness=0.89,
                    answer_relevancy=0.80,
                    context_precision=0.74,
                    context_recall=0.66,
                ),
            ],
        )

    def test_html_contains_run_id(self) -> None:
        report = self._make_report()
        html = render_html_report(report)
        assert "render01" in html

    def test_html_contains_metric_values(self) -> None:
        report = self._make_report()
        html = render_html_report(report)
        assert "0.91" in html
        assert "0.84" in html

    def test_html_contains_questions(self) -> None:
        report = self._make_report()
        html = render_html_report(report)
        assert "什么是向量数据库" in html
        assert "BGE-M3" in html

    def test_html_report_saves_to_disk(self, tmp_path: Path) -> None:
        report = self._make_report()
        html = render_html_report(report)
        out = tmp_path / "test_report.html"
        out.write_text(html, encoding="utf-8")
        assert out.exists()
        assert out.stat().st_size > 1000

    def test_html_structure_valid(self) -> None:
        report = self._make_report()
        html = render_html_report(report)
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert "<table" in html


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 端到端流程测试（Mock RAGAS + RAG API）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestRagasEvaluatorE2E:
    @pytest.mark.asyncio
    async def test_full_pipeline_with_mocks(
        self,
        eval_cfg: EvalSettings,
        mock_rag_response: RAGResponse,
        tmp_path: Path,
    ) -> None:
        """
        端到端测试：Mock RAG API 响应 + Mock RAGAS evaluate，
        验证报告生成流程完整执行，JSON 和 HTML 文件均正确写出。
        """
        from eval.ragas_runner import RagasEvaluator

        # Mock RAG API 返回
        mock_rag_resp_2 = RAGResponse(
            question="BGE-M3 模型支持多少种语言？",
            answer="BGE-M3 支持超过100种语言，含中英文。",
            contexts=["BGE-M3 是支持 100+ 语言的多功能嵌入模型。"],
            ground_truth="BGE-M3 支持超过100种语言。",
            latency_ms=280.0,
            trace_id="def67890",
        )

        # Mock RAGAS DataFrame 结果
        import pandas as pd
        mock_df = pd.DataFrame({
            "question": [mock_rag_response.question, mock_rag_resp_2.question],
            "answer": [mock_rag_response.answer, mock_rag_resp_2.answer],
            "faithfulness": [0.92, 0.88],
            "answer_relevancy": [0.85, 0.82],
            "context_precision": [0.78, 0.74],
        })

        mock_ragas_result = MagicMock()
        mock_ragas_result.to_pandas = MagicMock(return_value=mock_df)

        with (
            patch(
                "eval.ragas_runner.RagasEvaluator._collect_rag_responses",
                new_callable=AsyncMock,
                return_value=[mock_rag_response, mock_rag_resp_2],
            ),
            patch(
                "eval.ragas_runner.evaluate",
                return_value=mock_ragas_result,
            ),
            patch(
                "eval.ragas_runner._build_judge_llm",
                return_value=MagicMock(),
            ),
            patch(
                "eval.ragas_runner._build_judge_embeddings",
                return_value=MagicMock(),
            ),
        ):
            evaluator = RagasEvaluator(cfg=eval_cfg)
            report = await evaluator.run()

        # 报告基本验证
        assert report.total_questions == 2
        assert report.successful_evals == 2
        assert report.failed_evals == 0
        assert report.avg_faithfulness is not None
        assert abs(report.avg_faithfulness - 0.9) < 0.01
        assert report.overall_score is not None
        assert 0.0 < report.overall_score <= 1.0

        # 文件写出验证
        report_files = list(eval_cfg.ragas_report_dir.glob("eval_*.json"))
        html_files = list(eval_cfg.ragas_report_dir.glob("eval_*.html"))
        assert len(report_files) == 1
        assert len(html_files) == 1

        # JSON 内容验证
        saved = json.loads(report_files[0].read_text())
        assert saved["run_id"] == report.run_id
        assert saved["total_questions"] == 2

    @pytest.mark.asyncio
    async def test_handles_partial_api_failure(
        self,
        eval_cfg: EvalSettings,
        mock_rag_response: RAGResponse,
    ) -> None:
        """RAG API 部分失败时，报告应正确统计 failed_evals。"""
        from eval.ragas_runner import RagasEvaluator

        api_error = RuntimeError("Connection timeout")

        import pandas as pd
        mock_df = pd.DataFrame({
            "question": [mock_rag_response.question],
            "answer": [mock_rag_response.answer],
            "faithfulness": [0.90],
            "answer_relevancy": [0.83],
            "context_precision": [0.76],
        })
        mock_ragas_result = MagicMock()
        mock_ragas_result.to_pandas = MagicMock(return_value=mock_df)

        with (
            patch(
                "eval.ragas_runner.RagasEvaluator._collect_rag_responses",
                new_callable=AsyncMock,
                return_value=[mock_rag_response, api_error],  # 第2个失败
            ),
            patch("eval.ragas_runner.evaluate", return_value=mock_ragas_result),
            patch("eval.ragas_runner._build_judge_llm", return_value=MagicMock()),
            patch("eval.ragas_runner._build_judge_embeddings", return_value=MagicMock()),
        ):
            evaluator = RagasEvaluator(cfg=eval_cfg)
            report = await evaluator.run()

        assert report.total_questions == 2
        assert report.successful_evals == 1
        assert report.failed_evals == 1
        failed = [r for r in report.results if r.error is not None]
        assert len(failed) == 1
        assert "Connection timeout" in failed[0].error  # type: ignore
