# =============================================================================
# eval/ragas_runner.py
# RAGAS 评测引擎 — 生产级实现
# 功能：批量调用 RAG API → RAGAS 多指标评分 → JSON + HTML 报告输出
# 运行：python -m eval.ragas_runner
# Docker：docker compose run --rm ragas-eval
# =============================================================================
from __future__ import annotations

import asyncio
import json
import statistics
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from datasets import Dataset
from loguru import logger
from ragas import evaluate
from ragas.metrics import (
    AnswerRelevancy,
    ContextPrecision,
    ContextRecall,
    Faithfulness,
)
from tenacity import retry, stop_after_attempt, wait_random_exponential

from eval.models import (
    EvalDataset,
    EvalReport,
    EvalSettings,
    QAPair,
    RAGResponse,
    SingleEvalResult,
    eval_settings,
)
from eval.report_renderer import render_html_report


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Judge LLM 工厂
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _build_judge_llm(cfg: EvalSettings):
    """根据配置构建 RAGAS judge LLM 包装器。"""
    provider = cfg.ragas_judge_provider

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=cfg.ragas_judge_model,
            api_key=cfg.ragas_judge_api_key,
            temperature=0,
            max_retries=3,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic  # type: ignore[import-not-found]
        return ChatAnthropic(
            model=cfg.ragas_judge_model,
            api_key=cfg.anthropic_api_key,
            temperature=0,
            max_retries=3,
        )

    if provider == "ollama":
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(
            model=cfg.ragas_judge_model,
            base_url=cfg.ollama_base_url,
            temperature=0,
        )

    raise ValueError(f"Unsupported ragas_judge_provider: {provider!r}")


