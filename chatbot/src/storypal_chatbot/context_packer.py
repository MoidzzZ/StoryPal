"""将已排序故事证据组织为防剧透、可解释的 Agent 上下文包。"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any


DROP_SPOILER = "spoiler_boundary"
DROP_DUPLICATE = "duplicate"
DROP_LOWER_RELEVANCE = "lower_relevance"
DROP_NOT_ADJACENT = "not_adjacent"
DROP_TOKEN_BUDGET = "token_budget"


@dataclass(frozen=True)
class ContextPackResult:
    anchors: list[dict[str, Any]]
    adjacent_context: list[dict[str, Any]]
    dropped: list[dict[str, Any]]
    token_estimate: int
    source_anchors: list[dict[str, Any]]

    def diagnostics(self) -> dict[str, Any]:
        return {
            "selected": self.source_anchors,
            "dropped": self.dropped,
            "token_estimate": self.token_estimate,
        }


class ContextPacker:
    """纯函数式证据选择器；不调用模型、不读取存储，也不改变阅读进度。"""

    def __init__(
        self,
        *,
        token_budget: int = 2400,
        primary_limit: int = 3,
        adjacent_limit: int = 1,
        chars_per_token: float = 1.6,
    ) -> None:
        if token_budget <= 0 or primary_limit <= 0 or adjacent_limit < 0 or chars_per_token <= 0:
            raise ValueError("ContextPacker 参数必须为正数。")
        self.token_budget = token_budget
        self.primary_limit = primary_limit
        self.adjacent_limit = adjacent_limit
        self.chars_per_token = chars_per_token

    def _estimate_tokens(self, evidence: dict[str, Any]) -> int:
        content = f"{evidence.get('summary', '')}\n{evidence.get('raw_text', '')}".strip()
        return max(1, math.ceil(len(content) / self.chars_per_token))

    @staticmethod
    def _chapter(evidence: dict[str, Any]) -> str:
        return str(evidence.get("metadata", {}).get("chapter", ""))

    @staticmethod
    def _content_key(evidence: dict[str, Any]) -> str:
        content = f"{evidence.get('summary', '')}\n{evidence.get('raw_text', '')}"
        return re.sub(r"\s+", "", content)

    @staticmethod
    def _drop(item: dict[str, Any], reason: str) -> dict[str, Any]:
        return {
            "unit_id": str(item.get("unit_id", "")),
            "order": item.get("order"),
            "reason": reason,
        }

    def _source_anchor(self, evidence: dict[str, Any], *, role: str, tokens: int) -> dict[str, Any]:
        metadata = evidence.get("metadata", {})
        return {
            "work_id": str(evidence.get("work_id", "")),
            "unit_id": str(evidence.get("unit_id", "")),
            "order": int(evidence["order"]),
            "chapter": self._chapter(evidence),
            "line_range": [metadata.get("start_line"), metadata.get("end_line")],
            "role": role,
            "estimated_tokens": tokens,
        }

    def pack(
        self,
        candidates: list[dict[str, Any]],
        *,
        work_id: str,
        max_seen_order: int,
    ) -> ContextPackResult:
        """按硬安全过滤、去重、主证据和有限邻接扩展组织上下文。"""
        dropped: list[dict[str, Any]] = []
        safe: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_content: set[str] = set()
        for item in candidates:
            if not isinstance(item, dict):
                continue
            try:
                order = int(item["order"])
                unit_id = str(item["unit_id"])
            except (KeyError, TypeError, ValueError):
                dropped.append(self._drop(item, DROP_DUPLICATE))
                continue
            if item.get("work_id") != work_id or order > max_seen_order:
                dropped.append(self._drop(item, DROP_SPOILER))
                continue
            content_key = self._content_key(item)
            if unit_id in seen_ids or (content_key and content_key in seen_content):
                dropped.append(self._drop(item, DROP_DUPLICATE))
                continue
            seen_ids.add(unit_id)
            if content_key:
                seen_content.add(content_key)
            safe.append(dict(item))

        anchors: list[dict[str, Any]] = []
        adjacent: list[dict[str, Any]] = []
        source_anchors: list[dict[str, Any]] = []
        used_tokens = 0
        primary_candidates = safe[: self.primary_limit]
        for item in primary_candidates:
            tokens = self._estimate_tokens(item)
            if used_tokens + tokens > self.token_budget:
                dropped.append(self._drop(item, DROP_TOKEN_BUDGET))
                continue
            anchors.append(item)
            used_tokens += tokens
            source_anchors.append(self._source_anchor(item, role="anchor", tokens=tokens))

        anchor_positions = {(int(item["order"]), self._chapter(item)) for item in anchors}
        for item in safe[self.primary_limit :]:
            order = int(item["order"])
            chapter = self._chapter(item)
            is_adjacent = any(
                chapter == anchor_chapter and abs(order - anchor_order) == 1
                for anchor_order, anchor_chapter in anchor_positions
            )
            if not is_adjacent:
                reason = DROP_LOWER_RELEVANCE if len(anchors) < self.primary_limit else DROP_NOT_ADJACENT
                dropped.append(self._drop(item, reason))
                continue
            if len(adjacent) >= self.adjacent_limit:
                dropped.append(self._drop(item, DROP_LOWER_RELEVANCE))
                continue
            tokens = self._estimate_tokens(item)
            if used_tokens + tokens > self.token_budget:
                dropped.append(self._drop(item, DROP_TOKEN_BUDGET))
                continue
            adjacent.append(item)
            used_tokens += tokens
            source_anchors.append(self._source_anchor(item, role="adjacent", tokens=tokens))

        return ContextPackResult(
            anchors=anchors,
            adjacent_context=adjacent,
            dropped=dropped,
            token_estimate=used_tokens,
            source_anchors=source_anchors,
        )