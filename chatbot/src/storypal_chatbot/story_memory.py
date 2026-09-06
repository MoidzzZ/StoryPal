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