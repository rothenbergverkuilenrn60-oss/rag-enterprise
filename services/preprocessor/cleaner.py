# =============================================================================
# services/preprocessor/cleaner.py
# STAGE 1 — 预处理
# 职责：原始文本清洗 → 去重 → 语言检测 → 质量过滤
# =============================================================================
from __future__ import annotations
import hashlib
import re
import unicodedata
from pathlib import Path
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_random_exponential

from config.settings import settings
from utils.models import RawDocument, PreprocessResult, DocType
from utils.logger import log_latency

# ── 已见文档 checksum 集合（生产环境替换为 Redis SET） ─────────────────────
# 模块级别的集合，存储已处理文档的 SHA256 指纹。set 查找是 O(1)。注：进程重启后失效，生产应换 Redis SET
_seen_checksums: set[str] = set()


# ══════════════════════════════════════════════════════════════════════════════
# 文本清洗函数
# ══════════════════════════════════════════════════════════════════════════════
def _remove_html_tags(text: str) -> str:
    """去除 HTML/XML 标签，保留文本内容。"""
    # [^>] 匹配“不是 > 的任意字符，+ 的意思是前面的东西至少出现一次
    # [^>]+，匹配多个不是 > 的字符
    # 匹配：一个 < 开头，中间是任意不是 > 的字符，最后以 > 结尾
    return re.sub(r"<[^>]+>", " ", text)


def _normalize_whitespace(text: str) -> str:
    """合并多余空白符，统一换行。"""
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_unicode(text: str) -> str:
    """NFC 归一化，解决编码不一致问题。"""
    # # NFC 规范化：把「é」这种由多个字符组合的形式统一为单一字符，解决编码不一致
    return unicodedata.normalize("NFC", text)  


def _remove_control_characters(text: str) -> str:
    """移除不可打印控制字符（保留 \n \t）。"""
    # 这些十六进制范围是 ASCII 控制字符（如 NULL、退格等），保留 \n（0x0a）和 \t（0x09）
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)


def _remove_boilerplate(text: str) -> str:
    """移除常见模板文字（页眉/页脚/版权行）。"""
    patterns = [
        r"(?i)all rights reserved.*",
        r"(?i)confidential.*?do not distribute.*",
        r"第\s*\d+\s*页\s*/\s*共\s*\d+\s*页",
        r"Page\s+\d+\s+of\s+\d+",
    ]
    for p in patterns:
        text = re.sub(p, "", text)
    return text


def clean_text(text: str, config: dict | None = None) -> str:   # cfg: 配置字典，用于控制清洗流程
    """
    完整清洗流水线：
    HTML去标签 → 控制字符 → Unicode归一 → 模板文字 → 空白规范化
    """
    cfg = config or {}
    if cfg.get("clean_html", settings.preprocess_clean_html):
        text = _remove_html_tags(text)
    text = _remove_control_characters(text)
    text = _normalize_unicode(text)
    if cfg.get("remove_boilerplate", settings.preprocess_remove_headers):
        text = _remove_boilerplate(text)    # 移除常见模板文字（页眉/页脚/版权行）
    text = _normalize_whitespace(text)
    return text


# ══════════════════════════════════════════════════════════════════════════════
# 语言检测
# ══════════════════════════════════════════════════════════════════════════════
def detect_language(text: str) -> str:
    """
    轻量级语言检测（langdetect）。
    失败时回退到 'unknown'，不阻塞流水线。
    """
    sample = text[:500]
    try:
        from langdetect import detect
        lang = detect(sample)
        return lang
    except Exception:
        # 简单规则回退：含中文字符则判定为中文
        if re.search(r"[\u4e00-\u9fff]", sample):
            return "zh"
        return "unknown"


# ══════════════════════════════════════════════════════════════════════════════
# 去重
# ══════════════════════════════════════════════════════════════════════════════
def compute_checksum(text: str) -> str:
    # 计算文本的 SHA256 哈希值作为唯一指纹
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_duplicate(checksum: str) -> bool:
    # 检查 checksum 是否在已见集合中，O(1) 查找
    return checksum in _seen_checksums


def register_checksum(checksum: str) -> None:
    # 把新文档指纹加入集合，防止重复处理
    _seen_checksums.add(checksum)


# ══════════════════════════════════════════════════════════════════════════════
# 质量过滤
# ══════════════════════════════════════════════════════════════════════════════
def quality_check(text: str) -> list[str]:
    """返回质量警告列表；空列表表示通过。"""
    warnings: list[str] = []    # 返回警告列表，空列表表示通过。用列表而不是 bool，方便收集多个问题
    char_count = len(text)
    if char_count < settings.preprocess_min_chars:
        warnings.append(f"Text too short: {char_count} chars < {settings.preprocess_min_chars}")
    if char_count > settings.preprocess_max_chars:
        warnings.append(
            f"Text very long: {char_count} chars > {settings.preprocess_max_chars}, "
            "consider streaming processing"
        )
    # 乱码检测：连续高频非常见字符
    if len(re.findall(r"[^\x00-\x7f\u4e00-\u9fff\u3040-\u30ff]", text)) / max(char_count, 1) > 0.3:
        warnings.append("High ratio of non-standard characters — possible garbled text")
    return warnings


# ══════════════════════════════════════════════════════════════════════════════
# Preprocessor Service
# ══════════════════════════════════════════════════════════════════════════════
class PreprocessorService:
    """
    STAGE 1 入口：接收 RawDocument，输出 PreprocessResult。
    """

    @log_latency    # 装饰器：自动记录这个方法的执行时间到日志
    async def process(self, doc: RawDocument) -> PreprocessResult:
        logger.info(f"[Preprocess] START raw_id={doc.raw_id} type={doc.doc_type}")

        # 读取原始文本（此阶段不解析格式，仅处理 plain text 输入或已提取文本）
        raw_text = await self._read_raw_text(doc)   #（只有 txt/md 类型在这里读，PDF/Word 由 Extractor 处理）

        # 1. 清洗
        cleaned = clean_text(raw_text)

        # 2. 去重
        checksum = compute_checksum(cleaned)
        if settings.preprocess_deduplicate and is_duplicate(checksum):
            logger.warning(f"[Preprocess] DUPLICATE raw_id={doc.raw_id}")
            return PreprocessResult(
                raw_id=doc.raw_id,
                cleaned_text="",
                is_duplicate=True,      # 流水线看到这个标记会跳过后续处理
                duplicate_of=checksum,
            )
        register_checksum(checksum)

        # 3. 语言检测
        lang = detect_language(cleaned) if settings.preprocess_language_detect else "zh"

        # 4. 质量检查
        warnings = quality_check(cleaned)
        if any("too short" in w for w in warnings):
            logger.warning(f"[Preprocess] Quality issue raw_id={doc.raw_id}: {warnings}")

        result = PreprocessResult(
            raw_id=doc.raw_id,
            cleaned_text=cleaned,
            language=lang,
            warnings=warnings,
        )
        logger.info(
            f"[Preprocess] DONE raw_id={doc.raw_id} "
            f"chars={result.char_count} lang={lang}"
        )
        return result

    async def _read_raw_text(self, doc: RawDocument) -> str:
        """
        对于纯文本类型直接读取；
        其他类型在 STAGE 2 Extractor 处理，此处返回空占位。
        """
        path = Path(doc.file_path)
        if doc.doc_type in (DocType.TXT, DocType.MD):
            if path.exists():
                return path.read_text(encoding="utf-8", errors="ignore")
        # 非文本类型：返回空，由 Extractor 负责
        return ""


def get_preprocessor() -> PreprocessorService:
    return PreprocessorService()
