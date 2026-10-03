"""手账生命周期合成程序核验；不加载Embedding或调用真实模型。"""
import json

import pytest
from nanobot import RequestContext
from nanobot.agent.tools.context import request_context
from storypal_chatbot.storage import ReadingNotebookStore, ReadingProgressStore
from storypal_chatbot.tools import SaveJournalEntryTool, SearchReadingJournalTool
from storypal_chatbot.journal_review import JournalReviewObserver


def request(text="请记下我对老师选择的疑问", turn="t1", owner="alice", session="websocket:first"):
    return RequestContext(channel="websocket", chat_id="test", session_key=session,
                          sender_id=owner, turn_id=turn, original_user_text=text)


def progress(workspace, order, owner="alice", work="wandering_earth"):
    return ReadingProgressStore(workspace).set(owner, active_work=work, max_seen_order=order)


@pytest.mark.asyncio
async def test_revision_restores_safe_version_and_keeps_original(tmp_path):
    writer, reader = SaveJournalEntryTool(tmp_path), SearchReadingJournalTool(tmp_path)
    progress(tmp_path, 10)
    with request_context(request()):
        original = json.loads(await writer.execute(entry_type="prediction", content="我猜老师还会改变立场"))
    progress(tmp_path, 20)
    text = "把这个预测改成：目前还没证据，先保留怀疑"
    with request_context(request(text, "t2")):
        revised = json.loads(await writer.execute(action="revise", entry_id=original["id"],
                            content="目前还没证据，先保留怀疑", source_quote=text))
        assert revised["id"] == original["id"] and revised["anchor_order"] == 20
        assert revised["revisions"][0]["content"] == original["content"]
        assert revised["source_turn_id"] == "t2" and revised["updated_at"]
        retried = json.loads(await writer.execute(action="revise", entry_id=original["id"],
                            content="目前还没证据，先保留怀疑", source_quote=text))
        assert len(retried["revisions"]) == 1
    store = ReadingNotebookStore(tmp_path)
    earlier = store.list("alice", active_work="wandering_earth", max_seen_order=10)[0]
    assert earlier["content"] == original["content"] and earlier["revisions"] == []
    assert store.list("alice", active_work="wandering_earth", max_seen_order=9) == []
    assert store.list("bob", active_work="wandering_earth", max_seen_order=99) == []
    assert store.list("alice", active_work="other", max_seen_order=99) == []
    with request_context(request(session="websocket:later")):
        result = json.loads(await reader.execute(query="怀疑"))
        assert result["entries"][0]["content"] == revised["content"]


@pytest.mark.asyncio
async def test_add_retry_and_delete_all_versions_are_owner_work_scoped(tmp_path):
    writer = SaveJournalEntryTool(tmp_path)
    progress(tmp_path, 10)
    with request_context(request()):
        original = json.loads(await writer.execute(entry_type="question", content="这里的理由是什么"))
        duplicate = json.loads(await writer.execute(entry_type="question", content="这里的理由是什么"))
        assert duplicate["id"] == original["id"]
    for owner, work in [("bob", "wandering_earth"), ("alice", "other")]:
        progress(tmp_path, 10, owner, work)
        with request_context(request("删除这条手账", "delete", owner)):
            result = json.loads(await writer.execute(action="delete", entry_id=original["id"], source_quote="删除这条手账"))
            assert result["status"] == "absent"
    progress(tmp_path, 10)
    with request_context(request("修改这条手账", "revise")):
        changed = json.loads(await writer.execute(action="revise", entry_id=original["id"],
                        content="先不下结论", source_quote="修改这条手账"))
        assert len(changed["revisions"]) == 1
    with request_context(request("删除这条手账", "delete")):
        assert json.loads(await writer.execute(action="delete", entry_id=original["id"], source_quote="删除这条手账"))["status"] == "deleted"
        assert json.loads(await writer.execute(action="delete", entry_id=original["id"], source_quote="删除这条手账"))["status"] == "absent"
    assert ReadingNotebookStore(tmp_path).list("alice", active_work="wandering_earth", max_seen_order=100) == []
    assert json.loads(writer.store._path("alice").read_text(encoding="utf-8")) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["quote", "turn", "id", "type", "size", "action"])
async def test_invalid_mutation_does_not_change_journal(tmp_path, fault):
    writer = SaveJournalEntryTool(tmp_path)
    progress(tmp_path, 10)
    with request_context(request()):
        entry = json.loads(await writer.execute(entry_type="prediction", content="我猜老师会回来"))
    kwargs = dict(action="revise", entry_id=entry["id"], content="先保留怀疑", source_quote="修改这条")
    ctx = request("修改这条", "t2")
    if fault == "quote": kwargs["source_quote"] = "伪造的新原话"
    if fault == "turn": ctx = request("修改这条", None)
    if fault == "id": kwargs["entry_id"] = "不存在"
    if fault == "type": kwargs["entry_type"] = "question"
    if fault == "size": kwargs["content"] = "长" * 2001
    if fault == "action": kwargs["action"] = "confirm"
    with request_context(ctx):
        assert (await writer.execute(**kwargs)).is_error
    kept = ReadingNotebookStore(tmp_path).list("alice", active_work="wandering_earth", max_seen_order=10)[0]
    assert kept["content"] == entry["content"] and not kept["revisions"]


