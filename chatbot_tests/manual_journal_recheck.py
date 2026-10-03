"""仅授权后手动执行的两次合成验收；默认离线，不读取正式配置或工作区。"""
import argparse
import asyncio
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import inspect
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace

MODEL = "openai-codex/gpt-6-luna"
STAGE = ContextVar("journal_test_stage", default=None)
ATTEMPT = ContextVar("journal_test_attempt", default=None)
ROOT = Path(__file__).resolve().parents[1]

class Budget:
    def __init__(self, path):
        self.path = Path(path)
        rows = [json.loads(s) for s in self.path.read_text(encoding="utf-8").splitlines()] if self.path.exists() else []
        self.counts = Counter(r["stage"] for r in rows if r["event"] == "begin")
        if any(k not in {"recheck", "continuation"} or v > 1 for k, v in self.counts.items()):
            raise ValueError("无效历史预算")
    @property
    def total(self):
        return sum(self.counts.values())
    def append(self, row):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    def admit(self, body):
        stage, attempt = STAGE.get(), ATTEMPT.get()
        if stage not in {"recheck", "continuation"} or attempt is None:
            raise RuntimeError("禁止未声明步骤请求")
        if body.get("model") != "gpt-6-luna" or body.get("tools"):
            raise RuntimeError("禁止其他模型或工具")
        if attempt["sent"] or self.total >= 2 or self.counts[stage]:
            raise RuntimeError("禁止重发或超预算")
        attempt["sent"] = True
        number = self.total + 1
        self.append({"event": "begin", "request_no": number, "stage": stage,
            "model": body["model"], "body_sha256": hashlib.sha256(
                json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()})
        self.counts[stage] += 1
        return number

@contextmanager
def transport(budget):
    import nanobot.providers.openai_codex_provider as module
    original = module._request_codex
    async def guarded(url, headers, body, *args, **kwargs):
        if url != module.DEFAULT_CODEX_URL:
            raise RuntimeError("禁止其他端点")
        number, started = budget.admit(body), time.perf_counter()
        try:
            response = await original(url, headers, body, *args, **kwargs)
        except BaseException as exc:
            budget.append({"event": "end", "request_no": number, "status": "failed", "error_type": type(exc).__name__})
            raise
        budget.append({"event": "end", "request_no": number, "status": response.finish_reason,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "usage": response.usage.to_dict() if response.usage else None})
        return response
    module._request_codex = guarded
    try:
        yield
    finally:
        module._request_codex = original

def provider(root):
    from nanobot.providers.base import GenerationSettings
    from nanobot.providers.openai_codex_provider import OpenAICodexProvider
    class Bounded(OpenAICodexProvider):
        async def _call_codex(self, *args, **kwargs):
            token = ATTEMPT.set({"sent": False})
            try:
                return await super()._call_codex(*args, **kwargs)
            finally:
                ATTEMPT.reset(token)
        async def chat(self, **kwargs):
            stage = STAGE.get()
            (root / (stage + "-messages.json")).write_text(json.dumps(kwargs.get("messages"), ensure_ascii=False, indent=2), encoding="utf-8")
            response = await super().chat(**kwargs)
            (root / (stage + "-response.json")).write_text(json.dumps({"content": response.content,
                "finish_reason": response.finish_reason, "has_tool_calls": response.has_tool_calls}, ensure_ascii=False, indent=2), encoding="utf-8")
            return response
        async def chat_with_retry(self, **kwargs):
            allowed = inspect.signature(OpenAICodexProvider.chat).parameters
            return await self.chat(**{k: v for k, v in kwargs.items() if k in allowed})
        async def chat_stream_with_retry(self, **kwargs):
            return await self.chat_with_retry(**kwargs)
    instance = Bounded(default_model=MODEL)
    instance._native_compaction_available = False
    instance.generation = GenerationSettings(temperature=.1, reasoning_effort="medium", max_tokens=1600)
    return instance

class SyntheticBackend:
    retrieval = "fts"
    units = [{"work_id": "fiction", "unit_id": "f-10", "order": 10,
        "raw_text": "阿岚当时反对危险实验。", "summary": "", "score": .3, "metadata": {}},
        {"work_id": "fiction", "unit_id": "f-12", "order": 12,
        "raw_text": "阿岚返回救老师，但没有同意重启实验。", "summary": "", "score": .5, "metadata": {}}]
    def search(self, work_id, query, *, max_order, top_k, filters=None):
        return deepcopy([u for u in self.units if u["work_id"] == work_id and u["order"] <= max_order][:top_k])
    def get_unit(self, work_id, unit_id):
        return next(({**deepcopy(u), "score": 1.0} for u in self.units if u["work_id"] == work_id and u["unit_id"] == unit_id), None)

def preflight():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.jsonl"
        budget, rejected = Budget(path), 0
        def reject(body):
            nonlocal rejected
            try:
                budget.admit(body)
            except RuntimeError:
                rejected += 1
            else:
                raise AssertionError("守卫未拦截")
        body = {"model": "gpt-6-luna"}
        reject(body)
        st, at = STAGE.set("recheck"), ATTEMPT.set({"sent": False})
        reject({"model": "other"})
        reject({**body, "tools": ["forbidden"]})
        assert budget.admit(body) == 1
        reject(body)
        ATTEMPT.set({"sent": False})
        reject(body)
        budget = Budget(path)
        reject(body)
        STAGE.set("continuation")
        ATTEMPT.set({"sent": False})
        assert budget.admit(body) == 2
        ATTEMPT.set({"sent": False})
        reject(body)
        assert Budget(path).total == 2
        STAGE.reset(st)
        ATTEMPT.reset(at)
    print(json.dumps({"offline_guard_checks": rejected, "passed": True}), flush=True)

async def run(root):
    from nanobot import RequestContext
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import ToolsConfig
    from nanobot.session.manager import SessionManager
    from storypal_chatbot.bootstrap import install_persona
    from storypal_chatbot.journal_recheck import JournalRecheckCoordinator
    from storypal_chatbot.storage import ReadingNotebookStore, ReadingProgressStore
    from storypal_chatbot.story_memory import StoryMemoryService
    from storypal_chatbot.tools import SearchReadingJournalTool
    root.mkdir(parents=True, exist_ok=False)
    workspace = root / "workspace"
    install_persona(workspace)
    budget, model = Budget(root / "requests.jsonl"), provider(root)
    owner, key = "synthetic-review-reader", "websocket:synthetic-review"
    progress, journal = ReadingProgressStore(workspace), ReadingNotebookStore(workspace)
    progress.set(owner, active_work="fiction", max_seen_order=10)
    entry = journal.add(owner, active_work="fiction", anchor_order=10, anchor_text="旧位置", entry_type="prediction",
        content="我猜她救人也不会赞成危险实验", source_session_key="synthetic-old")
    progress.set(owner, active_work="fiction", max_seen_order=12)
    def snapshot():
        return {"progress": progress.get(owner), "journal": journal.list(owner, active_work="fiction", max_seen_order=12)}
    before = snapshot()
    view = {"work_id": "fiction", "previous_order": 10, "max_order": 12, "entries": [entry]}
    coordinator = JournalRecheckCoordinator(workspace, service=StoryMemoryService(SyntheticBackend()))
    request = RequestContext(channel="websocket", chat_id="synthetic", sender_id=owner, session_key=key,
        turn_id="synthetic-progress", original_user_text="继续读到这里了",
        runtime=SimpleNamespace(provider=model, model=MODEL, generation=model.generation))
    with transport(budget):
        os.environ["STORYPAL_AUTO_JOURNAL_REVIEW"] = "1"
        token = STAGE.set("recheck")
        try:
            coordinator.observe(request, view)
            await asyncio.gather(*list(coordinator._tasks.values()))
        finally:
            STAGE.reset(token)
            os.environ["STORYPAL_AUTO_JOURNAL_REVIEW"] = "0"
        document = coordinator.store.document(owner)
        print(json.dumps({"phase": "recheck", "result": coordinator.last_result, "requests": budget.total}), flush=True)
        if not document["reviews"]:
            (root / "result.json").write_text(json.dumps({"status": "recheck_failed", "requests": budget.total}), encoding="utf-8")
            return
        class IsolatedLoop(AgentLoop):
            def _register_default_tools(self, **kwargs):
                pass
        registry = ToolRegistry()
        loop = IsolatedLoop(bus=MessageBus(), provider=model, workspace=workspace, model=MODEL,
            context_window_tokens=272000, max_iterations=1, timezone="Asia/Shanghai", restrict_to_workspace=True,
            tool_registry=registry, tools_config=ToolsConfig(allowed_tools=[]),
            session_manager=SessionManager(workspace, sessions_root=root / "sessions"))
        loop.schedule_background = lambda coroutine: coroutine.close()
        reader = SearchReadingJournalTool(workspace)
        reader._recheck_coordinator = coordinator
        loop.register_runtime_context_provider(reader._provide_runtime_context)
        token = STAGE.set("continuation")
        try:
            output = await loop.process_direct("读到她回去救老师这里了。那我之前的猜测现在怎么看？先别替我改手账。",
                session_key=key, channel="websocket", chat_id="synthetic", sender_id=owner)
        finally:
            STAGE.reset(token)
        messages = json.loads((root / "continuation-messages.json").read_text(encoding="utf-8"))
        result = {"requests": budget.total, "unchanged": before == snapshot(),
            "review_in_context": "[手账复核已完成" in json.dumps(messages, ensure_ascii=False),
            "review": document["reviews"][0], "answer": output.content if output else None}
        (root / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: result[k] for k in ("requests", "unchanged", "review_in_context")}), flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-two-requests", action="store_true")
    parser.add_argument("--run-name")
    args = parser.parse_args()
    preflight()
    if args.approved_two_requests:
        if not args.run_name or not args.run_name.replace("-", "").isalnum():
            parser.error("必须指定新的简单run-name，不允许路径")
        asyncio.run(run(ROOT / ".runtime" / "isolated" / args.run_name))
