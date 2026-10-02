"""C2：程序契约测试，不把伪造 provider 输出当作语义验收。"""
from copy import deepcopy
from importlib.resources import files

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.agent.memory import Consolidator, MemoryArchiver, MemoryStore
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest
from nanobot.session.manager import Session, SessionManager
from nanobot.session.summary import session_summary_from_metadata
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.utils.prompt_templates import render_template
from nanobot.utils.workspace_prompts import WORKSPACE_PROMPT_MAX_CHARS
from storypal_chatbot.bootstrap import install_persona


class Provider(LLMProvider):
    def __init__(self, responses):
        super().__init__(provider_name="test")
        self.generation = GenerationSettings(max_tokens=1024, temperature=0.1)
        self.responses = iter(responses)
        self.calls = []

    def get_default_model(self):
        return "openai-codex/gpt-6-luna"

    async def chat(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def messages(**kwargs):
    prior = kwargs.get("session_summary")
    return [{"role": "system", "content": prior["text"] if prior else "测试归档"},
            *kwargs["history"], {"role": "user", "content": kwargs["current_message"]}]


def test_archive_template_install_preserves_user_edit(tmp_path):
    archive = tmp_path / "prompts/consolidator_archive.md"
    installed = install_persona(tmp_path)
    template = files("storypal_chatbot").joinpath("persona/prompts/consolidator_archive.md").read_text(encoding="utf-8")
    assert archive in installed and archive.read_text(encoding="utf-8") == template
    for tag in ["[读者观点]", "[暂定解释]", "[修正轨迹]", "[未解问题]"]:
        assert tag in template
    assert "失败" in template and "替换式" in template and "不在此摘要写入" in template
    archive.write_text("用户维护的共读归档规则", encoding="utf-8")
    assert archive not in install_persona(tmp_path)
    assert archive.read_text(encoding="utf-8") == "用户维护的共读归档规则"


def test_archive_override_scope_reload_and_builtin_fallback(tmp_path):
    archiver = MemoryArchiver(MemoryStore(tmp_path), messages, lambda: [])
    builtin = render_template("agent/consolidator_archive.md", strip=True)
    assert archiver._archive_template() == builtin
    path = tmp_path / "prompts/consolidator_archive.md"
    path.parent.mkdir()
    path.write_text("全局共读模板", encoding="utf-8")
    scoped = tmp_path / "project"
    scoped_file = scoped / "prompts/consolidator_archive.md"
    scoped_file.parent.mkdir(parents=True)
    assert archiver._archive_template(scoped) == "全局共读模板"
    scoped_file.write_text("项目专用模板", encoding="utf-8")
    assert archiver._archive_template(scoped) == "项目专用模板"
    scoped_file.write_text("更新后的项目模板", encoding="utf-8")
    assert archiver._archive_template(scoped) == "更新后的项目模板"
    scoped_file.write_text(" ", encoding="utf-8")
    assert archiver._archive_template(scoped) == "全局共读模板"
    path.write_bytes(b'\xff\xfe\xff')
    assert archiver._archive_template(scoped) == builtin


def test_archive_override_is_capped(tmp_path):
    path = tmp_path / "prompts/consolidator_archive.md"
    path.parent.mkdir()
    path.write_text("字" * (WORKSPACE_PROMPT_MAX_CHARS + 100), encoding="utf-8")
    archiver = MemoryArchiver(MemoryStore(tmp_path), messages, lambda: [])
    assert len(archiver._archive_template()) <= WORKSPACE_PROMPT_MAX_CHARS + 20
    assert len(archiver._archive_prompt_oversize_logged) == 1
    archiver._archive_template()
    assert len(archiver._archive_prompt_oversize_logged) == 1


@pytest.mark.asyncio
async def test_checkpoint_replaces_previous_and_survives_reload_without_other_writes(tmp_path):
    install_persona(tmp_path)
    store = MemoryStore(tmp_path)
    sessions = SessionManager(tmp_path)
    summaries = ["[读者观点] 旧读者判断\n[未解问题] 还没查证", "[修正轨迹] 旧读者判断 → 最新修正；用户分清了事实和解读\n[未解问题] 仍未查证"]
    provider = Provider([LLMResponse(content=summary, finish_reason="stop") for summary in summaries])
    runtime = LLMRuntime.capture(provider, provider.get_default_model(), context_window_tokens=200000)
    consolidator = Consolidator(store, sessions, messages, lambda: [])
    session = sessions.get_or_create("cli:c2")
    session.add_message("user", "旧读者判断")
    session.add_message("assistant", "暂定解释，不是事实")
    for index in range(5):
        session.add_message("user", f"其它话题{index}")
        session.add_message("assistant", "只是闲聊")
    sessions.save(session)
    before = {path: path.read_bytes() for path in tmp_path.glob("*.md")}
    await consolidator.compact_idle_session(session.key, runtime=runtime)
    session = sessions.get_or_create(session.key)
    session.add_message("user", "最新修正：前面不能算作事实")
    session.add_message("assistant", "承认修正，问题尚未核实")
    for index in range(5):
        session.add_message("user", f"继续闲聊{index}")
        session.add_message("assistant", "不新增剧情依据")
    sessions.save(session)
    await consolidator.compact_idle_session(session.key, runtime=runtime)
    assert provider.calls[1]["messages"][0]["content"] == summaries[0]
    assert "共读交接摘要" in provider.calls[1]["messages"][-1]["content"]
    assert len(provider.calls) == 2
    restored = SessionManager(tmp_path).get_or_create(session.key)
    summary = session_summary_from_metadata(restored.metadata, fallback_last_active=restored.updated_at)
    assert summary["text"] == summaries[1]
    assert restored.last_archived == len(restored.messages) == 24
    assert "旧读者判断" not in str(restored.get_history())
    assert "最新修正" not in str(restored.get_history())
    model_input = ContextBuilder(tmp_path).build_messages(history=restored.get_history(), current_message="继续前面的理解", session_summary=summary)
    assert summaries[1] in model_input[0]["content"]
    assert all(path.read_bytes() == content for path, content in before.items())
    assert not (tmp_path / ".storypal").exists()
    assert len(store.read_unprocessed_history(since_cursor=0)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    RuntimeError("测试调用失败"), LLMResponse(content="截断摘要", finish_reason="length"),
    LLMResponse(content="", finish_reason="stop"),
    LLMResponse(content=None, finish_reason="tool_calls", tool_calls=[ToolCallRequest(id="x", name="search_story", arguments={})]),
])
async def test_failed_archive_retains_previous_and_raw_fallback(tmp_path, response):
    provider = Provider([response])
    runtime = LLMRuntime.capture(provider, provider.get_default_model(), context_window_tokens=200000)
    store = MemoryStore(tmp_path)
    archiver = MemoryArchiver(store, messages, lambda: [])
    session = Session(key="cli:c2-failure")
    session.metadata["_last_summary"] = {"text": "已保留的旧观点", "last_active": session.updated_at.isoformat()}
    session.add_message("user", "本轮重要修正")
    session.add_message("assistant", "尚待查证")
    result = await archiver.archive_session(session, archive_end=2, runtime=runtime, input_token_budget=180000)
    assert "已保留的旧观点" in result and "本轮重要修正" in result and "[RAW]" in result
    assert session.last_archived == 0
    assert session.metadata["_last_summary"]["text"] == "已保留的旧观点"