@pytest.mark.asyncio
async def test_cannot_revise_later_entry_at_unconfirmed_scope(tmp_path):
    writer = SaveJournalEntryTool(tmp_path)
    progress(tmp_path, 20)
    with request_context(request()):
        entry = json.loads(await writer.execute(entry_type="prediction", content="后期的猜测"))
    ReadingProgressStore(tmp_path).clear("alice")
    with request_context(request("修改这条", "t2")):
        error = await writer.execute(action="revise", work_id="wandering_earth", entry_id=entry["id"],
                                     content="新的猜测", source_quote="修改这条")
        assert error.is_error


@pytest.mark.asyncio
async def test_progress_review_is_bounded_once_and_not_an_automatic_verdict(tmp_path):
    reader, writer = SearchReadingJournalTool(tmp_path), SaveJournalEntryTool(tmp_path)
    progress(tmp_path, 10)
    assert await reader._provide_runtime_context(request()) is None
    with request_context(request()):
        entry = json.loads(await writer.execute(entry_type="prediction", content="我猜老师会回来"))
    progress(tmp_path, 20)
    view = await reader._provide_runtime_context(request(session="websocket:new"))
    assert view.source == "storypal_journal_review" and view.replay is False
    assert entry["content"] in view.content and '"newly_read_orders": [11, 20]' in view.content
    assert "不自动判对错" in view.content
    assert await reader._provide_runtime_context(request()) is None
    assert await SearchReadingJournalTool(tmp_path)._provide_runtime_context(request()) is None
    assert ReadingNotebookStore(tmp_path).list("alice", active_work="wandering_earth", max_seen_order=20)[0]["status"] == "open"
    assert await reader._provide_runtime_context(request(owner="bob")) is None


def test_review_reset_first_use_and_whole_item_budget(tmp_path):
    observer = JournalReviewObserver(tmp_path)
    store = ReadingNotebookStore(tmp_path)
    assert observer.observe("alice", dict(active_work="wandering_earth", max_seen_order=10)) is None
    for index in range(5):
        store.add("alice", active_work="wandering_earth", anchor_order=10, anchor_text=None,
                  entry_type="question", content="问题" * 350 + str(index), source_session_key="test")
    result = observer.observe("alice", dict(active_work="wandering_earth", max_seen_order=20))
    assert len(result["entries"]) == 2
    assert sum(len(e["content"]) for e in result["entries"]) <= 1800
    assert observer.observe("alice", dict(active_work="wandering_earth", max_seen_order=5)) is None
    assert observer.observe("alice", dict(active_work="wandering_earth", max_seen_order=6)) is None
    assert observer.observe("alice", dict(active_work="wandering_earth", max_seen_order=True)) is None


@pytest.mark.asyncio
async def test_native_loop_review_snapshot_does_not_replay_or_add_model_call(tmp_path, monkeypatch):
    from copy import deepcopy
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools import ToolRegistry
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import ToolsConfig
    from nanobot.providers.base import LLMProvider, LLMResponse
    from nanobot.session.manager import SessionManager

    class Provider(LLMProvider):
        def __init__(self):
            super().__init__(provider_name="test")
            self.calls = []

        def get_default_model(self):
            return "openai-codex/gpt-6-luna"

        async def chat(self, messages, tools=None, **kwargs):
            self.calls.append(deepcopy(messages))
            return LLMResponse(content="替身只检查接线", finish_reason="stop")

    monkeypatch.setattr(AgentLoop, "_register_default_tools", lambda self, **kwargs: None)
    workspace = tmp_path / "workspace"
    provider = Provider()
    journal = SearchReadingJournalTool(workspace)
    progress(workspace, 10)
    JournalReviewObserver(workspace).observe("alice", dict(active_work="wandering_earth", max_seen_order=10))
    journal.store.add("alice", active_work="wandering_earth", anchor_order=10, anchor_text=None,
                      entry_type="prediction", content="我猜老师会回来", source_session_key="cli:test")
    progress(workspace, 20)
    registry = ToolRegistry()
    registry.register(journal)
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=workspace,
                     tool_registry=registry, tools_config=ToolsConfig(allowed_tools=[journal.name]),
                     session_manager=SessionManager(workspace, sessions_root=tmp_path / "sessions"))
    loop.schedule_background = lambda coro: coro.close()
    try:
        await loop.process_direct("读到新内容了，继续聊老师", session_key="cli:test", sender_id="alice")
        await loop.process_direct("先不分析了", session_key="cli:test", sender_id="alice")
        assert len(provider.calls) == 2
        first = json.dumps(provider.calls[0], ensure_ascii=False)
        second = json.dumps(provider.calls[1], ensure_ascii=False)
        assert "我猜老师会回来" in first
        assert "我猜老师会回来" not in second and "storypal_journal_review" not in second
    finally:
        await loop.aclose()
