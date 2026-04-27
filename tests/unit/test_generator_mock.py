# =============================================================================
# tests/unit/test_generator_mock.py
# 单元测试 — Generator / HyDE / Multi-Query（全程 mock LLM，零 Token 消耗）
#
# 核心思路：
#   用 unittest.mock.AsyncMock 替换真实 LLM 调用，让测试：
#   1. 不依赖 Ollama / OpenAI / Anthropic 服务可用性
#   2. 不消耗任何真实 API Token
#   3. 速度从"秒级"变为"毫秒级"
#   4. 可精确控制 LLM 的返回值，验证业务逻辑
#
# 运行：conda run -n torch_env pytest tests/unit/test_generator_mock.py -v
# =============================================================================
from __future__ import annotations

import os
os.environ.setdefault("APP_MODEL_DIR", "/tmp")

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from utils.models import (
    RetrievedChunk, ChunkMetadata, DocType,
    GenerationRequest,
)


# ══════════════════════════════════════════════════════════════════════════════
# 共用 Fixture
# ══════════════════════════════════════════════════════════════════════════════

def _make_chunk(content: str, doc_id: str = "doc_001") -> RetrievedChunk:
    """构造 RetrievedChunk，隔离对真实文件系统的依赖。"""
    return RetrievedChunk(
        chunk_id=f"chunk_{doc_id}",
        doc_id=doc_id,
        content=content,
        metadata=ChunkMetadata(
            source=f"/mnt/test/{doc_id}.pdf",
            doc_id=doc_id,
            doc_type=DocType.PDF,
        ),
    )


def _make_gen_request(query: str = "RAG系统有哪些功能？") -> GenerationRequest:
    return GenerationRequest(query=query, session_id="sess_test")


@pytest.fixture
def mock_llm() -> MagicMock:
    """
    通用 mock LLM：
    - chat()        → AsyncMock，返回固定字符串
    - stream_chat() → 异步生成器（逐 token yield）
    - supports_tools / supports_thinking → False（Ollama/OpenAI 默认行为）
    """
    llm = MagicMock()
    llm.chat = AsyncMock(return_value="RAG系统支持文档解析、向量检索和智能问答功能。")
    llm.supports_tools = False
    llm.supports_thinking = False

    async def _fake_stream(*args, **kwargs):
        for token in ["RAG", "系统", "支持", "向量检索"]:
            yield token

    llm.stream_chat = MagicMock(side_effect=_fake_stream)
    return llm


@pytest.fixture
def mock_llm_with_tools() -> MagicMock:
    """
    支持 Tool Use 的 mock LLM（模拟 Anthropic 行为）：
    - chat_with_tools() 返回结构化 JSON（忠实度评分）
    """
    llm = MagicMock()
    llm.chat = AsyncMock(return_value="基于文档内容的回答。")
    llm.chat_with_tools = AsyncMock(return_value={"score": 0.92, "reason": "内容直接来自上下文"})
    llm.supports_tools = True
    llm.supports_thinking = False
    return llm


# ══════════════════════════════════════════════════════════════════════════════
# 1. estimate_faithfulness — 关键词重叠（非 Tool Use 路径）
# ══════════════════════════════════════════════════════════════════════════════
class TestEstimateFaithfulnessKeyword:
    """
    当 llm_client=None 或 supports_tools=False 时，
    estimate_faithfulness 降级为关键词重叠算法，不调用任何 LLM。
    """

    @pytest.mark.asyncio
    async def test_matching_answer_high_score(self) -> None:
        chunk = _make_chunk("企业RAG系统支持PDF文档解析和向量化存储功能。")
        from services.generator.generator import estimate_faithfulness
        score = await estimate_faithfulness(
            "企业RAG系统支持PDF文档解析。", [chunk], llm_client=None
        )
        assert score >= 0.5

    @pytest.mark.asyncio
    async def test_unrelated_answer_lower_score(self) -> None:
        chunk = _make_chunk("苹果公司发布了最新款iPhone产品线。")
        from services.generator.generator import estimate_faithfulness
        score = await estimate_faithfulness(
            "量子计算将彻底改变密码学体系。", [chunk], llm_client=None
        )
        assert score < 0.8

    @pytest.mark.asyncio
    async def test_empty_answer_returns_zero(self) -> None:
        from services.generator.generator import estimate_faithfulness
        score = await estimate_faithfulness("", [_make_chunk("任意上下文")], llm_client=None)
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_empty_chunks_returns_zero(self) -> None:
        from services.generator.generator import estimate_faithfulness
        score = await estimate_faithfulness("有内容的回答", [], llm_client=None)
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_score_within_range(self) -> None:
        chunk = _make_chunk("测试内容用于验证分数范围的正确性。")
        from services.generator.generator import estimate_faithfulness
        score = await estimate_faithfulness("测试回答内容", [chunk], llm_client=None)
        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_no_tool_use_llm_falls_back_to_keyword(
        self, mock_llm: MagicMock
    ) -> None:
        """supports_tools=False 时，应跳过 chat_with_tools，用关键词重叠计算。"""
        chunk = _make_chunk("企业知识库包含合同、制度、报告等文档。")
        from services.generator.generator import estimate_faithfulness
        await estimate_faithfulness("企业知识库有合同文档。", [chunk], llm_client=mock_llm)
        # chat_with_tools 不应被调用
        assert not hasattr(mock_llm, "chat_with_tools") or \
               mock_llm.chat_with_tools.call_count == 0


