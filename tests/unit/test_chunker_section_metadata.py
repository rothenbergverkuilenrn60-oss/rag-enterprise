"""
tests/unit/test_chunker_section_metadata.py

RED-state Wave 0 scaffold for META-01 (Phase 8 SC #1, #4, #5).
These tests fail today; 08-03-PLAN.md (chunker) makes them green.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")


class TestSectionWalker:
    """META-01 SC#1: GB heading → section_id + section_title."""

    def test_gb_heading_regex_matches_decimal_section(self):
        from services.doc_processor.chunker import _GB_HEADING_RE
        m = _GB_HEADING_RE.search("3.10 定义的透光面")
        assert m is not None
        assert m.group(1) == "3.10"
        assert m.group(2).startswith("定义的透光面")

    def test_strip_ocr_markers_with_pages(self):
        from services.doc_processor.chunker import _strip_ocr_markers_with_pages
        body = "[第63页·OCR]\n3.10 定义的透光面\n本节定义了…\n[第64页·OCR]\n更多内容"
        clean, page_map = _strip_ocr_markers_with_pages(body)
        assert "[第63页·OCR]" not in clean
        assert "[第64页·OCR]" not in clean
        assert "3.10 定义的透光面" in clean
        # at least one offset → page_number entry
        assert 63 in page_map.values()
        assert 64 in page_map.values()

    def test_build_gb_section_map_returns_offset_id_title(self):
        from services.doc_processor.chunker import _build_gb_section_map
        clean = "前言文本\n3.10 定义的透光面\n本节定义了…\n3.11 其他术语\n更多内容"
        ranges = _build_gb_section_map(clean)
        assert any(sid == "3.10" and "定义" in title for (_off, sid, title) in ranges)
        assert any(sid == "3.11" for (_off, sid, _t) in ranges)


class TestSectionMetadataFields:
    """META-01 SC#1: section_id + section_title in ChunkMetadata, NOT in embedded text."""

    def test_section_metadata_fields_default_empty(self):
        from utils.models import ChunkMetadata
        m = ChunkMetadata()
        assert m.section_id == ""
        assert m.section_title == ""

    def test_legacy_chunk_backward_compat(self):
        # REQ A-3 acceptance #4 — chunks ingested before v1.1 (no section_* keys)
        # round-trip through model_validate without ValidationError.
        from utils.models import ChunkMetadata
        legacy = {"source": "x", "doc_id": "d", "title": "t"}
        m = ChunkMetadata.model_validate(legacy)
        assert m.section_id == ""
        assert m.section_title == ""

    def test_no_page_in_embedded_text_sample(self):
        """D-02 contract: content_with_header MUST NOT contain '第N页' or '[第N页·OCR]'."""
        # The actual chunker emits this; this test only encodes the invariant string-side.
        # Real chunker output is verified by test_section_walker_gb_heading.
        sample_cwh = "3.10 定义的透光面\n\n本节定义了…"
        assert "第" not in sample_cwh.split("\n\n", 1)[0]  # heading line: no 第
        assert "页" not in sample_cwh.split("\n\n", 1)[0]  # heading line: no 页
        assert "[第" not in sample_cwh                      # no OCR marker anywhere


