"""Explicitly authorized six-scene Sol/Luna batch, isolated from live users.

The transport boundary counts every admitted Responses request, including
failures. No retries, fallback models, background LLM work or downloads.
Token counts are provider usage, not a promised server output cap.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

from .replay import DATA, PIPELINE, ROOT, RUNTIME, load_cases

CASES = ("R14", "R25", "R26", "R21", "P01", "N01")
MODELS = {"user": "openai-codex/gpt-6-sol", "role": "openai-codex/gpt-6-luna"}
LIMITS = {"user": 1, "role": 3}
TOTAL_LIMIT = 24
SCOPE: ContextVar[tuple[str, str] | None] = ContextVar("retrieval_scope", default=None)
ATTEMPT: ContextVar[dict[str, bool] | None] = ContextVar("retrieval_attempt", default=None)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def write_new(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)


def run_path(path: Path) -> Path:
    path = path.resolve()
    parent = (RUNTIME / "isolated").resolve()
    if not path.is_relative_to(parent) or path == parent:
        raise ValueError("Run must be a child of the isolated runtime")
    return path


class RequestBudget:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                       if line.strip()] if path.exists() else []
        begins = [row for row in self.events if row["event"] == "begin"]
        self.counts = Counter((row["case_id"], row["role"]) for row in begins)
        self.total = len(begins)
        if self.total > TOTAL_LIMIT or any(self.counts[(case, role)] > LIMITS[role]
                                          for case, role in self.counts):
            raise ValueError("Existing ledger exceeds approved budget")

    def append(self, row: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.events.append(row)

    def admit(self, model: str, body: dict[str, Any]) -> int:
        scope, attempt = SCOPE.get(), ATTEMPT.get()
        if scope is None or attempt is None:
            raise RuntimeError("Unscoped request forbidden")
        case, role = scope
        if case not in CASES or role not in MODELS or model != MODELS[role].split("/", 1)[1]:
            raise RuntimeError("Unapproved scene, role or model")
        if attempt.get("sent"):
            raise RuntimeError("Automatic transport resend disabled")
        if self.total >= TOTAL_LIMIT or self.counts[scope] >= LIMITS[role]:
            raise RuntimeError("Approved request budget exhausted")
        attempt["sent"] = True
        self.total += 1
        self.counts[scope] += 1
        self.append({"event": "begin", "request_no": self.total, "case_id": case,
                     "role": role, "model": model, "body_sha256": digest(body)})
        return self.total


@contextmanager
def count_transport(budget: RequestBudget):
    import nanobot.providers.openai_codex_provider as module
    original = module._request_codex

    async def counted(url, headers, body, *args, **kwargs):
        if url != module.DEFAULT_CODEX_URL:
            raise RuntimeError("Unapproved model endpoint")
        number = budget.admit(body.get("model", ""), body)
        started = time.perf_counter()
        try:
            response = await original(url, headers, body, *args, **kwargs)
        except BaseException as exc:
            budget.append({"event": "end", "request_no": number, "status": "failed",
                           "error_type": type(exc).__name__,
                           "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)})
            raise
        budget.append({"event": "end", "request_no": number, "status": response.finish_reason,
                       "usage": response.usage.to_dict() if response.usage else None,
                       "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)})
        return response

    module._request_codex = counted
    try:
        yield
    finally:
        module._request_codex = original


def provider(role: str):
    from nanobot.providers.base import GenerationSettings
    from nanobot.providers.openai_codex_provider import OpenAICodexProvider

    class BoundedProvider(OpenAICodexProvider):
        async def _call_codex(self, *args, **kwargs):
            token = ATTEMPT.set({"sent": False})
            try:
                return await super()._call_codex(*args, **kwargs)
            finally:
                ATTEMPT.reset(token)

        async def chat_with_retry(self, **kwargs):
            allowed = inspect.signature(OpenAICodexProvider.chat).parameters
            return await self.chat(**{key: value for key, value in kwargs.items() if key in allowed})

        async def chat_stream_with_retry(self, **kwargs):
            allowed = inspect.signature(OpenAICodexProvider.chat_stream).parameters
            return await self.chat_stream(**{key: value for key, value in kwargs.items() if key in allowed})

    instance = BoundedProvider(default_model=MODELS[role])
    instance._native_compaction_available = False
    instance.generation = GenerationSettings(temperature=.1, reasoning_effort="medium",
                                             max_tokens=600 if role == "user" else 1800)
    return instance


def user_prompt(case: dict[str, Any]) -> list[dict[str, str]]:
    # Whitelist fields rather than serializing the case, which contains gold.
    return [{"role": "system", "content": (
        "你模拟正在阅读《流浪地球》的普通中文读者。只写一条自然的用户消息，"
        "保留给定问题的关注点与所有子问题，换一种真实口语表达。"
        "不要回答问题、增加事实或未读情节，不写分析、来源编号、检索词或标签。"
        "情绪暂停场景须保留不想分析的意思。只输出消息正文，尽量不超过120字。")},
        {"role": "user", "content": json.dumps({"question": case["raw_user"],
         "visible_context": case["visible_context"]}, ensure_ascii=False)}]


def selected_cases() -> list[dict[str, Any]]:
    by_id = {case["case_id"]: case for case in load_cases()}
    return [by_id[key] for key in CASES]


async def generate(root: Path, budget: RequestBudget) -> None:
    model = provider("user")
    for case in selected_cases():
        case_id = case["case_id"]
        destination = root / "generated" / (case_id + ".json")
        if destination.exists():
            continue  # Existing results are reviewed; never regenerate to select a better sample.
        messages = user_prompt(case)
        token = SCOPE.set((case_id, "user"))
        try:
            response = await model.chat_with_retry(messages=messages, tools=[], model=MODELS["user"],
                                                   max_tokens=600, temperature=.1, reasoning_effort="medium")
        finally:
            SCOPE.reset(token)
        valid = response.finish_reason == "stop" and isinstance(response.content, str) and 1 <= len(response.content.strip()) <= 400
        write_new(destination, {"case_id": case_id, "model": MODELS["user"], "max_order": case["max_order"],
                               "prompt_sha256": digest(messages), "question": response.content if valid else None,
                               "question_sha256": digest(response.content.strip()) if valid else None,
                               "status": "needs_intent_review" if valid else "generation_failed"})
        print(json.dumps({"case_id": case_id, "phase": "generate", "valid": valid,
                          "requests_used": budget.total}), flush=True)


def build_loop(root: Path, case: dict[str, Any], role_provider):
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import ToolsConfig
    from nanobot.session.manager import SessionManager
    from storypal_chatbot.bootstrap import install_persona
    from storypal_chatbot.storage import ReadingProgressStore
    from storypal_chatbot.story_memory import PipelineStoryMemoryBackend, StoryMemoryService
    from storypal_chatbot.tools import (GetStoryEvidenceTool, SearchStoryTool, StoryContextTool,
                                       StorySessionStateTool)

    class IsolatedLoop(AgentLoop):
        def _register_default_tools(self, **kwargs):
            pass  # Explicit registry; no plugin discovery or write/background tools.

    workspace = root / case["case_id"] / "workspace"
    install_persona(workspace)
    snapshot = root / "persona_snapshot"
    if snapshot.exists():
        from storypal_chatbot.bootstrap import PERSONA_FILES
        for name in PERSONA_FILES:
            (workspace / name).write_bytes((snapshot / name).read_bytes())
    service = StoryMemoryService(PipelineStoryMemoryBackend(data_root=DATA, pipeline_code_path=PIPELINE,
                                                           retrieval="auto"))
    state = StorySessionStateTool(workspace, service)
    owner, key = "retrieval-simulated-reader", "cli:retrieval-" + case["case_id"]
    ReadingProgressStore(workspace).set(owner, active_work=case["work_id"], max_seen_order=case["max_order"],
                                       current_anchor="隔离实验已确认范围", source_session_key=key)
    registry = ToolRegistry()
    for tool_class in (SearchStoryTool, StoryContextTool, GetStoryEvidenceTool):
        registry.register(tool_class(workspace, service))
    sessions = SessionManager(workspace, sessions_root=root / case["case_id"] / "sessions")
    if case["case_id"] == "R14":
        session = sessions.get_or_create(key)
        if not session.messages:
            session.add_message("user", "我们刚聊到小星老师讲解人类逃亡计划。")
            session.add_message("assistant", "你想接着聊哪一点？")
            sessions.save(session)
    loop = IsolatedLoop(bus=MessageBus(), provider=role_provider, workspace=workspace,
                        model=MODELS["role"], context_window_tokens=272000, max_iterations=3,
                        timezone="Asia/Shanghai", restrict_to_workspace=True, tool_registry=registry,
                        tools_config=ToolsConfig(allowed_tools=registry.tool_names), session_manager=sessions)
    loop.register_runtime_context_provider(state._provide_runtime_context)
    loop.schedule_background = lambda coroutine: coroutine.close()
    return loop, key, owner, service


async def roleplay(root: Path, budget: RequestBudget) -> None:
    from nanobot.agent.hook import AgentHook
    from storypal_chatbot.query_capture import IsolatedQueryCapture, export_query
    from .fusion_replay import SOURCE
    scope_file = root / "luna-outbound-scope.json"
    scope = json.loads(scope_file.read_text(encoding="utf-8"))
    authorization = json.loads((root / "materials-authorization.json").read_text(encoding="utf-8"))
    if (authorization.get("approved") is not True or authorization.get("model") != MODELS["role"]
            or authorization.get("scope_sha256") != hashlib.sha256(scope_file.read_bytes()).hexdigest()
            or scope.get("source_sha256") != hashlib.sha256(SOURCE.read_bytes()).hexdigest()
            or [(row["case_id"], row["max_order"]) for row in scope["scenes"]]
               != [(case["case_id"], case["max_order"]) for case in selected_cases()]):
        raise ValueError("Story-material authorization does not match the fixed scope")

    class CompletionAudit(AgentHook):
        def __init__(self):
            super().__init__()
            self.info = {"stop_reason": "not_observed"}

        async def after_run(self, context):
            self.info = {"stop_reason": context.stop_reason,
                         "had_injections": context.had_injections,
                         "has_error": bool(context.error or context.exception)}

    # One immutable persona snapshot for all six cases while the application
    # thread continues development. No live user files are read.
    from storypal_chatbot.bootstrap import PERSONA_FILES
    snapshot = root / "persona_snapshot"
    snapshot_manifest = root / "persona-snapshot.json"
    if not snapshot_manifest.exists():
        hashes = {}
        for name in PERSONA_FILES:
            data = (ROOT / "chatbot" / "src" / "storypal_chatbot" / "persona" / name).read_bytes()
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        write_new(snapshot_manifest, {"file_sha256": hashes, "source": "application package persona, not user workspace"})
    expected = json.loads(snapshot_manifest.read_text(encoding="utf-8"))["file_sha256"]
    if any(hashlib.sha256((snapshot / name).read_bytes()).hexdigest() != sha for name, sha in expected.items()):
        raise ValueError("Pinned persona was changed")
    acceptance = json.loads((root / "acceptance.json").read_text(encoding="utf-8"))
    for case in selected_cases():
        case_id = case["case_id"]
        destination = root / case_id / "result.json"
        if destination.exists():
            continue
        generated = json.loads((root / "generated" / (case_id + ".json")).read_text(encoding="utf-8"))
        review = acceptance.get(case_id, {})
        if not review.get("accepted") or review.get("question_sha256") != generated.get("question_sha256"):
            raise ValueError("Missing exact-question intent review: " + case_id)
        loop, key, owner, service = build_loop(root, case, provider("role"))
        capture = IsolatedQueryCapture(case_id=case_id, session_key=key, model=MODELS["role"],
                                       origin="agent_trace", root=RUNTIME)
        completion = CompletionAudit()
        token = SCOPE.set((case_id, "role"))
        response = None
        failure = None
        try:
            response = await loop.process_direct(generated["question"].strip(), session_key=key,
                                                  sender_id=owner, hooks=[capture, completion])
        except Exception as exc:
            failure = type(exc).__name__
        finally:
            SCOPE.reset(token)
            await loop.aclose()
        exported = None
        receipt_problem = capture.problem
        if failure is None:
            try:
                receipt = capture.seal(transcript=loop.sessions._get_session_path(key),
                                       output=root / case_id / "receipt.json")
                exported = export_query(receipt)
                write_new(root / case_id / "query-export.json", exported)
            except ValueError as exc:
                receipt_problem = str(exc)
        adapter = service.backend._adapter
        diagnostics = dict(getattr(adapter, "last_search_diagnostics", None) or {})
        write_new(destination, {"case_id": case_id, "model": MODELS["role"],
                               "question_sha256": generated["question_sha256"],
                               "final_content": response.content if response else None,
                               "failure": failure, "receipt_problem": receipt_problem,
                               "completion": completion.info,
                               "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                               "query_export": exported, "last_search_diagnostics": diagnostics})
        print(json.dumps({"case_id": case_id, "phase": "roleplay", "failure": failure,
                          "export_decision": exported["decision"] if exported else None,
                          "requests_used": budget.total}), flush=True)


async def run(args) -> None:
    root = run_path(args.run_root)
    sys.path.insert(0, str(ROOT / "chatbot" / "src"))
    from loguru import logger
    logger.remove()
    root.mkdir(parents=True, exist_ok=True)
    logger.add(str(root / (args.phase + ".log")), level="INFO")
    manifest = root / "batch.json"
    if not manifest.exists():
        if args.phase != "generate":
            raise ValueError("Generate and review questions first")
        write_new(manifest, {"schema": "retrieval-model-batch@1", "cases": CASES,
                            "models": MODELS, "request_limit": TOTAL_LIMIT, "per_scene": LIMITS,
                            "authorization": "2026-10-03 user: 按这个预算跑", "reasoning_effort": "medium",
                            "temperature_setting": .1, "temperature_sent": False,
                            "target_output_tokens": 36000, "server_token_cap": False,
                            "retrieval": "auto", "max_iterations": 3, "background_llm": False,
                            "persona": "production package files copied into isolated workspace",
                            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    if saved["models"] != MODELS or saved["request_limit"] != TOTAL_LIMIT or saved["cases"] != list(CASES):
        raise ValueError("Batch manifest differs from fixed approved protocol")
    budget = RequestBudget(root / "requests.jsonl")
    with count_transport(budget):
        await (generate(root, budget) if args.phase == "generate" else roleplay(root, budget))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--phase", choices=("generate", "roleplay"), required=True)
    parser.add_argument("--execute-authorized-batch", action="store_true", required=True)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
