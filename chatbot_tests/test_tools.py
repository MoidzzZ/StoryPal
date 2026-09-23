from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from nanobot import RequestContext
from nanobot.agent.tools.context import request_context

from storypal_chatbot.tools import (
    ALLOWED_MODEL,
    ReadNotesTool,
    ReadReadingNotebookTool,
    SaveJournalEntryTool,
    SearchReadingJournalTool,
    SearchHistoryMemoryTool,
    StorySessionStateTool,
    WriteHistoryMemoryTool,
    WriteNoteTool,
    WriteReadingNotebookTool,
)


def _request(session: str = "webui:test", sender: str = "user-1") -> RequestContext:
    return RequestContext(
        channel="websocket",
        chat_id="test",
        session_key=session,
        sender_id=sender,
    )


@pytest.mark.asyncio
async def test_story_state_is_scoped_and_monotonic(tmp_path):
    tool = StorySessionStateTool(tmp_path)
    with request_context(_request()):
        value = json.loads(
            await tool.execute(
                action="set",
                active_work="work-1",
                current_anchor="chapter-2",
                max_seen_order=12,
            )
        )
        assert value["active_work"] == "work-1"
        assert value["max_seen_order"] == 12

        error = await tool.execute(action="set", max_seen_order=8)
        assert error.is_error

    with request_context(_request(session="webui:other")):
        restored = json.loads(await tool.execute(action="get"))
        assert restored["active_work"] == "work-1"
        assert restored["max_seen_order"] == 12

    with request_context(_request(session="webui:other-user", sender="user-2")):
        isolated = json.loads(await tool.execute(action="get"))
        assert isolated["active_work"] is None


def test_user_progress_preserves_each_work_and_migrates_legacy_session(tmp_path):
    from storypal_chatbot.storage import ReadingProgressStore, SessionStateStore

    legacy = SessionStateStore(tmp_path)
    legacy.set("webui:old", active_work="work-1", current_anchor="第一章末", max_seen_order=10)
    progress = ReadingProgressStore(tmp_path)
    migrated = progress.get("alice", legacy_session_key="webui:old")
    assert migrated["max_seen_order"] == 10
    assert progress.get("alice")["current_anchor"] == "第一章末"

    progress.set("alice", active_work="work-2", max_seen_order=3)
    assert progress.get("alice")["active_work"] == "work-2"
    assert progress.set("alice", active_work="work-1")["max_seen_order"] == 10
    assert progress.get("bob")["active_work"] is None

@pytest.mark.asyncio
async def test_first_write_checks_legacy_progress_before_migration(tmp_path):
    from storypal_chatbot.storage import SessionStateStore

    SessionStateStore(tmp_path).set("webui:old", active_work="work-1", max_seen_order=10)
    tool = StorySessionStateTool(tmp_path)
    with request_context(_request(session="webui:old", sender="alice")):
        backwards = await tool.execute(action="set", active_work="work-1", max_seen_order=9)
        assert backwards.is_error
        assert json.loads(await tool.execute(action="get"))["max_seen_order"] == 10

@pytest.mark.asyncio
async def test_runtime_context_contains_spoiler_boundary(tmp_path):
    tool = StorySessionStateTool(tmp_path)
    with request_context(_request()):
        await tool.execute(action="set", active_work="work-1", max_seen_order=7)

    block = await tool._provide_runtime_context(_request())
    assert block is not None
    assert block.source == "storypal_session_state"
    assert '"max_seen_order": 7' in block.content
    assert "防剧透边界" in block.content


@pytest.mark.asyncio
async def test_runtime_context_rejects_every_model_except_luna(tmp_path):
    tool = StorySessionStateTool(tmp_path)
    blocked = _request()
    object.__setattr__(blocked, "runtime", SimpleNamespace(model="openai-codex/gpt-5.6-sol"))

    with pytest.raises(RuntimeError, match="模型策略拒绝"):
        await tool._provide_runtime_context(blocked)

    allowed = _request()
    object.__setattr__(allowed, "runtime", SimpleNamespace(model=ALLOWED_MODEL))
    assert await tool._provide_runtime_context(allowed) is not None


@pytest.mark.asyncio
async def test_notes_require_explicit_write_and_are_user_scoped(tmp_path):
    writer = WriteNoteTool(tmp_path)
    reader = ReadNotesTool(tmp_path)

    with request_context(_request(sender="alice")):
        created = json.loads(
            await writer.execute(action="add", title="偏好", content="我更喜欢反英雄角色")
        )
        notes = json.loads(await reader.execute())
        assert [note["id"] for note in notes] == [created["id"]]

    with request_context(_request(sender="bob")):
        assert json.loads(await reader.execute()) == []

    with request_context(_request(sender="alice")):
        deleted = json.loads(await writer.execute(action="delete", note_id=created["id"]))
        assert deleted == {"deleted": created["id"]}
        assert json.loads(await reader.execute()) == []


@pytest.mark.asyncio
async def test_reading_notebook_is_explicit_and_filtered_by_work_and_boundary(tmp_path):
    writer = WriteReadingNotebookTool(tmp_path)
    reader = ReadReadingNotebookTool(tmp_path)
    state = StorySessionStateTool(tmp_path)

    with request_context(_request(sender="alice")):
        await state.execute(action="set", active_work="work-1", current_anchor="第一章末", max_seen_order=10)
        prediction = json.loads(
            await writer.execute(
                action="add", entry_type="prediction", content="我猜这个选择会带来更大的代价"
            )
        )
        entries = json.loads(await reader.execute())
        assert [entry["id"] for entry in entries] == [prediction["id"]]
        assert entries[0]["anchor_order"] == 10
        assert entries[0]["anchor_text"] == "第一章末"

        await state.execute(action="set", active_work="work-2", max_seen_order=10)
        assert json.loads(await reader.execute()) == []

    with request_context(_request(sender="bob")):
        await state.execute(action="set", active_work="work-1", max_seen_order=10)
        assert json.loads(await reader.execute()) == []


