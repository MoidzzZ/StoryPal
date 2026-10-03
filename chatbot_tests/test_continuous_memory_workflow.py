"""连续理解跨模块程序验收：真实压缩／存储／工具／LanceDB，替身LLM和向量。

预设摘要、抽取与答复只检验传递和隔离，不可当作模型理解成绩。
"""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
from nanobot import RequestContext
from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.agent.memory import Consolidator, MemoryStore
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest
from nanobot.runtime_context import RuntimeContextBlock, append_runtime_context, RUNTIME_CONTEXT_HISTORY_META
from nanobot.session.manager import SessionManager
from nanobot.session.summary import session_summary_from_metadata
from nanobot.utils.llm_runtime import LLMRuntime

from storypal_chatbot.archive_maintenance import ArchivedMemoryCoordinator
from storypal_chatbot.bootstrap import install_persona
from storypal_chatbot.episodic_recall import EpisodicRecallService
from storypal_chatbot.interaction_note import InteractionNoteStore
from storypal_chatbot.storage import ReadingNotebookStore, ReadingProgressStore
from storypal_chatbot.tools import RecallInteractionHistoryTool, RecordInteractionNoteTool

SCENARIOS = [
    ("角色立场", "我喜欢阿岚回去救老师，但她反对实验，这有点矛盾。",
     "我不是说她不会救人，我关心的是转折有没有铺垫。", "error"),
    ("人物关系", "他们吵归吵，还是没丢下对方，这里我挺喜欢。",
     "我不是说他们已经和好了，只是这次没有抛下对方。", "empty"),
    ("局部因果", "城里突然断电，我猜和刚才那个装置有关系。",
     "先别把时间先后当因果，装置是不是原因还得查。", "unclassified"),
    ("叙事伏笔", "前面说过那只坏钟，我觉得这里可能在回扣它。",
     "我是在提一种读法，不是说作者已经证实了伏笔。", "evidence_returned"),
    ("情绪暂停", "阿岚还是回去了，看着有点难受。",
     "先不分析了，我现在只是想聊这个感受。", "error"),
]


