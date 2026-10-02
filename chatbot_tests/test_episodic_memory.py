"""M3-A 按日事实源：无模型调用、只使用隔离合成对话。"""
from copy import deepcopy

import pytest

from storypal_chatbot.episodic_memory import EpisodicMemoryStore


def messages():
    return [
        {"role": "user", "content": "我喜欢她救老师，但转得有点突然。", "timestamp": "2026-10-02T23:58:00+08:00"},
        {"role": "assistant", "content": "动机说得通不等于铺垫充分。", "timestamp": "2026-10-03T00:01:00+08:00"},
        {"role": "user", "content": "对，我质疑的是铺垫，不是她会不会救。", "timestamp": "2026-10-03T00:02:00+08:00"},
        {"role": "tool", "content": "检索失败，尚未查证。", "timestamp": "2026-10-03T00:03:00+08:00"},
        {"role": "user", "content": "未归档的后续内容", "timestamp": "2026-10-03T00:04:00+08:00"},
    ]


def candidate():
    return {"title": "区分动机与叙事铺垫", "context": "讨论救老师这一转折。",
            "development": "用户澄清喜欢结果但认为过程突然，关注铺垫而非行动能否成立。",
            "open_question": "前文是否给了足够铺垫仍未核验。",
            "source_refs": [{"message_index": 0, "quote": "转得有点突然"},
                            {"message_index": 2, "quote": "质疑的是铺垫"}]}


def store(tmp_path):
    result = EpisodicMemoryStore(tmp_path)
    assert result.bind_session("alice", "webui:demo", archived=0) == 0
    return result


def test_daily_markdown_restores_provenance_without_other_memory_writes(tmp_path):
    memory = store(tmp_path)
    result = memory.commit_archive("alice", "webui:demo", messages=messages(), archived_end=4,
                                   candidates=[candidate()], work_id="demo", max_seen_order=10)
    assert result["written"] == 1
    restored = EpisodicMemoryStore(tmp_path)
    assert restored.processed("alice", "webui:demo") == 4
    records = restored.list_records("alice")
    assert len(records) == 1 and records[0]["archive_range"] == [0, 4]
    assert records[0]["source_session_key"] == "webui:demo"
    assert [ref["message_index"] for ref in records[0]["source_refs"]] == [0, 2]
    assert "用户澄清" in records[0]["text"] and records[0]["max_seen_order"] == 10
    assert not restored.list_records("bob")
    files = [path.name for path in tmp_path.rglob("*.md")]
    assert files == ["2026-10-02.md"]  # 跨午夜按来源开始日期，不是写入时刻。
    assert not list(tmp_path.rglob("Note.md")) and not list(tmp_path.rglob("MEMORY.md"))


def test_binding_skips_old_archives_and_prevents_owner_takeover(tmp_path):
    memory = EpisodicMemoryStore(tmp_path)
    assert memory.bind_session("alice", "demo", archived=12) == 12
    assert memory.bind_session("alice", "demo", archived=20) == 12
    with pytest.raises(ValueError, match="owner"):
        memory.bind_session("bob", "demo", archived=12)
    assert not memory.list_records("bob")


@pytest.mark.parametrize("change", ["future", "invented_quote", "no_user", "missing_time", "invalid_scope"])
def test_invalid_candidates_do_not_advance_watermark_or_write(tmp_path, change):
    memory = store(tmp_path)
    sources, item = messages(), candidate()
    kwargs = {}
    if change == "future":
        item["source_refs"] = [{"message_index": 4, "quote": "后续内容"}]
    elif change == "invented_quote":
        item["source_refs"][0]["quote"] = "她以前参与了实验"
    elif change == "no_user":
        item["source_refs"] = [{"message_index": 3, "quote": "尚未查证"}]
    elif change == "missing_time":
        sources[0].pop("timestamp")
    else:
        kwargs = {"max_seen_order": 10}
    with pytest.raises(ValueError):
        memory.commit_archive("alice", "webui:demo", messages=sources, archived_end=4, candidates=[item], **kwargs)
    assert memory.processed("alice", "webui:demo") == 0 and not memory.list_records("alice")


