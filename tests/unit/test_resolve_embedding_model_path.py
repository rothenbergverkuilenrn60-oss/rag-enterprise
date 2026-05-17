"""Unit tests for config.settings.resolve_embedding_model_path (Plan 26-02 / TD-07).

Each test monkeypatches `APP_MODEL_DIR` to a tmp_path and reloads `config.settings`
so the module-level `MODEL_DIR` global picks up the patched value. Resolver search
order (first existing wins):
  1. Env override (APP_EMBEDDING_MODEL_PATH / APP_RERANKER_MODEL_PATH)
  2. MODEL_DIR / BAAI / <name>             (HF flat — bug fix target)
  3. MODEL_DIR / embedding_models / <name>  (legacy default)
  4. MODEL_DIR / models--BAAI--<name> / snapshots / <any sha>
  Fallback: legacy path (preserves crash-at-load-time semantics).
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")


def _reload_settings(monkeypatch, tmp_path: Path) -> object:
    """Patch APP_MODEL_DIR and force-reload config.settings.

    Returns the freshly-imported `resolve_embedding_model_path` function bound
    to the patched MODEL_DIR.
    """
    monkeypatch.setenv("APP_MODEL_DIR", str(tmp_path))
    # First-time import path: ensure the module is loaded so sys.modules has it
    import config.settings  # noqa: F401
    cfg = sys.modules["config.settings"]
    importlib.reload(cfg)
    return cfg.resolve_embedding_model_path


def test_env_override_wins(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_EMBEDDING_MODEL_PATH", "/explicit/embed/path")
    (tmp_path / "BAAI" / "bge-m3").mkdir(parents=True)  # disk path also exists
    resolve = _reload_settings(monkeypatch, tmp_path)
    assert resolve("bge-m3") == Path("/explicit/embed/path")


def test_hf_flat_layout_wins_over_legacy(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("APP_EMBEDDING_MODEL_PATH", raising=False)
    (tmp_path / "BAAI" / "bge-m3").mkdir(parents=True)
    (tmp_path / "embedding_models" / "bge-m3").mkdir(parents=True)
    resolve = _reload_settings(monkeypatch, tmp_path)
    assert resolve("bge-m3") == tmp_path / "BAAI" / "bge-m3"


def test_legacy_layout_returns_when_hf_flat_absent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("APP_EMBEDDING_MODEL_PATH", raising=False)
    (tmp_path / "embedding_models" / "bge-m3").mkdir(parents=True)
    resolve = _reload_settings(monkeypatch, tmp_path)
    assert resolve("bge-m3") == tmp_path / "embedding_models" / "bge-m3"


def test_hf_hub_cache_snapshot_resolved(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("APP_EMBEDDING_MODEL_PATH", raising=False)
    snapshot_root = tmp_path / "models--BAAI--bge-m3" / "snapshots" / "abc123"
    snapshot_root.mkdir(parents=True)
    (snapshot_root / "config.json").write_text("{}")
    resolve = _reload_settings(monkeypatch, tmp_path)
    result = resolve("bge-m3")
    assert result.parent.name == "snapshots"
    assert result.parent.parent.name == "models--BAAI--bge-m3"


def test_no_path_exists_returns_legacy_fallback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("APP_EMBEDDING_MODEL_PATH", raising=False)
    # empty tmp_path
    resolve = _reload_settings(monkeypatch, tmp_path)
    result = resolve("bge-m3")
    assert result == tmp_path / "embedding_models" / "bge-m3"
    # Critically: does NOT raise — preserves current crash-at-load semantics


def test_reranker_name_routes_correctly(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("APP_RERANKER_MODEL_PATH", raising=False)
    (tmp_path / "BAAI" / "bge-m3-rerank").mkdir(parents=True)
    resolve = _reload_settings(monkeypatch, tmp_path)
    assert resolve("bge-m3-rerank") == tmp_path / "BAAI" / "bge-m3-rerank"


def test_env_override_only_applies_to_matching_name(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_EMBEDDING_MODEL_PATH", "/embed/path")
    monkeypatch.delenv("APP_RERANKER_MODEL_PATH", raising=False)
    (tmp_path / "embedding_models" / "bge-m3-rerank").mkdir(parents=True)
    resolve = _reload_settings(monkeypatch, tmp_path)
    # Embedding env override should NOT affect reranker lookup
    assert resolve("bge-m3-rerank") == tmp_path / "embedding_models" / "bge-m3-rerank"