class Provider(LLMProvider):
    def __init__(self, responses):
        super().__init__(provider_name="isolated-workflow")
        self.responses = iter(responses)
        self.calls = []
        self.generation = GenerationSettings(max_tokens=1800, temperature=.1)

    def get_default_model(self):
        return "openai-codex/gpt-6-luna"

    async def chat(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class Encoder:
    model_name = "连续流程合成向量-v1"

    def __init__(self):
        self.calls = []

    def encode(self, texts):
        self.calls.append(list(texts))
        return [[1., 0., 0.] for _ in texts]


def response(payload):
    return LLMResponse(content=json.dumps(payload, ensure_ascii=False), finish_reason="stop")


def source(text):
    content, marker = append_runtime_context(text, [
        RuntimeContextBlock("storypal_session_state", "用户已确认阅读状态：" + json.dumps(
            {"active_work": "synthetic", "max_seen_order": 12}, ensure_ascii=False)),
        RuntimeContextBlock("storypal_story_view", "注入的故事资料不能变成用户亲口观点", replay=False),
    ])
    return {"role": "user", "content": content, RUNTIME_CONTEXT_HISTORY_META: marker,
            "timestamp": "2026-10-04T10:00:00+08:00"}


def transcript(initial, correction, tool_state="error"):
    observation = {"error": "合成检索失败，尚未查证"}
    if tool_state == "empty":
        observation = {"anchors": [], "adjacent_context": []}
    if tool_state == "unclassified":
        observation = {"unexpected": "尚未分类，不应当作核实"}
    if tool_state == "evidence_returned":
        observation = {"anchors": [{"work_id": "synthetic", "unit_id": "s-12", "order": 12,
                                    "raw_text": "钟没有走动。"}]}
    rows = [source("以后聊转折时，先分清动机和铺垫。"),
        {"role": "assistant", "content": "好。"}, source(initial),
        {"role": "assistant", "content": "需要查证的部分我不会先当事实。",
         "tool_calls": [{"id": "search-1", "type": "function", "function": {
             "name": "search_story", "arguments": json.dumps({"query": "前文铺垫"})}}]},
        {"role": "tool", "name": "search_story", "tool_call_id": "search-1",
         "content": json.dumps(observation, ensure_ascii=False)},
        {"role": "assistant", "content": "不把检索状态当作文学结论。"},
        source(correction), {"role": "assistant", "content": "沿着你现在的意思聊。"}]
    for i in range(5):
        rows.extend([source(f"无剧情闲聊{i}"), {"role": "assistant", "content": "只是换个话题。"}])
    for row in rows:
        row.setdefault("timestamp", "2026-10-04T10:01:00+08:00")
    return rows


def payload(topic, correction):
    return {"note_ops": [{"category": "preference", "content": "聊转折时先分清动机和铺垫",
                          "message_index": 0, "source_quote": "先分清动机和铺垫"}],
        "note_reviews": [], "episodes": [{"title": topic + "的讨论承接", "context": "我们围绕这一片段讨论。",
            "development": "用户澄清：" + correction, "open_question": "此前没有查清的依据仍不能当事实。",
            "source_refs": [{"message_index": 6, "quote": correction}]}]}


def request(provider, key="websocket:continuous", owner="synthetic-reader"):
    return RequestContext(channel="websocket", chat_id="isolated", session_key=key, sender_id=owner,
        turn_id="next-after-checkpoint", original_user_text="继续前面的讨论",
        runtime=SimpleNamespace(provider=provider, model=provider.get_default_model(), generation=provider.generation))


def setup(tmp_path, provider, rows):
    workspace = tmp_path / "workspace"
    install_persona(workspace)
    sessions = SessionManager(workspace)
    coordinator = ArchivedMemoryCoordinator(workspace)
    req = request(provider)
    coordinator.observe(req)  # 归档前绑定，不手动设置归档水位。
    session = sessions.get_or_create(req.session_key)
    session.messages = deepcopy(rows)
    sessions.save(session)
    ReadingProgressStore(workspace).set(req.sender_id, active_work="synthetic", max_seen_order=12)
    journal = ReadingNotebookStore(workspace)
    journal.add(req.sender_id, active_work="synthetic", anchor_order=10, anchor_text="旧位置",
                entry_type="prediction", content="这是一条保留原样的旧预测", source_session_key=req.session_key)
    builder = ContextBuilder(workspace)
    consolidator = Consolidator(MemoryStore(workspace), sessions, builder.build_messages, lambda: [])
    return workspace, sessions, coordinator, req, consolidator


async def maintain(coordinator, req):
    coordinator.observe(req)
    if coordinator._tasks:
        await asyncio.gather(*list(coordinator._tasks.values()))
        await asyncio.sleep(0)


def loop(workspace, provider, sessions, *, tools=(), coordinator=None):
    class IsolatedLoop(AgentLoop):
        def _register_default_tools(self, **kwargs):
            pass
    registry = ToolRegistry()
    for item in tools:
        registry.register(item)
    agent = IsolatedLoop(bus=MessageBus(), provider=provider, workspace=workspace,
        model=provider.get_default_model(), context_window_tokens=200000, max_iterations=3,
        tools_config=ToolsConfig(allowed_tools=registry.tool_names), tool_registry=registry, session_manager=sessions)
    agent.schedule_background = lambda coroutine: coroutine.close()
    note = RecordInteractionNoteTool(workspace)
    note._archive_notes = coordinator
    agent.register_runtime_context_provider(note._provide_runtime_context)
    return agent


@pytest.mark.asyncio
@pytest.mark.parametrize("topic,initial,correction,tool_state", SCENARIOS, ids=[s[0] for s in SCENARIOS])
async def test_real_checkpoint_maintenance_restart_continuation_and_new_session_recall(
        tmp_path, monkeypatch, topic, initial, correction, tool_state):
    pytest.importorskip("lancedb")
    for flag in ["STORYPAL_AUTO_NOTE", "STORYPAL_AUTO_EPISODE"]:
        monkeypatch.setenv(flag, "1")
    monkeypatch.setenv("STORYPAL_AUTO_JOURNAL_REVIEW", "0")
    summary = "[读者观点] " + initial + "\n[修正轨迹] 澄清而非撤回：" + correction + "\n[未解问题] 仍未查证。"
    provider = Provider([LLMResponse(content=summary, finish_reason="stop"), response(payload(topic, correction)),
        LLMResponse(content="替身同会话承接", finish_reason="stop"),
        LLMResponse(content=None, finish_reason="tool_calls", tool_calls=[ToolCallRequest(
            id="recall-1", name="recall_interaction_history", arguments={"query": topic + " 之前的澄清"})]),
        LLMResponse(content="替身跨会话承接", finish_reason="stop")])
    rows = transcript(initial, correction, tool_state)
    workspace, sessions, coordinator, req, consolidator = setup(tmp_path, provider, rows)
    before = deepcopy(ReadingNotebookStore(workspace).list(req.sender_id, active_work="synthetic", max_seen_order=12))
    persona_before = {name: (workspace / name).read_bytes() for name in ["SOUL.md", "USER.md", "AGENTS.md"]}
    runtime = LLMRuntime.capture(provider, provider.get_default_model(), context_window_tokens=200000)
    await consolidator.compact_idle_session(req.session_key, runtime=runtime)
    restored = SessionManager(workspace).get_or_create(req.session_key)
    assert restored.last_archived == len(rows) and restored.messages == rows
    assert initial not in str(restored.get_history()) and correction not in str(restored.get_history())
    checkpoint = session_summary_from_metadata(restored.metadata, fallback_last_active=restored.updated_at)
    assert checkpoint["text"] == summary
    await maintain(coordinator, req)
    assert len(provider.calls) == 2
    sent = json.loads(provider.calls[1]["messages"][1]["content"])
    assert sent["messages"][4]["result_state"] == tool_state and sent["scope"] == ["synthetic", 12]
    assert "注入的故事资料" not in json.dumps(sent, ensure_ascii=False)
    assert sent["messages"][6]["text"] == correction
    records = coordinator.episodes.list_records(req.sender_id)
    assert len(records) == 1 and records[0]["archive_range"] == [0, len(rows)]
    assert records[0]["source_refs"][0]["quote"] == correction
    assert coordinator.episodes.processed(req.sender_id, req.session_key) == len(rows)
    assert "聊转折时先分清" in InteractionNoteStore(workspace).read(req.sender_id)
    await maintain(ArchivedMemoryCoordinator(workspace), req)
    assert len(provider.calls) == 2  # 重启水位恢复，不再次抽取。
    current = loop(workspace, provider, SessionManager(workspace))
    try:
        output = await current.process_direct("刚才我是在澄清什么？", session_key=req.session_key,
            channel="websocket", chat_id="isolated", sender_id=req.sender_id)
        assert output.content == "替身同会话承接"
        assert summary in provider.calls[2]["messages"][0]["content"]
        assert not provider.calls[2]["tools"]
    finally:
        await current.aclose()
    encoder = Encoder()
    service = EpisodicRecallService(workspace, encoder_factory=lambda: encoder, token_budget=3000)
    fresh = loop(workspace, provider, SessionManager(workspace), tools=[RecallInteractionHistoryTool(workspace, service)])
    try:
        output = await fresh.process_direct("我们上次聊这个时，我后来澄清了什么？",
            session_key="websocket:new-isolated", channel="websocket", chat_id="isolated", sender_id=req.sender_id)
        assert output.content == "替身跨会话承接"
        assert summary not in str(provider.calls[3]["messages"])
        tool_msg = next(m for m in provider.calls[4]["messages"] if m["role"] == "tool")
        result = json.loads(tool_msg["content"])
        assert len(result["episodes"]) == 1 and correction in result["episodes"][0]["text"]
        assert [t["function"]["name"] for t in provider.calls[3]["tools"]] == ["recall_interaction_history"]
        assert len(encoder.calls) == 2  # 建索引＋查询；没有本地模型加载。
    finally:
        await fresh.aclose()
    assert ReadingNotebookStore(workspace).list(req.sender_id, active_work="synthetic", max_seen_order=12) == before
    assert all((workspace / name).read_bytes() == data for name, data in persona_before.items())
    assert ReadingProgressStore(workspace).get(req.sender_id)["max_seen_order"] == 12
    encoded = len(encoder.calls)
    assert service.recall(req.sender_id, work_id="synthetic", max_seen_order=11, query=topic)["episodes"] == []
    assert service.recall("other-reader", work_id="synthetic", max_seen_order=12, query=topic)["episodes"] == []
    assert service.recall(req.sender_id, work_id="other-work", max_seen_order=12, query=topic)["episodes"] == []
    assert len(encoder.calls) == encoded  # 全链生成的经历也不能借当前query越权读取。


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["network", "length", "empty", "tool_call"])
async def test_failed_summary_raw_fallback_can_still_extract_from_original_transcript(tmp_path, monkeypatch, fault):
    monkeypatch.setenv("STORYPAL_AUTO_NOTE", "1")
    monkeypatch.setenv("STORYPAL_AUTO_EPISODE", "1")
    failures = {"network": RuntimeError("合成归档失败"), "length": LLMResponse(content="截断", finish_reason="length"),
        "empty": LLMResponse(content="", finish_reason="stop"), "tool_call": LLMResponse(content=None,
        finish_reason="tool_calls", tool_calls=[ToolCallRequest(id="bad", name="search_story", arguments={})])}
    correction = SCENARIOS[0][2]
    provider = Provider([failures[fault], response(payload("角色立场", correction))])
    rows = transcript(SCENARIOS[0][1], correction)
    workspace, sessions, coordinator, req, consolidator = setup(tmp_path, provider, rows)
    await consolidator.compact_idle_session(req.session_key, runtime=LLMRuntime.capture(
        provider, provider.get_default_model(), context_window_tokens=200000))
    restored = SessionManager(workspace).get_or_create(req.session_key)
    checkpoint = session_summary_from_metadata(restored.metadata, fallback_last_active=restored.updated_at)
    assert "[RAW]" in checkpoint["text"] and correction in checkpoint["text"]
    assert restored.messages == rows
    await maintain(coordinator, req)
    assert coordinator.episodes.processed(req.sender_id, req.session_key) == len(rows)
    assert len(coordinator.episodes.list_records(req.sender_id)) == 1
    assert len(provider.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["invalid_json", "length", "tool_call", "assistant_note", "runtime_quote", "future_source"])
