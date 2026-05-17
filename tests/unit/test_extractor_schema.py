"""Phase 23 / MEM-03 — ExtractedFact Pydantic V2 schema gates.

Schema-level adversarial defense (T-23-03-A2): out-of-whitelist categories,
out-of-bucket importance, fact-length, and frozen-immutability are enforced by
Pydantic Literal types + cross-field model_validator — independent of LLM
behavior.

RED gate per Plan 23-03 Task 1 (turns GREEN once ExtractedFact is appended
to utils/models.py).
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest
from pydantic import ValidationError

from utils.models import ExtractedFact

# -----------------------------------------------------------------------------
# Test 1 — frozen immutability
# -----------------------------------------------------------------------------


def test_extracted_fact_frozen() -> None:
    """ExtractedFact.model_config['frozen'] is True; mutation raises."""
    f = ExtractedFact(
        fact="user prefers React",
        category="stable_preferences",
        importance=0.8,
    )
    assert f.model_config["frozen"] is True
    with pytest.raises((ValidationError, AttributeError, TypeError)):
        f.fact = "x"   # type: ignore[misc]   # frozen Pydantic V2 model


# -----------------------------------------------------------------------------
# Test 2 — cross-field category↔importance pairing
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cat,imp,valid",
    [
        ("stable_preferences", 0.8, True),
        ("recurring_topics",   0.5, True),
        ("transient_context",  0.2, True),
        ("stable_preferences", 0.5, False),
        ("recurring_topics",   0.8, False),
        ("transient_context",  0.5, False),
        ("stable_preferences", 0.2, False),
    ],
)
def test_category_importance_bucket_pairing(cat: str, imp: float, valid: bool) -> None:
    """The 1:1 mapping {stable_preferences→0.8, recurring_topics→0.5,
    transient_context→0.2} is enforced by @model_validator(mode='after').
    """
    if valid:
        f = ExtractedFact(fact="x", category=cat, importance=imp)   # type: ignore[arg-type]
        assert f.category == cat
        assert f.importance == imp
    else:
        with pytest.raises(ValidationError):
            ExtractedFact(fact="x", category=cat, importance=imp)   # type: ignore[arg-type]


# -----------------------------------------------------------------------------
# Test 3 — fact-length validator
# -----------------------------------------------------------------------------


def test_fact_length_validator() -> None:
    """Empty / whitespace-only / >200 chars rejected; valid bounds accepted;
    leading/trailing whitespace stripped.
    """
    # Empty fact rejected.
    with pytest.raises(ValidationError):
        ExtractedFact(fact="", category="stable_preferences", importance=0.8)

    # Whitespace-only fact rejected.
    with pytest.raises(ValidationError):
        ExtractedFact(fact="   ", category="stable_preferences", importance=0.8)

    # 201-char fact rejected.
    with pytest.raises(ValidationError):
        ExtractedFact(
            fact="x" * 201,
            category="stable_preferences",
            importance=0.8,
        )

    # 200-char fact accepted.
    f = ExtractedFact(
        fact="x" * 200,
        category="stable_preferences",
        importance=0.8,
    )
    assert len(f.fact) == 200

    # Leading/trailing whitespace stripped.
    f_stripped = ExtractedFact(
        fact="  hello  ",
        category="stable_preferences",
        importance=0.8,
    )
    assert f_stripped.fact == "hello"


# -----------------------------------------------------------------------------
# Test 4 — Literal rejection (out-of-whitelist category, out-of-bucket importance)
# -----------------------------------------------------------------------------


def test_literal_rejection() -> None:
    """Out-of-whitelist category and out-of-bucket importance both raise
    ValidationError (Literal type guard — first defense layer for T-23-03-A1).
    """
    # Out-of-whitelist category.
    with pytest.raises(ValidationError):
        ExtractedFact(
            fact="x",
            category="admin_policy",   # type: ignore[arg-type]
            importance=0.8,
        )

    # Out-of-bucket importance.
    with pytest.raises(ValidationError):
        ExtractedFact(
            fact="x",
            category="stable_preferences",
            importance=0.9,   # type: ignore[arg-type]
        )
