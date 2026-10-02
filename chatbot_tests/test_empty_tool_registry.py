"""空注册表是禁止工具，不应退回默认全集；无真实模型调用。"""
from copy import deepcopy

import pytest
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools import Tool, ToolRegistry, tool_parameters
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.runtime_context import RuntimeContextBlock
from nanobot.session.manager import SessionManager


@tool_parameters({"type": "object", "properties": {}})
class SentinelTool(Tool):
    @property
    def name(self):
        return "test_sentinel"

    @property
    def description(self):
        return "仅用于测试禁止执行和上下文隔离"

    async def execute(self, **kwargs):
        self.executed = True
        return "工具执行成功"

    def runtime_context_provider(self):
        async def provide(request):
            return RuntimeContextBlock("test_sentinel", "禁止泄漏的工具上下文")
        return provide


class Provider(LLMProvider):
    def __init__(self, request_forbidden=False):
        super().__init__(provider_name="test")
        self.calls = []
        self.request_forbidden = request_forbidden

    def get_default_model(self):
        return "openai-codex/gpt-6-luna"

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": deepcopy(messages), "tools": deepcopy(tools)})
        if self.request_forbidden and len(self.calls) == 1:
            return LLMResponse(content=None, finish_reason="tool_calls", tool_calls=[
                ToolCallRequest(id="forbidden", name="test_sentinel", arguments={})])
        return LLMResponse(content="隔离回答", finish_reason="stop")


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed,empty_override,expected", [
    ([], False, []), (["missing_tool"], False, []),
    (["test_sentinel"], False, ["test_sentinel"]),
    (None, False, ["test_sentinel"]), (None, True, []),
])
async def test_loop_preserves_empty_registry_through_context_and_runner(tmp_path, monkeypatch, allowed, empty_override, expected):
    monkeypatch.setattr(AgentLoop, "_register_default_tools", lambda self, **kwargs: None)
    provider = Provider()
    registry = ToolRegistry()
    registry.register(SentinelTool())
    workspace = tmp_path / "workspace"
    sessions = SessionManager(workspace, sessions_root=tmp_path / "sessions")
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=workspace, session_manager=sessions,
                     tool_registry=registry, tools_config=ToolsConfig(allowed_tools=allowed))
    loop.schedule_background = lambda coro: coro.close()
    try:
        result = await loop.process_direct("只需要直接回答", session_key="cli:empty-policy",
                                          tools=ToolRegistry() if empty_override else None)
        assert result.content == "隔离回答"
        assert len(provider.calls) == 1
        names = [item["function"]["name"] for item in provider.calls[0]["tools"] or []]
        assert names == expected
        visible = str(provider.calls[0]["messages"])
        assert ("禁止泄漏的工具上下文" in visible) == bool(expected)
    finally:
        await loop.aclose()


@pytest.mark.asyncio
async def test_unlisted_model_tool_call_is_rejected_not_executed(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentLoop, "_register_default_tools", lambda self, **kwargs: None)
    provider = Provider(request_forbidden=True)
    sentinel = SentinelTool()
    registry = ToolRegistry()
    registry.register(sentinel)
    workspace = tmp_path / "workspace"
    sessions = SessionManager(workspace, sessions_root=tmp_path / "sessions")
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=workspace, session_manager=sessions,
                     tool_registry=registry, max_iterations=2, tools_config=ToolsConfig(allowed_tools=[]))
    loop.schedule_background = lambda coro: coro.close()
    try:
        result = await loop.process_direct("不允许执行工具", session_key="cli:empty-execute")
        assert result.content == "隔离回答"
        assert not getattr(sentinel, "executed", False)
        assert all(not item["tools"] for item in provider.calls)
        observations = [m["content"] for m in provider.calls[1]["messages"] if m["role"] == "tool"]
        assert any("not found" in item for item in observations)
    finally:
        await loop.aclose()
