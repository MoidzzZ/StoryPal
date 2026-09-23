from __future__ import annotations

import json
from pathlib import Path

import pytest
from nanobot import RequestContext
from nanobot.agent.tools.context import request_context

from storypal_chatbot.storage import ReadingProgressStore
from storypal_chatbot.story_memory import (
    PipelineFtsBackend,
    PipelineStoryMemoryBackend,
    StoryMemoryError,
    StoryMemoryService,
    StoryProgressRequired,
)
from storypal_chatbot.tools import (GetStoryEvidenceTool, ReadingLocationTool, ResolveReadingLocationTool, SearchStoryTool, SetReadingProgressTool, StoryContextTool, StorySessionStateTool)


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

    def get_reading_locations(self, work_id):
        return {"work_id": work_id, "source_version": "test", "locations": [
            {"location_id": "chapter-01", "label": "第一章", "kind": "chapter", "start_order": 1, "end_order": 12, "unit_count": 12}
        ]}

    def get_recap(self, work_id, *, max_order, recent_limit=5):
        return {"work_id": work_id, "snapshot_order": max_order, "backdrop": "测试背景", "recent": [{"order": max_order, "summary": "已读事件"}]}

    def get_entity_context(self, work_id, name, *, max_order):
        return {"work_id": work_id, "name": name, "snapshot_order": max_order, "history": [{"order": 4, "value": "已读"}, {"order": max_order + 1, "value": "未来"}]}

    def get_plotline_context(self, work_id, title, *, max_order):
        return {"work_id": work_id, "title": title, "snapshot_order": max_order, "history": [{"order": 3, "value": "开始"}]}


def request(session: str = "webui:story", sender: str = "user-1") -> RequestContext:
    return RequestContext(channel="websocket", chat_id="story", session_key=session, sender_id=sender)


def test_search_returns_three_anchors_and_only_rank_4_5_neighbors():
    backend = FakeBackend([
        evidence(10, "第一章"), evidence(20, "第一章"), evidence(30, "第二章"),
        evidence(11, "第一章"), evidence(29, "第二章"), evidence(12, "第一章"),
    ])
    result = StoryMemoryService(backend).search(work_id="demo", query="为什么", max_seen_order=30)

    assert [item["order"] for item in result.anchors] == [10, 20, 30]
    assert [item["order"] for item in result.adjacent_context] == [11]
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
        assert [item["order"] for item in response["adjacent_context"]] == [5]
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
@pytest.mark.asyncio
async def test_reader_can_set_chapter_boundary_and_use_structured_context(tmp_path):
    backend = FakeBackend([evidence(4), evidence(8), evidence(12)])
    service = StoryMemoryService(backend)
    location_tool = ReadingLocationTool(tmp_path, service=service)
    context_tool = StoryContextTool(tmp_path, service=service)

    with request_context(request()):
        locations = json.loads(await location_tool.execute(action="list", work_id="demo"))
        assert locations["locations"][0]["label"] == "第一章"
        selected = json.loads(await location_tool.execute(action="set", work_id="demo", location_id="chapter-01"))
        assert selected["state"]["max_seen_order"] == 12

        recap = json.loads(await context_tool.execute(kind="recap"))
        assert recap["snapshot_order"] == 12
        entity = json.loads(await context_tool.execute(kind="entity", query="测试人物"))
        assert entity["history"] == [{"order": 4, "value": "已读"}]

@pytest.mark.asyncio
async def test_reading_progress_requires_another_user_turn_and_is_session_bound(tmp_path):
    service = StoryMemoryService(FakeBackend([evidence(12)]))
    resolver = ResolveReadingLocationTool(tmp_path, service=service)
    writer = SetReadingProgressTool(tmp_path, service=service)
    progress = ReadingProgressStore(tmp_path)

    first = RequestContext(
        channel="websocket", chat_id="story", session_key="webui:first",
        sender_id="alice", turn_id="turn-1", original_user_text="我大概读到第一章末了",
    )
    with request_context(first):
        locations = json.loads(await resolver.execute(work_id="demo"))
        assert locations["locations"][0]["location_id"] == "chapter-01"
        proposal = json.loads(
            await writer.execute(action="propose", work_id="demo", location_id="chapter-01")
        )
        assert proposal["status"] == "confirmation_required"
        assert progress.get("alice")["max_seen_order"] is None
        same_turn = await writer.execute(action="confirm", pending_id=proposal["pending_id"])
        assert same_turn.is_error

    other_session = RequestContext(
        channel="websocket", chat_id="story", session_key="webui:other",
        sender_id="alice", turn_id="turn-2", original_user_text="对，读完了",
    )
    with request_context(other_session):
        wrong_session = await writer.execute(action="confirm", pending_id=proposal["pending_id"])
        assert wrong_session.is_error

    other_user = RequestContext(
        channel="websocket", chat_id="story", session_key="webui:first",
        sender_id="bob", turn_id="turn-2", original_user_text="对，读完了",
    )
    with request_context(other_user):
        wrong_user = await writer.execute(action="confirm", pending_id=proposal["pending_id"])
        assert wrong_user.is_error

    confirmed_turn = RequestContext(
        channel="websocket", chat_id="story", session_key="webui:first",
        sender_id="alice", turn_id="turn-2", original_user_text="对，我读完第一章了",
    )
    with request_context(confirmed_turn):
        confirmed = json.loads(await writer.execute(action="confirm", pending_id=proposal["pending_id"]))
        assert confirmed["status"] == "confirmed"
        assert confirmed["state"]["max_seen_order"] == 12
        repeated = await writer.execute(action="confirm", pending_id=proposal["pending_id"])
        assert repeated.is_error

    assert progress.get("alice")["max_seen_order"] == 12
    block = await resolver.runtime_context_provider()(confirmed_turn)
    assert block is not None and '"max_seen_order": 12' in block.content
    assert progress.get("bob")["active_work"] is None


@pytest.mark.asyncio
async def test_reading_progress_cancel_does_not_write(tmp_path):
    service = StoryMemoryService(FakeBackend([evidence(12)]))
    writer = SetReadingProgressTool(tmp_path, service=service)
    progress = ReadingProgressStore(tmp_path)
    first = RequestContext(
        channel="websocket", chat_id="story", session_key="webui:cancel",
        sender_id="alice", turn_id="turn-1", original_user_text="是第一章吗",
    )
    with request_context(first):
        proposal = json.loads(await writer.execute(action="propose", work_id="demo", location_id="chapter-01"))
    second = RequestContext(
        channel="websocket", chat_id="story", session_key="webui:cancel",
        sender_id="alice", turn_id="turn-2", original_user_text="不，还没读完",
    )
    with request_context(second):
        cancelled = json.loads(await writer.execute(action="cancel", pending_id=proposal["pending_id"]))
        assert cancelled["status"] == "cancelled"
        assert progress.get("alice")["active_work"] is None