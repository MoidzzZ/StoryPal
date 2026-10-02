"""本地真实 LanceDB + 确定性向量替身，合成讨论；不是模型效果评测。"""
import json
from dataclasses import replace
from copy import deepcopy

import pytest
from nanobot import RequestContext
from nanobot.agent.tools.context import request_context
from storypal_chatbot.episodic_memory import EpisodicMemoryStore, _digest
from storypal_chatbot.episodic_recall import EpisodicRecallService, EpisodicRecallUnavailable, estimated_tokens
from storypal_chatbot.storage import ReadingProgressStore
from storypal_chatbot.tools import RecallInteractionHistoryTool


class Encoder:
    model_name = "合成向量替身-v1"

    def __init__(self):
        self.calls = []

    def encode(self, texts):
        self.calls.append(list(texts))
        return [[1., 0., 0.] if "铺垫" in text else [0., 1., 0.] for text in texts]


def add(workspace, *, owner="甲", session="websocket:旧讨论", work="wandering_earth", boundary=12,
        title="转折铺垫", development="用户质疑铺垫，不是认为行为不可能。"):
    store = EpisodicMemoryStore(workspace)
    store.bind_session(owner, session, archived=0)
    messages = [{"role": "user", "content": "我喜欢选择救人，但转得突然。", "timestamp": "2026-10-03T10:00:00+08:00"}]
    store.commit_archive(owner, session, messages=messages, archived_end=1, work_id=work,
                         max_seen_order=boundary, candidates=[{
                             "title": title, "context": "讨论角色转折。", "development": development,
                             "source_refs": [{"message_index": 0, "quote": "转得突然"}],
                         }])
    return store.list_records(owner)[-1]["id"]


def service(workspace, **kwargs):
    pytest.importorskip("lancedb")
    encoder = Encoder()
    return EpisodicRecallService(workspace, encoder_factory=lambda: encoder, **kwargs), encoder


def recall(svc, *, owner="甲", work="wandering_earth", boundary=12, query="之前说的铺垫"):
    return svc.recall(owner, work_id=work, max_seen_order=boundary, query=query)


def test_real_lance_prefilter_precedes_candidate_limit_and_owner_work_isolation(tmp_path):
    expected = add(tmp_path)
    for index in range(4):
        add(tmp_path, session=f"未来{index}", boundary=50 + index)
    add(tmp_path, owner="乙", session="别人的", boundary=1)
    add(tmp_path, session="其他作品", work="另一故事", boundary=1)
    add(tmp_path, session="未知范围", work=None, boundary=None)
    svc, encoder = service(tmp_path, candidate_limit=1)
    result = recall(svc)
    assert [r["id"] for r in result["episodes"]] == [expected]
    assert len(encoder.calls[0]) == 5  # 同用户同作品，索引可含未来，但查询预过滤。
    assert all("发生时间" not in text and "来源：" not in text and "[e-" not in text for text in encoder.calls[0])
    assert result["episodes"][0]["source_refs"][0]["quote"] == "转得突然"
    assert result["episodes"][0]["source_session_ref"] == _digest("websocket:旧讨论")
    assert "websocket:旧讨论" not in json.dumps(result, ensure_ascii=False)
    assert result["estimated_tokens"] == estimated_tokens(result) <= svc.token_budget


def test_restart_reuses_index_and_query_only_encodes_once(tmp_path):
    add(tmp_path)
    svc, encoder = service(tmp_path)
    first = recall(svc)
    assert len(encoder.calls) == 2
    restored = EpisodicRecallService(tmp_path, encoder_factory=lambda: encoder)
    assert recall(restored) == first
    assert len(encoder.calls) == 3
    assert not list(tmp_path.rglob("Note.md")) and not list(tmp_path.rglob("MEMORY.md"))


def test_markdown_edit_rebuilds_index_not_stale_cached_text(tmp_path):
    add(tmp_path)
    svc, encoder = service(tmp_path)
    first = recall(svc)
    path = next(svc.store._memory_root("甲").glob("*.md"))
    path.write_text(path.read_text(encoding="utf-8").replace("质疑铺垫", "再次澄清铺垫"), encoding="utf-8")
    second = recall(svc)
    assert second["source_version"] != first["source_version"]
    assert "再次澄清" in second["episodes"][0]["text"] and len(encoder.calls) == 4


def test_empty_source_does_not_load_model_or_search_leftover_cache(tmp_path):
    add(tmp_path)
    svc, encoder = service(tmp_path)
    recall(svc)
    path = next(svc.store._memory_root("甲").glob("*.md"))
    path.unlink()
    assert recall(svc)["reason"] == "no_eligible_episodes"
    assert len(encoder.calls) == 2
    assert recall(svc, owner="无记录用户")["episodes"] == []


def test_progress_rollback_does_not_read_future_records_or_load_encoder(tmp_path):
    add(tmp_path, boundary=20)
    svc, encoder = service(tmp_path)
    assert recall(svc, boundary=19)["episodes"] == [] and not encoder.calls
    assert recall(svc, boundary=20)["status"] == "ok"


