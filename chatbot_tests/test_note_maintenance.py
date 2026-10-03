"""Note生命周期：合成Markdown、替身维护provider，不读取真实笔记或调用模型。"""
import json
from copy import deepcopy

import pytest
from nanobot import RequestContext

from storypal_chatbot.interaction_note import InteractionNoteStore
from storypal_chatbot.tools import RecordInteractionNoteTool
from test_archive_maintenance import Provider, prepared, run, user


def add(store, *, owner="alice", category="observation", content="可能更喜欢先听感受", session="webui:joint"):
    return store.add(owner, category=category, content=content, source_session_key=session, source_turn_id="旧回合")


def review(note_id, *, action="retire", content=""):
    return {"note_id": note_id, "action": action, "content": content,
            "source_quote": "不是每次都想先聊感受", "source_text": "不是每次都想先聊感受，请别把它当固定偏好",
            "source_session_key": "webui:joint", "source_turn_id": "新回合"}


def test_temporary_is_current_session_only_without_deleting_source(tmp_path):
    store = InteractionNoteStore(tmp_path)
    item = add(store, category="temporary", content="这次先简短一点")
    add(store, category="preference", content="使用中文")
    assert "这次先简短一点" in store.read_for_context("alice", session_key="webui:joint")
    assert "这次先简短一点" not in store.read_for_context("alice", session_key="webui:new")
    assert "使用中文" in store.read_for_context("alice", session_key="webui:new")
    assert item["id"] in store.read("alice")
    restored = InteractionNoteStore(tmp_path)
    assert "这次先简短一点" in restored.read_for_context("alice", session_key="webui:joint")
    repeated = add(restored, category="temporary", content="这次先简短一点", session="webui:new")
    assert not repeated["duplicate"] and repeated["id"] != item["id"]
    assert "这次先简短一点" in restored.read_for_context("alice", session_key="webui:new")
    assert "这次先简短一点" not in restored.read_for_context("bob", session_key="webui:new")


def test_unknown_temporary_scope_not_injected_and_free_markdown_preserved(tmp_path):
    store = InteractionNoteStore(tmp_path)
    path = store._ensure_migrated("alice")
    store._write(path, store.read("alice").replace("## 临时事项\n", "## 临时事项\n\n手动写入但未标记scope\n") + "\n## 自定义约定\n保留我的原始Markdown\n")
    context = store.read_for_context("alice", session_key="webui:joint")
    assert "手动写入但未标记scope" not in context
    assert "保留我的原始Markdown" in context and "手动写入但未标记scope" in path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_runtime_provider_injects_only_current_active_notes(tmp_path):
    tool = RecordInteractionNoteTool(tmp_path)
    add(tool.store, category="temporary", content="这一会话只聊感受")
    req = RequestContext(channel="websocket", chat_id="test", session_key="webui:new", sender_id="alice", original_user_text="你好", turn_id="t")
    block = await tool._provide_runtime_context(req)
    assert "这一会话只聊感受" not in block.content and "不是剧情证据" in block.content
    assert block.replay is False


def test_retire_is_audited_not_injected_idempotent_and_stable_notes_untouched(tmp_path):
    store = InteractionNoteStore(tmp_path)
    observed = add(store)
    stable = add(store, category="constraint", content="不要主动剧透")
    snapshot = store.review_snapshot("alice")
    assert snapshot[0]["content"].startswith("待验证：")
    op = review(observed["id"])
    assert store.apply_reviews("alice", [op], snapshot=snapshot, validate_only=True)["reviewed"] == 1
    assert observed["id"] in store.read("alice")
    assert store.apply_reviews("alice", [op], snapshot=snapshot)["reviewed"] == 1
    assert observed["id"] not in store.read("alice") and stable["id"] in store.read("alice")
    raw = store._path("alice").read_text(encoding="utf-8")
    assert "旧记录" in raw and "不是每次都想先聊感受" in raw
    assert "旧记录" not in store.read_for_context("alice", session_key="webui:joint")
    assert store.apply_reviews("alice", [op], snapshot=snapshot)["reviewed"] == 0
    assert InteractionNoteStore(tmp_path).review_snapshot("alice") == []


def test_revision_keeps_id_tentative_status_and_source_history(tmp_path):
    store = InteractionNoteStore(tmp_path)
    observed = add(store)
    snapshot = store.review_snapshot("alice")
    store.apply_reviews("alice", [review(observed["id"], action="revise", content="有时想先聊感受，需看当轮意图")], snapshot=snapshot)
    current = store.review_snapshot("alice")[0]
    assert current["note_id"] == observed["id"] and current["content"].startswith("待验证：")
    assert "有时想先聊" in store.read("alice")
    assert snapshot[0]["line"] in store._path("alice").read_text(encoding="utf-8")


