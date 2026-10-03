"""隔离query交接；原生Hook/Runner/Session，替身provider不计真实Agent query。"""
import json
from copy import deepcopy
from pathlib import Path

import pytest
from nanobot.agent.hook import AgentRunHookContext
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools import Tool, tool_parameters
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.runtime_context import RuntimeContextBlock, append_runtime_context, RUNTIME_CONTEXT_HISTORY_META
from nanobot.session.manager import Session, SessionManager

from storypal_chatbot.query_capture import IsolatedQueryCapture, export_query


def user(*, order=15, partial=True):
    state = {"active_work": "wandering_earth", "max_seen_order": order,
             "reader_position": {"unit_order": 16} if partial else None}
    content, marker = append_runtime_context("他为什么这样说？", [RuntimeContextBlock(
        "storypal_session_state", "用户已确认阅读状态：" + json.dumps(state, ensure_ascii=False))])
    return {"role": "user", "content": content, RUNTIME_CONTEXT_HISTORY_META: marker}


def call(query="哲学课 死亡 谜语", *, key="c-1", name="search_story"):
    return {"id": key, "type": "function", "function": {"name": name,
             "arguments": json.dumps({"query": query}, ensure_ascii=False)}}


def transcript():
    return [user(), {"role": "assistant", "content": None, "tool_calls": [call()]},
            {"role": "tool", "name": "search_story", "tool_call_id": "c-1", "content": "不应导出的原始证据"},
            {"role": "assistant", "content": "这里只是替身最终回复"}]


async def prepared(tmp_path, messages=None, *, origin="synthetic", reason="completed", injections=False):
    root = tmp_path / "experiments"
    workspace = root / "isolated" / "run" / "workspace"
    manager = SessionManager(workspace, sessions_root=root / "isolated" / "run" / "sessions")
    session = Session(key="cli:query-test")
    session.messages = deepcopy(transcript() if messages is None else messages)
    for index, message in enumerate(session.messages):
        message["timestamp"] = f"2026-10-03T15:00:{index:02d}+08:00"
    # 证明不导出非query内容／真实owner／私有provider字段。
    session.metadata = {"owner": "不导出的身份", "secret": "不导出的测试秘密"}
    capture = IsolatedQueryCapture(case_id="R20", session_key=session.key, root=root, origin=origin,
                                   model="openai-codex/gpt-6-luna" if origin == "agent_trace" else "test")
    await capture.before_run(AgentRunHookContext(messages=[session.messages[0]]))
    await capture.after_run(AgentRunHookContext(messages=deepcopy(session.messages), stop_reason=reason,
                                               final_content="替身最终回复", had_injections=injections))
    manager.save(session)
    path = manager._get_session_path(session.key)
    receipt = root / "isolated" / "receipt.json"
    return capture, path, receipt, root, session, manager


@pytest.mark.asyncio
async def test_seal_export_preserves_actual_query_and_full_boundary_not_partial_unit(tmp_path):
    capture, path, receipt, root, session, manager = await prepared(tmp_path)
    before = path.read_bytes()
    capture.seal(transcript=path, output=receipt)
    item = export_query(receipt, root=root)
    assert item["arguments"] == {"query": "哲学课 死亡 谜语"} and item["max_order"] == 15
    assert item["origin"] == "synthetic" and item["decision"] == "search"
    assert path.read_bytes() == before
    assert set(item) == {"case_id", "origin", "trace_ref", "work_id", "max_order", "decision", "tool_name", "arguments"}
    exported = json.dumps(item, ensure_ascii=False) + receipt.read_text(encoding="utf-8")
    for value in ["不应导出的原始证据", "替身最终回复", "不导出的身份", "不导出的测试秘密", session.key]:
        assert value not in exported


@pytest.mark.asyncio
async def test_skip_requires_completed_no_tool_turn(tmp_path):
    capture, path, receipt, root, session, manager = await prepared(tmp_path, [user(), {"role": "assistant", "content": "先不分析了"}])
    capture.seal(transcript=path, output=receipt)
    item = export_query(receipt, root=root)
    assert item["decision"] == "skip" and "arguments" not in item and "tool_name" not in item


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,injections", [("cancelled", False), ("error", False), ("max_iterations", False), ("completed", True)])
async def test_failed_interrupted_or_injected_turn_cannot_be_skip(tmp_path, reason, injections):
    capture, path, receipt, root, session, manager = await prepared(tmp_path, reason=reason, injections=injections)
    with pytest.raises(ValueError, match="完成"):
        capture.seal(transcript=path, output=receipt)
    assert not receipt.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing_result", "duplicate_id", "wrong_name", "changed_progress", "other_tool", "forged_scope"])
async def test_incomplete_or_ambiguous_routes_are_rejected(tmp_path, fault):
    messages = transcript()
    if fault == "missing_result":
        del messages[2]
    elif fault == "duplicate_id":
        messages[1]["tool_calls"].append(call())
    elif fault == "wrong_name":
        messages[2]["name"] = "get_story_evidence"
    elif fault == "changed_progress":
        messages[1]["tool_calls"] = [call(name="set_reading_progress")]
        messages[2]["name"] = "set_reading_progress"
    elif fault == "other_tool":
        messages[1]["tool_calls"] = [call(name="story_context")]
        messages[2]["name"] = "story_context"
    else:
        messages[0].pop(RUNTIME_CONTEXT_HISTORY_META)
    capture, path, receipt, root, session, manager = await prepared(tmp_path, messages)
    with pytest.raises(ValueError):
        capture.seal(transcript=path, output=receipt)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["query", "boundary", "time", "pending", "checkpoint", "wrong_session"])
