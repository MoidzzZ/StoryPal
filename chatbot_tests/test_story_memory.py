from __future__ import annotations

import json
from pathlib import Path

import pytest
from nanobot import RequestContext
from nanobot.agent.tools.context import request_context

from storypal_chatbot.story_memory import (
    PipelineFtsBackend,
    PipelineStoryMemoryBackend,
    StoryMemoryError,
    StoryMemoryService,
    StoryProgressRequired,
)
from storypal_chatbot.tools import GetStoryEvidenceTool, SearchStoryTool, StorySessionStateTool


def evidence(order: int, chapter: str = "第一章", work: str = "demo") -> dict:
    return {
        "work_id": work,
        "unit_id": f"d-{order:04d}",
        "order": order,
        "raw_text": f"原文 {order}",
        "summary": f"摘要 {order}",
        "score": 1.0,
        "metadata": {"chapter": chapter, "start_line": order, "end_line": order},
    }


class FakeBackend:
    def __init__(self, hits: list[dict], units: list[dict] | None = None) -> None:
        self.hits = hits
        self.units = {item["unit_id"]: item for item in (units or hits)}
        self.calls: list[dict] = []
        self.retrieval = "fake"

    def search(self, work_id, query, *, max_order, top_k, filters=None):
        self.calls.append({"work_id": work_id, "query": query, "max_order": max_order, "top_k": top_k, "filters": filters})
        return list(self.hits)

    def get_unit(self, work_id, unit_id):
        return self.units.get(unit_id)


def request(session: str = "webui:story", sender: str = "user-1") -> RequestContext:
    return RequestContext(channel="websocket", chat_id="story", session_key=session, sender_id=sender)


def test_search_returns_three_anchors_and_only_rank_4_5_neighbors():
    backend = FakeBackend([
        evidence(10, "第一章"), evidence(20, "第一章"), evidence(30, "第二章"),
        evidence(11, "第一章"), evidence(29, "第二章"), evidence(12, "第一章"),
    ])
    result = StoryMemoryService(backend).search(work_id="demo", query="为什么", max_seen_order=30)

    assert [item["order"] for item in result.anchors] == [10, 20, 30]
    assert [item["order"] for item in result.adjacent_context] == [11, 29]
    assert backend.calls == [{"work_id": "demo", "query": "为什么", "max_order": 30, "top_k": 5, "filters": None}]
    assert result.retrieval == "fake"


def test_search_never_includes_spoilers_or_cross_chapter_neighbors():
    backend = FakeBackend([
        evidence(41), evidence(10, "第一章"), evidence(20, "第一章"),
        evidence(30, "第二章"), evidence(11, "第二章"), evidence(29, "第一章"),
    ])
    result = StoryMemoryService(backend).search(work_id="demo", query="事件", max_seen_order=40)

    assert all(item["order"] <= 40 for item in result.anchors + result.adjacent_context)
    assert result.adjacent_context == []


def test_search_requires_a_progress_boundary():
    service = StoryMemoryService(FakeBackend([]))
    with pytest.raises(StoryProgressRequired, match="防剧透边界"):
        service.search(work_id="demo", query="发生了什么", max_seen_order=None)


def test_direct_evidence_read_is_filtered_by_progress_and_work():
    backend = FakeBackend([], [evidence(9), evidence(10), evidence(11)])
    service = StoryMemoryService(backend)

    assert service.get_evidence(work_id="demo", unit_id="d-0009", max_seen_order=10)["order"] == 9
    with pytest.raises(StoryMemoryError, match="防剧透边界"):
        service.get_evidence(work_id="demo", unit_id="d-0011", max_seen_order=10)


@pytest.mark.asyncio
async def test_native_story_tools_use_session_state_without_advancing_it(tmp_path):
    backend = FakeBackend([evidence(4), evidence(8), evidence(12), evidence(5), evidence(9)], [evidence(4), evidence(8), evidence(12), evidence(5), evidence(9), evidence(13)])
    service = StoryMemoryService(backend)
    state_tool = StorySessionStateTool(tmp_path)
    search_tool = SearchStoryTool(tmp_path, service=service)
    evidence_tool = GetStoryEvidenceTool(tmp_path, service=service)

    with request_context(request()):
        await state_tool.execute(action="set", active_work="demo", max_seen_order=12)
        response = json.loads(await search_tool.execute(query="发动机"))
        assert [item["order"] for item in response["anchors"]] == [4, 8, 12]
        assert [item["order"] for item in response["adjacent_context"]] == [5, 9]
        assert json.loads(await state_tool.execute(action="get"))["max_seen_order"] == 12
        blocked = await evidence_tool.execute(unit_id="d-0013")
        assert blocked.is_error


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "story_mem" / "code").is_dir(),
    reason="本地管线数据按约定不纳入版本控制",
)
def test_local_pipeline_fts_returns_provenance_and_respects_progress():
    root = Path(__file__).resolve().parents[1] / "story_mem"
    service = StoryMemoryService(
        PipelineFtsBackend(data_root=root / "data", pipeline_code_path=root / "code")
    )
    result = service.search(
        work_id="wandering_earth", query="为什么人类要建造地球发动机", max_seen_order=20
    )

    assert result.anchors
    assert result.anchors[0]["unit_id"] == "we-0003"
    assert all(item["order"] <= 20 for item in result.anchors + result.adjacent_context)
    assert result.anchors[0]["metadata"]["start_line"] == 11
    assert result.retrieval == "fts"

def test_pipeline_auto_backend_passes_auto_to_frozen_adapter(tmp_path):
    created: list[tuple[Path, str]] = []

    class Adapter:
        def search(self, *_args, **_kwargs):
            return []

        def get_unit(self, *_args, **_kwargs):
            return None

    backend = PipelineStoryMemoryBackend(
        data_root=tmp_path / "data",
        pipeline_code_path=tmp_path / "code",
        adapter_factory=lambda path, retrieval: (created.append((path, retrieval)) or Adapter()),
    )

    assert backend.retrieval == "auto"
    backend.search("demo", "测试", max_order=1, top_k=1)
    assert created == [(tmp_path / "data", "auto")]