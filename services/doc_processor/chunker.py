# =============================================================================
# services/doc_processor/chunker.py
# STAGE 3 — 文档处理
# 支持七种分块策略：
#   recursive    递归字符分块（默认，稳健通用）
#   semantic     语义相似度断点分块
#   sentence     句子窗口分块
#   token        固定 token 数分块
#   structure    结构感知分块（识别章节/条款/表格行）★ 新增
#   parent_child 父子块（小块检索 + 大块召回）★ 新增
#   proposition  命题化分块（LLM 拆解独立事实）★ 新增
# =============================================================================
from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from loguru import logger

import anthropic
import httpx
import openai

from config.settings import settings
from utils.models import (
    ExtractedContent, DocumentChunk, ChunkMetadata,
    DocType, ChunkStrategy, StructureNode,
)
from utils.logger import log_latency


# ══════════════════════════════════════════════════════════════════════════════
# Token 计数（tiktoken / 字符估算回退）
# ══════════════════════════════════════════════════════════════════════════════
def count_tokens(text: str) -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")  # 加载 OpenAI GPT-4 使用的分词器，精确计算 token 数
        return len(enc.encode(text))
    except Exception:
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))   # 统计中文字符数
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 1.5 + other_chars / 4)


def _make_chunk_id(doc_id: str, idx: int, text: str) -> str:
    suffix = hashlib.md5(text[:64].encode(), usedforsecurity=False).hexdigest()[:8]
    return f"{doc_id}_{idx:04d}_{suffix}"