async def test_after_run_receipt_cannot_export_changed_or_uncommitted_transcript(tmp_path, fault):
    capture, path, receipt, root, session, manager = await prepared(tmp_path)
    capture.seal(transcript=path, output=receipt)
    if fault == "query":
        session.messages[1]["tool_calls"][0] = call("改成别的查询")
    elif fault == "boundary":
        session.messages[0] = user(order=80)
        session.messages[0]["timestamp"] = "2026-10-03T15:00:00+08:00"
    elif fault == "time":
        session.messages[0]["timestamp"] = "2026-10-03T16:00:00+08:00"
    elif fault == "pending":
        session.metadata["pending_user_turn"] = True
    elif fault == "wrong_session":
        header = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        header["key"] = "另一会话"
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[0] = json.dumps(header, ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        path.with_suffix(".checkpoint.json").write_text("{}", encoding="utf-8")
    if fault not in {"wrong_session", "checkpoint"}:
        manager.save(session)
    with pytest.raises(ValueError):
        export_query(receipt, root=root)


@pytest.mark.asyncio
async def test_isolation_and_no_overwrite(tmp_path):
    capture, path, receipt, root, session, manager = await prepared(tmp_path)
    capture.seal(transcript=path, output=receipt)
    with pytest.raises(ValueError, match="覆盖"):
        capture.seal(transcript=path, output=receipt)
    with pytest.raises(ValueError, match="隔离目录"):
        export_query(receipt, root=tmp_path / "另一个根")
    fake = json.loads(receipt.read_text(encoding="utf-8"))
    fake["transcript_ref"] = "../正式用户.jsonl"
    receipt.write_text(json.dumps(fake, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="隔离目录"):
        export_query(receipt, root=root)


@pytest.mark.asyncio
async def test_synthetic_origin_is_rejected_by_algorithm_capture_not_counted_as_agent_query(tmp_path):
    from retrieval_experiments.replay import capture_trace, load_cases
    capture, path, receipt, root, session, manager = await prepared(tmp_path)
    capture.seal(transcript=path, output=receipt)
    with pytest.raises(ValueError, match="origin"):
        capture_trace([export_query(receipt, root=root)], load_cases())


@pytest.mark.asyncio
async def test_later_turns_do_not_change_the_selected_original_range(tmp_path):
    capture, path, receipt, root, session, manager = await prepared(tmp_path)
    capture.seal(transcript=path, output=receipt)
    before = export_query(receipt, root=root)
    session.messages.extend([{**user(), "timestamp": "2026-10-03T16:00:00+08:00"},
                             {"role": "assistant", "content": "后来一轮", "timestamp": "2026-10-03T16:00:01+08:00"}])
    manager.save(session)
    assert export_query(receipt, root=root) == before


@pytest.mark.asyncio
async def test_cli_keeps_synthetic_label_and_never_overwrites(tmp_path, monkeypatch):
    import storypal_chatbot.query_capture as module
    capture, path, receipt, root, session, manager = await prepared(tmp_path)
    capture.seal(transcript=path, output=receipt)
    output = root / "agent-queries" / "synthetic.jsonl"
    monkeypatch.setattr(module, "DEFAULT_ROOT", root)
    monkeypatch.setattr("sys.argv", ["export", "--receipt", str(receipt), "--output", str(output)])
    module.main()
    assert json.loads(output.read_text(encoding="utf-8"))["origin"] == "synthetic"
    original = output.read_bytes()
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2 and output.read_bytes() == original


@tool_parameters({"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})
class SearchStub(Tool):
    @property
    def name(self):
        return "search_story"

    @property
    def description(self):
        return "隔离工具替身，不读取小说"

    async def execute(self, query, **kwargs):
        return '{"anchors":[],"adjacent_context":[]}'

    def runtime_context_provider(self):
        async def provide(request):
            return RuntimeContextBlock("storypal_session_state", '用户已确认阅读状态：{"active_work":"wandering_earth","max_seen_order":15}')
        return provide


class ScriptedProvider(LLMProvider):
    def __init__(self):
        super().__init__(provider_name="test")
        self.calls = 0

    def get_default_model(self):
        return "openai-codex/gpt-6-luna"

    async def chat(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(content=None, finish_reason="tool_calls", tool_calls=[ToolCallRequest(
                id="actual-stub-call", name="search_story", arguments={"query": "哲学课 死亡 谜语"})])
        return LLMResponse(content="替身最终回复，不评估文学效果", finish_reason="stop")


@pytest.mark.asyncio
async def test_native_loop_hooks_then_disk_seal_export_without_real_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentLoop, "_register_default_tools", lambda self, **kwargs: None)
    root = tmp_path / "experiments"
    workspace = root / "isolated" / "native" / "workspace"
    sessions = SessionManager(workspace, sessions_root=root / "isolated" / "native" / "sessions")
    registry = ToolRegistry()
    registry.register(SearchStub())
    provider = ScriptedProvider()
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=workspace, tool_registry=registry,
                     tools_config=ToolsConfig(allowed_tools=["search_story"]), session_manager=sessions)
    loop.schedule_background = lambda coro: coro.close()
    capture = IsolatedQueryCapture(case_id="R20", session_key="cli:native-query", root=root)
    try:
        await loop.process_direct("他为什么这样说？", session_key="cli:native-query", hooks=[capture])
        assert provider.calls == 2
        assert capture.problem is None
        receipt = root / "isolated" / "native" / "receipt.json"
        capture.seal(transcript=sessions._get_session_path("cli:native-query"), output=receipt)
        result = export_query(receipt, root=root)
        assert result["origin"] == "synthetic" and result["arguments"] == {"query": "哲学课 死亡 谜语"}
        assert not list(workspace.rglob("Note.md")) and not list(workspace.rglob("MEMORY.md"))
    finally:
        await loop.aclose()
