"""新授权15次：六场景／最多12 Luna＋3 Sol，仅合成材料与公开模板。

不复用旧请求额度；缺省只离线自检。不能把CLI参数当作人类授权。
"""
import argparse
import asyncio
from collections import Counter
from copy import deepcopy
from contextvars import ContextVar
import json
import os
from pathlib import Path
import tempfile

import manual_journal_recheck as guard
import test_continuous_memory_workflow as fixture

SOL = "openai-codex/gpt-6-sol"
STAGES = {s: "gpt-6-luna" for s in [
    "C1-archive", "C1-maintenance", "C1-recall-plan", "C1-recall-answer",
    "C2-archive", "C2-continuation", "C3-pause", "C4-evidence-plan", "C4-evidence-answer",
    "C5-journal-plan", "C5-journal-answer", "C6-sufficient"]}
STAGES.update({s: "gpt-6-sol" for s in ["Sol-C1", "Sol-C2", "Sol-C5"]})
SCHEDULE = ContextVar("memory_acceptance_schedule", default=None)


class Budget(guard.Budget):
    def __init__(self, path):
        self.path = Path(path)
        rows = [json.loads(s) for s in self.path.read_text(encoding="utf-8").splitlines()] if self.path.exists() else []
        self.counts = Counter(r["stage"] for r in rows if r["event"] == "begin")
        if any(k not in STAGES or v > 1 for k, v in self.counts.items()):
            raise ValueError("历史账本不属于本次授权")

    def admit(self, body):
        stage, attempt = guard.STAGE.get(), guard.ATTEMPT.get()
        if stage not in STAGES or attempt is None or body.get("model") != STAGES[stage]:
            raise RuntimeError("未授权步骤或模型")
        if attempt["sent"] or self.total >= 15 or self.counts[stage]:
            raise RuntimeError("禁止重发或超额")
        attempt["sent"] = True
        number = self.total + 1
        import hashlib
        self.append({"event": "begin", "request_no": number, "stage": stage, "model": body["model"],
                     "body_sha256": hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()})
        self.counts[stage] += 1
        return number


def preflight():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.jsonl"
        budget = Budget(path)
        def reject(body):
            try:
                budget.admit(body)
            except RuntimeError:
                return
            raise AssertionError("超额请求未拦截")
        reject({"model": "gpt-6-luna"})
        for stage, model in STAGES.items():
            guard.STAGE.set(stage)
            guard.ATTEMPT.set({"sent": False})
            reject({"model": "wrong"})
            budget.admit({"model": model})
            reject({"model": model})
            guard.ATTEMPT.set({"sent": False})
            reject({"model": model})
        assert Budget(path).total == 15
        reject({"model": "gpt-6-sol"})
        guard.STAGE.set(None)
        guard.ATTEMPT.set(None)
    print(json.dumps({"preflight": "passed", "luna_limit": 12, "sol_limit": 3}), flush=True)


def routed_provider(root):
    provider = guard.provider(root)
    original = provider.chat
    async def chat(**kwargs):
        schedule = SCHEDULE.get()
        if not schedule:
            raise RuntimeError("该场景调用预算已用尽，禁止追加")
        stage = schedule.pop(0)
        token = guard.STAGE.set(stage)
        try:
            return await original(**kwargs)
        finally:
            guard.STAGE.reset(token)
    provider.chat = chat
    return provider


async def within(stages, operation):
    token = SCHEDULE.set(list(stages))
    try:
        return await operation()
    finally:
        SCHEDULE.reset(token)


