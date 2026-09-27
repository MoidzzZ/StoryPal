"""为本地阅读器提供与 StoryMemory 同源的原文单元。"""

from __future__ import annotations

import json
from typing import Any

from .story_memory import PipelineStoryMemoryBackend, StoryMemoryError


def reading_document(
    work_id: str = "wandering_earth", backend: PipelineStoryMemoryBackend | None = None
) -> dict[str, Any]:
    """读取唯一已配置作品；不接受来自浏览器的任意文件路径。"""
    if work_id != "wandering_earth":
        raise StoryMemoryError("阅读器目前只支持《流浪地球》。")
    backend = backend or PipelineStoryMemoryBackend(retrieval="fts")
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
    normalized = (data_root / work_id / "01_normalized").resolve()
    if not normalized.is_relative_to(data_root):
        raise StoryMemoryError("阅读器段落数据路径无效。")
    try:
        meta = json.loads((normalized / "meta.json").read_text(encoding="utf-8"))
        lines = (normalized / "text.txt").read_text(encoding="utf-8").splitlines()
        line_numbers = meta["body_line_numbers"]
        if meta.get("work_id", work_id) != work_id or len(lines) != len(line_numbers) or any(
            not isinstance(number, int) for number in line_numbers
        ) or line_numbers != sorted(set(line_numbers)):
            raise ValueError("段落行号无效")
        by_line = dict(zip(line_numbers, lines))
        for unit in units:
            paragraph_lines = [
                number for number in line_numbers
                if unit["start_line"] <= number <= unit["end_line"]
            ]
            if unit["text"].splitlines() != [by_line[number] for number in paragraph_lines]:
                raise ValueError("原文单元与段落映射不一致")
            unit["paragraphs"] = [
                {
                    "text": by_line[number],
                    "line": number,
                    "location_id": f"paragraph:{unit['unit_id']}:{number}",
                    "end_order": unit["order"] if index == len(paragraph_lines) - 1 else unit["order"] - 1,
                }
                for index, number in enumerate(paragraph_lines)
            ]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise StoryMemoryError("阅读器段落位置数据无效。") from exc
    locations = backend.get_reading_locations(work_id)
    return {
        "work_id": work_id,
        "title": "流浪地球",
        "source_version": locations.get("source_version"),
        "locations": locations.get("locations", []),
        "units": units,
    }


def paragraph_locations(
    work_id: str, backend: PipelineStoryMemoryBackend, *,
    source_quote: str | None = None, source_line: int | None = None,
    location_id: str | None = None,
) -> dict[str, Any]:
    """只返回精确匹配的段尾锚点，不向 Agent 枚举未读原文。"""
    document = reading_document(work_id, backend)
    quote = source_quote.strip() if source_quote else None
    if not quote and source_line is None and not location_id:
        raise StoryMemoryError("请提供原文片段、行号或段落位置编号。")
    matches = []
    for unit in document["units"]:
        for paragraph in unit["paragraphs"]:
            if quote and quote not in paragraph["text"]:
                continue
            if source_line is not None and source_line != paragraph["line"]:
                continue
            if location_id and location_id != paragraph["location_id"]:
                continue
            matches.append({
                "location_id": paragraph["location_id"],
                "label": f"{unit['chapter_name']}第 {paragraph['line']} 行段尾",
                "kind": "paragraph",
                "unit_id": unit["unit_id"],
                "unit_order": unit["order"],
                "line": paragraph["line"],
                "end_order": paragraph["end_order"],
            })
    if len(matches) > 1 and source_line is None and location_id is None:
        return {
            "work_id": work_id,
            "source_version": document["source_version"],
            "locations": [],
            "ambiguous_count": len(matches),
            "message": "这段文字出现在多处，请补充阅读器显示的行号。",
        }
    return {
        "work_id": work_id,
        "source_version": document["source_version"],
        "locations": matches,
    }


def partial_reading_excerpt(work_id: str, position: dict[str, Any]) -> str | None:
    """只给尚未完整读完的当前单元注入段落前缀，绝不注入单元后文。"""
    document = reading_document(work_id)
    if document["source_version"] != position.get("source_version"):
        return None
    for unit in document["units"]:
        if unit["unit_id"] != position.get("unit_id"):
            continue
        selected = [
            paragraph["text"] for paragraph in unit["paragraphs"]
            if paragraph["line"] <= position.get("line", -1)
        ]
        if not selected or unit["paragraphs"][-1]["line"] <= position["line"]:
            return None
        return "\n".join(selected)[-1200:]
    return None