def test_validating_all_candidates_before_writing(tmp_path):
    memory = store(tmp_path)
    invalid = deepcopy(candidate())
    invalid["source_refs"][0]["quote"] = "没有出现过的话"
    with pytest.raises(ValueError):
        memory.commit_archive("alice", "webui:demo", messages=messages(), archived_end=4,
                              candidates=[candidate(), invalid])
    assert not memory.list_records("alice")


def test_retry_after_watermark_write_failure_is_idempotent(tmp_path, monkeypatch):
    import storypal_chatbot.episodic_memory as module
    memory = store(tmp_path)
    original = module._atomic_write

    def fail_state(path, content):
        if path.suffix == ".json":
            raise OSError("模拟水位写入失败")
        original(path, content)

    monkeypatch.setattr(module, "_atomic_write", fail_state)
    with pytest.raises(OSError):
        memory.commit_archive("alice", "webui:demo", messages=messages(), archived_end=4, candidates=[candidate()])
    assert memory.processed("alice", "webui:demo") == 0
    assert len(memory.list_records("alice")) == 1
    monkeypatch.setattr(module, "_atomic_write", original)
    result = memory.commit_archive("alice", "webui:demo", messages=messages(), archived_end=4, candidates=[candidate()])
    assert result["written"] == 0 and result["processed"] == 4
    assert len(memory.list_records("alice")) == 1
    # 完成提交后再次重送本批，不重复写，也不解释成新经历。
    repeated = memory.commit_archive("alice", "webui:demo", messages=messages(), archived_end=4, candidates=[candidate()])
    assert repeated["duplicate"] and len(memory.list_records("alice")) == 1


def test_empty_extraction_advances_only_watermark(tmp_path):
    memory = store(tmp_path)
    assert memory.commit_archive("alice", "webui:demo", messages=messages(), archived_end=4,
                                 candidates=[])["processed"] == 4
    assert not memory.list_records("alice")


def test_runtime_story_block_cannot_be_quoted_as_user_words(tmp_path):
    from nanobot.runtime_context import RuntimeContextBlock, append_runtime_context, RUNTIME_CONTEXT_HISTORY_META
    memory = store(tmp_path)
    sources = messages()
    content, marker = append_runtime_context(sources[0]["content"], [
        RuntimeContextBlock("story_view", "已经证实老师之前参与了实验", replay=False)])
    sources[0]["content"] = content
    sources[0][RUNTIME_CONTEXT_HISTORY_META] = marker
    item = candidate()
    item["source_refs"][0]["quote"] = "已经证实老师之前参与了实验"
    with pytest.raises(ValueError, match="逐字出自原消息"):
        memory.commit_archive("alice", "webui:demo", messages=sources, archived_end=4, candidates=[item])
    assert not memory.list_records("alice")


def test_scope_comes_from_caller_and_markdown_body_is_read_source(tmp_path):
    memory = store(tmp_path)
    item = candidate()
    item.update({"work_id": "未来作品", "max_seen_order": 999})
    memory.commit_archive("alice", "webui:demo", messages=messages(), archived_end=4,
                          candidates=[item], work_id="demo", max_seen_order=10)
    record = memory.list_records("alice")[0]
    assert record["work_id"] == "demo" and record["max_seen_order"] == 10
    path = next(tmp_path.rglob("*.md"))
    path.write_text(path.read_text(encoding="utf-8").replace("讨论救老师这一转折。", "经用户核验后的情境。"), encoding="utf-8")
    assert "经用户核验后的情境" in memory.list_records("alice")[0]["text"]


def test_date_only_timestamp_is_not_invented_as_midnight(tmp_path):
    memory = store(tmp_path)
    sources = messages()
    sources[0]["timestamp"] = "2026-10-02"
    with pytest.raises(ValueError, match="原消息时间"):
        memory.commit_archive("alice", "webui:demo", messages=sources, archived_end=4, candidates=[candidate()])