# ══════════════════════════════════════════════════════════════════════════════
# 2. estimate_faithfulness — LLM-as-Judge（Tool Use 路径）
# ══════════════════════════════════════════════════════════════════════════════
class TestEstimateFaithfulnessLLMJudge:
    """
    当 llm_client.supports_tools=True 时，使用 chat_with_tools 进行 LLM 评分，
    此处验证 mock 调用链路正确，不需要真实 Anthropic API。
    """

    @pytest.mark.asyncio
    async def test_uses_tool_use_when_supported(
        self, mock_llm_with_tools: MagicMock
    ) -> None:
        chunk = _make_chunk("系统采用混合检索架构，结合密集向量和稀疏BM25。")
        from services.generator.generator import estimate_faithfulness
        score = await estimate_faithfulness(
            "系统使用混合检索。", [chunk], llm_client=mock_llm_with_tools
        )
        # 应使用 LLM-as-Judge 的返回值（0.92）
        assert score == pytest.approx(0.92, abs=0.001)
        mock_llm_with_tools.chat_with_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_tool_use_receives_context_and_answer(
        self, mock_llm_with_tools: MagicMock
    ) -> None:
        """验证 chat_with_tools 的入参确实包含上下文和答案内容。"""
        chunk = _make_chunk("检索增强生成（RAG）通过外部知识库提升答案准确率。")
        answer = "RAG通过知识库提升准确率。"
        from services.generator.generator import estimate_faithfulness
        await estimate_faithfulness(answer, [chunk], llm_client=mock_llm_with_tools)

        call_kwargs = mock_llm_with_tools.chat_with_tools.call_args.kwargs
        assert "检索增强生成" in call_kwargs["user"]   # 上下文进入了 prompt
        assert answer in call_kwargs["user"]            # 答案进入了 prompt

    @pytest.mark.asyncio
    async def test_llm_judge_failure_falls_back_to_keyword(
        self, mock_llm_with_tools: MagicMock
    ) -> None:
        """LLM-as-Judge 失败时降级为关键词重叠，不抛异常。"""
        mock_llm_with_tools.chat_with_tools = AsyncMock(
            side_effect=RuntimeError("Anthropic API timeout")
        )
        chunk = _make_chunk("企业文档包含合同和制度。")
        from services.generator.generator import estimate_faithfulness
        score = await estimate_faithfulness("合同文档", [chunk], llm_client=mock_llm_with_tools)
        # 降级后仍返回合法分数
        assert 0.0 <= score <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# 3. GeneratorService.generate() — mock get_llm_client
