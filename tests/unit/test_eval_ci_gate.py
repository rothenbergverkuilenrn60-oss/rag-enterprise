"""Tests for scripts/eval_ci_gate.py RAGAS threshold gate (Task 3 — TEST-03)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")
os.environ.setdefault("RAGAS_REPORT_DIR", "/tmp/eval_reports")
os.environ.setdefault("RAGAS_EVAL_DATASET", "/tmp/qa_pairs_placeholder.json")

# Make scripts/ importable without __init__.py
_SCRIPTS_DIR = str(Path(__file__).parent.parent.parent / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_gate_passes_when_thresholds_met(monkeypatch) -> None:
    """Gate exits 0 (no exception) when faithfulness ≥ 0.85 and answer_relevancy ≥ 0.80."""
    import eval_ci_gate

    mock_report = MagicMock()
    mock_report.avg_faithfulness = 0.90
    mock_report.avg_answer_relevancy = 0.85
    mock_eval = MagicMock()
    mock_eval.run = AsyncMock(return_value=mock_report)
    monkeypatch.setattr(eval_ci_gate, "RagasEvaluator", lambda: mock_eval)

    # Should complete without raising SystemExit
    await eval_ci_gate.main()


@pytest.mark.asyncio
async def test_gate_fails_on_low_faithfulness(monkeypatch) -> None:
    """Gate exits 1 when avg_faithfulness < 0.85."""
    import eval_ci_gate

    mock_report = MagicMock()
    mock_report.avg_faithfulness = 0.80
    mock_report.avg_answer_relevancy = 0.85
    mock_eval = MagicMock()
    mock_eval.run = AsyncMock(return_value=mock_report)
    monkeypatch.setattr(eval_ci_gate, "RagasEvaluator", lambda: mock_eval)

    with pytest.raises(SystemExit) as exc:
        await eval_ci_gate.main()
    assert exc.value.code == 1


@pytest.mark.asyncio
async def test_gate_fails_on_low_answer_relevancy(monkeypatch) -> None:
    """Gate exits 1 when avg_answer_relevancy < 0.80."""
    import eval_ci_gate

    mock_report = MagicMock()
    mock_report.avg_faithfulness = 0.90
    mock_report.avg_answer_relevancy = 0.70
    mock_eval = MagicMock()
    mock_eval.run = AsyncMock(return_value=mock_report)
    monkeypatch.setattr(eval_ci_gate, "RagasEvaluator", lambda: mock_eval)

    with pytest.raises(SystemExit) as exc:
        await eval_ci_gate.main()
    assert exc.value.code == 1


@pytest.mark.asyncio
async def test_gate_fails_on_none_metric(monkeypatch) -> None:
    """Gate exits 1 when avg_faithfulness is None (missing metric treated as failure)."""
    import eval_ci_gate

    mock_report = MagicMock()
    mock_report.avg_faithfulness = None
    mock_report.avg_answer_relevancy = 0.85
    mock_eval = MagicMock()
    mock_eval.run = AsyncMock(return_value=mock_report)
    monkeypatch.setattr(eval_ci_gate, "RagasEvaluator", lambda: mock_eval)

    with pytest.raises(SystemExit) as exc:
        await eval_ci_gate.main()
    assert exc.value.code == 1