class TestSectionWalkerEndToEnd:
    """META-01 SC#1: full chunker pipeline — content_with_header == '{sid} {title}\\n\\n{body}'."""

    def test_chunker_emits_d02_form_for_gb_text(self):
        from services.doc_processor.chunker import (
            _build_gb_section_map,
            _strip_ocr_markers_with_pages,
            structure_aware_split,
            structure_nodes_to_chunks,
        )
        from utils.models import DocType, ExtractedContent
        body = (
            "[第63页·OCR]\n"
            "3.10 定义的透光面\n"
            "本节定义了灯具的发光面，要求满足以下条件：\n"
            "条件一……\n"
            "条件二……\n"
        )
        content = ExtractedContent(
            raw_id="test-gb-1",
            title="GB4785-2019",
            author="",
            body_text=body,
            doc_type=DocType.PDF,
            language="zh",
            metadata={"source": "test.pdf"},
            extraction_errors=[],
        )
        # 08-03 wires the pre-pass so structure_aware_split sees clean text and
        # structure_nodes_to_chunks receives the section + page maps.
        clean_body, page_offset_map = _strip_ocr_markers_with_pages(body)
        section_map = _build_gb_section_map(clean_body)
        nodes = structure_aware_split(clean_body)
        chunks = structure_nodes_to_chunks(
            nodes,
            "doc-1",
            content,
            section_map=section_map,
            page_offset_map=page_offset_map,
            full_clean_text=clean_body,
        )
        assert chunks, "expected at least one chunk from GB body_text"
        target = next(c for c in chunks if "灯具的发光面" in c.content)
        assert target.metadata.section_id == "3.10"
        assert target.metadata.section_title.startswith("定义的透光面")
        # D-02: content_with_header begins with "3.10 定义的透光面\n\n"
        assert target.content_with_header.startswith("3.10 定义的透光面\n\n")
        # Page/OCR markers MUST NOT be in embedded text
        assert "[第63页·OCR]" not in target.content_with_header
        assert "第63页" not in target.content_with_header
        # Page number derived from the OCR marker preceding this content.
        assert target.metadata.page_number == 63


class TestImageChunkSectionMetadata:
    """SC#4: image-caption chunks carry section_id/title from host page; D-04 content_with_header form."""

    @staticmethod
    def _build_fixture():
        """Shared GB fixture: one image on page 63 sitting under section 3.10."""
        import asyncio

        from services.doc_processor.chunker import (
            DocProcessorService,
            _build_gb_section_map,
            _strip_ocr_markers_with_pages,
        )
        from utils.models import DocType, ExtractedContent, ExtractedImage

        body = (
            "[第63页·OCR]\n"
            "3.10 定义的透光面\n"
            "本节定义了灯具的发光面。\n"
        )
        clean, page_offset_map = _strip_ocr_markers_with_pages(body)
        section_map = _build_gb_section_map(clean)

        content = ExtractedContent(
            raw_id="test-img-1",
            title="GB4785-2019",
            body_text=body,
            doc_type=DocType.PDF,
            language="zh",
            metadata={"source": "test.pdf"},
            images=[ExtractedImage(raw_bytes=b"\x89PNG\r\n", page_number=63)],
        )

        captured: dict[str, object] = {}

        class _FakeLLM:
            async def chat_with_vision(self, *, image_b64, query, media_type, system):
                captured["query"] = query
                captured["system"] = system
                return "示意图：透光面区域。"

        svc = DocProcessorService()
        chunks = asyncio.run(svc._chunk_images(
            images=content.images,
            content=content,
            doc_id="doc-1",
            llm_client=_FakeLLM(),
            start_index=0,
            section_map=section_map,
            page_offset_map=page_offset_map,
        ))
        return chunks, captured

    def test_image_chunk_carries_section_fields(self) -> None:
        chunks, captured = self._build_fixture()
        assert len(chunks) == 1
        meta = chunks[0].metadata
        assert meta.chunk_type == "image"
        assert meta.page_number == 63
        assert meta.section_id == "3.10"
        assert meta.section_title.startswith("定义的透光面")
        # D-04 part 1: vision prompt prefix carries page + section context.
        assert "图片位于第63页" in captured["query"]
        assert "3.10" in captured["query"]
        assert "定义的透光面" in captured["query"]

    def test_image_chunk_content_with_header_d04_form(self) -> None:
        chunks, _captured = self._build_fixture()
        assert len(chunks) == 1
        cwh = chunks[0].content_with_header
        # D-04 = D-02 shape: "{sid} {title}\n\n{caption}"
        assert cwh.startswith("3.10 定义的透光面\n\n")
        assert cwh.endswith("示意图：透光面区域。")
        assert "[第63页·OCR]" not in cwh
