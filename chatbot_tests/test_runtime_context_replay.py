"""通用临时上下文补丁的历史回放契约，包括重启与中途插入。"""
from copy import deepcopy

import pytest
from nanobot.agent.runner import AgentRunner
from nanobot.runtime_context import (
    RuntimeContextBlock, append_runtime_context, replay_history_message, public_history_message,
    RUNTIME_CONTEXT_HISTORY_META, RUNTIME_CONTEXT_MESSAGE_META,
)
from nanobot.session.manager import SessionManager


@pytest.mark.parametrize("visible", ["用户原话", [{"type": "text", "text": "用户原话"}, {"type": "image_url", "image_url": {"url": "data:test"}}]])
def test_exact_strip_preserves_original_and_other_context(visible):
    content, marker = append_runtime_context(visible, [RuntimeContextBlock("note", "约定"), RuntimeContextBlock("view", "当前视图", replay=False)])
    message = {"role": "user", "content": content, RUNTIME_CONTEXT_HISTORY_META: marker}
    original = deepcopy(message)
    replay = replay_history_message(message)
    expected, _ = append_runtime_context(visible, [RuntimeContextBlock("note", "约定")])
    assert replay["content"] == expected and message == original
    assert public_history_message(replay)["content"] == visible
    assert public_history_message(message)["content"] == visible


def test_identical_text_is_not_deleted_from_user_or_persistent_block():
    content, marker = append_runtime_context("重复", [RuntimeContextBlock("note", "重复"), RuntimeContextBlock("view", "重复", replay=False)])
    replay = replay_history_message({"content": content, RUNTIME_CONTEXT_HISTORY_META: marker})
    assert replay["content"] == "重复\n\n重复"
    broken = {"content": content + "真实追加", RUNTIME_CONTEXT_HISTORY_META: marker}
    assert replay_history_message(broken) == broken


def test_session_restart_tool_results_and_current_view(tmp_path):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:test")
    for turn in range(2):
        content, marker = append_runtime_context(f"用户观点{turn}", [RuntimeContextBlock("note", "非剧情约定"), RuntimeContextBlock("view", f"旧视图{turn}", replay=False)])
        session.add_message("user", content, **{RUNTIME_CONTEXT_HISTORY_META: marker})
        session.add_message("assistant", "", tool_calls=[{"id": f"c{turn}", "type": "function", "function": {"name": "search_story", "arguments": "{}"}}])
        session.add_message("tool", "原文证据保留", tool_call_id=f"c{turn}", name="search_story")
        session.add_message("assistant", "暂时解读")
    manager.save(session)
    loaded = SessionManager(tmp_path).get_or_create("websocket:test")
    history = loaded.get_history()
    assert "旧视图" not in str(history)
    assert sum(item["content"] == "原文证据保留" for item in history) == 2
    assert all("旧视图" in item["content"] for item in loaded.messages if item["role"] == "user")
    assert "非剧情约定" in str(history) and "用户观点0" in str(history)
    current, _ = append_runtime_context("继续聊", [RuntimeContextBlock("view", "当前视图", replay=False)])
    model_messages = [*history, {"role": "user", "content": current}]
    assert str(model_messages).count("当前视图") == 1


def test_injected_messages_keep_per_block_policy():
    left, lm = append_runtime_context("前一句", [RuntimeContextBlock("legacy-a", "旧常驻A"), RuntimeContextBlock("legacy-b", "旧常驻B")])
    right, rm = append_runtime_context("新一句", [RuntimeContextBlock("note", "约定"), RuntimeContextBlock("view", "临时视图", replay=False)])
    messages = [{"role": "user", "content": left, "_meta": {RUNTIME_CONTEXT_MESSAGE_META: lm}}]
    AgentRunner._append_injected_messages(messages, [{"role": "user", "content": right, "_meta": {RUNTIME_CONTEXT_MESSAGE_META: rm}}])
    merged = messages[0]
    replay = replay_history_message({"role": "user", "content": merged["content"], RUNTIME_CONTEXT_HISTORY_META: merged["_meta"][RUNTIME_CONTEXT_MESSAGE_META]})
    assert "前一句" in replay["content"] and "新一句" in replay["content"]
    assert "旧常驻A" in replay["content"] and "旧常驻B" in replay["content"] and "约定" in replay["content"]
    assert "临时视图" not in replay["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("volatile", [True, False])
async def test_actual_loop_rebuilds_opaque_state_only_when_needed(tmp_path, volatile):
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools import ToolRegistry, Tool, tool_parameters
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import ToolsConfig
    from nanobot.providers.base import LLMProvider, LLMResponse, ProviderConversationState

    class Provider(LLMProvider):
        def __init__(self):
            super().__init__(provider_name="test")
            self.contexts = []
            self.messages = []

        def get_default_model(self):
            return "openai-codex/gpt-6-luna"

        def can_resume_conversation_state(self, state, model=None):
            return True

        async def chat(self, messages, **kwargs):
            self.messages.append(deepcopy(messages))
            return LLMResponse(content="隔离测试回复", finish_reason="stop", provider_state=ProviderConversationState(
                kind="openai_responses", provider="test", model=self.get_default_model(), version=1, payload={"opaque": "旧输入可能已打包"}))

        async def chat_with_context(self, *, provider_context, **kwargs):
            self.contexts.append(provider_context.conversation_state)
            return await self.chat(**kwargs)

    provider = Provider()
    @tool_parameters({"type": "object", "properties": {}})
    class CurrentContextTool(Tool):
        @property
        def name(self):
            return "view_supplier"

        @property
        def description(self):
            return "测试上下文入口"

        async def execute(self, **kwargs):
            return "测试不调用这个工具"

        def runtime_context_provider(self):
            async def provide(request):
                return RuntimeContextBlock("view", "本轮唯一当前视图", replay=not volatile)
            return provide

    registry = ToolRegistry()
    registry.register(CurrentContextTool())
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path,
        model=provider.get_default_model(), tool_registry=registry, tools_config=ToolsConfig(allowed_tools=["view_supplier"]))
    loop.schedule_background = lambda coro: coro.close()
    session = loop.sessions.get_or_create("cli:c1-cache")
    content, marker = append_runtime_context("旧用户观点", [RuntimeContextBlock("view", "不应重复的旧视图", replay=not volatile)])
    session.add_message("user", content, **{RUNTIME_CONTEXT_HISTORY_META: marker})
    session.add_message("assistant", "旧解释")
    session.provider_state = ProviderConversationState(kind="openai_responses", provider="test", model=provider.get_default_model(), version=1, payload={"opaque": "旧缓存"})
    loop.sessions.save(session)
    loop.sessions.invalidate("cli:c1-cache")
    try:
        assert (await loop.process_direct("继续讨论", session_key="cli:c1-cache")).content == "隔离测试回复"
        assert provider.contexts
        visible_inputs = "\n".join(str(message.get("content", "")) for message in provider.messages[0])
        assert visible_inputs.count("本轮唯一当前视图") == 1
        if volatile:
            assert provider.contexts[0] is None
            assert "旧用户观点" in str(provider.messages[0])
            assert "不应重复的旧视图" not in str(provider.messages[0])
        else:
            assert provider.contexts[0] is not None
    finally:
        await loop.aclose()
