"""StoryPal 对 nanobot 工具白名单补丁的行为回归测试。"""

from pathlib import Path

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.runner import AgentRunResult
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import load_config
from nanobot.providers.base import LLMProvider, LLMResponse


class _NoNetworkProvider(LLMProvider):
    """若测试意外触发模型请求，立即失败。"""

    def __init__(self) -> None:
        super().__init__(provider_name="test")

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict | None = None,
    ) -> LLMResponse:
        raise AssertionError("白名单测试不应调用真实模型")

    def get_default_model(self) -> str:
        return "test-model"


class _RecordingRunner:
    def __init__(self) -> None:
        self.tool_names: list[str] = []

    async def run(self, spec):
        self.tool_names = spec.tools.tool_names
        return AgentRunResult(final_content="已验证", messages=[])


@pytest.mark.asyncio
async def test_storypal_runtime_only_exposes_allowlisted_tools() -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / ".runtime" / "nanobot" / "storypal" / "config.json")
    loop = AgentLoop.from_config(
        config,
        MessageBus(),
        provider=_NoNetworkProvider(),
        tool_registry=ToolRegistry(),
    )
    recorder = _RecordingRunner()
    loop.runner = recorder
    try:
        await loop.process_direct("测试工具可见性", session_key="test:tool-allowlist")
        assert recorder.tool_names == sorted([
            "story_state",
            "reading_location",
            "search_story",
            "get_story_evidence",
            "story_context",
            "read_notes",
            "write_note",
            "read_reading_notebook",
            "write_reading_notebook",
        ])
    finally:
        await loop.aclose()