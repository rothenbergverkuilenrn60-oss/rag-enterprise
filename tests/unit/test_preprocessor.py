# =============================================================================
# tests/unit/test_preprocessor.py
# 单元测试 — STAGE 1 预处理
# =============================================================================
import pytest
from services.preprocessor.cleaner import (
    compute_checksum,
    detect_language,
    quality_check,
    is_duplicate,
    register_checksum,
    _seen_checksums,
)


class TestChecksum:

    def test_same_text_same_checksum(self) -> None:
        t = "企业级RAG测试文本"
        assert compute_checksum(t) == compute_checksum(t)

    def test_different_text_different_checksum(self) -> None:
        assert compute_checksum("文本A") != compute_checksum("文本B")

    def test_checksum_is_hex_string(self) -> None:
        result = compute_checksum("test")
        assert all(c in "0123456789abcdef" for c in result)
        assert len(result) == 64  # SHA-256 hex


class TestDeduplication:

    def setup_method(self) -> None:
        _seen_checksums.clear()

    def test_first_occurrence_not_duplicate(self) -> None:
        cs = compute_checksum("唯一内容_" + str(id(self)))
        assert not is_duplicate(cs)

    def test_second_occurrence_is_duplicate(self) -> None:
        cs = compute_checksum("重复内容_" + str(id(self)))
        register_checksum(cs)
        assert is_duplicate(cs)


class TestLanguageDetection:

    def test_chinese_text_detected(self) -> None:
        lang = detect_language("这是一段中文文本，用于测试语言检测功能。")
        assert lang in ("zh", "zh-cn", "zh-tw")

    def test_english_text_detected(self) -> None:
        lang = detect_language(
            "This is an English text used for testing language detection functionality."
        )
        assert lang == "en"

    def test_empty_returns_unknown_or_lang(self) -> None:
        lang = detect_language("")
        assert isinstance(lang, str)


class TestQualityCheck:

    def test_normal_text_passes(self) -> None:
        text = "这是一段正常的企业文档内容，包含足够多的字符用于质量检查。" * 3
        warnings = quality_check(text)
        assert not any("too short" in w for w in warnings)

    def test_short_text_warning(self) -> None:
        warnings = quality_check("短")
        assert any("too short" in w for w in warnings)

    def test_returns_list(self) -> None:
        result = quality_check("任意文本内容")
        assert isinstance(result, list)