# ══════════════════════════════════════════════════════════════════════════════
# Strategy 1 — 递归字符分块（默认）
# ══════════════════════════════════════════════════════════════════════════════
class RecursiveTextSplitter:
    _SEPARATORS_ZH = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]
    _SEPARATORS_EN = ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " ", ""]

    def __init__(
        self,
        chunk_size: int = settings.chunk_size,
        chunk_overlap: int = settings.chunk_overlap,
        language: str = "zh",
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._seps = self._SEPARATORS_ZH if language.startswith("zh") else self._SEPARATORS_EN

    def split(self, text: str) -> list[str]:
        chunks: list[str] = []
        self._split_recursive(text.strip(), list(self._seps), chunks)
        return [c.strip() for c in chunks if len(c.strip()) >= settings.chunk_min_size]

    def _split_recursive(self, text: str, seps: list[str], acc: list[str]) -> None: # acc 是累积结果列表
        if len(text) <= self.chunk_size:
            if text.strip():
                acc.append(text)
            return
        sep = seps[0] if seps else ""
        if not sep:
            # 最后手段：硬截断，每次前进（chunk_size - overlap）个字符，重叠部分保证连续性
            for i in range(0, len(text), self.chunk_size - self.chunk_overlap):
                acc.append(text[i: i + self.chunk_size])
            return
        parts = text.split(sep)
        current = ""    # 当前分块，当 current 太长时，就会被提交到 acc，然后重新开始累积
        for part in parts:
            sep_str = sep if current else ""
            candidate = current + sep_str + part    # 试探性拼接，用来判断：拼进去会不会超过 chunk_size
            if len(candidate) > self.chunk_size and current:
                if len(current) > self.chunk_size:
                    self._split_recursive(current, seps[1:], acc)
                else:
                    acc.append(current)
                overlap_start = max(0, len(current) - self.chunk_overlap)
                current = current[overlap_start:] + sep + part if current[overlap_start:] else part
            else:
                current = candidate
        if current.strip():
            if len(current) > self.chunk_size:
                self._split_recursive(current, seps[1:], acc)
            else:
                acc.append(current)


# ══════════════════════════════════════════════════════════════════════════════
# Strategy 2 — 语义分块
# ══════════════════════════════════════════════════════════════════════════════
def semantic_split(text: str, threshold: float = 0.5) -> list[str]:
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
        sentences = re.split(r"(?<=[。！？.!?])\s*", text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
        if len(sentences) <= 1:
            return [text]
        model = SentenceTransformer(str(settings.embedding_model_path))
        # 把一组句子编码成向量，让模型在输出时对每个向量做 L2 归一化
        embeddings = model.encode(sentences, normalize_embeddings=True)
        chunks: list[str] = []
        current_sentences: list[str] = [sentences[0]]   # 当前正在构建的“一个 chunk 内的句子
        for i in range(1, len(sentences)):
            sim = float(np.dot(embeddings[i - 1], embeddings[i]))
            if sim < threshold:
                chunks.append(" ".join(current_sentences))   #  把“一个完整 chunk”加入最终结果
                current_sentences = [sentences[i]]   # 重新开始构建下一个 chunk
            else:
                current_sentences.append(sentences[i])  # 把一个句子加入当前 chunk 的句子列表
        if current_sentences:
            chunks.append(" ".join(current_sentences))
        return chunks
    except Exception as exc:
        logger.warning(f"Semantic split failed ({exc}), falling back to recursive")
        return RecursiveTextSplitter().split(text)


# ══════════════════════════════════════════════════════════════════════════════
# Strategy 3 — 句子窗口
# ══════════════════════════════════════════════════════════════════════════════
def sentence_window_split(text: str, window: int = settings.sentence_window_size) -> list[str]:
    sentences = re.split(r"(?<=[。！？.!?])\s*", text)  # \s* 允许句号后面有若干空白（空格、换行等），一起作为分隔符丢掉
    sentences = [s.strip() for s in sentences if len(s.strip()) > 1]
    chunks: list[str] = []
    for i, _ in enumerate(sentences):   # 用 enumerate 而不是 range(len(sentences))，更 Pythonic
        start = max(0, i - window)
        end = min(len(sentences), i + window + 1)   # +1 是因为切片右边是开区间
        chunks.append(" ".join(sentences[start:end]))
    # dict.fromkeys(chunks)：利用字典 key 唯一性去重，同时保留原有顺序
    return list(dict.fromkeys(chunks))


# ══════════════════════════════════════════════════════════════════════════════
# Strategy 4 — 结构感知分块 ★ 新增
# ══════════════════════════════════════════════════════════════════════════════

# 中文企业制度文档常见的结构标记正则
_CHAPTER_PATTERNS = [
    re.compile(r"^第[一二三四五六七八九十百零\d]+章\s*[\u4e00-\u9fff\w]+"),  # 第一章 总则
    re.compile(r"^[\u4e00-\u9fff]{1,4}篇\s*[\u4e00-\u9fff\w]+"),              # 第一篇
]
_ARTICLE_PATTERNS = [
    re.compile(r"^第[一二三四五六七八九十百零\d]+条\s*"),                       # 第十五条
    re.compile(r"^\d+[\.、]\s*[\u4e00-\u9fff]"),                               # 1. 年假
    re.compile(r"^[（(][一二三四五六七八九十\d]+[）)]\s*"),                     # （一）
]
_LIST_PATTERNS = [
    re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩]"),
    re.compile(r"^[a-zA-Z][\.、]\s"),
    re.compile(r"^\s*[-•·]\s+"),
]


def _classify_line(line: str) -> str:
    """把一行文本分类为 chapter / article / list_item / paragraph。"""
    stripped = line.strip()
    if not stripped:
        return "empty"
    for p in _CHAPTER_PATTERNS:
        if p.match(stripped):
            return "chapter"
    for p in _ARTICLE_PATTERNS:
        if p.match(stripped):
            return "article"
    for p in _LIST_PATTERNS:
        if p.match(stripped):
            return "list_item"
    return "paragraph"


def structure_aware_split(text: str) -> list[StructureNode]:
    """
    把文档文本解析为 StructureNode 列表。
    每个节点是一个自然语义单元（章节 / 条款 / 列表项 / 普通段落）。

    核心思路：逐行扫描，遇到章节/条款标题就开始新节点，
    把所属正文内容挂到该节点下，保留完整的层级上下文。
    """
    lines = text.split("\n")
    nodes: list[StructureNode] = []

    current_chapter = ""
    current_article = ""
    current_node_type = "paragraph"
    current_lines: list[str] = []

    def flush(node_type: str, heading: str, parent: str) -> None:
        content = "\n".join(current_lines).strip()
        if content:
            nodes.append(StructureNode(
                node_type=node_type,
                heading=heading,
                parent_heading=parent,
                content=content,
                level=0 if node_type == "chapter" else 1 if node_type == "article" else 2,
            ))
    '''
    遇到 chapter 行（比如“第一章 总则”）：
        current_chapter 被更新为这一行
        current_article 被清空为 ""
    遇到 article 行（比如“第二条 工作时间”）：
        current_article 被更新为这一行
    遇到普通段落 / 列表项：
        标题变量不变，只往 current_lines 里追加内容
    '''
    for line in lines:
        line_type = _classify_line(line)
        stripped = line.strip()

        if line_type == "empty":
            current_lines.append("")
            continue

        if line_type == "chapter":
            # 遇到新章节：先把当前积累的内容 flush
            # 如果 a 是“真值”（非空字符串、非 0、非 None 等），返回 a；否则返回 b
            flush(current_node_type, current_article or current_chapter, current_chapter)
            current_lines = []
            current_chapter = stripped
            current_article = ""
            current_node_type = "chapter"
            current_lines.append(stripped)

        elif line_type == "article":
            # 遇到新条款：flush 当前，开新节点
            flush(current_node_type, current_article or current_chapter, current_chapter)
            current_lines = []
            current_article = stripped
            current_node_type = "article"
            current_lines.append(stripped)

        elif line_type == "list_item":
            # 列表项：flush 当前段落，列表项单独成一个小节点
            if current_lines and any(l.strip() for l in current_lines):
                flush(current_node_type, current_article or current_chapter, current_chapter)
                current_lines = []
            current_node_type = "list_item"
            current_lines.append(stripped)

        else:
            # 普通段落：直接追加
            if current_node_type == "list_item" and current_lines:
                # 列表项后接普通文字，先 flush 列表项
                flush("list_item", current_article or current_chapter, current_chapter)
                current_lines = []
                current_node_type = "article" if current_article else "chapter"
            current_lines.append(stripped)

    # 最后一块
    flush(current_node_type, current_article or current_chapter, current_chapter)

    # 如果解析结果为空（文档无结构标记），降级到递归分块
    if not nodes:
        logger.warning("[StructureAware] No structure detected, falling back to recursive")
        raw = RecursiveTextSplitter().split(text)
        for i, t in enumerate(raw):
            nodes.append(StructureNode(node_type="paragraph", content=t))

    logger.info(f"[StructureAware] Parsed {len(nodes)} structure nodes")
    return nodes


def _get_dynamic_chunk_size(node_type: str) -> int:
    """
    动态 chunk size：根据节点类型返回最优切分大小。

    表格行需要保持结构紧凑（小块），法规条款保持完整性（中小块），
    普通段落用默认值，章节导言允许更大以保留上下文。
    """
    if not getattr(settings, "dynamic_chunk_size_enabled", True):
        return settings.chunk_size
    size_map = {
        "table_row":  getattr(settings, "chunk_size_table",     256),
        "article":    getattr(settings, "chunk_size_article",   384),
        "list_item":  getattr(settings, "chunk_size_article",   384),
        "paragraph":  getattr(settings, "chunk_size_paragraph", 512),
        "chapter":    getattr(settings, "chunk_size_chapter",   768),
    }
    return size_map.get(node_type, settings.chunk_size)


def structure_nodes_to_chunks(
    nodes: list[StructureNode],
    doc_id: str,
    content: ExtractedContent,
) -> list[DocumentChunk]:
    """
    把 StructureNode 列表转换为 DocumentChunk 列表，同时注入层级元数据。
    支持动态 chunk size：不同节点类型使用不同的切分大小。
    """
    chunks: list[DocumentChunk] = []
    total = len(nodes)

    for idx, node in enumerate(nodes):
        if not node.content.strip():
            continue

        # 动态 chunk size：根据节点类型决定是否需要二次切分
        dynamic_size = _get_dynamic_chunk_size(node.node_type)
        node_text = node.content.strip()

        # 如果节点内容超过动态 size 上限，用对应 size 的 splitter 二次切分
        if count_tokens(node_text) > dynamic_size:
            splitter = RecursiveTextSplitter(
                chunk_size=dynamic_size,
                chunk_overlap=settings.chunk_overlap,
                language=content.language or "zh",
            )
            sub_texts = splitter.split(node_text)
        else:
            sub_texts = [node_text]

        for sub_idx, sub_text in enumerate(sub_texts):
            if not sub_text.strip():
                continue
            # 构建带层级上下文的嵌入文本
            context_parts = []
            if node.parent_heading:
                context_parts.append(node.parent_heading)
            if node.heading and node.heading != node.parent_heading:
                context_parts.append(node.heading)
            context_header = " > ".join(context_parts) if context_parts else content.title
            enriched = f"[{node.node_type}] {context_header}\n\n{sub_text}"

            # 二次切分时在 chunk_id 中加入子索引，保证唯一性
            unique_idx = idx * 100 + sub_idx
            chunk_id = _make_chunk_id(doc_id, unique_idx, sub_text)
            meta = ChunkMetadata(
                source=content.metadata.get("source", ""),
                doc_id=doc_id,
                title=content.title,
                author=content.author,
                section=node.parent_heading,
                sub_section=node.heading,
                chunk_index=unique_idx,
                total_chunks=total,
                doc_type=content.doc_type,
                node_type=node.node_type,
                chunk_level="child",
            )
            chunks.append(DocumentChunk(
                chunk_id=chunk_id,
                doc_id=doc_id,
                content=sub_text,
                content_with_header=enriched,
                metadata=meta,
                token_count=count_tokens(sub_text),
            ))

    return chunks


# ══════════════════════════════════════════════════════════════════════════════
# Strategy 5 — 父子块 ★ 新增
# ══════════════════════════════════════════════════════════════════════════════
def parent_child_split(
    text: str,
    content: ExtractedContent,
    doc_id: str,
) -> tuple[list[DocumentChunk], list[DocumentChunk]]:
    """
    生成两套块：
    - child_chunks：小块（chunk_size），用于向量检索，粒度细、语义纯
    - parent_chunks：大块（parent_chunk_size），用于召回后扩展，给 LLM 更多上下文

    返回 (child_chunks, parent_chunks)，由 VectorizerService 分别存入两个 collection。
    child.metadata.parent_chunk_id 指向对应 parent 的 chunk_id。
    """
    parent_size = settings.parent_chunk_size      # 默认 2048
    child_size  = settings.chunk_size              # 默认 512
    overlap     = settings.chunk_overlap           # 默认 64
    language    = getattr(content, "language", "zh")

    # ── 生成父块（大块）─────────────────────────────────────────────────────
    parent_splitter = RecursiveTextSplitter(
        chunk_size=parent_size,
        chunk_overlap=overlap * 2,   # 父块 overlap 适当大一些
        language=language,
    )
    parent_texts = parent_splitter.split(text)
    parent_chunks: list[DocumentChunk] = []

    for pidx, ptext in enumerate(parent_texts):
        pid = _make_chunk_id(doc_id, pidx, ptext) + "_P"
        meta = ChunkMetadata(
            source=content.metadata.get("source", ""),
            doc_id=doc_id,
            title=content.title,
            author=content.author,
            chunk_index=pidx,
            total_chunks=len(parent_texts),
            doc_type=content.doc_type,
            chunk_level="parent",
        )
        parent_chunks.append(DocumentChunk(
            chunk_id=pid,
            doc_id=doc_id,
            content=ptext,
            content_with_header=f"来源：{content.title}\n\n{ptext}",
            metadata=meta,
            token_count=count_tokens(ptext),
        ))

    # ── 生成子块（小块），并关联到父块 ───────────────────────────────────────
    child_splitter = RecursiveTextSplitter(
        chunk_size=child_size,
        chunk_overlap=overlap,
        language=language,
    )
    child_chunks: list[DocumentChunk] = []
    child_global_idx = 0

    for pidx, parent in enumerate(parent_chunks):
        child_texts = child_splitter.split(parent.content)
        for cidx, ctext in enumerate(child_texts):
            if len(ctext.strip()) < settings.chunk_min_size:
                continue
            cid = _make_chunk_id(doc_id, child_global_idx, ctext)
            meta = ChunkMetadata(
                source=content.metadata.get("source", ""),
                doc_id=doc_id,
                title=content.title,
                author=content.author,
                chunk_index=child_global_idx,
                total_chunks=-1,       # 子块总数在全部生成后回填
                doc_type=content.doc_type,
                chunk_level="child",
                parent_chunk_id=parent.chunk_id,  # ← 关键：记录父块 ID
            )
            child_chunks.append(DocumentChunk(
                chunk_id=cid,
                doc_id=doc_id,
                content=ctext,
                content_with_header=f"来源：{content.title}\n\n{ctext}",
                metadata=meta,
                token_count=count_tokens(ctext),
                parent_content=parent.content,     # ← 父块原文，检索后直接可用
            ))
            child_global_idx += 1

    # 回填子块总数
    for c in child_chunks:
        c.metadata.total_chunks = len(child_chunks)

    logger.info(
        f"[ParentChild] doc_id={doc_id} "
        f"parent={len(parent_chunks)} child={len(child_chunks)}"
    )
    return child_chunks, parent_chunks


# ══════════════════════════════════════════════════════════════════════════════
# Strategy 6 — 命题化分块 ★ 新增
# ══════════════════════════════════════════════════════════════════════════════
_PROPOSITION_SYSTEM = """\
你是企业文档分析专家。将文档片段分解为独立的、自包含的事实陈述（命题）。

<rules>
  1. 每条命题必须是一个完整的、可独立理解的事实句子。
  2. 消除所有指代不明（将「它」「该规定」「上述」替换为具体名称）。
  3. 数字、时间、金额、条件必须完整保留在命题中。
  4. 一行一条命题，不加编号，不加任何格式符号。
  5. 不添加原文没有的信息，不省略任何事实。
  6. 输出语言与原文一致。
</rules>"""

_PROPOSITION_USER = """\
<document_source>{title}</document_source>
<section>{section}</section>

<chunk>
{chunk_text}
</chunk>

请输出命题列表："""


async def proposition_split(
    chunk_text: str,
    content: ExtractedContent,
    section: str,
    llm_client,
    max_retries: int = 2,
) -> list[str]:
    """
    命题化分块：用 LLM 把一个文本块拆解为多个独立事实陈述。

    例：「员工试用期为1-3个月，用人部门需提前7天告知人事行政部合格与否」
    →  「员工试用期为1至3个月」
       「用人部门须在试用期结束前7天通知人事行政部员工考核结果」

    每个命题语义极纯，向量检索精度最高。
    失败时降级返回原始文本（作为单个命题）。
    """
    for attempt in range(max_retries + 1):
        try:
            resp = await llm_client.chat(
                system=_PROPOSITION_SYSTEM,
                user=_PROPOSITION_USER.format(
                    title=content.title or "企业文档",
                    section=section or "正文",
                    chunk_text=chunk_text,
                ),
                temperature=0.0,            # 命题化要求确定性输出
                task_type="summarize",      # → Haiku，批量处理成本极低
            )
            propositions = [
                line.strip()
                for line in resp.strip().split("\n")
                if line.strip() and len(line.strip()) >= 8
            ]
            if propositions:
                logger.debug(
                    f"[Proposition] {len(propositions)} props from "
                    f"{count_tokens(chunk_text)} tokens"
                )
                return propositions
            raise ValueError("Empty proposition list returned")
        except Exception as exc:
            if attempt < max_retries:
                logger.warning(f"[Proposition] attempt {attempt+1} failed: {exc}, retrying...")
                await asyncio.sleep(1.0 * (attempt + 1))
            else:
                logger.warning(f"[Proposition] all retries exhausted, using original text: {exc}")
                return [chunk_text]

    return [chunk_text]


# ══════════════════════════════════════════════════════════════════════════════
# 元数据头注入（静态兜底）
# ══════════════════════════════════════════════════════════════════════════════
def inject_metadata_header(chunk_text: str, meta: ChunkMetadata) -> str:
    parts = [f"来源：{meta.title}" if meta.title else ""]
    if meta.section:
        parts.append(f"章节：{meta.section}")
    if meta.sub_section:
        parts.append(f"条款：{meta.sub_section}")
    if meta.page_number:
        parts.append(f"页码：{meta.page_number}")
    header = " | ".join(p for p in parts if p)
    return f"{header}\n\n{chunk_text}" if header else chunk_text


# ══════════════════════════════════════════════════════════════════════════════
# Contextual Retrieval（动态上下文注入）
# ══════════════════════════════════════════════════════════════════════════════
_CONTEXT_SYSTEM = """\
你是企业文档分析专家。为文档片段生成简短的上下文说明，
帮助检索系统理解该片段在整篇文档中的位置和意义。
只输出上下文说明，不要添加任何前缀、标签或格式符号。"""

# 遵循 Anthropic 官方 Contextual Retrieval 推荐格式（XML document/chunk 标签）
_CONTEXT_USER_TMPL = """\
<document>
{full_text}
</document>

以下是需要定位的文档片段：
<chunk>
{chunk_text}
</chunk>

请用 2-3 句话说明该片段在整篇文档中的位置与作用，点明其所属章节/主题及描述的规定内容。\
不要复述原文，只补充背景信息。直接输出说明文字。"""

_MAX_FULL_TEXT_CHARS = 6000

_IMAGE_CAPTION_SYSTEM = """\
你是专业的图像描述助手。
请用简洁、准确的语言描述图片中的主要内容：
  - 描述图片中的关键视觉元素（图表类型、数据趋势、对象、文字）
  - 若图片包含文字，完整提取文字内容
  - 只输出描述内容，不要添加额外说明
"""


async def contextual_enrichment(
    chunk_text: str,
    full_doc_text: str,
    meta: ChunkMetadata,
    llm_client,
) -> str:
    if len(full_doc_text) > _MAX_FULL_TEXT_CHARS:
        half = _MAX_FULL_TEXT_CHARS // 2
        trimmed = (
            full_doc_text[:half]
            + "\n\n...[文档中间部分已省略]...\n\n"
            + full_doc_text[-half:]
        )
    else:
        trimmed = full_doc_text
    try:
        context_desc = await llm_client.chat(
            system=_CONTEXT_SYSTEM,
            user=_CONTEXT_USER_TMPL.format(full_text=trimmed, chunk_text=chunk_text),
            temperature=0.1,
            task_type="summarize",      # → Haiku，成本极低（入库阶段大量调用）
        )
        context_desc = context_desc.strip()
        if not context_desc:
            raise ValueError("LLM returned empty context")
        logger.debug(f"[Contextual] generated: {context_desc[:80]}...")
        return f"{context_desc}\n\n{chunk_text}"
    except Exception as exc:
        logger.warning(f"[Contextual] LLM failed, fallback to static header: {exc}")
        return inject_metadata_header(chunk_text, meta)


# ══════════════════════════════════════════════════════════════════════════════
# DocProcessor Service — 统一调度入口
# ══════════════════════════════════════════════════════════════════════════════
class DocProcessorService:
    """
    STAGE 3 入口：根据 chunk_strategy 调度对应分块策略，
    输出 DocumentChunk 列表（父子块策略同时返回父块供 VectorizerService 单独存储）。

    策略路由：
      recursive    → RecursiveTextSplitter
      semantic     → semantic_split
      sentence     → sentence_window_split
      structure    → structure_aware_split（结构感知，★ 新增）
      parent_child → parent_child_split（父子块，★ 新增）
      proposition  → proposition_split（命题化，★ 新增，需 llm_client）
    """

    def __init__(self) -> None:
        # 读取新字段，同时兼容旧字段名
        self._primary = getattr(settings, "chunk_primary_strategy",
                                getattr(settings, "chunk_strategy", "auto"))
        self._use_parent_child  = getattr(settings, "parent_child_enabled", False)
        self._use_contextual    = getattr(settings, "contextual_retrieval_enabled", False)
        self._use_proposition   = getattr(settings, "proposition_on_articles", False)

    @log_latency
    async def process(
        self,
        content: ExtractedContent,
        doc_id: str,
        llm_client=None,
    ) -> list[DocumentChunk]:
        """
        分块流水线主入口，四层叠加：

          第一层（必选）：chunk_primary_strategy 决定按什么边界切
            "auto"      → 有章节结构用 structure，否则 recursive
            "structure" → 按文档自然结构切（章节/条款/表格行）
            "recursive" → 递归字符分块（通用兜底）
            "semantic"  → 语义相似度断点切
            "sentence"  → 句子窗口切

          第二层（可选）：parent_child_enabled = true
            在第一层块的基础上生成父子两套，子块检索，父块送 LLM

          第三层（可选）：contextual_retrieval_enabled = true
            对每个子块调用 LLM 生成上下文说明，拼在前面再嵌入

          第四层（可选）：proposition_on_articles = true
            对 article 类型节点额外做命题化拆解（精确条款查询场景）
        """
        if not content.body_text.strip() and not content.images:
            logger.warning(f"[DocProcess] Empty body_text and no images for doc_id={doc_id}")
            return []

        # Image-only document: skip text chunking pipeline, go straight to image chunks
        if not content.body_text.strip() and content.images:
            logger.info(
                f"[DocProcess] Image-only doc: doc_id={doc_id} "
                f"images={len(content.images)}"
            )
            return await self._chunk_images(
                images=content.images,
                content=content,
                doc_id=doc_id,
                llm_client=llm_client,
                start_index=0,
            )

        # 确定实际使用的主策略
        primary = self._resolve_primary_strategy(content)

        logger.info(
            f"[DocProcess] START doc_id={doc_id} "
            f"primary={primary} "
            f"parent_child={self._use_parent_child} "
            f"contextual={'on' if (self._use_contextual and llm_client) else 'off'} "
            f"proposition={'on' if (self._use_proposition and llm_client) else 'off'} "
            f"chars={len(content.body_text)}"
        )

        # ── 第一层：主切法 ────────────────────────────────────────────────────
        if primary == "structure":
            child_chunks = await self._process_structure(content, doc_id, llm_client)
        else:
            child_chunks = await self._process_basic(content, doc_id, llm_client)

        # ── 第四层（可选）：对 article 节点做命题化 ───────────────────────────
        # 在父子块分层之前做命题化，避免父块内容被命题化拆碎
        if self._use_proposition and llm_client:
            child_chunks = await self._apply_proposition_on_articles(
                child_chunks, content, llm_client
            )

        # ── 第二层（可选）：父子块分层 ────────────────────────────────────────
        if self._use_parent_child:
            child_chunks, parent_chunks = await self._make_parent_child(
                child_chunks, content, doc_id
            )
            all_chunks = child_chunks + parent_chunks
        else:
            all_chunks = child_chunks

        # ── 第三层（可选）：Contextual Enrichment ────────────────────────────
        if self._use_contextual and llm_client:
            # 只对子块做 Contextual Enrichment，父块不参与
            enriched_children = await self._apply_contextual(
                [c for c in all_chunks if c.metadata.chunk_level != "parent"],
                content.body_text,
                llm_client,
            )
            parents = [c for c in all_chunks if c.metadata.chunk_level == "parent"]
            all_chunks = enriched_children + parents

        # ── Image chunks (appended after all text chunks) ─────────────────────
        if content.images and llm_client is not None:
            image_chunks = await self._chunk_images(
                images=content.images,
                content=content,
                doc_id=doc_id,
                llm_client=llm_client,
                start_index=len(all_chunks),
            )
            all_chunks.extend(image_chunks)

        logger.info(
            f"[DocProcess] DONE doc_id={doc_id} "
            f"total={len(all_chunks)} "
            f"child={sum(1 for c in all_chunks if c.metadata.chunk_level != 'parent')} "
            f"parent={sum(1 for c in all_chunks if c.metadata.chunk_level == 'parent')}"
        )
        return all_chunks

    def _resolve_primary_strategy(self, content: ExtractedContent) -> str:
        """
        auto 模式：检测文档是否有章节结构，有则用 structure，否则 recursive。
        其他模式直接返回配置值。
        """
        if self._primary != "auto":
            return self._primary
        # 简单启发式：文档中有「第X章」或「第X条」模式则认为有结构
        sample = content.body_text[:3000]
        has_structure = bool(
            re.search(r"第[一二三四五六七八九十百零\d]+[章条]", sample)
        )
        resolved = "structure" if has_structure else "recursive"
        logger.debug(f"[DocProcess] auto resolved to: {resolved}")
        return resolved

    # ── 父子块分层（第二层）─────────────────────────────────────────────────────
    async def _make_parent_child(
        self,
        child_chunks: list[DocumentChunk],
        content: ExtractedContent,
        doc_id: str,
    ) -> tuple[list[DocumentChunk], list[DocumentChunk]]:
        """
        把第一层切出的子块聚合成父块：
        将相邻的若干子块合并为一个父块（目标大小 parent_chunk_size），
        每个子块的 parent_chunk_id 指向对应父块。
        这样父块是真实的连续文本段，比单独用递归切更自然。
        """
        target_parent_size = settings.parent_chunk_size
        parent_chunks: list[DocumentChunk] = []
        updated_children: list[DocumentChunk] = []

        # 按 parent_chunk_size 滑动窗口聚合相邻子块
        current_group: list[DocumentChunk] = []
        current_tokens = 0
        group_idx = 0

        def _flush_group() -> None:
            nonlocal group_idx
            if not current_group:
                return
            parent_text = "\n\n".join(c.content for c in current_group)
            pid = _make_chunk_id(doc_id, group_idx, parent_text) + "_P"
            meta = ChunkMetadata(
                source=current_group[0].metadata.source,
                doc_id=doc_id,
                title=content.title,
                author=content.author,
                section=current_group[0].metadata.section,
                chunk_index=group_idx,
                total_chunks=-1,
                doc_type=content.doc_type,
                chunk_level="parent",
            )
            parent_chunks.append(DocumentChunk(
                chunk_id=pid,
                doc_id=doc_id,
                content=parent_text,
                content_with_header=f"来源：{content.title}\n\n{parent_text}",
                metadata=meta,
                token_count=count_tokens(parent_text),
            ))
            # 回写 parent_chunk_id 到每个子块
            for c in current_group:
                c.metadata.parent_chunk_id = pid
                c.parent_content = parent_text
                updated_children.append(c)
            group_idx += 1

        for chunk in child_chunks:
            if current_tokens + chunk.token_count > target_parent_size and current_group:
                _flush_group()
                current_group = []
                current_tokens = 0
            current_group.append(chunk)
            current_tokens += chunk.token_count

        _flush_group()  # 最后一组

        # 回填父块总数
        total_parents = len(parent_chunks)
        for p in parent_chunks:
            p.metadata.total_chunks = total_parents

        logger.info(
            f"[ParentChild] {len(updated_children)} children → "
            f"{total_parents} parents"
        )
        return updated_children, parent_chunks

    # ── 命题化（第四层，仅对 article 节点）────────────────────────────────────
    async def _apply_proposition_on_articles(
        self,
        chunks: list[DocumentChunk],
        content: ExtractedContent,
        llm_client,
    ) -> list[DocumentChunk]:
        """
        对 node_type=="article" 的块做命题化拆解，其他类型保持原样。
        只处理条款节点，避免对章节标题、表格行等做不必要的命题化。
        """
        concurrency = getattr(settings, "proposition_concurrency", 3)
        max_retries = getattr(settings, "proposition_max_retries", 2)
        sem = asyncio.Semaphore(concurrency)

        result: list[DocumentChunk] = []
        prop_total = 0

        async def _maybe_propositionize(chunk: DocumentChunk) -> list[DocumentChunk]:
            if chunk.metadata.node_type != "article":
                return [chunk]
            async with sem:
                props = await proposition_split(
                    chunk_text=chunk.content,
                    content=content,
                    section=chunk.metadata.sub_section or chunk.metadata.section,
                    llm_client=llm_client,
                    max_retries=max_retries,
                )
            # 把命题列表包装成 DocumentChunk
            prop_chunks = []
            for pidx, prop in enumerate(props):
                if len(prop.strip()) < 8:
                    continue
                new_meta = chunk.metadata.model_copy(update={
                    "chunk_level": "proposition",
                    "node_type":   "proposition",
                    "chunk_index": chunk.metadata.chunk_index * 100 + pidx,
                })
                prop_chunks.append(DocumentChunk(
                    chunk_id=_make_chunk_id(chunk.doc_id, chunk.metadata.chunk_index * 100 + pidx, prop),
                    doc_id=chunk.doc_id,
                    content=prop,
                    content_with_header=f"来源：{content.title}\n\n{prop}",
                    metadata=new_meta,
                    token_count=count_tokens(prop),
                ))
            return prop_chunks if prop_chunks else [chunk]

        groups = await asyncio.gather(
            *[_maybe_propositionize(c) for c in chunks]
        )
        for group in groups:
            prop_total += sum(1 for c in group if c.metadata.node_type == "proposition")
            result.extend(group)

        logger.info(f"[Proposition] article chunks → {prop_total} propositions")
        return result

    # ── 结构感知 ──────────────────────────────────────────────────────────────
    async def _process_structure(

        self,
        content: ExtractedContent,
        doc_id: str,
        llm_client,
    ) -> list[DocumentChunk]:
        nodes = structure_aware_split(content.body_text)
        chunks = structure_nodes_to_chunks(nodes, doc_id, content)

        # 表格单独处理：每行一个命题式块
        table_chunks = self._process_tables(content, doc_id, len(chunks))
        chunks.extend(table_chunks)

        # 可选：对结构块再做 Contextual Enrichment
        if self._use_contextual and llm_client:
            chunks = await self._apply_contextual(chunks, content.body_text, llm_client)

        return chunks

    # ── 父子块 ────────────────────────────────────────────────────────────────
    async def _process_parent_child(
        self,
        content: ExtractedContent,
        doc_id: str,
        llm_client,
    ) -> list[DocumentChunk]:
        child_chunks, parent_chunks = parent_child_split(
            content.body_text, content, doc_id
        )

        # 父块也放入返回列表，用 chunk_level="parent" 标记
        # VectorizerService 会把它们分到单独 collection
        all_chunks = child_chunks + parent_chunks

        if self._use_contextual and llm_client:
            child_chunks = await self._apply_contextual(
                child_chunks, content.body_text, llm_client
            )
            all_chunks = child_chunks + parent_chunks

        return all_chunks

    # ── 命题化 ────────────────────────────────────────────────────────────────
    async def _process_proposition(
        self,
        content: ExtractedContent,
        doc_id: str,
        llm_client,
    ) -> list[DocumentChunk]:
        if llm_client is None:
            logger.warning(
                "[DocProcess] proposition strategy requires llm_client, "
                "falling back to structure"
            )
            return await self._process_structure(content, doc_id, llm_client)

        # 先用递归切块，再对每块做命题化拆解
        raw_chunks = RecursiveTextSplitter(
            chunk_size=settings.chunk_size,
            language=getattr(content, "language", "zh"),
        ).split(content.body_text)

        # 用结构解析提取章节上下文，给命题化提供 section 参数
        nodes = structure_aware_split(content.body_text)
        # 建立文本 → 节点的映射（简化：按顺序对应）
        section_map = {i: (nodes[i].heading if i < len(nodes) else "") for i in range(len(raw_chunks))}

        concurrency = getattr(settings, "proposition_concurrency", 3)
        max_retries = getattr(settings, "proposition_max_retries", 2)
        sem = asyncio.Semaphore(concurrency)

        async def _propositionize(idx: int, chunk_text: str) -> list[str]:
            async with sem:
                return await proposition_split(
                    chunk_text=chunk_text,
                    content=content,
                    section=section_map.get(idx, ""),
                    llm_client=llm_client,
                    max_retries=max_retries,
                )

        results = await asyncio.gather(
            *[_propositionize(i, t) for i, t in enumerate(raw_chunks)]
        )

        # 展平命题列表，构建 DocumentChunk
        all_propositions: list[str] = []
        for prop_list in results:
            all_propositions.extend(prop_list)

        chunks: list[DocumentChunk] = []
        for idx, prop in enumerate(all_propositions):
            if len(prop.strip()) < 8:
                continue
            chunk_id = _make_chunk_id(doc_id, idx, prop)
            meta = ChunkMetadata(
                source=content.metadata.get("source", ""),
                doc_id=doc_id,
                title=content.title,
                author=content.author,
                chunk_index=idx,
                total_chunks=len(all_propositions),
                doc_type=content.doc_type,
                chunk_level="proposition",
                node_type="proposition",
            )
            chunks.append(DocumentChunk(
                chunk_id=chunk_id,
                doc_id=doc_id,
                content=prop,
                content_with_header=f"来源：{content.title}\n\n{prop}",
                metadata=meta,
                token_count=count_tokens(prop),
            ))

        logger.info(f"[Proposition] {len(raw_chunks)} chunks → {len(chunks)} propositions")
        return chunks

    # ── 基础策略（recursive/semantic/sentence）────────────────────────────────
    async def _process_basic(
        self,
        content: ExtractedContent,
        doc_id: str,
        llm_client,
    ) -> list[DocumentChunk]:
        raw_chunks = self._basic_split(content.body_text, content)
        total = len(raw_chunks)
        use_contextual = self._use_contextual and llm_client is not None
        concurrency = getattr(settings, "contextual_retrieval_concurrency", 3)
        sem = asyncio.Semaphore(concurrency)

        async def _build(idx: int, chunk_text: str) -> DocumentChunk | None:
            if len(chunk_text.strip()) < settings.chunk_min_size:
                return None
            chunk_id = _make_chunk_id(doc_id, idx, chunk_text)
            meta = ChunkMetadata(
                source=content.metadata.get("source", ""),
                doc_id=doc_id,
                title=content.title,
                author=content.author,
                chunk_index=idx,
                total_chunks=total,
                doc_type=content.doc_type,
            )
            if not settings.chunk_add_metadata_header:
                enriched = chunk_text
            elif use_contextual:
                async with sem:
                    enriched = await contextual_enrichment(
                        chunk_text=chunk_text,
                        full_doc_text=content.body_text,
                        meta=meta,
                        llm_client=llm_client,
                    )
            else:
                enriched = inject_metadata_header(chunk_text, meta)
            return DocumentChunk(
                chunk_id=chunk_id,
                doc_id=doc_id,
                content=chunk_text,
                content_with_header=enriched,
                metadata=meta,
                token_count=count_tokens(chunk_text),
            )

        results = await asyncio.gather(
            *[_build(i, t) for i, t in enumerate(raw_chunks)]
        )
        return [c for c in results if c is not None]

    def _basic_split(self, text: str, content: ExtractedContent) -> list[str]:
        s = self._primary
        lang = getattr(content, "language", "zh")
        if s in ("recursive", "token"):
            return RecursiveTextSplitter(language=lang).split(text)
        elif s == "semantic":
            return semantic_split(text)
        elif s == "sentence":
            return sentence_window_split(text)
        return RecursiveTextSplitter(language=lang).split(text)

    # ── 表格专项处理（供 structure 策略调用）─────────────────────────────────
    def _process_tables(
        self,
        content: ExtractedContent,
        doc_id: str,
        start_idx: int,
    ) -> list[DocumentChunk]:
        """
        表格每行单独成块，块前注入表头作为上下文，防止表格被切断。
        """
        table_chunks: list[DocumentChunk] = []
        idx = start_idx
        for table in content.tables:
            rows: list[list] = table.get("rows", [])
            if not rows:
                continue
            # 第一行作为表头
            header_row = " | ".join(str(c) for c in rows[0])
            for row in rows[1:]:
                row_text = " | ".join(str(c) for c in row)
                if not any(str(c).strip() for c in row):
                    continue
                # 块内容：「[表格行] 表头\n数据行」
                chunk_text = f"[表格行]\n{header_row}\n{row_text}"
                chunk_id = _make_chunk_id(doc_id, idx, chunk_text)
                meta = ChunkMetadata(
                    source=content.metadata.get("source", ""),
                    doc_id=doc_id,
                    title=content.title,
                    chunk_index=idx,
                    total_chunks=-1,
                    doc_type=content.doc_type,
                    node_type="table_row",
                    chunk_level="child",
                )
                table_chunks.append(DocumentChunk(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    content=chunk_text,
                    content_with_header=f"来源：{content.title} | 表格\n\n{chunk_text}",
                    metadata=meta,
                    token_count=count_tokens(chunk_text),
                ))
                idx += 1
        return table_chunks

    # ── Image Chunks（Stage 3 图像分块）────────────────────────────────────────
    async def _chunk_images(
        self,
        images: list,
        content: "ExtractedContent",
        doc_id: str,
        llm_client: object,
        start_index: int = 0,
    ) -> list["DocumentChunk"]:
        """
        Caption each ExtractedImage via LLM and produce DocumentChunk objects.
        D-03: catch (openai.APIError, httpx.HTTPError, anthropic.APIError) only.
        D-04: on failure, append to content.extraction_errors, continue; do not raise.
        """
        if llm_client is None:
            logger.warning(
                f"[Chunker] no llm_client — skipping image captioning: doc_id={doc_id}"
            )
            return []

        chunks: list[DocumentChunk] = []

        for img_offset, img in enumerate(images):
            chunk_index = start_index + img_offset
            image_b64 = base64.b64encode(img.raw_bytes).decode()
            media_type = f"image/{img.ext}" if img.ext != "jpg" else "image/jpeg"

            try:
                caption: str = await llm_client.chat_with_vision(
                    image_b64=image_b64,
                    query="请描述这张图片的内容。",
                    media_type=media_type,
                    system=_IMAGE_CAPTION_SYSTEM,
                )
            except (openai.APIError, httpx.HTTPError, anthropic.APIError) as exc:
                logger.warning(
                    f"[Chunker] image caption failed: doc_id={doc_id} "
                    f"page={img.page_number}",
                    exc_info=exc,
                )
                content.extraction_errors.append(
                    f"Image p{img.page_number} skipped: {type(exc).__name__}"
                )
                continue

            if not caption.strip():
                logger.warning(
                    f"[Chunker] empty caption: doc_id={doc_id} "
                    f"page={img.page_number} — skipping"
                )
                content.extraction_errors.append(
                    f"Image p{img.page_number} skipped: empty caption"
                )
                continue

            chunk_id = _make_chunk_id(doc_id, chunk_index, caption)
            meta = ChunkMetadata(
                source=content.title or doc_id,
                doc_id=doc_id,
                chunk_type="image",
                image_b64=image_b64,
                page_number=img.page_number,
                chunk_index=chunk_index,
                doc_type=content.doc_type,
                language=content.language,
                chunk_level="child",
                node_type="image",
            )
            chunks.append(DocumentChunk(
                chunk_id=chunk_id,
                doc_id=doc_id,
                content=caption,
                content_with_header=caption,
                metadata=meta,
                token_count=len(caption.split()),
            ))

        logger.info(
            f"[Chunker] image chunks produced: doc_id={doc_id} "
            f"total={len(chunks)} skipped={len(images) - len(chunks)}"
        )
        return chunks

    # ── Contextual Enrichment 批量应用 ───────────────────────────────────────
    async def _apply_contextual(
        self,
        chunks: list[DocumentChunk],
        full_doc_text: str,
        llm_client,
    ) -> list[DocumentChunk]:
        concurrency = getattr(settings, "contextual_retrieval_concurrency", 3)
        sem = asyncio.Semaphore(concurrency)

        async def _enrich(chunk: DocumentChunk) -> DocumentChunk:
            async with sem:
                chunk.content_with_header = await contextual_enrichment(
                    chunk_text=chunk.content,
                    full_doc_text=full_doc_text,
                    meta=chunk.metadata,
                    llm_client=llm_client,
                )
            return chunk

        return list(await asyncio.gather(*[_enrich(c) for c in chunks]))


def get_doc_processor() -> DocProcessorService:
    return DocProcessorService()