def test_threshold_and_whole_response_budget_are_distinct_from_unavailability(tmp_path):
    add(tmp_path)
    svc, encoder = service(tmp_path, token_budget=128)
    result = recall(svc)
    assert result["reason"] == "token_budget" and result["budget_dropped"] == 1
    assert result["estimated_tokens"] == estimated_tokens(result) <= 128
    assert recall(svc, query="角色衣服")["reason"] == "below_threshold"


def test_budget_can_fill_more_than_two_records(tmp_path):
    for index in range(4):
        add(tmp_path, session=f"讨论{index}")
    svc, encoder = service(tmp_path, token_budget=4000)
    result = recall(svc)
    assert len(result["episodes"]) == 4 and result["budget_dropped"] == 0
    assert result["estimated_tokens"] <= 4000


def test_missing_local_model_is_error_and_never_attempts_remote_download(tmp_path, monkeypatch):
    add(tmp_path)
    monkeypatch.setenv("STORYPAL_EPISODE_MODEL", str(tmp_path / "不存在"))
    with pytest.raises(EpisodicRecallUnavailable, match="不会自动联网"):
        recall(EpisodicRecallService(tmp_path))


@pytest.mark.parametrize("field,value", [("max_seen_order", True), ("owner_hash", "另一个用户"),
                                         ("time_end", "2026-10-04T10:00:00+08:00"), ("archive_range", [0, 0])])
def test_corrupt_markdown_fails_closed_before_embedding(tmp_path, field, value):
    add(tmp_path)
    svc, encoder = service(tmp_path)
    path = next(svc.store._memory_root("甲").glob("*.md"))
    text = path.read_text(encoding="utf-8")
    line = next(line for line in text.splitlines() if line.startswith("<!-- episode-meta "))
    meta = json.loads(line[len("<!-- episode-meta "):-len(" -->")])
    meta[field] = value
    path.write_text(text.replace(line, "<!-- episode-meta " + json.dumps(meta, ensure_ascii=False) + " -->"), encoding="utf-8")
    with pytest.raises(ValueError):
        recall(svc)
    assert not encoder.calls


def test_invalid_vector_does_not_publish_index_version(tmp_path):
    add(tmp_path)
    svc, encoder = service(tmp_path)
    encoder.encode = lambda texts: [[float("nan"), 0.] for _ in texts]
    with pytest.raises(ValueError, match="向量"):
        recall(svc)
    assert not list(tmp_path.rglob("version.json"))


def test_corrupt_cached_index_cannot_supply_foreign_ids(tmp_path):
    add(tmp_path)
    svc, encoder = service(tmp_path)
    recall(svc)
    import lancedb
    root = svc.store.root / _digest("甲") / "index" / _digest("wandering_earth")
    db = lancedb.connect(str(root / "vectors.lance"))
    db.create_table("episodes", data=[{"id": "未知用户的id", "ord": 1, "vector": [1., 0., 0.]}], mode="overwrite")
    with pytest.raises(ValueError, match="范围不一致"):
        recall(svc)


def test_environment_config_is_server_controlled(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYPAL_EPISODE_THRESHOLD", "0.6")
    monkeypatch.setenv("STORYPAL_EPISODE_TOKEN_BUDGET", "700")
    svc = EpisodicRecallService.from_environment(tmp_path)
    assert svc.threshold == 0.6 and svc.token_budget == 700
    monkeypatch.setenv("STORYPAL_EPISODE_THRESHOLD", "nan")
    with pytest.raises(ValueError, match="阈值"):
        EpisodicRecallService.from_environment(tmp_path)


@pytest.mark.asyncio
async def test_tool_uses_server_owner_and_boundary_not_model_kwargs(tmp_path):
    add(tmp_path)
    svc, encoder = service(tmp_path)
    ReadingProgressStore(tmp_path).set("甲", active_work="wandering_earth", max_seen_order=12)
    tool = RecallInteractionHistoryTool(tmp_path, service=svc)
    request = RequestContext(channel="websocket", sender_id="甲", session_key="websocket:新会话", chat_id="测试")
    before = deepcopy(tool.state_store.get("甲"))
    with request_context(request):
        result = json.loads(await tool.execute(query="铺垫", owner="乙", work_id="其他", max_seen_order=100))
        assert result["status"] == "ok"
    assert tool.state_store.get("甲") == before and tool.read_only
    assert set(tool.parameters["properties"]) == {"query"}
    request = replace(request, sender_id="乙")
    with request_context(request):
        result = await tool.execute(query="铺垫")
        assert result.is_error and "已确认阅读范围" in str(result)


@pytest.mark.asyncio
async def test_tool_dependency_failure_is_error_not_empty(tmp_path):
    add(tmp_path)
    def unavailable():
        raise EpisodicRecallUnavailable("本地经历向量模型无法加载")
    svc = EpisodicRecallService(tmp_path, encoder_factory=unavailable)
    ReadingProgressStore(tmp_path).set("甲", active_work="wandering_earth", max_seen_order=12)
    request = RequestContext(channel="websocket", sender_id="甲", session_key="websocket:新会话", chat_id="测试")
    with request_context(request):
        result = await RecallInteractionHistoryTool(tmp_path, service=svc).execute(query="铺垫")
    assert result.is_error and "无法加载" in str(result)
