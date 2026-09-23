"""交互 Note.md 的迁移、隔离和工具写入边界。"""

import json

import pytest
from nanobot import RequestContext
from nanobot.agent.tools.context import request_context

from storypal_chatbot.interaction_note import InteractionNoteStore
from storypal_chatbot.storage import NotesStore
from storypal_chatbot.tools import ForgetInteractionNoteTool, RecordInteractionNoteTool


def _request(*, sender="alice", session="webui:first", text=None, turn="turn-1"):
    return RequestContext(
        channel="websocket",
        chat_id="test",
        session_key=session,
        sender_id=sender,
        original_user_text=text,
        turn_id=turn,
    )


def test_legacy_notes_migrate_to_markdown_without_deleting_source(tmp_path):
    old = NotesStore(tmp_path)
    old.add("alice", content="请用中文交流", title="偏好", source_session_key="webui:old")
    store = InteractionNoteStore(tmp_path)

    note = store.read("alice")
    assert "请用中文交流" in note
    assert "## 旧版明确笔记" in note
    assert len(old.list("alice")) == 1
    assert "请用中文交流" not in store.read("bob")


@pytest.mark.asyncio
async def test_explicit_note_is_injected_across_sessions_and_can_be_forgotten(tmp_path):
    record = RecordInteractionNoteTool(tmp_path)
    forget = ForgetInteractionNoteTool(tmp_path)
    with request_context(_request(text="请记住：我喜欢先聊感受再看证据。")):
        saved = json.loads(await record.execute(
            category="preference",
            content="先聊感受再看证据",
            source_quote="我喜欢先聊感受再看证据",
        ))
        assert saved["duplicate"] is False
        repeated = json.loads(await record.execute(
            category="preference",
            content="先聊感受再看证据",
            source_quote="我喜欢先聊感受再看证据",
        ))
        assert repeated["duplicate"] is True

    block = await record._provide_runtime_context(_request(session="webui:later"))
    assert block.source == "storypal_interaction_note"
    assert "先聊感受再看证据" in block.content
    assert "不是剧情证据" in block.content
    other = await record._provide_runtime_context(_request(sender="bob"))
    assert "先聊感受再看证据" not in other.content

    with request_context(_request(text="忘记刚才那条偏好", turn="turn-2")):
        assert json.loads(await forget.execute(note_id=saved["id"])) == {"forgotten": saved["id"]}
    assert "先聊感受再看证据" not in store_text(tmp_path, "alice")


@pytest.mark.asyncio
async def test_note_rejects_unquoted_history_or_tool_content(tmp_path):
    record = RecordInteractionNoteTool(tmp_path)
    with request_context(_request(text="今天聊聊《流浪地球》")):
        result = await record.execute(
            category="observation",
            content="用户喜欢某个角色",
            source_quote="用户喜欢某个角色",
        )
        assert result.is_error
    assert "用户喜欢某个角色" not in store_text(tmp_path, "alice")


def store_text(tmp_path, owner):
    return InteractionNoteStore(tmp_path).read(owner)