def dump(root, name, value):
    (root / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


async def simulate(root, provider, stage, target):
    response = await within([stage], lambda: provider.chat(model=SOL, tools=[], max_tokens=400,
        reasoning_effort="medium", messages=[{"role": "system", "content":
        "你模拟普通中文读者。只写一条口语消息，保留目标，不回答、不补剧情、不说出预设答案，最多150字。"},
        {"role": "user", "content": target}]))
    text = response.content.strip() if response.content else ""
    if response.finish_reason != "stop" or response.has_tool_calls or not 1 <= len(text) <= 250:
        return None
    return text


def state_provider(workspace):
    from nanobot.runtime_context import RuntimeContextBlock
    from storypal_chatbot.storage import ReadingProgressStore
    async def state(request):
        value = ReadingProgressStore(workspace).get(request.sender_id)
        return RuntimeContextBlock("storypal_session_state", "用户已确认阅读状态：" + json.dumps(value, ensure_ascii=False), replay=False)
    return state


async def ask(workspace, provider, key, owner, text, stages, *, tools=(), blocks=()):
    from nanobot.runtime_context import RuntimeContextBlock
    from nanobot.session.manager import SessionManager
    agent = fixture.loop(workspace, provider, SessionManager(workspace), tools=tools)
    agent.max_iterations = len(stages)
    agent.register_runtime_context_provider(state_provider(workspace))
    for name, body in blocks:
        async def context(request, name=name, body=body):
            return RuntimeContextBlock(name, body, replay=False)
        agent.register_runtime_context_provider(context)
    try:
        output = await within(stages, lambda: agent.process_direct(text, session_key=key,
            channel="websocket", chat_id="synthetic", sender_id=owner))
        return output.content if output else None
    finally:
        await agent.aclose()


async def run(root):
    from nanobot.utils.llm_runtime import LLMRuntime
    from nanobot.session.manager import SessionManager
    from nanobot.session.summary import session_summary_from_metadata
    from storypal_chatbot.bootstrap import install_persona
    from storypal_chatbot.storage import ReadingNotebookStore, ReadingProgressStore
    from storypal_chatbot.episodic_recall import EpisodicRecallService
    from storypal_chatbot.story_memory import StoryMemoryService, StoryMemoryError
    from storypal_chatbot.tools import GetStoryEvidenceTool, RecallInteractionHistoryTool, SearchReadingJournalTool
    root.mkdir(parents=True, exist_ok=False)
    dump(root, "scope.json", {"luna_limit": 12, "sol_limit": 3, "materials": "仅合成材料＋公开规则",
                              "gpu": False, "formal_workspace": False, "novel_original": False})
    budget, provider = Budget(root / "requests.jsonl"), routed_provider(root)
    os.environ.update({"STORYPAL_AUTO_NOTE": "0", "STORYPAL_AUTO_EPISODE": "0", "STORYPAL_AUTO_JOURNAL_REVIEW": "0"})
    result = {"scenarios": {}, "requests": 0}
    def save():
        result["requests"] = budget.total
        result["by_model"] = dict(Counter(STAGES[k] for k, v in budget.counts.items() for _ in range(v)))
        dump(root, "result.json", result)
    with guard.transport(budget):
        generated = {}
        for stage, target in [
            ("Sol-C1", "新会话，只记得之前聊阿岚救老师时质疑转折铺垫，不记得后来怎么澄清。想找回自己的讨论，不是查剧情事实。"),
            ("Sol-C2", "同一会话继续。之前喜欢阿岚救老师但认为转折突然，后来澄清关心铺垫而不是救人是否可能。想确认我们刚才关注什么。"),
            ("Sol-C5", "记不清自己保存的阿岚旧预测了。当前看见她救老师但没同意重启实验，想回看旧预测并比较。不要修改手账。")]:
            generated[stage] = await simulate(root, provider, stage, target)
            save()
        dump(root, "simulated-users.json", generated)
        initial, correction = fixture.SCENARIOS[0][1:3]
        for case in ["C1", "C2"]:
            # 原生压缩前绑定owner与水位0；抽取只在C1压缩提交之后启用。
            os.environ.update({"STORYPAL_AUTO_NOTE": "1", "STORYPAL_AUTO_EPISODE": "1"})
            workspace, sessions, coordinator, req, consolidator = fixture.setup(
                root / case, provider, fixture.transcript(initial, correction))
            os.environ.update({"STORYPAL_AUTO_NOTE": "0", "STORYPAL_AUTO_EPISODE": "0"})
            before = deepcopy(sessions.get_or_create(req.session_key).messages)
            await within([case + "-archive"], lambda: consolidator.compact_idle_session(req.session_key,
                runtime=LLMRuntime.capture(provider, guard.MODEL, context_window_tokens=200000)))
            restored = SessionManager(workspace).get_or_create(req.session_key)
            summary = session_summary_from_metadata(restored.metadata, fallback_last_active=restored.updated_at)
            item = {"summary": summary, "original_preserved": restored.messages == before,
                    "archived": restored.last_archived}
            result["scenarios"][case] = item
            save()
            if case == "C1":
                os.environ.update({"STORYPAL_AUTO_NOTE": "1", "STORYPAL_AUTO_EPISODE": "1"})
                await within(["C1-maintenance"], lambda: fixture.maintain(coordinator, req))
                os.environ.update({"STORYPAL_AUTO_NOTE": "0", "STORYPAL_AUTO_EPISODE": "0"})
                item["maintenance"] = coordinator.last_result
                item["records"] = coordinator.episodes.list_records(req.sender_id)
                item["note"] = coordinator.notes.read(req.sender_id)
                journal = ReadingNotebookStore(workspace)
                journal_before = journal.list(req.sender_id, active_work="synthetic", max_seen_order=12)
                # 检索接线用确定性向量，不加载BGE；该批不评估召回排序准确率。
                svc = EpisodicRecallService(workspace, encoder_factory=fixture.Encoder, token_budget=3000)
                if generated["Sol-C1"]:
                    item["answer"] = await ask(workspace, provider, "websocket:fresh-memory", req.sender_id,
                        generated["Sol-C1"], ["C1-recall-plan", "C1-recall-answer"],
                        tools=[RecallInteractionHistoryTool(workspace, svc)])
                item["journal_unchanged"] = journal_before == journal.list(req.sender_id, active_work="synthetic", max_seen_order=12)
            elif generated["Sol-C2"]:
                item["answer"] = await ask(workspace, provider, req.session_key, req.sender_id,
                    generated["Sol-C2"], ["C2-continuation"])
            save()
        class FailingBackend:
            def get_unit(self, work_id, unit_id):
                raise StoryMemoryError("合成来源不可用：这次没有取得原文，不是作品没有。")
        for case in ["C3", "C4", "C5", "C6"]:
            workspace = root / case / "workspace"
            install_persona(workspace)
            owner, key = "synthetic-reader", "websocket:" + case
            progress = ReadingProgressStore(workspace)
            progress.set(owner, active_work="synthetic", max_seen_order=12)
            tools = [GetStoryEvidenceTool(workspace, StoryMemoryService(FailingBackend()))]
            blocks = [("synthetic_fragment", "人工合成当前片段：阿岚反对老师用危险实验救城；老师被困后她回去救人，但没有同意重启实验。没有交代此前参与实验。")]
            if case == "C3":
                question, stages = "我挺喜欢她没丢下老师，可是有点难受。先别分析，也别查资料了。", ["C3-pause"]
            elif case == "C4":
                question, stages = "请按已知单元s-12核对原句，它是否交代阿岚此前参与实验？不要补未读内容。", ["C4-evidence-plan", "C4-evidence-answer"]
                blocks = []  # 已知来源ID但没有原句，必须面对合成来源失败。
            elif case == "C5":
                journal = ReadingNotebookStore(workspace)
                journal.add(owner, active_work="synthetic", anchor_order=10, anchor_text="旧位置", entry_type="prediction",
                            content="我猜阿岚回去救老师就代表她赞成危险实验", source_session_key="synthetic-old")
                before = journal.list(owner, active_work="synthetic", max_seen_order=12)
                tools = [SearchReadingJournalTool(workspace)]
                question, stages = generated["Sol-C5"], ["C5-journal-plan", "C5-journal-answer"]
            else:
                question, stages = "只看当前片段，她去救人能证明她以前参与过实验吗？别把猜测当事实。", ["C6-sufficient"]
            item = {"answer": await ask(workspace, provider, key, owner, question, stages, tools=tools, blocks=blocks) if question else None}
            item["progress_unchanged"] = progress.get(owner)["max_seen_order"] == 12
            if case == "C5":
                item["journal_unchanged"] = before == journal.list(owner, active_work="synthetic", max_seen_order=12)
            result["scenarios"][case] = item
            save()
    print(json.dumps({"requests": budget.total, "by_model": result["by_model"], "scenes": list(result["scenarios"])}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-15-synthetic-requests", action="store_true")
    parser.add_argument("--run-name")
    args = parser.parse_args()
    preflight()
    if args.approved_15_synthetic_requests:
        if not args.run_name or not args.run_name.replace("-", "").isalnum():
            parser.error("必须指定新的简单run-name")
        asyncio.run(run(guard.ROOT / ".runtime" / "isolated" / args.run_name))