@pytest.mark.parametrize("bad", ["stable", "role_source", "target", "promote", "too_long", "duplicate", "owner"])
def test_bad_review_rejected_before_any_write(tmp_path, bad):
    store = InteractionNoteStore(tmp_path)
    observed = add(store)
    stable = add(store, category="preference", content="保持中文")
    snapshot = store.review_snapshot("alice")
    ops = [review(observed["id"])]
    owner = "alice"
    if bad == "stable":
        ops[0]["note_id"] = stable["id"]
    elif bad == "role_source":
        ops[0]["source_quote"] = "编造来源"
    elif bad == "target":
        ops[0]["note_id"] = "ffffffffffff"
    elif bad == "promote":
        ops[0]["action"] = "confirm"
    elif bad == "too_long":
        ops[0].update(action="revise", content="甲" * 801)
    elif bad == "duplicate":
        ops.append(deepcopy(ops[0]))
    else:
        owner = "bob"
    previous = store._path("alice").read_bytes()
    with pytest.raises(ValueError):
        store.apply_reviews(owner, ops, snapshot=snapshot)
    assert store._path("alice").read_bytes() == previous


def test_changed_target_during_model_call_not_resurrected(tmp_path):
    store = InteractionNoteStore(tmp_path)
    observed = add(store)
    snapshot = store.review_snapshot("alice")
    store.forget("alice", observed["id"])
    with pytest.raises(ValueError, match="已变化"):
        store.apply_reviews("alice", [review(observed["id"])], snapshot=snapshot)
    assert observed["id"] not in store.read("alice")


def test_modified_target_rejected_and_unrelated_append_preserved(tmp_path):
    store = InteractionNoteStore(tmp_path)
    observed = add(store)
    snapshot = store.review_snapshot("alice")
    stable = add(store, category="agreement", content="新约定要保留")
    store.apply_reviews("alice", [review(observed["id"], action="revise", content="新的待验证表达")], snapshot=snapshot)
    assert stable["id"] in store.read("alice")
    with pytest.raises(ValueError, match="已变化"):
        store.apply_reviews("alice", [review(observed["id"])], snapshot=snapshot)
    assert "新的待验证表达" in store.read("alice")


@pytest.mark.parametrize("mode", ["moved_category", "duplicate_id"])
def test_snapshot_cannot_modify_moved_stable_category_or_ambiguous_id(tmp_path, mode):
    store = InteractionNoteStore(tmp_path)
    observed = add(store)
    snapshot = store.review_snapshot("alice")
    path = store._path("alice")
    document = path.read_text(encoding="utf-8")
    line = snapshot[0]["line"]
    document = document.replace("## 行为约束\n", "## 行为约束\n\n" + line + "\n", 1)
    if mode == "moved_category":
        document = document.replace("## 开放观察\n\n" + line + "\n", "## 开放观察\n", 1)
    store._write(path, document)
    previous = path.read_bytes()
    with pytest.raises(ValueError, match="已变化"):
        store.apply_reviews("alice", [review(observed["id"])], snapshot=snapshot)
    assert path.read_bytes() == previous


def test_snapshot_is_bounded_and_empty_read_does_not_create_notes(tmp_path):
    store = InteractionNoteStore(tmp_path)
    assert store.review_snapshot("alice") == [] and not list(tmp_path.rglob("Note.md"))
    for index in range(7):
        add(store, content=str(index) + "甲" * 790)
    snapshot = store.review_snapshot("alice")
    assert len(snapshot) <= 4 and sum(len(entry["content"]) for entry in snapshot) <= 2400


def test_empty_observation_and_category_deduplication(tmp_path):
    store = InteractionNoteStore(tmp_path)
    with pytest.raises(ValueError):
        add(store, content="   ")
    stable = add(store, category="constraint", content="这一会话简短")
    temporary = add(store, category="temporary", content="这一会话简短")
    assert temporary["id"] != stable["id"]
    assert add(store, category="temporary", content="这一会话简短")["duplicate"] is True


