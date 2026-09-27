"""桌面阅读器只暴露当前作品的原文单元与章节锚点。"""

import json

import pytest

from storypal_chatbot import reader
from storypal_chatbot.story_memory import StoryMemoryError


class FakeBackend:
    def __init__(self, data_root):
        self.data_root = data_root

    def get_reading_locations(self, work_id):
        return {"source_version": "version-1", "locations": [
            {"location_id": "chapter-01", "label": "第一章", "start_order": 1, "end_order": 2},
        ]}


def test_reader_returns_only_text_and_chapter_anchors(tmp_path, monkeypatch):
    source = tmp_path / "wandering_earth" / "02_segmented" / "units.jsonl"
    source.parent.mkdir(parents=True)
    rows = [
        {"work_id": "wandering_earth", "unit_id": f"we-{order:04d}", "order": order,
         "chapter_name": "第一章", "start_line": order * 2, "end_line": order * 2,
         "text": f"第{order}段", "summary": "不应送到阅读器的未来摘要"}
        for order in (1, 2)
    ]
    source.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    normalized = tmp_path / "wandering_earth" / "01_normalized"
    normalized.mkdir()
    (normalized / "meta.json").write_text(json.dumps({"body_line_numbers": [2, 4]}), encoding="utf-8")
    (normalized / "text.txt").write_text("第1段\n第2段\n", encoding="utf-8")
    monkeypatch.setattr(reader, "PipelineStoryMemoryBackend", lambda **_: FakeBackend(tmp_path))

    payload = reader.reading_document()

    assert payload["source_version"] == "version-1"
    assert [unit["text"] for unit in payload["units"]] == ["第1段", "第2段"]
    assert "summary" not in payload["units"][0]
    assert payload["locations"][0]["end_order"] == 2
    assert [unit["paragraphs"][0]["line"] for unit in payload["units"]] == [2, 4]


def test_reader_resolves_exact_paragraph_and_keeps_mid_unit_boundary(tmp_path, monkeypatch):
    source = tmp_path / "wandering_earth" / "02_segmented" / "units.jsonl"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({
        "work_id": "wandering_earth", "unit_id": "we-0001", "order": 1,
        "chapter_name": "第一章", "start_line": 3, "end_line": 7,
        "text": "第一段。\n死亡。\n第三段。",
    }, ensure_ascii=False), encoding="utf-8")
    normalized = tmp_path / "wandering_earth" / "01_normalized"
    normalized.mkdir()
    (normalized / "meta.json").write_text(json.dumps({"body_line_numbers": [3, 5, 7]}), encoding="utf-8")
    (normalized / "text.txt").write_text("第一段。\n死亡。\n第三段。\n", encoding="utf-8")
    backend = FakeBackend(tmp_path)
    monkeypatch.setattr(reader, "PipelineStoryMemoryBackend", lambda **_: backend)

    found = reader.paragraph_locations("wandering_earth", backend, source_quote="死亡。")
    assert found["locations"] == [{
        "location_id": "paragraph:we-0001:5", "label": "第一章第 5 行段尾",
        "kind": "paragraph", "unit_id": "we-0001", "unit_order": 1,
        "line": 5, "end_order": 0,
    }]
    assert reader.partial_reading_excerpt("wandering_earth", {
        "unit_id": "we-0001", "line": 5, "source_version": "version-1",
    }) == "第一段。\n死亡。"
    assert reader.partial_reading_excerpt("wandering_earth", {
        "unit_id": "we-0001", "line": 5, "source_version": "old-version",
    }) is None
    ambiguous = reader.paragraph_locations("wandering_earth", backend, source_quote="段。")
    assert ambiguous["locations"] == []
    assert ambiguous["ambiguous_count"] == 2


def test_reader_rejects_other_work_and_broken_order(tmp_path, monkeypatch):
    with pytest.raises(StoryMemoryError):
        reader.reading_document("other_work")

    source = tmp_path / "wandering_earth" / "02_segmented" / "units.jsonl"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({"work_id": "wandering_earth", "unit_id": "we-0002",
                                  "order": 2, "chapter_name": "第一章", "start_line": 1,
                                  "end_line": 1, "text": "段落"}), encoding="utf-8")
    monkeypatch.setattr(reader, "PipelineStoryMemoryBackend", lambda **_: FakeBackend(tmp_path))
    with pytest.raises(StoryMemoryError):
        reader.reading_document()
