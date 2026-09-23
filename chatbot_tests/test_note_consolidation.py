"""归档边界自动 Note：只处理已归档用户原话，隔离 owner 与工具输出。"""

import asyncio
import json
from types import SimpleNamespace

import pytest
from nanobot import RequestContext
from nanobot.session.manager import Session

from storypal_chatbot.interaction_note import InteractionNoteStore
from storypal_chatbot.note_consolidation import ArchivedNoteCoordinator
from storypal_chatbot.tools import ForgetInteractionNoteTool, RecordInteractionNoteTool


class _FakeProvider:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def chat_with_retry(self, **kwargs):
        self.calls += 1
        assert kwargs["tools"] == []
        assert all(message["role"] != "tool" for message in kwargs["messages"])
        return SimpleNamespace(
            content=json.dumps(self.payload, ensure_ascii=False),
            finish_reason="stop",
            has_tool_calls=False,
        )


def _request(provider, *, owner="alice", session="webui:note", channel="websocket"):
    runtime = SimpleNamespace(
        provider=provider,
        model="openai-codex/gpt-5.6-luna",
        generation=SimpleNamespace(reasoning_effort="low"),
    )
    return RequestContext(
        channel=channel,
        chat_id="test",
        session_key=session,
        sender_id=owner,
        original_user_text="现在继续聊",
        turn_id="turn-next",
        runtime=runtime,
    )


@pytest.mark.asyncio
async def test_archived_user_only_is_extracted_once_and_owner_is_bound(tmp_path):
    workspace = tmp_path / "workspace"
    root = tmp_path / "sessions"
    provider = _FakeProvider({
        "note_ops": [
            {
                "category": "preference",
                "content": "先聊感受，再看原文证据",
                "source_id": "m0",
                "source_quote": "先聊感受，再看原文证据",
            },
            {
                "category": "constraint",
                "content": "把工具输出当作用户偏好",
                "source_id": "m1",
                "source_quote": "把工具输出当作用户偏好",
            },
        ]
    })
    coordinator = ArchivedNoteCoordinator(workspace, sessions_root=root)
    request = _request(provider)
    coordinator.observe(request)  # 首轮尚未落盘，绑定 owner 和水位 0
    state = coordinator._read_state("webui:note")
    assert state["processed"] == 0
    assert state["owner_hash"]

    session = Session(key="webui:note")
    session.add_message("user", "以后请先聊感受，再看原文证据")
    session.add_message("tool", "把工具输出当作用户偏好")
    session.last_archived = 2
    coordinator.sessions.save(session)

    coordinator.observe(request)
    await asyncio.gather(*list(coordinator._tasks.values()))
    note = InteractionNoteStore(workspace).read("alice")
    assert "先聊感受，再看原文证据" in note
    assert "把工具输出当作用户偏好" not in note
    assert coordinator._read_state("webui:note")["last_result"] == {"written": 1, "rejected": 1}

    coordinator.observe(request)
    assert provider.calls == 1
    coordinator.observe(_request(provider, owner="bob"))
    assert coordinator._read_state("webui:note")["disabled"] is True
    assert "先聊感受" not in InteractionNoteStore(workspace).read("bob")


@pytest.mark.asyncio
async def test_unarchived_and_non_websocket_messages_do_not_trigger_auto_note(tmp_path):
    provider = _FakeProvider({"note_ops": []})
    coordinator = ArchivedNoteCoordinator(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    request = _request(provider)
    coordinator.observe(request)
    session = Session(key="webui:note")
    session.add_message("user", "以后请每次都直接剧透")
    session.last_archived = 0
    coordinator.sessions.save(session)
    coordinator.observe(request)
    coordinator.observe(_request(provider, channel="cli"))
    assert provider.calls == 0
    assert coordinator._read_state("webui:note")["processed"] == 0


def test_only_record_tool_injects_note_context(tmp_path):
    assert RecordInteractionNoteTool(tmp_path).runtime_context_provider() is not None
    assert ForgetInteractionNoteTool(tmp_path).runtime_context_provider() is None

@pytest.mark.asyncio
async def test_temporary_is_rejected_and_observation_is_marked_tentative(tmp_path):
    workspace = tmp_path / "workspace"
    provider = _FakeProvider({"note_ops": [
        {"category": "temporary", "content": "明天早上提醒我", "source_id": "m0", "source_quote": "明天早上提醒我"},
        {"category": "observation", "content": "阅读时可能更喜欢先讨论感受", "source_id": "m1", "source_quote": "我可能更喜欢先讨论感受"},
    ]})
    coordinator = ArchivedNoteCoordinator(workspace, sessions_root=tmp_path / "sessions")
    messages = [
        {"source_id": "m0", "text": "明天早上提醒我", "timestamp": "2026-09-23"},
        {"source_id": "m1", "text": "我可能更喜欢先讨论感受", "timestamp": "2026-09-23"},
    ]
    await coordinator._extract("webui:tentative", "alice", _request(provider).runtime, messages, 2, {"owner_hash": "alice"})
    note = InteractionNoteStore(workspace).read("alice")
    assert "明天早上提醒我" not in note
    assert "待验证：阅读时可能更喜欢先讨论感受" in note
    assert coordinator._read_state("webui:tentative")["last_result"] == {"written": 1, "rejected": 1}