async def test_valid_checkpoint_invalid_extraction_is_not_consumed_and_retries_after_restart(tmp_path, monkeypatch, fault):
    monkeypatch.setenv("STORYPAL_AUTO_NOTE", "1")
    monkeypatch.setenv("STORYPAL_AUTO_EPISODE", "1")
    correction = SCENARIOS[0][2]
    good = payload("角色立场", correction)
    bad = deepcopy(good)
    if fault == "assistant_note":
        bad["note_ops"][0].update(message_index=1, source_quote="好")
    if fault == "runtime_quote":
        bad["episodes"][0]["source_refs"][0]["quote"] = "注入的故事资料不能变成用户亲口观点"
    if fault == "future_source":
        bad["episodes"][0]["source_refs"][0]["message_index"] = 100
    invalid = response(bad)
    if fault == "invalid_json":
        invalid = LLMResponse(content="不是JSON", finish_reason="stop")
    if fault == "length":
        invalid = LLMResponse(content=json.dumps(good, ensure_ascii=False), finish_reason="length")
    if fault == "tool_call":
        invalid = LLMResponse(content=None, finish_reason="tool_calls", tool_calls=[ToolCallRequest(
            id="bad", name="write_memory", arguments={})])
    provider = Provider([LLMResponse(content="合成有效checkpoint", finish_reason="stop"), invalid, response(good)])
    rows = transcript(SCENARIOS[0][1], correction)
    workspace, sessions, coordinator, req, consolidator = setup(tmp_path, provider, rows)
    await consolidator.compact_idle_session(req.session_key, runtime=LLMRuntime.capture(
        provider, provider.get_default_model(), context_window_tokens=200000))
    await maintain(coordinator, req)
    assert coordinator.last_result["status"] == "deferred"
    assert coordinator.episodes.processed(req.sender_id, req.session_key) == 0
    assert not coordinator.episodes.list_records(req.sender_id)
    assert "聊转折时先分清" not in coordinator.notes.read(req.sender_id)
    retry = ArchivedMemoryCoordinator(workspace)
    await maintain(retry, req)
    assert len(provider.calls) == 3 and len(retry.episodes.list_records(req.sender_id)) == 1
    assert retry.episodes.processed(req.sender_id, req.session_key) == len(rows)