# ══════════════════════════════════════════════════════════════════════════════
class TestGeneratorServiceMocked:
    """
    patch services.generator.generator.get_llm_client，
    让 GeneratorService.__init__ 拿到 mock LLM，整个测试不触碰真实服务。
    """

    @pytest.mark.asyncio
    async def test_generate_returns_answer(self, mock_llm: MagicMock) -> None:
        """基础场景：有 chunks 时调用 LLM 并返回答案。"""
        with patch("services.generator.generator.get_llm_client", return_value=mock_llm):
            from services.generator.generator import GeneratorService
            svc = GeneratorService()
            chunks = [_make_chunk("企业RAG系统支持PDF文档解析和向量化存储。")]
            req = _make_gen_request()

            resp = await svc.generate(req, chunks)

        assert resp.answer == "RAG系统支持文档解析、向量检索和智能问答功能。"
        mock_llm.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_empty_chunks_no_llm_call(
        self, mock_llm: MagicMock
    ) -> None:
        """空 chunks 时直接返回兜底答案，不调用 LLM（节省 Token）。"""
        with patch("services.generator.generator.get_llm_client", return_value=mock_llm):
            from services.generator.generator import GeneratorService
            svc = GeneratorService()
            resp = await svc.generate(_make_gen_request(), chunks=[])

        assert "未找到" in resp.answer
        mock_llm.chat.assert_not_called()   # ← 关键断言：空 chunks 不消耗 Token

    @pytest.mark.asyncio
    async def test_generate_prompt_includes_chunk_content(
        self, mock_llm: MagicMock
    ) -> None:
        """验证 LLM 收到的 prompt 里确实包含检索到的 chunk 内容。"""
        chunk_content = "企业差旅费报销标准：出差补贴每天200元。"
        with patch("services.generator.generator.get_llm_client", return_value=mock_llm):
            from services.generator.generator import GeneratorService
            svc = GeneratorService()
            await svc.generate(_make_gen_request("出差补贴是多少？"), [_make_chunk(chunk_content)])

        call_kwargs = mock_llm.chat.call_args.kwargs
        # chunk 内容必须出现在 user prompt 中
        assert chunk_content in call_kwargs["user"]

    @pytest.mark.asyncio
    async def test_generate_includes_session_id_in_response(
        self, mock_llm: MagicMock
    ) -> None:
        with patch("services.generator.generator.get_llm_client", return_value=mock_llm):
            from services.generator.generator import GeneratorService
            svc = GeneratorService()
            req = GenerationRequest(query="测试", session_id="my_session_123")
            resp = await svc.generate(req, [_make_chunk("任意内容。")])

        assert resp.session_id == "my_session_123"

    @pytest.mark.asyncio
    async def test_generate_faithfulness_score_populated(
        self, mock_llm: MagicMock
    ) -> None:
        """返回值中 faithfulness_score 应在 [0, 1] 范围内。"""
        with patch("services.generator.generator.get_llm_client", return_value=mock_llm):
            from services.generator.generator import GeneratorService
            svc = GeneratorService()
            resp = await svc.generate(
                _make_gen_request(), [_make_chunk("向量化存储用于相似度搜索。")]
            )

        assert 0.0 <= resp.faithfulness_score <= 1.0

    @pytest.mark.asyncio
    async def test_generate_latency_ms_positive(self, mock_llm: MagicMock) -> None:
        with patch("services.generator.generator.get_llm_client", return_value=mock_llm):
            from services.generator.generator import GeneratorService
            svc = GeneratorService()
            resp = await svc.generate(
                _make_gen_request(), [_make_chunk("测试延迟记录。")]
            )

        assert resp.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_generate_uses_tool_use_llm_judge(
        self, mock_llm_with_tools: MagicMock
    ) -> None:
        """Anthropic-like LLM（supports_tools=True）应触发 LLM-as-Judge 评分路径。"""
        with patch(
            "services.generator.generator.get_llm_client",
            return_value=mock_llm_with_tools,
        ):
            from services.generator.generator import GeneratorService
            svc = GeneratorService()
            resp = await svc.generate(
                _make_gen_request(),
                [_make_chunk("混合检索融合密集向量和BM25稀疏索引。")],
            )

        assert resp.faithfulness_score == pytest.approx(0.92, abs=0.001)
        mock_llm_with_tools.chat_with_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_with_chat_history(self, mock_llm: MagicMock) -> None:
        """对话历史应被注入 prompt，验证多轮对话上下文传递。"""
        history = [
            {"role": "user",      "content": "什么是RAG？"},
            {"role": "assistant", "content": "RAG是检索增强生成技术。"},
        ]
        with patch("services.generator.generator.get_llm_client", return_value=mock_llm):
            from services.generator.generator import GeneratorService
            svc = GeneratorService()
            await svc.generate(
                _make_gen_request("它有什么优势？"),
                [_make_chunk("RAG相比纯LLM更准确且可溯源。")],
                chat_history=history,
            )

        call_kwargs = mock_llm.chat.call_args.kwargs
        # 对话历史内容应出现在 user prompt 中
        assert "RAG是检索增强生成技术" in call_kwargs["user"]

    @pytest.mark.asyncio
    async def test_generate_multiple_chunks_all_in_prompt(
        self, mock_llm: MagicMock
    ) -> None:
        """多个 chunks 都应出现在 prompt 中。"""
        chunks = [
            _make_chunk("第一条：合同签署需要法务审批。", "doc_001"),
            _make_chunk("第二条：超过10万元需要总裁签字。",  "doc_002"),
        ]
        with patch("services.generator.generator.get_llm_client", return_value=mock_llm):
            from services.generator.generator import GeneratorService
            svc = GeneratorService()
            await svc.generate(_make_gen_request("合同如何审批？"), chunks)

        user_prompt = mock_llm.chat.call_args.kwargs["user"]
        assert "法务审批" in user_prompt
        assert "总裁签字" in user_prompt