def _build_judge_embeddings(cfg: EvalSettings):
    """RAGAS 内部向量化（用于 answer_relevancy 余弦相似度计算）。"""
    provider = cfg.ragas_judge_provider

    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(api_key=cfg.ragas_judge_api_key)

    if provider == "ollama":
        from langchain_community.embeddings import OllamaEmbeddings
        return OllamaEmbeddings(
            model="bge-m3",
            base_url=cfg.ollama_base_url,
        )

    # Anthropic 无官方 embedding，降级到 OpenAI
    from langchain_openai import OpenAIEmbeddings
    logger.warning("Anthropic judge: using OpenAI embeddings for RAGAS internal metrics.")
    return OpenAIEmbeddings(api_key=cfg.ragas_judge_api_key)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RAG API 客户端
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class RAGAPIClient:
    """调用本系统 /query 端点，返回结构化 RAGResponse。"""

    def __init__(self, cfg: EvalSettings) -> None:
        self._base_url = cfg.rag_api_base_url.rstrip("/")
        self._timeout = httpx.Timeout(cfg.request_timeout_sec)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "RAGAPIClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={"Content-Type": "application/json"},
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(multiplier=1, max=10),
        reraise=True,
    )
    async def query(self, qa: QAPair) -> RAGResponse:
        """向 /query 发起请求，解析答案与上下文。"""
        if self._client is None:
            raise RuntimeError("Client not initialized. Use async context manager.")

        payload = {"query": qa.question, "top_k": 6}
        response = await self._client.post("/query", json=payload)
        response.raise_for_status()

        body: dict[str, Any] = response.json()
        data: dict[str, Any] = body.get("data", {})

        # 兼容 GenerationResponse 结构
        answer: str = data.get("answer", "")
        sources: list[dict[str, Any]] = data.get("sources", [])
        contexts: list[str] = [
            s.get("content", s.get("text", "")) for s in sources if s
        ]
        latency_ms: float = data.get("latency_ms", 0.0)
        trace_id: str = data.get("trace_id", body.get("trace_id", ""))

        return RAGResponse(
            question=qa.question,
            answer=answer,
            contexts=contexts,
            ground_truth=qa.ground_truth,
            latency_ms=latency_ms,
            trace_id=trace_id,
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 评测引擎
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class RagasEvaluator:
    """
    批量执行 RAGAS 评测的主引擎。

    流程：
      1. 从 JSON 文件加载 QAPair 数据集
      2. 批量调用 RAG API 获得 answer + contexts
      3. 构建 HuggingFace Dataset → 调用 ragas.evaluate
      4. 聚合指标 → 生成 EvalReport → 写出 JSON + HTML
    """

    def __init__(self, cfg: EvalSettings = eval_settings) -> None:
        self._cfg = cfg
        self._llm = _build_judge_llm(cfg)
        self._embeddings = _build_judge_embeddings(cfg)

    # ── 数据加载 ────────────────────────────────────────────────────────────
    def load_dataset(self) -> EvalDataset:
        path = self._cfg.ragas_eval_dataset
        if not path.exists():
            raise FileNotFoundError(f"Eval dataset not found: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        return EvalDataset.model_validate(raw)

    # ── 批量 RAG 调用 ────────────────────────────────────────────────────────
    async def _collect_rag_responses(
        self,
        pairs: list[QAPair],
        batch_size: int,
    ) -> list[RAGResponse | Exception]:
        """
        并发调用 RAG API（受 batch_size 控制的信号量限流），
        失败时记录异常而非中断整批。
        """
        sem = asyncio.Semaphore(batch_size)
        results: list[RAGResponse | Exception] = [None] * len(pairs)  # type: ignore

        async with RAGAPIClient(self._cfg) as client:
            async def _call(idx: int, qa: QAPair) -> None:
                async with sem:
                    try:
                        results[idx] = await client.query(qa)
                        logger.debug(
                            f"[EvalQuery] [{idx+1}/{len(pairs)}] "
                            f"trace={results[idx].trace_id} "  # type: ignore
                            f"latency={results[idx].latency_ms:.0f}ms"  # type: ignore
                        )
                    except Exception as exc:
                        results[idx] = exc
                        logger.warning(
                            f"[EvalQuery] [{idx+1}/{len(pairs)}] "
                            f"FAILED: {exc}"
                        )

            await asyncio.gather(*[_call(i, p) for i, p in enumerate(pairs)])

        return results

    # ── RAGAS 评测 ──────────────────────────────────────────────────────────
    def _build_metrics(self) -> list:
        cfg = self._cfg
        metrics = []
        if cfg.eval_faithfulness:
            metrics.append(Faithfulness(llm=self._llm))
        if cfg.eval_answer_relevancy:
            metrics.append(AnswerRelevancy(llm=self._llm, embeddings=self._embeddings))
        if cfg.eval_context_precision:
            metrics.append(ContextPrecision(llm=self._llm))
        if cfg.eval_context_recall:
            metrics.append(ContextRecall(llm=self._llm))
        if not metrics:
            raise ValueError("At least one RAGAS metric must be enabled.")
        return metrics

    def _run_ragas(
        self,
        responses: list[RAGResponse],
    ) -> dict[str, list[float | None]]:
        """
        将 RAGResponse 列表转为 HuggingFace Dataset 并调用 ragas.evaluate。
        返回每个问题每个指标的浮点分数。
        """
        records: list[dict[str, Any]] = []
        for r in responses:
            record: dict[str, Any] = {
                "question": r.question,
                "answer": r.answer,
                "contexts": r.contexts if r.contexts else [""],
            }
            if r.ground_truth:
                record["ground_truth"] = r.ground_truth
            records.append(record)

        hf_dataset = Dataset.from_list(records)
        metrics = self._build_metrics()

        logger.info(
            f"[RAGAS] Evaluating {len(records)} samples "
            f"with metrics: {[m.__class__.__name__ for m in metrics]}"
        )

        result = evaluate(
            dataset=hf_dataset,
            metrics=metrics,
            raise_exceptions=False,   # 单条失败不中断整批
        )

        # result 是 pandas DataFrame（ragas 0.2+）
        df = result.to_pandas()
        score_map: dict[str, list[float | None]] = {}
        for col in df.columns:
            if col not in ("question", "answer", "contexts", "ground_truth"):
                score_map[col] = [
                    None if (v is None or (isinstance(v, float) and v != v))
                    else float(v)
                    for v in df[col].tolist()
                ]
        return score_map

    # ── 聚合 & 报告 ─────────────────────────────────────────────────────────
    @staticmethod
    def _safe_mean(values: list[float | None]) -> float | None:
        valid = [v for v in values if v is not None]
        return round(statistics.mean(valid), 4) if valid else None

    def _build_report(
        self,
        run_id: str,
        dataset: EvalDataset,
        rag_responses: list[RAGResponse | Exception],
        pairs: list[QAPair],
        started_at: datetime,
        batch_faith_scores: list[float | None] | None = None,
    ) -> EvalReport:
        """整合 RAG 响应和 RAGAS 评分，构建最终报告。"""

        # 区分成功/失败
        valid_responses: list[RAGResponse] = []
        failed_indices: set[int] = set()
        for idx, resp in enumerate(rag_responses):
            if isinstance(resp, Exception):
                failed_indices.add(idx)
            else:
                valid_responses.append(resp)

        # 调用 RAGAS
        score_map: dict[str, list[float | None]] = {}
        if valid_responses:
            try:
                score_map = self._run_ragas(valid_responses)
            except Exception as exc:
                logger.error(f"[RAGAS] Batch evaluation failed: {exc}\n{traceback.format_exc()}")

        # 构建 SingleEvalResult 列表
        results: list[SingleEvalResult] = []
        valid_idx = 0
        for raw_idx, pair in enumerate(pairs):
            if raw_idx in failed_indices:
                exc = rag_responses[raw_idx]
                results.append(SingleEvalResult(
                    question=pair.question,
                    answer="",
                    context_count=0,
                    latency_ms=0.0,
                    trace_id="",
                    error=str(exc),
                ))
                continue

            resp: RAGResponse = valid_responses[valid_idx]  # type: ignore
            # 忠实度优先用 Batch API 结果（更准确、成本更低），回退到 RAGAS
            batch_faith = (
                batch_faith_scores[valid_idx]
                if batch_faith_scores and valid_idx < len(batch_faith_scores)
                else None
            )
            ragas_faith = score_map.get("faithfulness", [None] * (valid_idx + 1))[valid_idx]
            final_faith = batch_faith if batch_faith is not None else ragas_faith

            result = SingleEvalResult(
                question=resp.question,
                answer=resp.answer,
                context_count=len(resp.contexts),
                latency_ms=resp.latency_ms,
                trace_id=resp.trace_id,
                faithfulness=final_faith,
                answer_relevancy=score_map.get("answer_relevancy", [None] * (valid_idx + 1))[valid_idx],
                context_precision=score_map.get("context_precision", [None] * (valid_idx + 1))[valid_idx],
                context_recall=score_map.get("context_recall", [None] * (valid_idx + 1))[valid_idx],
                answer_correctness=score_map.get("answer_correctness", [None] * (valid_idx + 1))[valid_idx],
            )
            results.append(result)
            valid_idx += 1

        # 聚合均值
        def _col(key: str) -> list[float | None]:
            return [r.__dict__.get(key) for r in results]

        latencies = [r.latency_ms for r in results if r.latency_ms > 0]

        return EvalReport(
            run_id=run_id,
            dataset_name=dataset.name,
            judge_model=f"{self._cfg.ragas_judge_provider}/{self._cfg.ragas_judge_model}",
            started_at=started_at,
            finished_at=datetime.utcnow(),
            total_questions=len(pairs),
            successful_evals=len(valid_responses),
            failed_evals=len(failed_indices),
            avg_faithfulness=self._safe_mean(_col("faithfulness")),
            avg_answer_relevancy=self._safe_mean(_col("answer_relevancy")),
            avg_context_precision=self._safe_mean(_col("context_precision")),
            avg_context_recall=self._safe_mean(_col("context_recall")),
            avg_answer_correctness=self._safe_mean(_col("answer_correctness")),
            avg_latency_ms=round(statistics.mean(latencies), 1) if latencies else None,
            results=results,
        )

    # ── 主入口 ──────────────────────────────────────────────────────────────
    async def run(self) -> EvalReport:
        run_id = str(uuid.uuid4())[:8]
        started_at = datetime.utcnow()
        cfg = self._cfg

        logger.info("=" * 60)
        logger.info(f"[RAGAS] Evaluation run_id={run_id}")
        logger.info(f"[RAGAS] Dataset: {cfg.ragas_eval_dataset}")
        logger.info(f"[RAGAS] Judge: {cfg.ragas_judge_provider}/{cfg.ragas_judge_model}")
        logger.info("=" * 60)

        # 1. 加载数据集
        dataset = self.load_dataset()
        logger.info(f"[RAGAS] Loaded {len(dataset.pairs)} QA pairs from '{dataset.name}'")

        # 2. 批量调用 RAG API
        logger.info(f"[RAGAS] Querying RAG API (batch_size={cfg.ragas_batch_size})...")
        rag_responses = await self._collect_rag_responses(
            dataset.pairs,
            cfg.ragas_batch_size,
        )

        # 3. Anthropic Batch API 忠实度评分（可选，provider=anthropic 时生效）
        batch_faith_scores: list[float | None] = []
        if self._cfg.ragas_judge_provider == "anthropic" and self._cfg.anthropic_api_key:
            valid_resps = [r for r in rag_responses if isinstance(r, RAGResponse)]
            if valid_resps:
                try:
                    judge = AnthropicBatchFaithfulnessJudge(
                        api_key=self._cfg.anthropic_api_key,
                    )
                    batch_faith_scores = judge.score_batch(valid_resps)
                    logger.info(f"[RAGAS] Batch faithfulness: {len(batch_faith_scores)} scores")
                except Exception as exc:
                    logger.warning(f"[RAGAS] Batch judge failed (fallback to RAGAS): {exc}")

        # 4. 构建报告
        report = self._build_report(
            run_id, dataset, rag_responses, dataset.pairs, started_at,
            batch_faith_scores=batch_faith_scores,
        )

        # 4. 写出 JSON 报告
        report_dir = cfg.ragas_report_dir
        ts = started_at.strftime("%Y%m%d_%H%M%S")
        json_path = report_dir / f"eval_{run_id}_{ts}.json"
        json_path.write_text(
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"[RAGAS] JSON report saved: {json_path}")

        # 5. 写出 HTML 报告
        html_path = report_dir / f"eval_{run_id}_{ts}.html"
        html_content = render_html_report(report)
        html_path.write_text(html_content, encoding="utf-8")
        logger.info(f"[RAGAS] HTML report saved: {html_path}")

        # 5b. 分类维度报告
        try:
            from eval.category_report import generate_category_report
            cat_html_path = generate_category_report(
                report=report,
                dataset_path=cfg.ragas_eval_dataset,
                report_dir=report_dir,
                ts=ts,
            )
            logger.info(f"[RAGAS] Category report saved: {cat_html_path}")
        except Exception as exc:
            logger.warning(f"[RAGAS] Category report skipped: {exc}")

        # 6. 打印摘要
        summary = report.summary_dict()
        logger.info("=" * 60)
        logger.info("[RAGAS] ━━ EVALUATION SUMMARY ━━")
        for k, v in summary.items():
            if k not in ("started_at", "finished_at", "run_id"):
                logger.info(f"  {k:<25} = {v}")
        logger.info("=" * 60)

        # 7. 低分结果自动推送到人工标注队列（闭环核心）
        await self._push_low_score_to_annotation(report, rag_responses, dataset.pairs)

        return report

    async def _push_low_score_to_annotation(
        self,
        report,
        rag_responses: list,
        pairs: list[QAPair],
    ) -> None:
        """
        RAGAS 评估后，将忠实度 < 0.6 的样本自动推入人工标注队列。
        标注员评分并纠正后，结果写回黄金数据集，形成数据质量飞轮。
        """
        try:
            from services.annotation.annotation_service import get_annotation_service
            annotation_svc = get_annotation_service()
            pushed = 0
            for i, (result, pair) in enumerate(zip(report.results, pairs)):
                faith = result.faithfulness
                if faith is not None and faith < 0.6:
                    resp = rag_responses[i] if i < len(rag_responses) else None
                    contexts = resp.contexts if hasattr(resp, "contexts") else []
                    await annotation_svc.push_task_from_ragas(
                        question=result.question,
                        answer=result.answer,
                        contexts=contexts,
                        ragas_score=faith,
                        ground_truth=pair.ground_truth or "",
                    )
                    pushed += 1
            if pushed:
                logger.info(f"[RAGAS] {pushed} low-score samples pushed to annotation queue")
        except Exception as exc:
            logger.warning(f"[RAGAS] Annotation push failed (non-fatal): {exc}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Anthropic Batch API 忠实度评估器
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class AnthropicBatchFaithfulnessJudge:
    """使用 Anthropic Message Batches API 批量评估忠实度。

    相比逐条调用的优势：
      - 成本降低 50%（Batch API 定价折扣）
      - 无并发速率限制，可一次提交数百条
      - 结果异步返回，不阻塞主流程
      - 适合离线评估场景（非实时）

    工作流程：
      1. 将所有 (answer, context) 对打包为一个 Batch 请求
      2. 提交后立即返回 batch_id
      3. 轮询直到 batch 处于 ended 状态（通常 1-30 分钟）
      4. 逐条读取评分结果
    """

    _JUDGE_SYSTEM = """\
你是忠实度评估专家。判断答案是否完全基于给定上下文，不含外部知识或推断。
只调用工具，输出结构化评分。"""

    _JUDGE_TOOL = {
        "name": "score_faithfulness",
        "description": "输出忠实度评分",
        "input_schema": {
            "type": "object",
            "properties": {
                "score":  {"type": "number", "description": "0.0-1.0 忠实度分数"},
                "reason": {"type": "string", "description": "20字以内评分理由"},
            },
            "required": ["score", "reason"],
        },
    }

    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001") -> None:
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model  = model

    def _make_request(self, custom_id: str, answer: str, context: str) -> dict:
        return {
            "custom_id": custom_id,
            "params": {
                "model":      self._model,
                "max_tokens": 256,
                "system":     self._JUDGE_SYSTEM,
                "tools":      [self._JUDGE_TOOL],
                "tool_choice": {"type": "any"},
                "messages": [{
                    "role": "user",
                    "content": (
                        f"<context>\n{context[:1500]}\n</context>\n\n"
                        f"<answer>\n{answer}\n</answer>"
                    ),
                }],
            },
        }

    def score_batch(
        self,
        responses: list[RAGResponse],
        poll_interval_sec: int = 15,
        max_wait_sec: int = 1800,
    ) -> list[float | None]:
        """批量评分，返回与 responses 等长的 score 列表（失败条目为 None）。"""
        import time as _time

        if not responses:
            return []

        # 1. 构建 batch 请求
        requests = [
            self._make_request(
                custom_id=f"faith_{i}",
                answer=r.answer,
                context=" ".join(r.contexts[:3]),
            )
            for i, r in enumerate(responses)
        ]

        # 2. 提交 batch
        batch = self._client.messages.batches.create(requests=requests)
        batch_id = batch.id
        logger.info(f"[BatchJudge] Submitted batch_id={batch_id} size={len(requests)}")

        # 3. 轮询直到完成
        deadline = _time.time() + max_wait_sec
        while _time.time() < deadline:
            _time.sleep(poll_interval_sec)
            status = self._client.messages.batches.retrieve(batch_id)
            logger.info(
                f"[BatchJudge] batch_id={batch_id} "
                f"processing={status.request_counts.processing} "
                f"succeeded={status.request_counts.succeeded} "
                f"errored={status.request_counts.errored}"
            )
            if status.processing_status == "ended":
                break
        else:
            logger.warning(f"[BatchJudge] Timeout waiting for batch {batch_id}")
            return [None] * len(responses)

        # 4. 读取结果
        scores: dict[int, float | None] = {}
        for result in self._client.messages.batches.results(batch_id):
            idx = int(result.custom_id.split("_")[1])
            if result.result.type == "succeeded":
                msg = result.result.message
                for block in msg.content:
                    if block.type == "tool_use" and block.name == "score_faithfulness":
                        scores[idx] = float(block.input.get("score", 0.5))
                        break
            else:
                scores[idx] = None

        return [scores.get(i) for i in range(len(responses))]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 入口
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async def main() -> None:
    from loguru import logger as _logger
    import sys
    _logger.remove()
    _logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<8} | {message}")

    evaluator = RagasEvaluator()
    report = await evaluator.run()

    overall = report.overall_score
    exit_code = 0 if (overall is not None and overall >= 0.6) else 1
    raise SystemExit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
