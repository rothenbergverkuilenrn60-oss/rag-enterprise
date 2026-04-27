"""Tests for eval/models.py QAPair stratification fields (Task 1 — TEST-02/03)."""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")
os.environ.setdefault("RAGAS_REPORT_DIR", "/tmp/eval_reports")
os.environ.setdefault("RAGAS_EVAL_DATASET", "/tmp/qa_pairs_placeholder.json")

import pytest
import pydantic

from eval.models import QAPair, EvalDataset


def test_qapair_accepts_doc_type_literal() -> None:
    """QAPair with a valid doc_type Literal value constructs without error."""
    pair = QAPair(question="q?", ground_truth="a", doc_type="policy_factual")
    assert pair.doc_type == "policy_factual"


def test_qapair_rejects_invalid_doc_type() -> None:
    """QAPair with an unknown doc_type raises ValidationError."""
    with pytest.raises(pydantic.ValidationError):
        QAPair(question="q?", doc_type="invalid_type")


def test_qapair_doc_type_optional() -> None:
    """QAPair without doc_type constructs and defaults to None."""
    pair = QAPair(question="q?")
    assert pair.doc_type is None


def test_qapair_topic_and_source_doc_optional() -> None:
    """QAPair topic and source_doc both default to None."""
    pair = QAPair(question="q?")
    assert pair.topic is None
    assert pair.source_doc is None


def test_eval_dataset_round_trip_with_strata() -> None:
    """EvalDataset round-trips correctly with stratification fields."""
    raw = {
        "pairs": [
            {
                "question": "q",
                "doc_type": "procedural",
                "topic": "leave_policy",
                "source_doc": "docs/x.pdf",
            }
        ]
    }
    dataset = EvalDataset.model_validate(raw)
    assert len(dataset.pairs) == 1
    pair = dataset.pairs[0]
    assert pair.doc_type == "procedural"
    assert pair.topic == "leave_policy"
    assert pair.source_doc == "docs/x.pdf"