@pytest.mark.asyncio
async def test_atomic_journal_tools_restore_across_sessions_and_keep_owner_scope(tmp_path):
    state = StorySessionStateTool(tmp_path)
    save = SaveJournalEntryTool(tmp_path)
    search = SearchReadingJournalTool(tmp_path)

    with request_context(_request(session="webui:first", sender="alice")):
        await state.execute(action="set", active_work="work-1", max_seen_order=10)
        saved = json.loads(
            await save.execute(entry_type="prediction", content="我猜这项决定以后会有代价")
        )
        assert saved["anchor_order"] == 10

    with request_context(_request(session="webui:later", sender="alice")):
        result = json.loads(await search.execute(query="代价"))
        assert result["total"] == 1
        assert result["entries"][0]["id"] == saved["id"]
        assert result["truncated"] is False

    with request_context(_request(session="webui:other", sender="bob")):
        await state.execute(action="set", active_work="work-1", max_seen_order=10)
        assert json.loads(await search.execute())["entries"] == []

@pytest.mark.asyncio
async def test_prediction_can_be_saved_before_progress_is_confirmed(tmp_path):
    save = SaveJournalEntryTool(tmp_path)
    search = SearchReadingJournalTool(tmp_path)
    state = StorySessionStateTool(tmp_path)

    with request_context(_request(session="webui:first", sender="alice")):
        saved = json.loads(
            await save.execute(
                work_id="wandering_earth",
                entry_type="prediction",
                content="我猜他们最终会真的推动地球",
            )
        )
        assert saved["anchor_order"] == 0
        assert saved["anchor_status"] == "unconfirmed"
        assert json.loads(await state.execute(action="get"))["active_work"] is None

    with request_context(_request(session="webui:later", sender="alice")):
        result = json.loads(await search.execute(work_id="wandering_earth"))
        assert [entry["id"] for entry in result["entries"]] == [saved["id"]]
        assert result["entries"][0]["anchor_status"] == "unconfirmed"

@pytest.mark.asyncio
async def test_reading_notebook_requires_story_boundary(tmp_path):
    writer = WriteReadingNotebookTool(tmp_path)
    with request_context(_request()):
        error = await writer.execute(action="add", entry_type="reaction", content="这一段很难过")
    assert error.is_error
    assert "已读范围" in str(error)

@pytest.mark.asyncio
async def test_history_memory_is_explicit_searchable_and_boundary_scoped(tmp_path):
    writer = WriteHistoryMemoryTool(tmp_path)
    reader = SearchHistoryMemoryTool(tmp_path)
    state = StorySessionStateTool(tmp_path)

    with request_context(_request(session="webui:first", sender="alice")):
        await state.execute(action="set", active_work="work-1", max_seen_order=10)
        created = json.loads(
            await writer.execute(
                action="add",
                memory_type="prediction",
                content="我猜这次选择会带来更大的代价",
                entities=["选择"],
                source_trace="turn:first:1",
                evidence_refs=["unit-0010"],
                idempotency_key="prediction-1",
            )
        )
        retried = json.loads(
            await writer.execute(
                action="add",
                memory_type="prediction",
                content="重试不应产生第二条",
                idempotency_key="prediction-1",
            )
        )
        assert retried["memory_id"] == created["memory_id"]
        assert retried["content"] == created["content"]
        assert retried["source_session"] != "webui:first"

    with request_context(_request(session="webui:later", sender="alice")):
        await state.execute(action="set", active_work="work-1", max_seen_order=10)
        memories = json.loads(await reader.execute(query="代价"))["memories"]
        assert [memory["memory_id"] for memory in memories] == [created["memory_id"]]
        assert memories[0]["evidence_refs"] == ["unit-0010"]

    with request_context(_request(session="webui:before", sender="alice")):
        backwards = await state.execute(action="set", active_work="work-1", max_seen_order=9)
        assert backwards.is_error
        assert [item["memory_id"] for item in json.loads(await reader.execute(query="代价"))["memories"]] == [created["memory_id"]]

    with request_context(_request(session="webui:other-work", sender="alice")):
        await state.execute(action="set", active_work="work-2", max_seen_order=20)
        assert json.loads(await reader.execute(query="代价"))["memories"] == []

    with request_context(_request(session="webui:other-user", sender="bob")):
        await state.execute(action="set", active_work="work-1", max_seen_order=20)
        assert json.loads(await reader.execute(query="代价"))["memories"] == []

    with request_context(_request(session="webui:later", sender="alice")):
        deleted = json.loads(await writer.execute(action="delete", memory_id=created["memory_id"]))
        assert deleted == {"deleted": created["memory_id"]}
        assert json.loads(await reader.execute(query="代价"))["memories"] == []


@pytest.mark.asyncio
async def test_history_memory_rejects_non_trace_content_and_does_not_pollute_store(tmp_path):
    writer = WriteHistoryMemoryTool(tmp_path)
    reader = SearchHistoryMemoryTool(tmp_path)
    state = StorySessionStateTool(tmp_path)

    with request_context(_request(sender="alice")):
        await state.execute(action="set", active_work="work-1", max_seen_order=10)
        error = await writer.execute(
            action="add",
            memory_type="reflection",
            content="这个工具失败不应该变成记忆",
            source_trace="tool output:\nraw content",
        )
        assert error.is_error
        assert json.loads(await reader.execute(query="失败"))["memories"] == []
