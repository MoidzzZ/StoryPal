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
    StorySessionStateTool,
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
        other = json.loads(await tool.execute(action="get"))
        assert other["active_work"] is None


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
async def test_reading_notebook_requires_story_boundary(tmp_path):
    writer = WriteReadingNotebookTool(tmp_path)
    with request_context(_request()):
        error = await writer.execute(action="add", entry_type="reaction", content="这一段很难过")
    assert error.is_error
    assert "已读范围" in str(error)