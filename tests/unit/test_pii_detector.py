# =============================================================================
# tests/unit/test_pii_detector.py
# TDD RED — PII detector entity-type mapping and US entity names
# =============================================================================
from __future__ import annotations

import os
import pytest

# Ensure settings can load without real model dir
os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")


class TestPIIDetectorUSEntityNames:
    """PIIDetector must emit Presidio-compatible US entity type names."""

    def test_ssn_dashed_returns_us_ssn_type(self) -> None:
        """detect() on text with dashed SSN returns finding with pii_type 'US_SSN'."""
        from services.preprocessor.pii_detector import get_pii_detector
        detector = get_pii_detector()
        result = detector.detect("My SSN is 123-45-6789 please keep it safe.")
        pii_types = result.pii_types
        assert "US_SSN" in pii_types, (
            f"Expected 'US_SSN' in pii_types but got: {pii_types}"
        )

    def test_credit_card_luhn_returns_credit_card_type(self) -> None:
        """detect() on text with valid Luhn credit card returns 'CREDIT_CARD' type."""
        from services.preprocessor.pii_detector import get_pii_detector
        detector = get_pii_detector()
        # 4111111111111111 is a well-known Luhn-valid Visa test number
        result = detector.detect("Pay with card 4111111111111111 for this order.")
        pii_types = result.pii_types
        assert "CREDIT_CARD" in pii_types, (
            f"Expected 'CREDIT_CARD' in pii_types but got: {pii_types}"
        )

    def test_bank_card_alias_maps_to_us_bank_number(self) -> None:
        """bank_card findings expand to include 'US_BANK_NUMBER' alias."""
        from services.preprocessor.pii_detector import get_pii_detector
        detector = get_pii_detector()
        # 4111111111111111 is Luhn-valid and starts with 4 (in _BANK_CARD pattern range)
        result = detector.detect("Account number: 4111111111111111")
        pii_types = result.pii_types
        assert "US_BANK_NUMBER" in pii_types, (
            f"Expected 'US_BANK_NUMBER' alias in pii_types but got: {pii_types}"
        )

    def test_ssn_masked_text_replaces_original(self) -> None:
        """SSN in detected text is masked in masked_text output."""
        from services.preprocessor.pii_detector import get_pii_detector
        detector = get_pii_detector()
        result = detector.detect("SSN: 123-45-6789")
        assert "123-45-6789" not in result.masked_text, (
            "Original SSN should be masked in masked_text"
        )

    def test_no_false_positive_on_normal_text(self) -> None:
        """Clean text returns has_pii=False."""
        from services.preprocessor.pii_detector import get_pii_detector
        detector = get_pii_detector()
        result = detector.detect("The quarterly report shows revenue of $1.2M.")
        assert result.has_pii is False, (
            f"Expected no PII in clean text but found: {result.pii_types}"
        )


class TestSettingsPIIDefaults:
    """Settings must have pii_block_on_detect=True and pii_block_entities with 5 types."""

    def test_pii_block_on_detect_defaults_to_true(self) -> None:
        """pii_block_on_detect must default to True (fail-safe default)."""
        from config.settings import Settings
        s = Settings()
        assert s.pii_block_on_detect is True, (
            f"pii_block_on_detect should default to True, got {s.pii_block_on_detect}"
        )

    def test_pii_block_entities_field_exists(self) -> None:
        """Settings must have pii_block_entities field."""
        from config.settings import Settings
        s = Settings()
        assert hasattr(s, "pii_block_entities"), (
            "Settings is missing pii_block_entities field"
        )

    def test_pii_block_entities_contains_required_types(self) -> None:
        """pii_block_entities must contain all 5 required Presidio entity names."""
        from config.settings import Settings
        s = Settings()
        required = {"US_SSN", "CREDIT_CARD", "US_BANK_NUMBER", "US_DRIVER_LICENSE", "US_PASSPORT"}
        actual = set(s.pii_block_entities)
        missing = required - actual
        assert not missing, (
            f"pii_block_entities missing required types: {missing}. Got: {actual}"
        )

    def test_pii_block_entities_has_exactly_five_entries(self) -> None:
        """pii_block_entities must contain exactly 5 entries."""
        from config.settings import Settings
        s = Settings()
        assert len(s.pii_block_entities) == 5, (
            f"pii_block_entities should have 5 entries, got {len(s.pii_block_entities)}: {s.pii_block_entities}"
        )
