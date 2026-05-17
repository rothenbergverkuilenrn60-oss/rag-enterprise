"""Per-test FastAPI factory.

Implements TD-02 D-01 brute-force singleton reset + isolated app construction.

`_SINGLETON_INVENTORY` is enumerated in RESEARCH §1 and lint-tested by
`tests/unit/test_singleton_inventory_complete.py` (created in plan 27-01).

Reset semantics: every test that goes through `create_app()` (or the `app_factory`
fixture) starts with every cached service singleton set to None. Production code is
untouched — the reset is test-process-local mutation of module attributes.

The `create_app()` factory itself lazy-imports `main._configure_app`, which is
introduced in plan 27-01. Until 27-01 lands, calling `create_app()` will raise
ImportError on `_configure_app`. Tests that depend on that path gate themselves
via `pytest.importorskip` or a `getattr(main, '_configure_app', None) is None`
skip check.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

# Module-attr tuples (module_path, attr_name). Order does not matter — reset is
# idempotent. Enumerated from RESEARCH §1 (services only — 4 cached non-service
# primitives are intentionally excluded: tokenizer cache, exception-class caches,
# and an asyncio.Semaphore; see RESEARCH §1 entries 24/26/27/38 for rationale).
_SINGLETON_INVENTORY: tuple[tuple[str, str], ...] = (
    ("services.nlu.nlu_service",              "_nlu_service"),
    ("services.nlu.nlu_service",              "_ner_pipeline"),
    ("services.nlu.filter_extractor",         "_filter_extractor"),
    ("services.nlu.entity_disambiguator",     "_disambiguator"),
    ("services.nlu.entity_disambiguator",     "_entity_lookup"),
    ("services.retriever.retriever",          "_retriever"),
    ("services.retriever.retriever",          "_reranker"),
    ("services.feedback.feedback_service",    "_feedback_service"),
    ("services.auth.oidc_auth",               "_auth_service"),
    ("services.agent.executor",               "_executor_instance"),
    ("services.agent.tools.registry",         "_registry"),
    ("services.agent.tools.web_search",       "_tavily_client"),
    ("services.agent.extractor",              "_extractor"),
    ("services.agent.planner",                "_planner_instance"),
    ("services.memory.memory_service",        "_memory_service"),
    ("services.annotation.annotation_service", "_annotation_service"),
    ("services.vectorizer.indexer",           "_vectorizer"),
    ("services.vectorizer.vector_store",      "_store_instance"),
    ("services.vectorizer.embedder",          "_embedder_instance"),
    ("services.knowledge.knowledge_service",  "_knowledge_service"),
    ("services.knowledge.version_service",    "_version_service"),
    ("services.knowledge.summary_indexer",    "_summary_indexer"),
    ("services.audit.audit_service",          "_audit_service"),
    ("services.generator.generator",          "_generator"),
    ("services.generator.llm_client",         "_llm_instance"),
    ("services.pipeline",                     "_ingest_pipeline"),
    ("services.pipeline",                     "_query_pipeline"),
    ("services.pipeline",                     "_agent_pipeline"),
    ("services.pipeline",                     "_swarm_pipeline"),
    ("services.tenant.tenant_service",        "_tenant_service"),
    ("services.rules.rules_engine",           "_rules_engine"),
    ("services.events.event_bus",             "_event_bus"),
    ("services.preprocessor.pii_detector",    "_pii_detector"),
    ("services.ab_test.ab_test_service",      "_ab_service"),
)


def _reset_singletons() -> None:
    """Reset every module-level service singleton to None.

    Iterates `_SINGLETON_INVENTORY`, imports each module, and zeroes the attr if
    present (`hasattr` guard makes the reset tolerant of refactors that rename
    or remove a singleton). Idempotent.
    """
    for module_path, attr in _SINGLETON_INVENTORY:
        mod = importlib.import_module(module_path)
        if hasattr(mod, attr):
            setattr(mod, attr, None)


def create_app(
    *,
    dependency_overrides: dict[Callable[..., Any], Callable[..., Any]] | None = None,
) -> FastAPI:
    """Build a fresh, isolated FastAPI app for testing.

    Each call resets the service-singleton graph and constructs a new FastAPI
    instance via `main.lifespan`, so two tests running in parallel see
    independent state.

    Args:
        dependency_overrides: optional `dep_fn -> stub_fn` mapping applied to
            the new app's `dependency_overrides` dict.

    Returns:
        A new FastAPI instance with middleware + routers mounted.

    Note:
        `main._configure_app` is introduced in plan 27-01. Until then, this
        call will raise `ImportError`. Tests that exercise `create_app()`
        should gate via `pytest.importorskip` or a `getattr` skip check.
    """
    _reset_singletons()
    # Lazy import — main imports settings + many singletons at module load.
    from main import _configure_app, lifespan  # type: ignore[attr-defined]

    app = FastAPI(lifespan=lifespan)
    _configure_app(app)  # mounts middleware + routers
    if dependency_overrides:
        app.dependency_overrides.update(dependency_overrides)
    return app
