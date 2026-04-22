# =============================================================================
# services/preprocessor/pii_detector.py
# PII 检测与脱敏：GDPR / 数据安全法 / 个人信息保护法 合规
#
# 支持检测：中国身份证 / 手机号 / 银行卡（Luhn验证）/ 邮箱 / IPv4 / 统一社会信用代码
# 脱敏策略：替换中间位为 *，保留足够信息供人工核查
#
# 生产升级路径：替换为 Microsoft Presidio（pip install presidio-analyzer presidio-anonymizer）
#   analyzer = AnalyzerEngine()  # 支持 50+ PII 类型，含中文
#   anonymizer = AnonymizerEngine()
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class PIIFinding:
    """单条 PII 发现记录。"""
    pii_type: str       # id_card | phone | bank_card | email | ip_address | credit_code
    original: str       # 原始文本（仅记录在审计日志，不写入正文）
    masked: str         # 脱敏后文本（替换原文写入正文）
    start: int = 0
    end: int = 0
    confidence: float = 1.0


# SEC-03: map internal type names → additional Presidio-compatible aliases
_PII_TYPE_ALIASES: dict[str, list[str]] = {
    "bank_card": ["CREDIT_CARD", "US_BANK_NUMBER"],
}


@dataclass
class PIIDetectionResult:
    """一次 PII 检测的完整结果。"""
    original_text: str
    masked_text: str
    findings: list[PIIFinding] = field(default_factory=list)
    has_pii: bool = False
    pii_types: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.has_pii = len(self.findings) > 0
        seen: set[str] = set()
        expanded: list[str] = []
        for f in self.findings:
            t = f.pii_type
            if t not in seen:
                expanded.append(t)
                seen.add(t)
            for alias in _PII_TYPE_ALIASES.get(t, []):
                if alias not in seen:
                    expanded.append(alias)
                    seen.add(alias)
        self.pii_types = expanded


