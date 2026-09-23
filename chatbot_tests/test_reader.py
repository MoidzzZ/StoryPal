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
    monkeypatch.setattr(reader, "PipelineStoryMemoryBackend", lambda **_: FakeBackend(tmp_path))

    payload = reader.reading_document()

    assert payload["source_version"] == "version-1"
    assert [unit["text"] for unit in payload["units"]] == ["第1段", "第2段"]
    assert "summary" not in payload["units"][0]
    assert payload["locations"][0]["end_order"] == 2


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
