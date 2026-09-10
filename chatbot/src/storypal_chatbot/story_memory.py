"""StoryPal 自有的故事记忆契约与协作方检索适配器。"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class StoryMemoryError(RuntimeError):
    """StoryPal 故事检索的基础错误。"""


class StoryProgressRequired(StoryMemoryError):
    """搜索缺少防剧透边界时抛出。"""


class StoryMemoryBackend(Protocol):
    def search(
        self,
        work_id: str,
        query: str,
        *,
        max_order: int,
        top_k: int,
        filters: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_unit(self, work_id: str, unit_id: str) -> dict[str, Any] | None: ...

    def get_reading_locations(self, work_id: str) -> dict[str, Any]: ...

    def get_recap(
        self, work_id: str, *, max_order: int, recent_limit: int = 5
    ) -> dict[str, Any]: ...

    def get_entity_context(
        self, work_id: str, name: str, *, max_order: int
    ) -> dict[str, Any]: ...

    def get_plotline_context(
        self, work_id: str, title: str, *, max_order: int
    ) -> dict[str, Any]: ...


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


class PipelineStoryMemoryBackend:
    """仅通过冻结的适配器接口使用协作方管线。

    ``auto`` 优先使用本地向量索引；向量模型、LanceDB 或索引不可用时，
    协作方适配器会自动退回 SQLite FTS5，最后才扫描事实源。
    """

    def __init__(
        self,
        *,
        data_root: Path | None = None,
        pipeline_code_path: Path | None = None,
        retrieval: str | None = None,
        adapter_factory: Any | None = None,
    ) -> None:
        selected_retrieval = retrieval or os.environ.get("STORYPAL_STORY_RETRIEVAL", "auto")
        if selected_retrieval not in {"auto", "vector", "fts"}:
            raise StoryMemoryError("STORYPAL_STORY_RETRIEVAL 只能是 auto、vector 或 fts。")
        story_root = Path(os.environ.get("STORYPAL_STORY_ROOT", _project_root() / "story_mem"))
        self.data_root = Path(data_root or os.environ.get("STORYPAL_STORY_DATA_ROOT", story_root / "data"))
        self.pipeline_code_path = Path(
            pipeline_code_path or os.environ.get("STORYPAL_PIPELINE_CODE_PATH", story_root / "code")
        )
        self.retrieval = selected_retrieval
        self._adapter_factory = adapter_factory
        self._adapter: Any | None = None

    def _get_adapter(self) -> Any:
        if self._adapter is not None:
            return self._adapter
        if self._adapter_factory is not None:
            self._adapter = self._adapter_factory(self.data_root, self.retrieval)
            return self._adapter
        if not self.pipeline_code_path.is_dir():
            raise StoryMemoryError(
                f"故事处理管线代码不可用：{self.pipeline_code_path}. "
                "请配置 STORYPAL_PIPELINE_CODE_PATH。"
            )
        code_path = str(self.pipeline_code_path)
        if code_path not in sys.path:
            sys.path.insert(0, code_path)
        try:
            from storymemory.adapter import StoryMemory
        except ImportError as exc:
            raise StoryMemoryError("无法导入故事处理管线适配器。") from exc
        self._adapter = StoryMemory(data_root=self.data_root, retrieval=self.retrieval)
        return self._adapter

    def search(
        self,
        work_id: str,
        query: str,
        *,
        max_order: int,
        top_k: int,
        filters: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        return self._get_adapter().search(
            work_id, query, max_order=max_order, top_k=top_k, filters=filters
        )

    def get_unit(self, work_id: str, unit_id: str) -> dict[str, Any] | None:
        return self._get_adapter().get_unit(work_id, unit_id)

    def get_reading_locations(self, work_id: str) -> dict[str, Any]:
        return self._get_adapter().get_reading_locations(work_id)

    def get_recap(
        self, work_id: str, *, max_order: int, recent_limit: int = 5
    ) -> dict[str, Any]:
        return self._get_adapter().get_recap(
            work_id, max_order=max_order, recent_limit=recent_limit
        )

    def get_entity_context(
        self, work_id: str, name: str, *, max_order: int
    ) -> dict[str, Any]:
        return self._get_adapter().get_entity_context(work_id, name, max_order=max_order)

    def get_plotline_context(
        self, work_id: str, title: str, *, max_order: int
    ) -> dict[str, Any]:
        return self._get_adapter().get_plotline_context(work_id, title, max_order=max_order)


class PipelineFtsBackend(PipelineStoryMemoryBackend):
    """兼容旧调用方的显式 FTS 后端。新运行时请使用自动策略后端。"""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("retrieval", "fts")
        super().__init__(**kwargs)


@dataclass(frozen=True)
class StorySearchResult:
    work_id: str
    max_seen_order: int
    retrieval: str
    anchors: list[dict[str, Any]]
    adjacent_context: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_id": self.work_id,
            "retrieval": self.retrieval,
            "max_seen_order": self.max_seen_order,
            "anchors": self.anchors,
            "adjacent_context": self.adjacent_context,
        }


class StoryMemoryService:
    """在任意后端之上执行 StoryPal 的安全与证据包规则。"""

    def __init__(self, backend: StoryMemoryBackend) -> None:
        self.backend = backend

    @staticmethod
    def _safe_evidence(
        evidence: dict[str, Any], work_id: str, max_seen_order: int
    ) -> dict[str, Any] | None:
        try:
            order = int(evidence["order"])
        except (KeyError, TypeError, ValueError):
            return None
        if evidence.get("work_id") != work_id or order > max_seen_order:
            return None
        return dict(evidence)

    def search(
        self,
        *,
        work_id: str | None,
        query: str,
        max_seen_order: int | None,
        chapter: str | None = None,
    ) -> StorySearchResult:
        if not work_id:
            raise StoryProgressRequired("检索故事证据前请先设置当前作品。")
        if max_seen_order is None:
            raise StoryProgressRequired(
                "检索前请先设置 max_seen_order；StoryPal 不会在缺少防剧透边界时检索。"
            )
        if not query or not query.strip():
            raise StoryMemoryError("故事检索词不能为空。")
        filters = {"chapter": chapter.strip()} if chapter and chapter.strip() else None
        raw_hits = self.backend.search(
            work_id, query.strip(), max_order=max_seen_order, top_k=5, filters=filters
        )
        hits = [
            safe
            for item in raw_hits
            if (safe := self._safe_evidence(item, work_id, max_seen_order)) is not None
        ]
        anchors = hits[:3]
        anchor_keys = {
            (int(hit["order"]), str(hit.get("metadata", {}).get("chapter", "")))
            for hit in anchors
        }
        adjacent: list[dict[str, Any]] = []
        for candidate in hits[3:5]:
            chapter_name = str(candidate.get("metadata", {}).get("chapter", ""))
            candidate_order = int(candidate["order"])
            if any(
                chapter_name == anchor_chapter and abs(candidate_order - anchor_order) == 1
                for anchor_order, anchor_chapter in anchor_keys
            ):
                adjacent.append(candidate)
        return StorySearchResult(
            work_id=work_id,
            max_seen_order=max_seen_order,
            retrieval=str(getattr(self.backend, "retrieval", "unknown")),
            anchors=anchors,
            adjacent_context=adjacent,
        )

    def reading_locations(self, *, work_id: str | None) -> dict[str, Any]:
        if not work_id:
            raise StoryProgressRequired("请选择作品后再读取阅读位置。")
        raw = self.backend.get_reading_locations(work_id)
        locations = raw.get("locations") if isinstance(raw, dict) else None
        if not isinstance(locations, list):
            raise StoryMemoryError("故事处理管线返回的阅读位置格式无效。")
        safe_locations = []
        for location in locations:
            if not isinstance(location, dict):
                continue
            try:
                end_order = int(location["end_order"])
            except (KeyError, TypeError, ValueError):
                continue
            safe_locations.append({
                "location_id": str(location.get("location_id", "")),
                "label": str(location.get("label", "")),
                "kind": str(location.get("kind", "chapter")),
                "start_order": int(location.get("start_order", 0)),
                "end_order": end_order,
                "unit_count": int(location.get("unit_count", 0)),
            })
        return {"work_id": work_id, "source_version": raw.get("source_version"), "locations": safe_locations}

    def structured_context(
        self,
        *,
        kind: str,
        work_id: str | None,
        max_seen_order: int | None,
        query: str | None = None,
    ) -> dict[str, Any]:
        """取得供回答组织使用的已读结构化线索，不替代原文证据。"""
        if not work_id or max_seen_order is None:
            raise StoryProgressRequired("读取故事状态前请先设置作品和已读范围。")
        if kind == "recap":
            raw = self.backend.get_recap(work_id, max_order=max_seen_order)
        elif kind == "entity":
            if not query or not query.strip():
                raise StoryMemoryError("查询人物或术语状态时必须提供名称。")
            raw = self.backend.get_entity_context(work_id, query.strip(), max_order=max_seen_order)
        elif kind == "plotline":
            if not query or not query.strip():
                raise StoryMemoryError("查询情节线时必须提供名称。")
            raw = self.backend.get_plotline_context(work_id, query.strip(), max_order=max_seen_order)
        else:
            raise StoryMemoryError("结构化故事查询类型无效。")
        if not isinstance(raw, dict):
            raise StoryMemoryError("故事处理管线返回的结构化记忆格式无效。")
        safe = dict(raw)
        safe["work_id"] = work_id
        safe["max_order"] = max_seen_order
        history = safe.get("history")
        if isinstance(history, list):
            safe["history"] = [
                item for item in history
                if isinstance(item, dict) and int(item.get("order", -1)) <= max_seen_order
            ]
        snapshot_order = safe.get("snapshot_order")
        if snapshot_order is not None and int(snapshot_order) > max_seen_order:
            raise StoryMemoryError("结构化记忆越过了当前防剧透边界。")
        return safe

    def get_evidence(
        self, *, work_id: str | None, unit_id: str, max_seen_order: int | None
    ) -> dict[str, Any]:
        if not work_id or max_seen_order is None:
            raise StoryProgressRequired("读取故事证据前请先设置作品和 max_seen_order。")
        evidence = self.backend.get_unit(work_id, unit_id)
        if evidence is None:
            raise StoryMemoryError(f"未找到故事证据：{unit_id}")
        safe = self._safe_evidence(evidence, work_id, max_seen_order)
        if safe is None:
            raise StoryMemoryError("请求的证据位于当前防剧透边界之外。")
        return safe