class PIIDetector:
    """
    基于正则表达式的轻量级 PII 检测器（无外部依赖）。

    检测规则：
      1. 中国身份证号（18位，含简单格式校验）
      2. 手机号（1开头11位大陆手机号）
      3. 银行卡号（13-19位，Luhn算法验证减少误判）
      4. 电子邮件地址
      5. IPv4 地址
      6. 统一社会信用代码（18位企业标识）

    脱敏格式：
      身份证：保留前6后4，中间8位 → ****
      手机号：保留前3后4，中间4位 → ****
      银行卡：保留后4位，前面全 → **** **** ****
      邮箱：  保留首字符+域名，用户名中间 → ***
      IP：   保留前三段，最后段 → ***
      信用代码：保留前4后4，中间 → **********
    """

    # ── 正则模式（按误判率从低到高排序，先检测精度高的）────────────────────────

    # 18位身份证：6位地区码 + 8位生日 + 3位顺序码 + 1位校验码（数字或X）
    _ID_CARD = re.compile(
        r"\b([1-9]\d{5})"           # 地区码
        r"(19|20)\d{2}"             # 年份
        r"(0[1-9]|1[0-2])"         # 月份
        r"(0[1-9]|[12]\d|3[01])"   # 日期
        r"\d{3}[\dXx]\b"           # 顺序码+校验码
    )
    # 大陆手机号：1[3-9]开头，11位
    _PHONE = re.compile(r"\b(1[3-9]\d{9})\b")
    # 银行卡：13-19位数字（Luhn验证减少误判）
    _BANK_CARD = re.compile(r"\b([3-6]\d{12,18})\b")
    # 邮箱
    _EMAIL = re.compile(
        r"\b([a-zA-Z0-9._%+\-]+)@([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b"
    )
    # IPv4
    _IP_V4 = re.compile(
        r"\b(\d{1,3}\.\d{1,3}\.\d{1,3})\.\d{1,3}\b"
    )
    # 统一社会信用代码：2位登记机关+6位行政区划+9位主体标识+1位校验码
    _CREDIT_CODE = re.compile(
        r"\b([0-9A-HJ-NP-RT-Y]{2}\d{6}[0-9A-HJ-NP-RT-Y]{10})\b"
    )
    # US Social Security Number: SEC-03 — dashed format NNN-NN-NNNN
    _US_SSN = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")

    def detect(self, text: str) -> PIIDetectionResult:
        """
        检测文本中的 PII，返回脱敏后文本和所有发现。

        注意：findings 中的 original 字段包含原始 PII 数据，
        应只写入审计日志，不返回给调用方。
        """
        findings: list[PIIFinding] = []

        # ── 身份证号 ─────────────────────────────────────────────────────────
        for m in self._ID_CARD.finditer(text):
            val = m.group(0)
            masked_val = val[:6] + "********" + val[-4:]
            findings.append(PIIFinding(
                pii_type="id_card",
                original=val,
                masked=masked_val,
                start=m.start(),
                end=m.end(),
            ))

        # ── 手机号 ───────────────────────────────────────────────────────────
        for m in self._PHONE.finditer(text):
            val = m.group(0)
            masked_val = val[:3] + "****" + val[-4:]
            findings.append(PIIFinding(
                pii_type="phone",
                original=val,
                masked=masked_val,
                start=m.start(),
                end=m.end(),
            ))

        # ── 银行卡号（Luhn验证）──────────────────────────────────────────────
        for m in self._BANK_CARD.finditer(text):
            val = m.group(0)
            if len(val) >= 13 and self._luhn_check(val):
                masked_val = "*" * (len(val) - 4) + val[-4:]
                findings.append(PIIFinding(
                    pii_type="bank_card",
                    original=val,
                    masked=masked_val,
                    start=m.start(),
                    end=m.end(),
                ))

        # ── 邮箱 ─────────────────────────────────────────────────────────────
        for m in self._EMAIL.finditer(text):
            user_part, domain = m.group(1), m.group(2)
            masked_user = user_part[0] + "***" if len(user_part) > 1 else "***"
            masked_val = f"{masked_user}@{domain}"
            findings.append(PIIFinding(
                pii_type="email",
                original=m.group(0),
                masked=masked_val,
                start=m.start(),
                end=m.end(),
            ))

        # ── IPv4 地址 ────────────────────────────────────────────────────────
        for m in self._IP_V4.finditer(text):
            val = m.group(0)
            masked_val = m.group(1) + ".***"
            findings.append(PIIFinding(
                pii_type="ip_address",
                original=val,
                masked=masked_val,
                start=m.start(),
                end=m.end(),
            ))

        # ── US Social Security Number ────────────────────────────────────────
        for m in self._US_SSN.finditer(text):
            val = m.group(0)
            masked_val = "***-**-" + m.group(3)
            findings.append(PIIFinding(
                pii_type="US_SSN",
                original=val,
                masked=masked_val,
                start=m.start(),
                end=m.end(),
            ))

        # ── 统一社会信用代码 ─────────────────────────────────────────────────
        for m in self._CREDIT_CODE.finditer(text):
            val = m.group(0)
            masked_val = val[:4] + "**********" + val[-4:]
            findings.append(PIIFinding(
                pii_type="credit_code",
                original=val,
                masked=masked_val,
                start=m.start(),
                end=m.end(),
            ))

        # ── 应用脱敏（倒序替换，避免偏移错乱）──────────────────────────────────
        masked_text = text
        if findings:
            # 按 start 位置倒序，从后往前替换
            for finding in sorted(findings, key=lambda f: f.start, reverse=True):
                masked_text = (
                    masked_text[:finding.start]
                    + finding.masked
                    + masked_text[finding.end:]
                )

        result = PIIDetectionResult(
            original_text=text,
            masked_text=masked_text,
            findings=findings,
        )

        if result.has_pii:
            logger.info(
                f"[PII] Detected {len(findings)} item(s): "
                f"types={result.pii_types}"
            )

        return result

    @staticmethod
    def _luhn_check(card_number: str) -> bool:
        """
        Luhn 算法验证银行卡号有效性，大幅减少纯数字串的误报。
        """
        digits = [int(d) for d in card_number if d.isdigit()]
        if len(digits) < 13:
            return False
        total = 0
        for i, digit in enumerate(reversed(digits)):
            if i % 2 == 1:
                digit *= 2
                if digit > 9:
                    digit -= 9
            total += digit
        return total % 10 == 0


_pii_detector: PIIDetector | None = None


def get_pii_detector() -> PIIDetector:
    global _pii_detector
    if _pii_detector is None:
        _pii_detector = PIIDetector()
    return _pii_detector
