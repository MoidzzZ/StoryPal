"""进度复核工作流：合成原文、真实服务薄层、替身provider；无外发／GPU。"""
import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from nanobot import RequestContext
from nanobot.agent.tools.context import request_context

from storypal_chatbot.journal_recheck import JournalRecheckCoordinator, JournalRecheckStore, entry_revision
from storypal_chatbot.storage import ReadingNotebookStore, ReadingProgressStore
from storypal_chatbot.story_memory import StoryMemoryService
from storypal_chatbot.tools import SearchReadingJournalTool


class Backend:
    retrieval = "fts"

    def __init__(self):
        self.units = [{"work_id": "fiction", "unit_id": "f-10", "order": 10,
                       "raw_text": "阿岚当时反对危险实验。", "summary": "", "score": 0.3, "metadata": {}},
                      {"work_id": "fiction", "unit_id": "f-12", "order": 12,
                       "raw_text": "阿岚返回救老师，但没有同意重启实验。", "summary": "", "score": 0.5, "metadata": {}}]

    def search(self, work_id, query, *, max_order, top_k, filters=None):
        return [deepcopy(e) for e in self.units if e["work_id"] == work_id and e["order"] <= max_order][:top_k]

    def get_unit(self, work_id, unit_id):
        item = next((e for e in self.units if e["work_id"] == work_id and e["unit_id"] == unit_id), None)
        return {**deepcopy(item), "score": 1.0} if item else None


