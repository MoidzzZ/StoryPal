"""为本地阅读器提供与 StoryMemory 同源的原文单元。"""

from __future__ import annotations

import json
from typing import Any

from .story_memory import PipelineStoryMemoryBackend, StoryMemoryError


def reading_document(work_id: str = "wandering_earth") -> dict[str, Any]:
    """读取唯一已配置作品；不接受来自浏览器的任意文件路径。"""
    if work_id != "wandering_earth":
        raise StoryMemoryError("阅读器目前只支持《流浪地球》。")
    backend = PipelineStoryMemoryBackend(retrieval="fts")
    source = (backend.data_root / work_id / "02_segmented" / "units.jsonl").resolve()
    data_root = backend.data_root.resolve()
    if not source.is_relative_to(data_root) or not source.is_file():
        raise StoryMemoryError("阅读器原文尚未准备好。")

    units: list[dict[str, Any]] = []
    try:
        with source.open("r", encoding="utf-8") as stream:
            for raw in stream:
                if not raw.strip():
                    continue
                item = json.loads(raw)
                if item.get("work_id") != work_id:
                    raise StoryMemoryError("阅读器数据与作品不匹配。")
                units.append({
                    "unit_id": str(item["unit_id"]),
                    "order": int(item["order"]),
                    "chapter_name": str(item["chapter_name"]),
                    "start_line": int(item["start_line"]),
                    "end_line": int(item["end_line"]),
                    "text": str(item["text"]),
                })
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise StoryMemoryError("阅读器原文读取失败。") from exc
    if not units or [unit["order"] for unit in units] != list(range(1, len(units) + 1)):
        raise StoryMemoryError("阅读器原文单元顺序无效。")
    locations = backend.get_reading_locations(work_id)
    return {
        "work_id": work_id,
        "title": "流浪地球",
        "source_version": locations.get("source_version"),
        "locations": locations.get("locations", []),
        "units": units,
    }