# ══════════════════════════════════════════════════════════════════════════════
# 4. GeneratorService.stream_generate() — 异步生成器 mock
# ══════════════════════════════════════════════════════════════════════════════
class TestStreamGenerateMocked:

    @pytest.mark.asyncio
    async def test_stream_yields_tokens(self, mock_llm: MagicMock) -> None:
        """流式生成应逐 token yield，最终拼接结果正确。"""
        with patch("services.generator.generator.get_llm_client", return_value=mock_llm):
            from services.generator.generator import GeneratorService
            svc = GeneratorService()
            tokens: list[str] = []
            async for token in svc.stream_generate(
                _make_gen_request(), [_make_chunk("企业知识库支持混合检索。")]
            ):
                tokens.append(token)

        assert tokens == ["RAG", "系统", "支持", "向量检索"]
        assert "".join(tokens) == "RAG系统支持向量检索"

    @pytest.mark.asyncio
    async def test_stream_empty_chunks_yields_fallback(
        self, mock_llm: MagicMock
    ) -> None:
        """空 chunks 时流式接口应 yield 兜底提示，不调用 LLM。"""
        with patch("services.generator.generator.get_llm_client", return_value=mock_llm):
            from services.generator.generator import GeneratorService
            svc = GeneratorService()
            tokens: list[str] = []
            async for token in svc.stream_generate(_make_gen_request(), chunks=[]):
                tokens.append(token)

        result = "".join(tokens)
        assert "未找到" in result
        mock_llm.stream_chat.assert_not_called()   # ← 零 Token 消耗


# ══════════════════════════════════════════════════════════════════════════════
# 5. HyDE 查询改写 — mock LLM 控制改写结果
# ══════════════════════════════════════════════════════════════════════════════
class TestHydeRewriteMocked:

    @pytest.mark.asyncio
    async def test_hyde_returns_llm_response(self) -> None:
        """HyDE 应将 LLM 生成的假设答案作为新查询，提升检索语义。"""
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(
            return_value="企业RAG系统通过向量数据库检索相关文档片段，再由LLM生成最终答案。"
        )
        from services.retriever.retriever import hyde_rewrite
        result = await hyde_rewrite("RAG是什么？", mock_llm)

        assert result == "企业RAG系统通过向量数据库检索相关文档片段，再由LLM生成最终答案。"
        mock_llm.chat.assert_called_once()
        # 验证调用参数中包含原始查询
        call_kwargs = mock_llm.chat.call_args.kwargs
        assert "RAG是什么" in call_kwargs["user"]

    @pytest.mark.asyncio
    async def test_hyde_fallback_on_llm_error(self) -> None:
        """LLM 调用失败时，HyDE 应静默降级，返回原始查询（不抛异常）。"""
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=RuntimeError("Connection refused"))

        from services.retriever.retriever import hyde_rewrite
        result = await hyde_rewrite("合同审批流程", mock_llm)

        assert result == "合同审批流程"   # 降级到原始查询

    @pytest.mark.asyncio
    async def test_hyde_chat_called_with_correct_system_prompt(self) -> None:
        """验证 HyDE 的 system prompt 要求 LLM 生成'假设性回答'。"""
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="假设性回答内容")

        from services.retriever.retriever import hyde_rewrite
        await hyde_rewrite("年假政策", mock_llm)

        call_kwargs = mock_llm.chat.call_args.kwargs
        system_prompt = call_kwargs["system"]
        assert (
            "answer" in system_prompt.lower()
            or "paragraph" in system_prompt.lower()
            or "假设" in system_prompt  # hypothetical (Chinese)
            or "段落" in system_prompt  # paragraph (Chinese)
        )