class Provider:
    def __init__(self, payload, *, during=None, finish_reason="stop", tool_calls=False):
        self.payload, self.during = payload, during
        self.finish_reason, self.tool_calls = finish_reason, tool_calls
        self.calls = []

    async def chat(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        assert kwargs["tools"] == []
        if self.during:
            await self.during()
        if isinstance(self.payload, Exception):
            raise self.payload
        return SimpleNamespace(content=json.dumps(self.payload, ensure_ascii=False),
                               finish_reason=self.finish_reason, has_tool_calls=self.tool_calls)


def req(provider, owner="alice"):
    return RequestContext(channel="websocket", chat_id="test", sender_id=owner,
        session_key="websocket:review", turn_id="t-progress", original_user_text="继续读到这里了",
        runtime=SimpleNamespace(provider=provider, model="openai-codex/gpt-6-luna",
                                generation=SimpleNamespace(reasoning_effort="low")))


def prepared(tmp_path):
    progress = ReadingProgressStore(tmp_path)
    progress.set("alice", active_work="fiction", max_seen_order=10)
    entry = ReadingNotebookStore(tmp_path).add("alice", active_work="fiction", anchor_order=10,
        anchor_text="旧位置", entry_type="prediction", content="我猜她救人也不会赞成危险实验", source_session_key="old")
    progress.set("alice", active_work="fiction", max_seen_order=12)
    view = {"work_id": "fiction", "previous_order": 10, "max_order": 12, "entries": [entry]}
    payload = {"reviews": [{"entry_id": entry["id"], "status": "supports",
        "analysis": "救人和认可实验仍是两回事；这条新行动暂时支持原猜测。",
        "evidence_refs": [{"unit_id": "f-12", "quote": "没有同意重启实验"}]}]}
    backend = Backend()
    coordinator = JournalRecheckCoordinator(tmp_path, service=StoryMemoryService(backend))
    return coordinator, view, payload, backend


async def run(coordinator, request, view=None):
    coordinator.observe(request, view)
    tasks = list(coordinator._tasks.values())
    if tasks:
        await asyncio.gather(*tasks)
        await asyncio.sleep(0)


def entries(tmp_path, owner="alice", order=12):
    return ReadingNotebookStore(tmp_path).list(owner, active_work="fiction", max_seen_order=order)


@pytest.mark.asyncio
async def test_disabled_default_does_not_queue_or_call_model(tmp_path, monkeypatch):
    monkeypatch.delenv("STORYPAL_AUTO_JOURNAL_REVIEW", raising=False)
    coordinator, view, payload, _ = prepared(tmp_path)
    provider = Provider(payload)
    await run(coordinator, req(provider), view)
    assert not provider.calls and coordinator.store.document("alice") == {"jobs": [], "reviews": []}
    assert coordinator.service.backend.retrieval == "fts"


@pytest.mark.asyncio
async def test_review_is_separate_provisional_and_restarts_with_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYPAL_AUTO_JOURNAL_REVIEW", "1")
    coordinator, view, payload, _ = prepared(tmp_path)
    provider = Provider(payload)
    await run(coordinator, req(provider), view)
    assert len(provider.calls) == 1
    document = JournalRecheckStore(tmp_path).document("alice")
    assert document["jobs"][0]["status"] == "completed"
    review = document["reviews"][0]
    assert review["provisional"] and review["status"] == "supports"
    assert review["max_order"] == 12 and review["evidence_refs"][0]["order"] == 12
    assert review["source_session"] != "websocket:review" and review["source_turn_id"] == "t-progress"
    assert entries(tmp_path)[0]["content"] == view["entries"][0]["content"] and entries(tmp_path)[0]["status"] == "open"
    assert ReadingProgressStore(tmp_path).get("alice")["max_seen_order"] == 12
    await run(coordinator, req(provider), view)
    assert len(provider.calls) == 1
    store = JournalRecheckStore(tmp_path)
    assert len(store.visible("alice", work_id="fiction", max_order=12, entries=entries(tmp_path))) == 1
    assert store.visible("alice", work_id="fiction", max_order=10, entries=entries(tmp_path, order=10)) == []
    assert store.visible("alice", work_id="other", max_order=99, entries=entries(tmp_path)) == []
    assert store.visible("bob", work_id="fiction", max_order=99, entries=entries(tmp_path, owner="bob")) == []
    assert store.take_notice("alice", work_id="fiction", max_order=12, entries=entries(tmp_path))
    assert store.take_notice("alice", work_id="fiction", max_order=12, entries=entries(tmp_path)) is None
    with request_context(req(provider)):
        assert json.loads(await SearchReadingJournalTool(tmp_path).execute())["reviews"][0]["review_id"] == review["review_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["quote", "future_ref", "old_only", "duplicate", "missing", "oversize", "finish", "tools", "error"])
async def test_invalid_or_failed_model_output_not_saved_or_retried_forever(tmp_path, monkeypatch, fault):
    monkeypatch.setenv("STORYPAL_AUTO_JOURNAL_REVIEW", "1")
    coordinator, view, payload, _ = prepared(tmp_path)
    item = payload["reviews"][0]
    if fault == "quote": item["evidence_refs"][0]["quote"] = "并不存在的原文"
    if fault == "future_ref": item["evidence_refs"][0]["unit_id"] = "f-99"
    if fault == "old_only": item["evidence_refs"] = [{"unit_id": "f-10", "quote": "反对危险实验"}]
    if fault == "duplicate": payload["reviews"].append(deepcopy(item))
    if fault == "missing": payload["reviews"] = []
    if fault == "oversize": item["analysis"] = "长" * 401
    provider = Provider(RuntimeError("不保存这段异常正文") if fault == "error" else payload,
                        finish_reason="length" if fault == "finish" else "stop", tool_calls=fault == "tools")
    await run(coordinator, req(provider), view)
    document = coordinator.store.document("alice")
    assert document["reviews"] == [] and document["jobs"][0]["status"] == "failed"
    assert "不保存这段异常正文" not in json.dumps(document, ensure_ascii=False)
    await run(coordinator, req(provider))
    assert len(provider.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revise", "delete", "reset", "switch_work", "source"])
async def test_changes_during_inflight_review_do_not_commit_stale_answer(tmp_path, monkeypatch, change):
    monkeypatch.setenv("STORYPAL_AUTO_JOURNAL_REVIEW", "1")
    coordinator, view, payload, backend = prepared(tmp_path)
    async def during():
        journal = ReadingNotebookStore(tmp_path)
        if change == "revise":
            journal.revise("alice", view["entries"][0]["id"], active_work="fiction", anchor_order=12,
                anchor_text=None, content="我关心的是她的理由，不是是否认可实验", source_session_key="new",
                source_turn_id="t2", source_quote="修改这条", operation_id="revise")
        if change == "delete": journal.delete("alice", view["entries"][0]["id"])
        if change == "reset": ReadingProgressStore(tmp_path).clear("alice")
        if change == "switch_work": ReadingProgressStore(tmp_path).set("alice", active_work="other", max_seen_order=1)
        if change == "source": backend.units[1]["raw_text"] = "原文在等待期间变更。"
    await run(coordinator, req(Provider(payload, during=during)), view)
    document = coordinator.store.document("alice")
    assert document["reviews"] == [] and document["jobs"][0]["status"] in {"superseded", "failed"}


@pytest.mark.asyncio
async def test_pending_job_survives_restart_and_unknown_does_not_claim_absence(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYPAL_AUTO_JOURNAL_REVIEW", "1")
    coordinator, view, payload, backend = prepared(tmp_path)
    coordinator.store.enqueue("alice", view, session_key="old", turn_id="t-old")
    backend.units = []
    item = payload["reviews"][0]
    item.update(status="unknown", analysis="当前没有取得足够证据，不能确认或推翻。", evidence_refs=[])
    restarted = JournalRecheckCoordinator(tmp_path, service=StoryMemoryService(backend))
    provider = Provider(payload)
    await run(restarted, req(provider))
    assert len(provider.calls) == 1
    assert restarted.store.document("alice")["reviews"][0]["status"] == "unknown"


@pytest.mark.asyncio
async def test_cancel_leaves_pending_and_resume_does_not_overwrite_original(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYPAL_AUTO_JOURNAL_REVIEW", "1")
    coordinator, view, payload, backend = prepared(tmp_path)
    reached = asyncio.Event()
    async def during():
        reached.set()
        await asyncio.Event().wait()
    coordinator.observe(req(Provider(payload, during=during)), view)
    await asyncio.wait_for(reached.wait(), 2)
    task = next(iter(coordinator._tasks.values()))
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    await asyncio.sleep(0)
    assert coordinator.store.document("alice")["jobs"][0]["status"] == "pending"
    restarted = JournalRecheckCoordinator(tmp_path, service=StoryMemoryService(backend))
    await run(restarted, req(Provider(payload)))
    assert len(restarted.store.document("alice")["reviews"]) == 1
    assert entries(tmp_path)[0]["content"] == view["entries"][0]["content"]


@pytest.mark.asyncio
async def test_deleted_or_revised_entry_hides_existing_review(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYPAL_AUTO_JOURNAL_REVIEW", "1")
    coordinator, view, payload, _ = prepared(tmp_path)
    await run(coordinator, req(Provider(payload)), view)
    journal = ReadingNotebookStore(tmp_path)
    journal.revise("alice", view["entries"][0]["id"], active_work="fiction", anchor_order=12,
                   anchor_text=None, content="现在的问题不同了", source_session_key="new", source_turn_id="t2",
                   source_quote="更新问题", operation_id="revision")
    assert coordinator.store.visible("alice", work_id="fiction", max_order=12, entries=entries(tmp_path)) == []
    journal.delete("alice", view["entries"][0]["id"])
    assert coordinator.store.visible("alice", work_id="fiction", max_order=12, entries=entries(tmp_path)) == []


@pytest.mark.asyncio
async def test_runtime_notice_is_once_and_does_not_schedule_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYPAL_AUTO_JOURNAL_REVIEW", "1")
    coordinator, view, payload, _ = prepared(tmp_path)
    provider = Provider(payload)
    await run(coordinator, req(provider), view)
    monkeypatch.setenv("STORYPAL_AUTO_JOURNAL_REVIEW", "0")
    reader = SearchReadingJournalTool(tmp_path)
    first = await reader._provide_runtime_context(req(provider))
    assert first.source == "storypal_journal_recheck" and first.replay is False
    assert "AI暂定解读" in first.content
    assert await reader._provide_runtime_context(req(provider)) is None
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_corrupt_queue_is_not_silently_reset_or_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYPAL_AUTO_JOURNAL_REVIEW", "1")
    coordinator, view, payload, _ = prepared(tmp_path)
    path = coordinator.store._path("alice")
    path.parent.mkdir(parents=True)
    path.write_text("损坏的JSON，必须保留", encoding="utf-8")
    provider = Provider(payload)
    await run(coordinator, req(provider), view)
    assert not provider.calls and path.read_text(encoding="utf-8") == "损坏的JSON，必须保留"


@pytest.mark.asyncio
async def test_progress_reset_during_source_revalidation_blocks_commit(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYPAL_AUTO_JOURNAL_REVIEW", "1")
    coordinator, view, payload, backend = prepared(tmp_path)
    original = backend.get_unit
    def get_unit(work_id, unit_id):
        ReadingProgressStore(tmp_path).clear("alice")
        return original(work_id, unit_id)
    backend.get_unit = get_unit
    await run(coordinator, req(Provider(payload)), view)
    assert coordinator.store.document("alice")["reviews"] == []


@pytest.mark.asyncio
async def test_duplicate_observation_during_inflight_does_not_add_request(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYPAL_AUTO_JOURNAL_REVIEW", "1")
    coordinator, view, payload, _ = prepared(tmp_path)
    reached, release = asyncio.Event(), asyncio.Event()
    async def during():
        reached.set()
        await release.wait()
    provider = Provider(payload, during=during)
    coordinator.observe(req(provider), view)
    await asyncio.wait_for(reached.wait(), 2)
    coordinator.observe(req(provider), view)
    assert len(provider.calls) == 1
    release.set()
    await asyncio.gather(*list(coordinator._tasks.values()))
    assert len(coordinator.store.document("alice")["reviews"]) == 1


@pytest.mark.asyncio
async def test_separator_body_does_not_become_summary_based_fact(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYPAL_AUTO_JOURNAL_REVIEW", "1")
    coordinator, view, payload, backend = prepared(tmp_path)
    backend.units = [{"work_id": "fiction", "unit_id": "f-12", "order": 12,
                      "raw_text": "---", "summary": "摘要虚构了主角认可实验", "score": 0.5, "metadata": {}}]
    payload["reviews"][0].update(status="unknown", analysis="未取得足够可用原文，暂不能核验。", evidence_refs=[])
    provider = Provider(payload)
    await run(coordinator, req(provider), view)
    sent = json.loads(provider.calls[0]["messages"][1]["content"])
    assert sent["evidence"] == []
    assert "摘要虚构" not in str(provider.calls)
    assert coordinator.store.document("alice")["reviews"][0]["status"] == "unknown"