@pytest.mark.asyncio
async def test_native_loop_does_not_replay_old_note_snapshot_or_opaque_provider_state(tmp_path):
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import ToolsConfig
    from nanobot.providers.base import LLMProvider, LLMResponse, ProviderConversationState

    class CapturingProvider(LLMProvider):
        def __init__(self):
            super().__init__(provider_name="test")
            self.inputs, self.states = [], []

        def get_default_model(self):
            return "openai-codex/gpt-6-luna"

        def can_resume_conversation_state(self, state, model=None):
            return True

        async def chat(self, messages, **kwargs):
            self.inputs.append(deepcopy(messages))
            return LLMResponse(content="合成回复", finish_reason="stop", provider_state=ProviderConversationState(
                kind="openai_responses", provider="test", model=self.get_default_model(), version=1, payload={"opaque": "快照"}))

        async def chat_with_context(self, *, provider_context, **kwargs):
            self.states.append(provider_context.conversation_state)
            return await self.chat(**kwargs)

    provider = CapturingProvider()
    tool = RecordInteractionNoteTool(tmp_path)
    observed = add(tool.store, content="旧观察不应恢复", session="websocket:note-replay")
    registry = ToolRegistry()
    registry.register(tool)
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, tool_registry=registry,
                     tools_config=ToolsConfig(allowed_tools=["record_interaction_note"]), model=provider.get_default_model())
    loop.schedule_background = lambda coro: coro.close()
    try:
        await loop.process_direct("第一轮原话", session_key="websocket:note-replay", sender_id="alice", channel="websocket")
        assert "旧观察不应恢复" in str(provider.inputs[0])
        snapshot = tool.store.review_snapshot("alice")
        tool.store.apply_reviews("alice", [review(observed["id"])], snapshot=snapshot)
        await loop.process_direct("第二轮原话", session_key="websocket:note-replay", sender_id="alice", channel="websocket")
        assert "旧观察不应恢复" not in str(provider.inputs[1])
        assert "第一轮原话" in str(provider.inputs[1]) and provider.states[1] is None
        saved = loop.sessions.get_or_create("websocket:note-replay").messages
        assert "旧观察不应恢复" in str(saved)
        assert "旧记录" not in str(provider.inputs[1])
    finally:
        await loop.aclose()


@pytest.mark.asyncio
async def test_archive_review_reuses_single_call_and_does_not_recur_on_every_turn(tmp_path):
    provider = Provider({"note_ops": [], "episodes": [], "note_reviews": []})
    coordinator, req = prepared(tmp_path, provider, messages=[user("不是每次都想先聊感受，请别把它当固定偏好")])
    observed = add(coordinator.notes)
    provider.result["note_reviews"] = [{"note_id": observed["id"], "action": "retire", "message_index": 0, "source_quote": "不是每次都想先聊感受"}]
    await run(coordinator, req)
    assert len(provider.calls) == 1 and coordinator.last_result["note_reviews"] == 1
    assert json.loads(provider.calls[0]["messages"][1]["content"])["existing_observations"][0]["note_id"] == observed["id"]
    assert observed["id"] not in coordinator.notes.read("alice")
    await run(coordinator, req)
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_archive_review_cannot_use_assistant_or_disabled_note_path(tmp_path, monkeypatch):
    provider = Provider({"note_ops": [], "episodes": [], "note_reviews": []})
    messages = [user("用户原话"), {"role": "assistant", "content": "不是每次都想先聊感受", "timestamp": "2026-10-03T10:01:00+08:00"}]
    coordinator, req = prepared(tmp_path, provider, messages=messages)
    observed = add(coordinator.notes)
    provider.result["note_reviews"] = [{"note_id": observed["id"], "action": "retire", "message_index": 1, "source_quote": "不是每次都想先聊感受"}]
    await run(coordinator, req)
    assert coordinator.last_result["status"] == "deferred" and coordinator.episodes.processed("alice", req.session_key) == 0
    assert observed["id"] in coordinator.notes.read("alice")
    monkeypatch.setenv("STORYPAL_AUTO_NOTE", "0")
    provider.result["note_reviews"][0]["message_index"] = 0
    await run(coordinator, req)
    assert not json.loads(provider.calls[-1]["messages"][1]["content"])["existing_observations"]
    assert coordinator.episodes.processed("alice", req.session_key) == 0


def test_write_failure_preserves_active_document(tmp_path, monkeypatch):
    store = InteractionNoteStore(tmp_path)
    observed = add(store)
    snapshot = store.review_snapshot("alice")
    previous = store._path("alice").read_bytes()
    def fail(path, content):
        raise OSError("模拟写入失败")
    monkeypatch.setattr(store, "_write", fail)
    with pytest.raises(OSError):
        store.apply_reviews("alice", [review(observed["id"])], snapshot=snapshot)
    assert store._path("alice").read_bytes() == previous
