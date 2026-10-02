"""C3 的加载、工具/引用链程序契约；不将替身输出当模型决策评测。"""
import json
from copy import deepcopy
from importlib.resources import files
from pathlib import Path

import pytest
from nanobot import RequestContext
from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.agent.skills import SkillsLoader, parse_skill_metadata, valid_skill_metadata
from nanobot.agent.tools import ToolRegistry
from nanobot.agent.tools.context import request_context
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.session.manager import SessionManager
from storypal_chatbot.bootstrap import install_persona
from storypal_chatbot.context_packer import ContextPacker, DROP_TOKEN_BUDGET
from storypal_chatbot.storage import ReadingProgressStore
from storypal_chatbot.story_memory import StoryMemoryService, StoryMemoryError
from storypal_chatbot.tools import SearchStoryTool, StoryContextTool, GetStoryEvidenceTool

NAME = "continuous-story-discussion"
RESOURCE = "persona/skills/continuous-story-discussion/SKILL.md"


def test_skill_packaging_identity_and_preserving_custom_text(tmp_path):
    written = install_persona(tmp_path)
    path = tmp_path / "skills" / NAME / "SKILL.md"
    source = files("storypal_chatbot").joinpath(RESOURCE).read_text(encoding="utf-8")
    assert path in written and path.read_text(encoding="utf-8") == source
    meta = parse_skill_metadata(source)
    assert valid_skill_metadata(meta, NAME)
    loader = SkillsLoader(tmp_path)
    assert NAME in loader.get_always_skills()
    for method in ["一、连续理解", "二、按缺口核验", "三、手账回看"]:
        assert method in source
    path.write_text("用户自定义方法，不应覆盖", encoding="utf-8")
    assert path not in install_persona(tmp_path)
    assert path.read_text(encoding="utf-8") == "用户自定义方法，不应覆盖"


def test_native_context_injects_once_and_can_disable_skill(tmp_path):
    install_persona(tmp_path)
    builder = ContextBuilder(tmp_path)
    prompt = builder.build_system_prompt(include_memory=False)
    assert prompt.count("### Skill: " + NAME) == 1
    assert "metadata:\n  nanobot:" not in prompt
    assert "当前片段、服务端已读故事视图、近期对话和共读摘要" in prompt
    assert "优先检索再回答" not in prompt
    disabled = ContextBuilder(tmp_path, disabled_skills=[NAME]).build_system_prompt(include_memory=False)
    assert "### Skill: " + NAME not in disabled
    path = tmp_path / "skills" / NAME / "SKILL.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n下一轮生效的测试方法", encoding="utf-8")
    assert "下一轮生效的测试方法" in builder.build_system_prompt(include_memory=False)


@pytest.mark.asyncio
async def test_real_loop_sees_skill_without_file_tools_or_extra_model_call(tmp_path, monkeypatch):
    class Provider(LLMProvider):
        def __init__(self):
            super().__init__(provider_name="test")
            self.calls = []

        def get_default_model(self):
            return "openai-codex/gpt-6-luna"

        async def chat(self, messages, tools=None, **kwargs):
            self.calls.append({"messages": deepcopy(messages), "tools": deepcopy(tools)})
            return LLMResponse(content="替身只检查接线，不评估回复质量", finish_reason="stop")

    monkeypatch.setattr(AgentLoop, "_register_default_tools", lambda self, **kwargs: None)
    workspace = tmp_path / "workspace"
    install_persona(workspace)
    provider = Provider()
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=workspace,
                     tools_config=ToolsConfig(allowed_tools=[]),
                     session_manager=SessionManager(workspace, sessions_root=tmp_path / "sessions"))
    loop.schedule_background = lambda coro: coro.close()
    try:
        await loop.process_direct("先不分析了，只想聊聊现在的感受", session_key="cli:c3")
        assert len(provider.calls) == 1 and not provider.calls[0]["tools"]
        system = provider.calls[0]["messages"][0]["content"]
        assert system.count("### Skill: " + NAME) == 1
        assert "用户只想表达感受或暂停分析时，不强推分析" in system
    finally:
        await loop.aclose()


@pytest.mark.asyncio
async def test_pipeline_name_hint_to_structured_history_to_evidence_is_boundary_safe(tmp_path, monkeypatch):
    code = Path(__file__).resolve().parents[1] / "story_mem/code"
    if not code.is_dir():
        pytest.skip("需要本地独立 StoryMem 协作仓库，不读取正式小说数据")
    monkeypatch.syspath_prepend(str(code))
    from storymemory.adapter import StoryMemory
    from storypipe.model import StoryUnit, save_units
    from storypal_chatbot.story_memory import PipelineStoryMemoryBackend
    data = tmp_path / "data"
    units = []
    for order in [1, 2]:
        item = StoryUnit("demo", f"d-{order}", order, 1, "第一章", order, order, "名称线索测试")
        item.context_refs = ["甲"]
        item.entity_updates = [{"kind": "character", "name": "甲", "delta": "测试变化"}]
        item.state_snapshot = {"characters": [{"name": "甲", "status": "当前状态"}], "last_order": order}
        units.append(item)
    save_units(data / "demo/03_extracted/units_extracted.jsonl", units)
    adapter = StoryMemory(data, retrieval="fts")
    backend = PipelineStoryMemoryBackend(adapter_factory=lambda root, retrieval: adapter, retrieval="fts")
    service = StoryMemoryService(backend)
    workspace = tmp_path / "workspace"
    ReadingProgressStore(workspace).set("reader", active_work="demo", max_seen_order=1)
    request = RequestContext(channel="websocket", sender_id="reader", session_key="webui:c3", chat_id="test")
    with request_context(request):
        search = json.loads(await SearchStoryTool(workspace, service).execute(query="名称线索"))
        hint = search["anchors"][0]["metadata"]["context_refs"][0]
        context = json.loads(await StoryContextTool(workspace, service).execute(kind="entity", query=hint))
        assert context["history"] and all(row["order"] <= 1 for row in context["history"])
        unit_id = context["history"][0]["unit_id"]
        result = json.loads(await GetStoryEvidenceTool(workspace, service).execute(unit_id=unit_id))
        assert result["unit_id"] == "d-1" and result["metadata"]["context_refs"] == ["甲"]
        denied = await GetStoryEvidenceTool(workspace, service).execute(unit_id="d-2")
        assert denied.is_error
        missing = json.loads(await StoryContextTool(workspace, service).execute(kind="entity", query="不存在的名称"))
        assert not missing["history"]
    assert ReadingProgressStore(workspace).get("reader")["max_seen_order"] == 1


def test_reference_metadata_is_counted_in_existing_content_budget():
    item = {"work_id": "demo", "unit_id": "d-1", "order": 1, "summary": "短", "raw_text": "短", "metadata": {"context_refs": ["很长的名称" * 100]}}
    packed = ContextPacker(token_budget=20).pack([item], work_id="demo", max_seen_order=1)
    assert not packed.anchors and packed.dropped[0]["reason"] == DROP_TOKEN_BUDGET
    assert ContextPacker(token_budget=20).pack([{**item, "metadata": {}}], work_id="demo", max_seen_order=1).anchors
