"""tests/unit/test_reranker_service_app.py — Phase 15 backfill.

Covers services/reranker_service/app.py: RerankerModel fallback prediction,
loaded prediction, /rerank endpoint happy + error paths, /health, /metrics.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.mark.unit
def test_reranker_model_fallback_when_unloaded():
    from services.reranker_service.app import RerankerModel
    m = RerankerModel("path/to/model")
    scores = m.predict("alpha beta", ["alpha gamma", "delta"])
    assert len(scores) == 2
    # First candidate shares "alpha" with query → higher than second
    assert scores[0] > scores[1]


@pytest.mark.unit
def test_reranker_model_uses_loaded_model():
    """Loaded predict path: stub _model.predict to drive return values."""
    from services.reranker_service.app import RerankerModel
    m = RerankerModel("path/x")
    fake_model = MagicMock()
    fake_model.predict = MagicMock(return_value=[0.9, 0.1])
    m._model = fake_model
    m._loaded = True
    out = m.predict("q", ["a", "b"])
    assert out == [0.9, 0.1]
    fake_model.predict.assert_called_once()


@pytest.mark.unit
def test_reranker_model_load_failure_keeps_unloaded(monkeypatch):
    """Error path: CrossEncoder import failure → fallback retained."""
    import sys
    import types as _types

    fake = _types.ModuleType("sentence_transformers")

    def boom(*_a, **_kw):
        raise RuntimeError("model not found")

    fake.CrossEncoder = boom
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake)
    from services.reranker_service.app import RerankerModel
    m = RerankerModel("nonexistent/path")
    m.load()
    assert m._loaded is False


@pytest.mark.unit
def test_health_endpoint_returns_model_status():
    from services.reranker_service import app as app_module
    app_module._models["default"] = MagicMock()
    app_module._models["default"]._loaded = True
    client = TestClient(app_module.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "models" in body


@pytest.mark.unit
def test_metrics_endpoint_returns_text_response():
    from services.reranker_service import app as app_module
    client = TestClient(app_module.app)
    resp = client.get("/metrics")
    assert resp.status_code == 200


@pytest.mark.unit
def test_rerank_rejects_empty_candidates():
    """Error path: empty candidates → HTTP 422."""
    from services.reranker_service import app as app_module
    client = TestClient(app_module.app)
    resp = client.post("/rerank", json={"query": "q", "candidates": []})
    assert resp.status_code == 422


@pytest.mark.unit
def test_rerank_returns_top_k(monkeypatch):
    """Happy path: stub default model → predictable scores → ranked_ids ordered."""
    from services.reranker_service import app as app_module
    fake = MagicMock()
    fake.model_path = "stub-model"
    fake.predict = MagicMock(return_value=[0.1, 0.9, 0.5])
    app_module._models["default"] = fake
    client = TestClient(app_module.app)
    resp = client.post("/rerank", json={
        "query": "q",
        "candidates": ["a", "b", "c"],
        "candidate_ids": ["id-a", "id-b", "id-c"],
        "top_k": 2,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["ranked_ids"]) == 2
    assert body["ranked_ids"][0] == "id-b"
    assert body["scores"] == [0.1, 0.9, 0.5]
    assert body["model_used"] == "stub-model"


@pytest.mark.unit
def test_rerank_no_model_returns_503(monkeypatch):
    """Error path: no model registered → HTTP 503."""
    from services.reranker_service import app as app_module
    monkeypatch.setattr(app_module, "_models", {}, raising=False)
    client = TestClient(app_module.app)
    resp = client.post("/rerank", json={"query": "q", "candidates": ["a"]})
    assert resp.status_code == 503