# ══════════════════════════════════════════════════════════════════════════════
# 6. Multi-Query 扩展 — mock 控制变体数量和内容
# ══════════════════════════════════════════════════════════════════════════════
class TestMultiQueryExpandMocked:

    @pytest.mark.asyncio
    async def test_returns_original_plus_variants(self) -> None:
        """结果应包含原始查询 + N 个变体。"""
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=(
            "员工请假如何操作\n"
            "请假的审批步骤是什么\n"
            "如何申请年假"
        ))
        from services.retriever.retriever import multi_query_expand
        results = await multi_query_expand("请假流程", mock_llm, n=3)

        # 原始查询 + 最多 3 个变体
        assert results[0] == "请假流程"   # 第一个始终是原始查询
        assert len(results) >= 2
        assert len(results) <= 4

    @pytest.mark.asyncio
    async def test_fallback_on_llm_error(self) -> None:
        """LLM 失败时降级，只返回 [原始查询]，不抛异常。"""
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=ConnectionError("LLM unavailable"))

        from services.retriever.retriever import multi_query_expand
        results = await multi_query_expand("差旅报销标准", mock_llm)

        assert results == ["差旅报销标准"]

    @pytest.mark.asyncio
    async def test_llm_called_with_n_in_prompt(self) -> None:
        """验证 prompt 中包含期望的变体数量 n。"""
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="变体一\n变体二")

        from services.retriever.retriever import multi_query_expand
        await multi_query_expand("绩效考核标准", mock_llm, n=5)

        call_kwargs = mock_llm.chat.call_args.kwargs
        assert "5" in call_kwargs["system"]   # system prompt 中应提到 n=5

    @pytest.mark.asyncio
    async def test_empty_lines_filtered(self) -> None:
        """LLM 返回的空行应被过滤，不出现在结果中。"""
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="\n变体一\n\n变体二\n\n")

        from services.retriever.retriever import multi_query_expand
        results = await multi_query_expand("测试查询", mock_llm)

        assert "" not in results
        assert all(q.strip() for q in results)


# ══════════════════════════════════════════════════════════════════════════════
# 7. build_rag_prompt — 纯函数，无需 mock
# ══════════════════════════════════════════════════════════════════════════════
class TestBuildRagPrompt:
    """
    build_rag_prompt 是纯函数（无 IO / 无 LLM 调用），
    直接测试 prompt 结构是否符合预期。
    """

    def test_returns_system_and_user_tuple(self) -> None:
        from services.generator.generator import build_rag_prompt
        system, user = build_rag_prompt("测试问题", [_make_chunk("测试内容")])
        assert isinstance(system, str) and len(system) > 0
        assert isinstance(user, str)   and len(user) > 0

    def test_user_prompt_contains_query(self) -> None:
        from services.generator.generator import build_rag_prompt
        _, user = build_rag_prompt("公司的年假政策是什么？", [_make_chunk("内容")])
        assert "公司的年假政策是什么" in user

    def test_user_prompt_contains_chunk_content(self) -> None:
        from services.generator.generator import build_rag_prompt
        chunk_text = "员工工作满1年享有5天带薪年假。"
        _, user = build_rag_prompt("年假天数", [_make_chunk(chunk_text)])
        assert chunk_text in user

    def test_multiple_chunks_all_present(self) -> None:
        from services.generator.generator import build_rag_prompt
        chunks = [
            _make_chunk("第一章内容：合同审批需法务确认。", "d1"),
            _make_chunk("第二章内容：超额需总裁审批。",     "d2"),
        ]
        _, user = build_rag_prompt("审批流程", chunks)
        assert "合同审批需法务确认" in user
        assert "超额需总裁审批"     in user

    def test_chat_history_injected(self) -> None:
        from services.generator.generator import build_rag_prompt
        history = [{"role": "user", "content": "之前的问题"}, {"role": "assistant", "content": "之前的答案"}]
        _, user = build_rag_prompt("追问", [_make_chunk("内容")], chat_history=history)
        assert "之前的问题" in user
        assert "之前的答案" in user

    def test_long_term_context_injected(self) -> None:
        from services.generator.generator import build_rag_prompt
        _, user = build_rag_prompt(
            "问题", [_make_chunk("内容")],
            long_term_context="用户是财务总监，关注成本控制",
        )
        assert "财务总监" in user

    def test_system_prompt_contains_rules(self) -> None:
        from services.generator.generator import build_rag_prompt
        system, _ = build_rag_prompt("问题", [_make_chunk("内容")])
        assert "documents" in system.lower() or "规则" in system or "rules" in system.lower()