@pytest.mark.asyncio
async def test_pending_maintenance_does_not_block_foreground_and_note_appears_next_turn(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYPAL_AUTO_NOTE", "1")
    monkeypatch.setenv("STORYPAL_AUTO_EPISODE", "1")
    entered, release = asyncio.Event(), asyncio.Event()
    correction = SCENARIOS[0][2]
    class PausingProvider(Provider):
        async def chat(self, **kwargs):
            self.calls.append(deepcopy(kwargs))
            if len(self.calls) == 1:
                return LLMResponse(content="当前澄清的有效checkpoint", finish_reason="stop")
            if len(self.calls) == 2:
                entered.set()
                await release.wait()
                return response(payload("人物立场", correction))
            return LLMResponse(content="前台可继续聊", finish_reason="stop")
    provider = PausingProvider([])
    rows = transcript(SCENARIOS[0][1], correction)
    workspace, sessions, coordinator, req, consolidator = setup(tmp_path, provider, rows)
    await consolidator.compact_idle_session(req.session_key, runtime=LLMRuntime.capture(
        provider, provider.get_default_model(), context_window_tokens=200000))
    coordinator.observe(req)
    await asyncio.wait_for(entered.wait(), timeout=5)
    coordinator.observe(req)
    assert len(provider.calls) == 2 and len(coordinator._tasks) == 1
    agent = loop(workspace, provider, SessionManager(workspace), coordinator=coordinator)
    try:
        output = await asyncio.wait_for(agent.process_direct("先聊着，不用等后台",
            session_key=req.session_key, channel="websocket", chat_id="isolated", sender_id=req.sender_id), timeout=8)
        assert output.content == "前台可继续聊" and not release.is_set()
        assert coordinator.episodes.processed(req.sender_id, req.session_key) == 0
        assert "聊转折时先分清动机和铺垫" not in str(provider.calls[2]["messages"])
        release.set()
        await asyncio.gather(*list(coordinator._tasks.values()))
        await asyncio.sleep(0)
        await agent.process_direct("现在继续", session_key=req.session_key, channel="websocket",
                                   chat_id="isolated", sender_id=req.sender_id)
        assert "聊转折时先分清动机和铺垫" in str(provider.calls[3]["messages"])
        assert len(provider.calls) == 4 and coordinator.episodes.processed(req.sender_id, req.session_key) == len(rows)
    finally:
        release.set()
        if coordinator._tasks:
            await asyncio.gather(*list(coordinator._tasks.values()))
        await agent.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["no_value", "both_disabled", "note_only", "episode_only"])
