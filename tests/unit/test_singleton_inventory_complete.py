"""D-03 lint test — `_SINGLETON_INVENTORY` must cover every module-level
`_X = None` cache under `services/`.

Plan 27-01 Task 2 — Implements RESEARCH §Theme 1 lines 457-498.

Fails CI deterministically when a new singleton lands under `services/` without an
entry in `tests/factories/app.py::_SINGLETON_INVENTORY`. The fix is always to
add the new entry to the inventory (NOT to add it to `_SKIP` — `_SKIP` is
reserved for the 4 known non-service primitives enumerated in RESEARCH §1
entries 24/26/27/38).
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")

import re
from pathlib import Path

SERVICES_DIR = Path("services")

# Non-service module-level `_X = None` patterns under services/. These are
# cached primitives, not service instances — resetting them across tests would
# either be incorrect (tokenizer cache) or pointless (lazy class/handle refs).
# Sourced from RESEARCH §1 entries 24/26/27/38.
_SKIP: set[tuple[str, str]] = {
    ("services/generator/generator.py",  "_tiktoken_enc"),
    ("services/generator/llm_client.py", "_anthropic_rate_limit_cls"),
    ("services/generator/llm_client.py", "_anthropic_overload_cls"),
    ("services/extractor/ocr_engine.py", "_sem"),
}


def test_singleton_inventory_covers_all_module_globals() -> None:
    """Every `^_X(...)? = None` line under services/ must be in `_SINGLETON_INVENTORY`
    or explicitly in `_SKIP` with a documented reason.
    """
    from tests.factories.app import _SINGLETON_INVENTORY

    inventory: set[tuple[str, str]] = {
        (mod.replace(".", "/") + ".py", attr) for mod, attr in _SINGLETON_INVENTORY
    }

    missing: list[tuple[str, str]] = []
    name_re = re.compile(r"^(_[a-zA-Z_]\w*)\s*[:=]")

    for py in SERVICES_DIR.rglob("*.py"):
        rel = str(py).replace("\\", "/")
        text = py.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.lstrip()
            # Indented lines are inside functions/classes — not module-level.
            if stripped != line:
                continue
            m = name_re.match(stripped)
            if not m:
                continue
            if "= None" not in line:
                continue
            attr = m.group(1)
            if (rel, attr) in _SKIP:
                continue
            if (rel, attr) not in inventory:
                missing.append((rel, attr))

    assert not missing, (
        "Module-level singletons in services/ not covered by "
        "_SINGLETON_INVENTORY: "
        f"{missing}. "
        "Fix: add each (module_path, attr) to "
        "`tests/factories/app.py::_SINGLETON_INVENTORY`. "
        "Do NOT add to `_SKIP` unless the attr is a non-service primitive "
        "(see _SKIP comment for the 4 documented exceptions)."
    )
