# =============================================================================
# services/nlu/entity_disambiguator.py
# 实体消歧：解决同名实体（同名人员、同名政策、同名文档）的指代歧义
#
# 消歧策略优先级（由高到低）：
#   1. 上下文线索（部门/职位/时间修饰词）→ 高置信度
#   2. 用户画像（历史频繁关联实体）→ 中置信度
#   3. 租户范围缩小（同 tenant 内限定）→ 低-中置信度
#   4. 降级：返回低置信度，触发澄清提示
#
# 生产升级路径：接 Neo4j 知识图谱，候选集合来自图查询而非规则
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class DisambiguatedEntity:
    """消歧后的实体，包含唯一标识和置信度。"""
    original_text: str
    entity_type: str
    resolved_id: str            # 唯一标识（如 "person::张伟::HR部"，生产中为图数据库 ID）
    resolved_name: str          # 规范化名称
    confidence: float = 1.0
    disambiguation_method: str = "exact"   # exact | context | profile | tenant_scope | fallback
    candidates: list[str] = field(default_factory=list)   # 歧义候选列表（有多个时触发澄清）
    needs_clarification: bool = False


class EntityDisambiguator:
    """
    实体消歧器（规则 + 上下文启发式）。

    当前实现为无外部依赖的轻量版本，消歧逻辑基于：
      - 查询文本中的部门/职位/时间修饰词（上下文线索）
      - 用户历史画像（user_profile.frequent_topics）
      - 租户 ID 缩小候选范围

    注意：confidence < 0.7 时，调用方应考虑触发澄清提示。
    """

    # 消歧线索模式
    _DEPT_PATTERNS = re.compile(
        r"(人事(行政)?部|财务部|技术部|研发部|法务部|销售部|市场部|运营部|产品部|IT部|HR|人力资源)"
    )
    _ROLE_PATTERNS = re.compile(
        r"(总监|经理|主管|专员|助理|VP|CEO|CTO|CFO|总裁|副总|主任|负责人|团队长)"
    )
    _TIME_PATTERNS = re.compile(
        r"(2022|2023|2024|2025|今年|去年|上一版|最新|现行|修订版|最近|当前)"
    )
    _POLICY_VERSION = re.compile(r"[（(]\d{4}[)）]版?|v\d+(\.\d+)?")

    def disambiguate(
        self,
        entity_text: str,
        entity_type: str,
        query_context: str,
        user_profile: dict | None = None,
        tenant_id: str = "",
    ) -> DisambiguatedEntity:
        """
        对单个实体做消歧。

        Args:
            entity_text: 实体原文，如"张伟"
            entity_type: 实体类型，如"person"
            query_context: 完整查询文本（含上下文线索）
            user_profile: 用户画像字典（含 frequent_topics 等）
            tenant_id: 租户 ID（用于范围缩小）

        Returns:
            DisambiguatedEntity，含 resolved_id 和 confidence
        """
        normalized = self._normalize(entity_text, entity_type)

        # 提取上下文消歧线索
        dept_hint = self._extract_dept_hint(query_context)
        role_hint = self._extract_role_hint(query_context)
        time_hint = self._extract_time_hint(query_context)

        resolved_id, method, confidence = self._resolve(
            normalized, entity_type,
            dept_hint, role_hint, time_hint,
            user_profile, tenant_id,
        )

        needs_clarification = confidence < 0.65

        result = DisambiguatedEntity(
            original_text=entity_text,
            entity_type=entity_type,
            resolved_id=resolved_id,
            resolved_name=normalized,
            confidence=confidence,
            disambiguation_method=method,
            needs_clarification=needs_clarification,
        )

        if needs_clarification:
            logger.debug(
                f"[Disambiguate] low confidence: '{entity_text}' "
                f"type={entity_type} conf={confidence:.2f} "
                f"method={method} → clarification recommended"
            )

        return result

    def disambiguate_batch(
        self,
        entities: list,        # list[Entity] from nlu_service
        query_context: str,
        user_profile: dict | None = None,
        tenant_id: str = "",
    ) -> list[DisambiguatedEntity]:
        """
        批量消歧，返回与输入 entities 等长的结果列表。
        """
        return [
            self.disambiguate(
                entity.text,
                entity.entity_type,
                query_context,
                user_profile,
                tenant_id,
            )
            for entity in entities
        ]

    def build_clarification_hint(
        self,
        ambiguous_entities: list[DisambiguatedEntity],
    ) -> str:
        """
        根据低置信度实体，生成澄清提示文本。
        """
        if not ambiguous_entities:
            return ""
        names = "、".join(
            f"「{e.original_text}」({e.entity_type})"
            for e in ambiguous_entities
        )
        return f"您提到的 {names} 存在多个匹配项，请补充更多信息（如所属部门、时间或版本）以精确查找。"

    # ── 内部辅助方法 ─────────────────────────────────────────────────────────

    def _normalize(self, text: str, entity_type: str) -> str:
        """
        实体文本规范化：
          - 数字：中文数字转阿拉伯数字
          - policy：去除年份括号（同一政策不同年份版本分开处理）
        """
        _NUM_MAP = {
            "一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
            "六": "6", "七": "7", "八": "8", "九": "9", "十": "10",
            "百": "100", "千": "1000",
        }
        for cn, num in _NUM_MAP.items():
            text = text.replace(cn, num)

        if entity_type == "policy":
            text = self._POLICY_VERSION.sub("", text).strip()

        return text.strip()

    def _extract_dept_hint(self, context: str) -> str:
        m = self._DEPT_PATTERNS.search(context)
        return m.group(0) if m else ""

    def _extract_role_hint(self, context: str) -> str:
        m = self._ROLE_PATTERNS.search(context)
        return m.group(0) if m else ""

    def _extract_time_hint(self, context: str) -> str:
        m = self._TIME_PATTERNS.search(context)
        return m.group(0) if m else ""

    def _resolve(
        self,
        normalized: str,
        entity_type: str,
        dept_hint: str,
        role_hint: str,
        time_hint: str,
        user_profile: dict | None,
        tenant_id: str,
    ) -> tuple[str, str, float]:
        """
        启发式 resolved_id 生成。
        生产实现：查询知识图谱，此处用规则模拟置信度评估。
        返回 (resolved_id, method, confidence)
        """
        parts = [normalized]
        method = "fallback"
        confidence = 0.60     # 无线索时的基础置信度

        if dept_hint:
            parts.append(dept_hint)
            method = "context"
            confidence = max(confidence, 0.85)

        if role_hint:
            parts.append(role_hint)
            method = "context"
            confidence = max(confidence, 0.88)

        if time_hint:
            parts.append(time_hint)
            # 时间线索单独不足以完全消歧，但能提升置信度
            if method != "context":
                method = "context"
            confidence = max(confidence, 0.78)

        # 用户历史画像：如果用户历史中频繁与某实体关联
        if user_profile and entity_type in ("person", "policy"):
            frequent = user_profile.get("frequent_topics", [])
            for topic in frequent:
                if isinstance(topic, str) and normalized in topic:
                    method = "profile" if method == "fallback" else method
                    confidence = max(confidence, 0.75)
                    break

        # 租户范围缩小：在特定 tenant 内，相同名称实体唯一性更高
        if tenant_id and method == "fallback":
            method = "tenant_scope"
            confidence = max(confidence, 0.68)

        resolved_id = f"{entity_type}::" + "::".join(parts)
        return resolved_id, method, confidence


