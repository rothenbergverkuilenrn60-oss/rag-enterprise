"""Tests for QA dataset stratification and holdout discipline (Task 2 — TEST-03)."""
from __future__ import annotations

import json
import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")
os.environ.setdefault("RAGAS_REPORT_DIR", "/tmp/eval_reports")
os.environ.setdefault("RAGAS_EVAL_DATASET", "/tmp/qa_pairs_placeholder.json")

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
QA_PAIRS_PATH = REPO_ROOT / "eval" / "datasets" / "qa_pairs.json"
HOLDOUT_MANIFEST_PATH = REPO_ROOT / "eval" / "datasets" / "holdout_manifest.json"

VALID_DOC_TYPES = {"policy_factual", "procedural", "comparison", "definition", "multi_hop"}


def test_qa_dataset_has_at_least_200_pairs() -> None:
    """eval/datasets/qa_pairs.json must contain ≥ 200 QA pairs."""
    data = json.loads(QA_PAIRS_PATH.read_text(encoding="utf-8"))
    pairs = data["pairs"]
    assert len(pairs) >= 200, f"Expected ≥200 pairs, got {len(pairs)}"


def test_qa_dataset_stratified_by_doc_type() -> None:
    """All 5 doc_type strata must be present and each stratum ≥ 15 pairs."""
    data = json.loads(QA_PAIRS_PATH.read_text(encoding="utf-8"))
    pairs = data["pairs"]
    counts: dict[str, int] = {}
    for p in pairs:
        dt = p.get("doc_type")
        if dt:
            counts[dt] = counts.get(dt, 0) + 1
    missing = VALID_DOC_TYPES - counts.keys()
    assert not missing, f"Missing strata: {missing}"
    thin = {k: v for k, v in counts.items() if v < 15}
    assert not thin, f"Strata with fewer than 15 pairs: {thin}"


def test_qa_dataset_holdout_only() -> None:
    """Every QAPair.source_doc must be listed in holdout_manifest.json."""
    manifest = json.loads(HOLDOUT_MANIFEST_PATH.read_text(encoding="utf-8"))
    holdout_paths = {d["path"] for d in manifest["holdout_docs"]}
    data = json.loads(QA_PAIRS_PATH.read_text(encoding="utf-8"))
    violators = [
        p["source_doc"]
        for p in data["pairs"]
        if p.get("source_doc") and p["source_doc"] not in holdout_paths
    ]
    assert not violators, f"QA pairs reference non-holdout docs: {violators[:5]}"