async def test_archive_empty_or_disabled_categories_do_not_force_other_memory(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("STORYPAL_AUTO_NOTE", "1")
    monkeypatch.setenv("STORYPAL_AUTO_EPISODE", "1")
    correction = SCENARIOS[0][2]
    extracted = payload("人物立场", correction)
    if mode == "no_value":
        extracted = {"note_ops": [], "note_reviews": [], "episodes": []}
    if mode == "note_only":
        extracted["episodes"] = []
    if mode == "episode_only":
        extracted["note_ops"] = []
    provider = Provider([LLMResponse(content="有效checkpoint", finish_reason="stop"), response(extracted)])
    rows = transcript(SCENARIOS[0][1], correction)
    workspace, sessions, coordinator, req, consolidator = setup(tmp_path, provider, rows)
    await consolidator.compact_idle_session(req.session_key, runtime=LLMRuntime.capture(
        provider, provider.get_default_model(), context_window_tokens=200000))
    if mode in {"both_disabled", "episode_only"}:
        monkeypatch.setenv("STORYPAL_AUTO_NOTE", "0")
    if mode in {"both_disabled", "note_only"}:
        monkeypatch.setenv("STORYPAL_AUTO_EPISODE", "0")
    await maintain(coordinator, req)
    records = coordinator.episodes.list_records(req.sender_id)
    note = coordinator.notes.read(req.sender_id)
    if mode == "both_disabled":
        assert len(provider.calls) == 1 and coordinator.episodes.processed(req.sender_id, req.session_key) == 0
    else:
        assert len(provider.calls) == 2 and coordinator.episodes.processed(req.sender_id, req.session_key) == len(rows)
    assert bool(records) == (mode == "episode_only")
    assert ("聊转折时先分清" in note) == (mode == "note_only")


@pytest.mark.asyncio
async def test_extraction_cannot_quote_beyond_visible_truncated_frame(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYPAL_AUTO_NOTE", "1")
    monkeypatch.setenv("STORYPAL_AUTO_EPISODE", "1")
    correction = "前缀" * 800 + "末尾才有的重要纠正"
    rows = transcript(SCENARIOS[0][1], correction)
    item = payload("人物立场", "末尾才有的重要纠正")
    item["episodes"][0]["source_refs"][0]["quote"] = "末尾才有的重要纠正"
    provider = Provider([LLMResponse(content="有效checkpoint", finish_reason="stop"), response(item)])
    workspace, sessions, coordinator, req, consolidator = setup(tmp_path, provider, rows)
    await consolidator.compact_idle_session(req.session_key, runtime=LLMRuntime.capture(
        provider, provider.get_default_model(), context_window_tokens=200000))
    await maintain(coordinator, req)
    sent = json.loads(provider.calls[1]["messages"][1]["content"])
    assert sent["messages"][6]["truncated"] and "末尾才有的重要纠正" not in sent["messages"][6]["text"]
    assert coordinator.last_result["status"] == "deferred"
    assert coordinator.episodes.processed(req.sender_id, req.session_key) == 0
    assert not coordinator.episodes.list_records(req.sender_id)