_disambiguator: EntityDisambiguator | None = None


def get_disambiguator() -> EntityDisambiguator:
    global _disambiguator
    if _disambiguator is None:
        _disambiguator = EntityDisambiguator()


# ══════════════════════════════════════════════════════════════════════════════
# Redis 实体知识库（Entity Lookup，替代 ES entity lookup）
# ══════════════════════════════════════════════════════════════════════════════

class RedisEntityLookup:
    """
    基于 Redis HASH 的实体知识库查询。
    替代 Elasticsearch entity lookup，功能等价，无需额外基础设施。

    键结构：
      entity:kb:{entity_type}   → Hash {normalized_name: json(EntityRecord)}
      entity:alias:{alias}      → string: canonical_name（别名映射）

    EntityRecord 字段：
      id, canonical_name, entity_type, aliases, description,
      tenant_ids (允许访问的租户列表，空=全部), metadata

    使用方式：
      lookup = get_entity_lookup()
      record = await lookup.find("年假", entity_type="policy_term", tenant_id="t1")
    """

    _TTL = 86400  # 缓存 24h

    def __init__(self) -> None:
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            from utils.cache import get_redis
            self._redis = await get_redis()
        return self._redis

    async def find(
        self,
        text: str,
        entity_type: str = "",
        tenant_id: str = "",
    ) -> dict | None:
        """
        在知识库中查找实体。
        先查精确别名映射，再查各类型知识库。
        """
        import json
        r = await self._get_redis()

        # 1. 别名映射（如「HR」→「人力资源部」）
        canonical = await r.get(f"entity:alias:{text}")
        lookup_text = canonical.decode() if canonical else text

        # 2. 指定类型查找
        if entity_type:
            raw = await r.hget(f"entity:kb:{entity_type}", lookup_text)
            if raw:
                record = json.loads(raw)
                if self._tenant_allowed(record, tenant_id):
                    return record

        # 3. 全类型扫描
        for etype in ["policy_term", "department", "person", "product", "process"]:
            raw = await r.hget(f"entity:kb:{etype}", lookup_text)
            if raw:
                record = json.loads(raw)
                if self._tenant_allowed(record, tenant_id):
                    return record

        return None

    @staticmethod
    def _tenant_allowed(record: dict, tenant_id: str) -> bool:
        allowed = record.get("tenant_ids", [])
        return not allowed or not tenant_id or tenant_id in allowed

    async def upsert(
        self,
        entity_type: str,
        canonical_name: str,
        aliases: list[str] | None = None,
        description: str = "",
        tenant_ids: list[str] | None = None,
        metadata: dict | None = None,
    ) -> None:
        """向知识库写入/更新一条实体记录。"""
        import json
        r = await self._get_redis()
        record = {
            "canonical_name": canonical_name,
            "entity_type": entity_type,
            "aliases": aliases or [],
            "description": description,
            "tenant_ids": tenant_ids or [],
            "metadata": metadata or {},
        }
        pipe = r.pipeline()
        pipe.hset(f"entity:kb:{entity_type}", canonical_name, json.dumps(record))
        for alias in (aliases or []):
            pipe.set(f"entity:alias:{alias}", canonical_name)
        await pipe.execute()
        logger.info(f"[EntityLookup] Upserted: {entity_type}::{canonical_name}")

    async def delete(self, entity_type: str, canonical_name: str) -> None:
        r = await self._get_redis()
        await r.hdel(f"entity:kb:{entity_type}", canonical_name)

    async def enrich_entity(
        self,
        text: str,
        entity_type: str,
        tenant_id: str = "",
    ) -> dict:
        """
        用知识库信息增强实体：返回包含 description/canonical_name/metadata 的字典。
        若未找到则返回基础信息（不失败）。
        """
        record = await self.find(text, entity_type, tenant_id)
        if record:
            return {
                "text": text,
                "entity_type": entity_type,
                "canonical_name": record.get("canonical_name", text),
                "description": record.get("description", ""),
                "metadata": record.get("metadata", {}),
                "source": "entity_kb",
            }
        return {"text": text, "entity_type": entity_type, "source": "not_found"}


_entity_lookup: RedisEntityLookup | None = None


def get_entity_lookup() -> RedisEntityLookup:
    global _entity_lookup
    if _entity_lookup is None:
        _entity_lookup = RedisEntityLookup()
    return _entity_lookup
    return _disambiguator
