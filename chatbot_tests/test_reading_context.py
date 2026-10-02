"""C1 契约验收：用虚构字段隔离验证，不访问用户工作区。"""
from copy import deepcopy

import pytest
from nanobot import RequestContext
from nanobot.runtime_context import normalize_runtime_context_blocks

from storypal_chatbot.reading_context import ReadingContextProjector
from storypal_chatbot.story_memory import StoryMemoryService
from storypal_chatbot.tools import ResolveReadingLocationTool


def view(order=2, work="demo"):
    return {"work_id": work, "max_order": order, "snapshot_order": order,
        "source_version": "a" * 64, "status": "ok", "reason": None,
        "provenance": {"kind": "progressive_snapshot", "unit_id": f"d-{order}", "order_range": [1, order]},
        "snapshot": {"work_id": work, "last_order": order, "backdrop": "前章背景",
            "recent": [{"order": order, "text": "当前事件"}],
            "backdrop_buffer": [{"order": 1, "text": "更早的事件"}, {"order": order, "text": "当前事件"}],
            "characters": [{"name": "甲", "status": "犹豫", "last_seen_order": order}],
            "objects": [{"name": "信", "note": "未打开", "last_seen_order": 1}],
            "locations": [{"name": "城", "note": "目的地", "last_seen_order": 1}],
            "plotlines": [{"title": "选择", "status": "open", "opened_order": 1, "key_orders": [1, order]}]}}


def test_budget_complete_items_and_all_types():
    result = ReadingContextProjector().project(view(), work_id="demo", boundary=2)
    assert result.diagnostics["status"] == "ok"
    assert result.diagnostics["estimated_tokens"] <= 1500
    assert set(result.payload["state"]) == {"recent", "characters", "objects", "locations", "plotlines", "backdrop_buffer", "backdrop"}
    assert len(result.payload["state"]["backdrop_buffer"]) == 1
    assert result.diagnostics["duplicate_count"] == 1
    assert result.payload["provenance"]["order_range"] == [1, 2]
    source = view()
    source["snapshot"]["characters"][0]["note"] = "非常长的内容" * 500
    projector = ReadingContextProjector(token_budget=900)
    result = projector.project(source, work_id="demo", boundary=2)
    assert result.payload["omitted_counts"]["characters"] == 1
    assert "characters" not in result.payload["state"]
    assert projector.estimate(result.content) == result.diagnostics["estimated_tokens"] <= 900
    assert "非常长的内容" not in result.content
    assert ReadingContextProjector(token_budget=1).project(view(), work_id="demo", boundary=2).content is None


def test_cumulative_characters_do_not_starve_other_groups():
    source = view()
    source["snapshot"]["characters"] *= 100
    result = ReadingContextProjector().project(source, work_id="demo", boundary=2)
    assert set(result.payload["state"]) == {"recent", "characters", "objects", "locations", "plotlines", "backdrop_buffer", "backdrop"}
    assert result.payload["omitted_counts"]["characters"] > 0


@pytest.mark.parametrize("mutation", [
    {"snapshot_order": 3}, {"work_id": "other"}, {"max_order": 3}, {"source_version": None},
    {"snapshot": {"work_id": "demo", "last_order": 2, "characters": [{"last_seen_order": 3}]}},
    {"snapshot": {"work_id": "demo", "last_order": 2, "plotlines": [{"key_orders": [3]}]}},
    {"snapshot": {"work_id": "demo", "last_order": 2, "recent": [] , "backdrop": []}},
    {"snapshot": {"work_id": "demo", "last_order": 2, "characters": [{"name": [], "status": "出现"}]}},
])
def test_untrusted_backend_is_rechecked(mutation):
    source = view()
    source.update(deepcopy(mutation))
    class Backend:
        def get_progressive_view(self, work_id, *, max_order):
            return source
    safe = StoryMemoryService(Backend()).progressive_view(work_id="demo", max_seen_order=2)
    assert safe["status"] == "unavailable" and "snapshot" not in safe


@pytest.mark.asyncio
async def test_provider_partial_boundary_owner_restart_switch_and_clear(tmp_path):
    class Backend:
        calls = []
        def get_progressive_view(self, work_id, *, max_order):
            self.calls.append((work_id, max_order))
            if not max_order:
                return {"status": "unavailable", "reason": "no_completed_unit", "work_id": work_id, "max_order": max_order}
            return view(max_order, work_id)
    backend = Backend()
    service = StoryMemoryService(backend)
    resolver = ResolveReadingLocationTool(tmp_path, service)
    state = resolver.state_context.store
    request = RequestContext(channel="websocket", chat_id="test", session_key="websocket:test", sender_id="test-owner")
    state.set("test-owner", active_work="demo", max_seen_order=2, reader_position={"unit_order": 3, "line": 7})
    before = state.get("test-owner")
    blocks = normalize_runtime_context_blocks(await resolver.runtime_context_provider()(request))
    assert [block.source for block in blocks] == ["storypal_session_state", "storypal_story_view"]
    assert blocks[1].replay is False and backend.calls[-1] == ("demo", 2)
    assert state.get("test-owner") == before
    restarted = ResolveReadingLocationTool(tmp_path, service)
    blocks2 = normalize_runtime_context_blocks(await restarted.runtime_context_provider()(request))
    assert blocks2[1].content == blocks[1].content
    other = RequestContext(channel="websocket", chat_id="test", session_key="websocket:other", sender_id="other-owner")
    assert len(normalize_runtime_context_blocks(await restarted.runtime_context_provider()(other))) == 1
    state.set("test-owner", active_work="other", max_seen_order=1)
    changed = normalize_runtime_context_blocks(await restarted.runtime_context_provider()(request))
    assert '"work_id":"other"' in changed[1].content and '"work_id":"demo"' not in changed[1].content
    state.clear("test-owner")
    assert len(normalize_runtime_context_blocks(await restarted.runtime_context_provider()(request))) == 1
    state.set("test-owner", active_work="demo")
    state.clear("test-owner")
    state.set("test-owner", active_work="demo", max_seen_order=0)
    assert len(normalize_runtime_context_blocks(await restarted.runtime_context_provider()(request))) == 1
    assert backend.calls[-1] == ("demo", 0)


@pytest.mark.asyncio
async def test_backend_failure_preserves_state_context(tmp_path):
    class Backend:
        def get_progressive_view(self, *args, **kwargs):
            raise OSError("测试故障")
    resolver = ResolveReadingLocationTool(tmp_path, StoryMemoryService(Backend()))
    resolver.state_context.store.set("test-owner", active_work="demo", max_seen_order=2)
    request = RequestContext(channel="websocket", chat_id="test", session_key="websocket:test", sender_id="test-owner")
    blocks = normalize_runtime_context_blocks(await resolver.runtime_context_provider()(request))
    assert [block.source for block in blocks] == ["storypal_session_state"]
    assert resolver.state_context.last_story_view_diagnostics["reason"] == "OSError"
