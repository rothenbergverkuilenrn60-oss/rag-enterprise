# =============================================================================
# tests/unit/test_chunker.py
# 分块模块单元测试 — 覆盖全部七种策略
# 运行：conda run -n torch_env pytest tests/unit/test_chunker.py -v
# =============================================================================
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.doc_processor.chunker import (
    RecursiveTextSplitter,
    count_tokens,
    inject_metadata_header,
    structure_aware_split,
    structure_nodes_to_chunks,
    parent_child_split,
    sentence_window_split,
    semantic_split,
    contextual_enrichment,
    DocProcessorService,
)
from utils.models import (
    ChunkMetadata, DocType, ExtractedContent, StructureNode, DocumentChunk,
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Fixtures
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@pytest.fixture
def long_zh_text() -> str:
    """超过单块大小的中文文本。"""
    base = "这是一段测试文本，包含完整的语义内容，用于验证分块逻辑是否正确工作。"
    return base * 30   # ~1500 字符


@pytest.fixture
def policy_text() -> str:
    """模拟企业制度文档（含章节/条款/列表结构）。"""
    return """第一章 总则

第一条 为规范公司人事管理，特制定本制度。

第二条 本制度适用于公司全体员工，包括试用期员工。

第二章 考勤管理

第三条 工作时间
公司实行标准工时制，每天工作8小时，每周工作40小时。

第四条 年假规定
员工工作满1年享有5天带薪年假。
员工工作满3年享有10天带薪年假。
员工工作满10年享有15天带薪年假。

第五条 请假流程
①员工提前1天在系统中申请
②直属主管审批
③人事行政部备案

第三章 薪酬管理

第六条 薪资构成
薪资由基本工资、绩效工资、津贴三部分组成。

第七条 发薪日
每月15日为发薪日，如遇节假日则提前至最近工作日发放。"""


@pytest.fixture
def sample_content(policy_text: str) -> ExtractedContent:
    return ExtractedContent(
        raw_id="test-001",
        title="员工手册",
        author="人事部",
        doc_type=DocType.PDF,
        body_text=policy_text,
        language="zh",
        tables=[
            {"rows": [["假期类型", "天数", "条件"], ["年假", "5天", "满1年"], ["年假", "10天", "满3年"]]},
        ],
    )


@pytest.fixture
def sample_metadata() -> ChunkMetadata:
    return ChunkMetadata(
        source="/mnt/f/docs/policy.pdf",
        doc_id="doc-001",
        title="员工手册",
        section="第二章 考勤管理",
        sub_section="第四条 年假规定",
        chunk_index=0,
        total_chunks=10,
        doc_type=DocType.PDF,
    )


@pytest.fixture
def mock_llm():
    """返回固定上下文说明的 mock LLM。"""
    llm = MagicMock()
    llm.chat = AsyncMock(return_value="本片段属于考勤管理章节，描述了员工年假的具体天数标准。")
    return llm


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Strategy 1: RecursiveTextSplitter
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestRecursiveTextSplitter:

    def test_basic_split_produces_chunks(self, long_zh_text: str) -> None:
        splitter = RecursiveTextSplitter(chunk_size=200, chunk_overlap=20)
        chunks = splitter.split(long_zh_text)
        assert len(chunks) > 1

    def test_chunk_size_respected(self, long_zh_text: str) -> None:
        splitter = RecursiveTextSplitter(chunk_size=200, chunk_overlap=20)
        chunks = splitter.split(long_zh_text)
        oversized = [c for c in chunks if len(c) > 250]
        assert len(oversized) == 0, f"Chunks exceed size limit: {[len(c) for c in oversized]}"

    def test_short_text_returns_single_chunk(self) -> None:
        # 短文本不满足全局 chunk_min_size，需要使用足够长的文本
        # 或者用 chunk_min_size=1 的 splitter 测试此行为
        text = "这是一段测试文字，需要足够的字符数量才能通过最小 chunk 尺寸过滤器（默认100字符），因此这里补充了更多内容，确保长度超过阈值，整段文本应当被正确识别为单一完整的文本块，不应该被分割成多个部分。"
        splitter = RecursiveTextSplitter(chunk_size=512)
        chunks = splitter.split(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_empty_text_returns_empty(self) -> None:
        assert RecursiveTextSplitter().split("") == []
        assert RecursiveTextSplitter().split("   ") == []

    def test_overlap_carries_context(self) -> None:
        text = "第一部分内容。" * 50 + "第二部分内容。" * 50
        splitter = RecursiveTextSplitter(chunk_size=100, chunk_overlap=30)
        chunks = splitter.split(text)
        assert len(chunks) >= 2

    def test_english_text_split(self) -> None:
        text = "This is a test sentence. " * 50
        splitter = RecursiveTextSplitter(chunk_size=200, language="en")
        chunks = splitter.split(text)
        assert len(chunks) > 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Strategy 2: sentence_window_split
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestSentenceWindowSplit:

    def test_produces_overlapping_chunks(self) -> None:
        text = "第一句话。第二句话。第三句话。第四句话。第五句话。"
        chunks = sentence_window_split(text, window=1)
        assert len(chunks) > 0

    def test_no_duplicates(self) -> None:
        text = "苹果很甜。香蕉很长。橙子很酸。葡萄很圆。"
        chunks = sentence_window_split(text, window=1)
        assert len(chunks) == len(set(chunks))

    def test_window_size_zero(self) -> None:
        text = "句子一。句子二。句子三。"
        chunks = sentence_window_split(text, window=0)
        assert len(chunks) >= 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Strategy 3: inject_metadata_header（静态头）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestInjectMetadataHeader:

    def test_header_injected(self, sample_metadata: ChunkMetadata) -> None:
        result = inject_metadata_header("正文内容", sample_metadata)
        assert "员工手册" in result
        assert "正文内容" in result

    def test_header_contains_section(self, sample_metadata: ChunkMetadata) -> None:
        result = inject_metadata_header("内容", sample_metadata)
        assert "考勤管理" in result

    def test_header_contains_sub_section(self, sample_metadata: ChunkMetadata) -> None:
        result = inject_metadata_header("内容", sample_metadata)
        assert "年假规定" in result

    def test_no_crash_on_empty_metadata(self) -> None:
        meta = ChunkMetadata(doc_id="x")
        result = inject_metadata_header("内容", meta)
        assert "内容" in result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Strategy 4: structure_aware_split ★ 新增
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestStructureAwareSplit:

    def test_detects_chapters(self, policy_text: str) -> None:
        nodes = structure_aware_split(policy_text)
        chapter_nodes = [n for n in nodes if n.node_type == "chapter"]
        assert len(chapter_nodes) >= 3, f"Expected ≥3 chapters, got {len(chapter_nodes)}"

    def test_detects_articles(self, policy_text: str) -> None:
        nodes = structure_aware_split(policy_text)
        article_nodes = [n for n in nodes if n.node_type == "article"]
        assert len(article_nodes) >= 5, f"Expected ≥5 articles, got {len(article_nodes)}"

    def test_detects_list_items(self, policy_text: str) -> None:
        nodes = structure_aware_split(policy_text)
        list_nodes = [n for n in nodes if n.node_type == "list_item"]
        assert len(list_nodes) >= 1

    def test_parent_heading_populated(self, policy_text: str) -> None:
        nodes = structure_aware_split(policy_text)
        article_nodes = [n for n in nodes if n.node_type == "article"]
        # 条款节点应该有父章节标题
        with_parent = [n for n in article_nodes if n.parent_heading]
        assert len(with_parent) > 0

    def test_fallback_on_unstructured_text(self) -> None:
        plain = "这是一段普通文本，没有任何章节标记，" * 20
        nodes = structure_aware_split(plain)
        assert len(nodes) > 0
        # 降级为 paragraph
        assert all(n.node_type == "paragraph" for n in nodes)

    def test_nodes_to_chunks_enriched_text(
        self, policy_text: str, sample_content: ExtractedContent
    ) -> None:
        nodes = structure_aware_split(policy_text)
        chunks = structure_nodes_to_chunks(nodes, "doc-001", sample_content)
        assert len(chunks) > 0
        # content_with_header 应包含层级上下文
        for c in chunks:
            assert c.content_with_header != c.content or not c.metadata.section
            assert c.content  # content 非空

    def test_metadata_section_populated(
        self, policy_text: str, sample_content: ExtractedContent
    ) -> None:
        nodes = structure_aware_split(policy_text)
        chunks = structure_nodes_to_chunks(nodes, "doc-001", sample_content)
        # 至少部分块应有 section 元数据
        with_section = [c for c in chunks if c.metadata.section]
        assert len(with_section) > 0

    def test_table_processing_produces_row_chunks(
        self, sample_content: ExtractedContent
    ) -> None:
        svc = DocProcessorService()
        table_chunks = svc._process_tables(sample_content, "doc-001", start_idx=100)
        assert len(table_chunks) == 2   # 3行表格去掉表头剩2行
        for c in table_chunks:
            assert "表格行" in c.content
            assert c.metadata.node_type == "table_row"

    def test_table_chunk_contains_header(self, sample_content: ExtractedContent) -> None:
        svc = DocProcessorService()
        table_chunks = svc._process_tables(sample_content, "doc-001", start_idx=0)
        # 每个数据行应该包含表头
        for c in table_chunks:
            assert "假期类型" in c.content   # 表头内容

    @pytest.mark.asyncio
    async def test_process_structure_strategy(self, sample_content: ExtractedContent) -> None:
        svc = DocProcessorService.__new__(DocProcessorService)
        svc._primary = 'structure'
        svc._use_contextual = False
        svc._use_parent_child = False
        svc._use_proposition = False
        chunks = await svc.process(sample_content, "doc-001")
        assert len(chunks) > 0
        assert all(isinstance(c, DocumentChunk) for c in chunks)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Strategy 5: parent_child_split ★ 新增
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestParentChildSplit:

    def test_returns_two_lists(self, policy_text: str, sample_content: ExtractedContent) -> None:
        child_chunks, parent_chunks = parent_child_split(policy_text, sample_content, "doc-001")
        assert isinstance(child_chunks, list)
        assert isinstance(parent_chunks, list)
        assert len(child_chunks) > 0
        assert len(parent_chunks) > 0

    def test_child_smaller_than_parent(
        self, sample_content: ExtractedContent
    ) -> None:
        # 生成足够长的文本，使子块（chunk_size=512）小于父块（parent_chunk_size=2048）
        long_text = ("第一章 总则\n第一条 本制度适用于全体员工。\n" * 30 +
                     "第二章 考勤管理\n第二条 工作时间为标准工时制每天八小时。\n" * 30)
        child_chunks, parent_chunks = parent_child_split(long_text, sample_content, "doc-001")
        assert len(child_chunks) > 0 and len(parent_chunks) > 0
        avg_child = sum(c.token_count for c in child_chunks) / len(child_chunks)
        avg_parent = sum(p.token_count for p in parent_chunks) / len(parent_chunks)
        assert avg_child < avg_parent, f"avg_child={avg_child:.0f} should < avg_parent={avg_parent:.0f}"

    def test_parent_chunk_id_populated(
        self, policy_text: str, sample_content: ExtractedContent
    ) -> None:
        child_chunks, parent_chunks = parent_child_split(policy_text, sample_content, "doc-001")
        parent_ids = {p.chunk_id for p in parent_chunks}
        # 所有子块都应引用一个真实存在的父块 ID
        for c in child_chunks:
            assert c.metadata.parent_chunk_id in parent_ids, (
                f"child {c.chunk_id} references non-existent parent {c.metadata.parent_chunk_id}"
            )

    def test_chunk_levels_correct(
        self, policy_text: str, sample_content: ExtractedContent
    ) -> None:
        child_chunks, parent_chunks = parent_child_split(policy_text, sample_content, "doc-001")
        assert all(c.metadata.chunk_level == "child" for c in child_chunks)
        assert all(p.metadata.chunk_level == "parent" for p in parent_chunks)

    def test_parent_content_attached_to_child(
        self, policy_text: str, sample_content: ExtractedContent
    ) -> None:
        child_chunks, _ = parent_child_split(policy_text, sample_content, "doc-001")
        # 子块应携带 parent_content 字段
        with_parent_content = [c for c in child_chunks if c.parent_content]
        assert len(with_parent_content) > 0

    def test_child_total_chunks_backfilled(
        self, policy_text: str, sample_content: ExtractedContent
    ) -> None:
        child_chunks, _ = parent_child_split(policy_text, sample_content, "doc-001")
        expected = len(child_chunks)
        for c in child_chunks:
            assert c.metadata.total_chunks == expected

    @pytest.mark.asyncio
    async def test_process_parent_child_strategy(
        self, sample_content: ExtractedContent
    ) -> None:
        svc = DocProcessorService.__new__(DocProcessorService)
        svc._primary = 'recursive'
        svc._use_contextual = False
        svc._use_parent_child = True
        svc._use_proposition = False
        chunks = await svc.process(sample_content, "doc-001")
        assert len(chunks) > 0
        child_chunks = [c for c in chunks if c.metadata.chunk_level == "child"]
        parent_chunks = [c for c in chunks if c.metadata.chunk_level == "parent"]
        assert len(child_chunks) > 0
        assert len(parent_chunks) > 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Strategy 6: proposition_split ★ 新增
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestPropositionSplit:

    @pytest.mark.asyncio
    async def test_splits_into_multiple_propositions(
        self, sample_content: ExtractedContent, mock_llm: MagicMock
    ) -> None:
        from services.doc_processor.chunker import proposition_split
        mock_llm.chat = AsyncMock(return_value=(
            "员工试用期为1至3个月\n"
            "用人部门须提前7天通知人事行政部试用期考核结果\n"
            "普通员工转正须经直属主管审批"
        ))
        chunk_text = "员工试用期为1-3个月，用人部门需提前7天告知人事，转正须主管审批。"
        props = await proposition_split(chunk_text, sample_content, "试用与转正", mock_llm)
        assert len(props) == 3
        assert all(len(p) >= 8 for p in props)

    @pytest.mark.asyncio
    async def test_falls_back_on_llm_failure(
        self, sample_content: ExtractedContent
    ) -> None:
        from services.doc_processor.chunker import proposition_split
        failing_llm = MagicMock()
        failing_llm.chat = AsyncMock(side_effect=RuntimeError("LLM timeout"))
        chunk_text = "原始文本内容。"
        props = await proposition_split(chunk_text, sample_content, "", failing_llm, max_retries=0)
        assert props == [chunk_text]

    @pytest.mark.asyncio
    async def test_filters_empty_lines(
        self, sample_content: ExtractedContent, mock_llm: MagicMock
    ) -> None:
        from services.doc_processor.chunker import proposition_split
        mock_llm.chat = AsyncMock(return_value="\n\n员工试用期为一至三个月\n\n\n绩效工资按月核算发放\n\n")
        props = await proposition_split("文本内容在此", sample_content, "", mock_llm)
        assert "" not in props
        assert len(props) == 2

    @pytest.mark.asyncio
    async def test_process_proposition_strategy(
        self, sample_content: ExtractedContent, mock_llm: MagicMock
    ) -> None:
        mock_llm.chat = AsyncMock(return_value="员工试用期为一至三个月\n绩效工资按月核算发放\n年假天数依工龄递增")
        svc = DocProcessorService.__new__(DocProcessorService)
        svc._primary = 'structure'
        svc._use_contextual = False
        svc._use_parent_child = False
        svc._use_proposition = True
        chunks = await svc.process(sample_content, "doc-001", llm_client=mock_llm)
        assert len(chunks) > 0
        # 只有 article 类节点会被命题化，其余节点保持 chunk_level="child"
        prop_chunks = [c for c in chunks if c.metadata.chunk_level == "proposition"]
        assert len(prop_chunks) > 0, "应有至少一个命题化块"

    @pytest.mark.asyncio
    async def test_proposition_fallback_without_llm(
        self, sample_content: ExtractedContent
    ) -> None:
        """命题化策略在没有 llm_client 时应降级（use_proposition=True 但无 LLM 则跳过命题化）。"""
        svc = DocProcessorService.__new__(DocProcessorService)
        svc._primary = 'recursive'
        svc._use_contextual = False
        svc._use_parent_child = False
        svc._use_proposition = True
        chunks = await svc.process(sample_content, "doc-001", llm_client=None)
        assert len(chunks) > 0   # 降级后仍有输出


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Contextual Enrichment
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestContextualEnrichment:

    @pytest.mark.asyncio
    async def test_prepends_context(
        self, sample_metadata: ChunkMetadata, mock_llm: MagicMock
    ) -> None:
        chunk_text = "员工年假5天。"
        result = await contextual_enrichment(chunk_text, "全文内容", sample_metadata, mock_llm)
        assert chunk_text in result
        assert "考勤管理章节" in result   # mock 返回的上下文说明

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self, sample_metadata: ChunkMetadata) -> None:
        failing_llm = MagicMock()
        failing_llm.chat = AsyncMock(side_effect=RuntimeError("connection error"))
        chunk_text = "年假内容。"
        result = await contextual_enrichment(chunk_text, "全文", sample_metadata, failing_llm)
        # 降级到静态头，原始内容仍在
        assert chunk_text in result

    @pytest.mark.asyncio
    async def test_long_doc_truncated(
        self, sample_metadata: ChunkMetadata, mock_llm: MagicMock
    ) -> None:
        long_doc = "测试文档内容。" * 2000   # 远超 _MAX_FULL_TEXT_CHARS
        chunk_text = "目标片段。"
        result = await contextual_enrichment(chunk_text, long_doc, sample_metadata, mock_llm)
        assert chunk_text in result
        # LLM 应只被调用一次（截断后调用）
        assert mock_llm.chat.call_count == 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# count_tokens
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestCountTokens:

    def test_positive_count(self) -> None:
        assert count_tokens("hello world") > 0

    def test_empty_string(self) -> None:
        assert count_tokens("") == 0

    def test_chinese_text_reasonable_count(self) -> None:
        text = "这是一段中文测试文本，共有二十个汉字左右。"
        count = count_tokens(text)
        assert 8 <= count <= 40   # 合理范围

    def test_chinese_fewer_tokens_than_chars(self) -> None:
        text = "中文字符" * 100   # 400 字符
        assert count_tokens(text) < 400   # token 数应少于字符数


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DocProcessorService 基础策略集成测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestDocProcessorService:

    def _make_svc(self, strategy: str = 'recursive', contextual: bool = False) -> DocProcessorService:
        """Helper: 创建不调用 __init__ 的 DocProcessorService 实例，设置所有必要属性。"""
        svc = DocProcessorService.__new__(DocProcessorService)
        svc._primary = strategy
        svc._use_contextual = contextual
        svc._use_parent_child = False
        svc._use_proposition = False
        return svc

    @pytest.mark.asyncio
    async def test_recursive_strategy(self, sample_content: ExtractedContent) -> None:
        svc = self._make_svc('recursive')
        chunks = await svc.process(sample_content, "doc-001")
        assert len(chunks) > 0
        assert all(isinstance(c, DocumentChunk) for c in chunks)

    @pytest.mark.asyncio
    async def test_empty_content_returns_empty(self) -> None:
        svc = self._make_svc('recursive')
        empty = ExtractedContent(raw_id="x", body_text="")
        chunks = await svc.process(empty, "doc-empty")
        assert chunks == []

    @pytest.mark.asyncio
    async def test_contextual_enrichment_called(
        self, sample_content: ExtractedContent, mock_llm: MagicMock
    ) -> None:
        svc = self._make_svc('recursive', contextual=True)
        chunks = await svc.process(sample_content, "doc-001", llm_client=mock_llm)
        assert len(chunks) > 0
        # LLM 应被调用（每块一次）
        assert mock_llm.chat.call_count >= 1

    @pytest.mark.asyncio
    async def test_contextual_skipped_without_llm(
        self, sample_content: ExtractedContent
    ) -> None:
        svc = self._make_svc('recursive', contextual=True)
        # 没有 llm_client 时应静默降级到静态头
        chunks = await svc.process(sample_content, "doc-001", llm_client=None)
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_all_strategies_produce_output(
        self, sample_content: ExtractedContent, mock_llm: MagicMock
    ) -> None:
        """所有策略都应产生非空输出，不抛出异常。"""
        strategies = ['recursive', 'sentence', 'structure', 'parent_child']
        for strategy in strategies:
            svc = DocProcessorService.__new__(DocProcessorService)
            svc._primary = strategy
            svc._use_contextual = False
            svc._use_parent_child = (strategy == 'parent_child')
            svc._use_proposition = False
            chunks = await svc.process(sample_content, f"doc-{strategy}")
            assert len(chunks) > 0, f"Strategy '{strategy}' produced no chunks"
