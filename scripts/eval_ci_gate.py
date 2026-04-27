"""RAGAS CI gate — exits 1 if faithfulness < 0.85 or answer_relevancy < 0.80 (TEST-03).

Usage:
    python scripts/eval_ci_gate.py

Environment variables:
    RAG_API_BASE_URL   — staging RAG API endpoint (passed via CI secrets)
    RAGAS_JUDGE_API_KEY / OPENAI_API_KEY  — judge LLM key
"""
from __future__ import annotations

import asyncio
import sys

from eval.ragas_runner import RagasEvaluator

FAITHFULNESS_THRESHOLD = 0.85
ANSWER_RELEVANCY_THRESHOLD = 0.80


async def main() -> None:
    evaluator = RagasEvaluator()
    report = await evaluator.run()

    failures: list[str] = []
    if report.avg_faithfulness is None or report.avg_faithfulness < FAITHFULNESS_THRESHOLD:
        failures.append(
            f"faithfulness={report.avg_faithfulness} < {FAITHFULNESS_THRESHOLD}"
        )
    if (
        report.avg_answer_relevancy is None
        or report.avg_answer_relevancy < ANSWER_RELEVANCY_THRESHOLD
    ):
        failures.append(
            f"answer_relevancy={report.avg_answer_relevancy} < {ANSWER_RELEVANCY_THRESHOLD}"
        )

    if failures:
        for msg in failures:
            print(f"FAIL: {msg}", file=sys.stderr)
        raise SystemExit(1)

    print("PASS: All RAGAS thresholds met.")


if __name__ == "__main__":
    asyncio.run(main())
