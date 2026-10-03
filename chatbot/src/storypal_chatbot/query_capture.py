"""显式隔离验收的回合收据与只读query导出；不注册普通聊天工具或扫描用户会话。"""
from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from nanobot.agent.hook import AgentHook, AgentRunHookContext
from nanobot.runtime_context import RUNTIME_CONTEXT_HISTORY_META, RUNTIME_CONTEXT_MESSAGE_META

from .archive_maintenance import archived_reading_scope
from .episodic_memory import _atomic_write, _digest, _integer, _time
from .model_policy import ALLOWED_MODELS

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / ".runtime" / "retrieval-experiments"


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _canonical(message: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(message, dict) or message.get("role") not in {"user", "assistant", "tool"}:
        raise ValueError("验收只支持文本用户／助手／工具消息")
    result = {k: deepcopy(message[k]) for k in ("role", "content", "tool_calls", "tool_call_id", "name") if k in message}
    if result["role"] == "assistant" and result.get("content") is None and result.get("tool_calls"):
        result["content"] = ""
    if not isinstance(result.get("content"), str):
        raise ValueError("首版query验收不支持多模态消息")
    marker = message.get(RUNTIME_CONTEXT_HISTORY_META)
    if marker is None and isinstance(message.get("_meta"), dict):
        marker = message["_meta"].get(RUNTIME_CONTEXT_MESSAGE_META)
    if marker is not None:
        result[RUNTIME_CONTEXT_HISTORY_META] = deepcopy(marker)
    if result["role"] == "tool":
        result.pop("content", None)  # 验证调用配对，不承诺工具原始内容／查证结论通过。
    return result


def _turn(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    start = next((i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"), None)
    if start is None:
        raise ValueError("缺少当前用户请求")
    return [_canonical(message) for message in messages[start:]]


def _decision(turn: list[dict[str, Any]]) -> dict[str, Any]:
    if (len(turn) < 2 or turn[0]["role"] != "user" or turn[-1]["role"] != "assistant"
            or turn[-1].get("tool_calls") or not turn[-1].get("content", "").strip()):
        raise ValueError("回合没有完整的最终回复")
    pending, seen, calls = {}, set(), []
    for message in turn[1:]:
        if message["role"] == "assistant":
            if pending:
                raise ValueError("工具结果缺失")
            tool_calls = message.get("tool_calls") or []
            if not isinstance(tool_calls, list):
                raise ValueError("工具调用结构无效")
            for call in tool_calls:
                if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
                    raise ValueError("工具调用结构无效")
                key, function = call.get("id"), call["function"]
                name, args = function.get("name"), function.get("arguments")
                if not isinstance(key, str) or not key or key in seen or not isinstance(name, str) or not name.strip():
                    raise ValueError("工具调用标识重复／缺失")
                args = json.loads(args) if isinstance(args, str) else args
                if not isinstance(args, dict):
                    raise ValueError("工具参数无效")
                if name in {"set_reading_progress", "story_state", "reading_location"}:
                    raise ValueError("隔离查询验收不允许回合内变更／重定阅读状态")
                if name == "search_story" and (set(args) != {"query"} or not isinstance(args["query"], str)
                                               or not 1 <= len(args["query"].strip()) <= 400):
                    raise ValueError("实际search_story参数无效")
                item = {"id": key, "name": name, "arguments": args}
                calls.append(item)
                seen.add(key)
                pending[key] = name
        elif message["role"] == "tool":
            key = message.get("tool_call_id")
            if not isinstance(key, str) or key not in pending or message.get("name") not in {None, pending[key]}:
                raise ValueError("工具结果未配对或重复")
            del pending[key]
        else:
            raise ValueError("回合包含额外输入，不是单请求验收")
    if pending:
        raise ValueError("工具结果缺失")
    search = next((call for call in calls if call["name"] == "search_story"), None)
    if search:
        return {"decision": "search", "tool_name": "search_story", "arguments": search["arguments"]}
    if calls:
        raise ValueError("本轮走其他工具路线，不能误记为无需检索")
    return {"decision": "skip"}


def _inside(path: str | Path, root: Path) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(root.resolve()) or resolved == root.resolve():
        raise ValueError("导出材料必须位于显式隔离目录")
    return resolved


def _read_transcript(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if path.stat().st_size > 4_000_000:
        raise ValueError("隔离原始记录超过首版读取限额")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not records or not isinstance(records[0], dict) or records[0].get("_type") != "metadata":
        raise ValueError("缺少原生会话元数据")
    header = records[0]
    metadata = header.get("metadata")
    if (not isinstance(metadata, dict) or metadata.get("pending_user_turn") or metadata.get("runtime_checkpoint")
            or path.with_suffix(".checkpoint.json").exists()):
        raise ValueError("会话存在待完成输入／运行checkpoint")
    messages = []
    for record in records[1:]:
        if not isinstance(record, dict):
            raise ValueError("原始会话记录损坏")
        if record.get("_type") == "provider_state":
            continue  # 私有provider状态不是query来源，绝不导出。
        if record.get("_type") is not None:
            raise ValueError("原始会话记录类型不支持")
        messages.append(record)
    return header, messages


class IsolatedQueryCapture(AgentHook):
    """只由验收代码显式传入hooks；after_run不写文件，落盘后再seal。"""

    def __init__(self, *, case_id: str, session_key: str, origin: str = "synthetic",
                 model: str = "test", root: Path = DEFAULT_ROOT) -> None:
        super().__init__()
        if not isinstance(case_id, str) or not case_id.strip() or len(case_id) > 80:
            raise ValueError("案例标识无效")
        if origin not in {"synthetic", "agent_trace"} or (origin == "agent_trace" and model not in ALLOWED_MODELS):
            raise ValueError("真实来源只能由已授权Luna验收显式声明")
        self.case_id, self.session_ref, self.origin, self.model = case_id, _digest(session_key), origin, model
        self.root = Path(root).resolve()
        self.isolated_root = self.root / "isolated"
        self.receipt = None
        self.start = None
        self.problem = None

    async def before_run(self, context: AgentRunHookContext) -> None:
        if self.start is not None:
            self.problem = "一个收集器只能观察一次回合"
            return
        try:
            self.start = _turn(context.messages)[0]
            if archived_reading_scope(self.start, include_partial=False) is None:
                raise ValueError("当前请求没有可核对的服务端完整已读边界")
        except ValueError as exc:
            self.problem = str(exc)

    async def after_run(self, context: AgentRunHookContext) -> None:
        try:
            if (self.problem or context.stop_reason != "completed" or context.error or context.exception
                    or context.had_injections or not isinstance(context.final_content, str) or not context.final_content.strip()):
                raise ValueError(self.problem or "失败／打断／额外注入不是完成的查询决策")
            turn = _turn(context.messages)
            if self.start is None or turn[0] != self.start:
                raise ValueError("请求／运行时状态在回合内发生变化")
            scope = archived_reading_scope(turn[0], include_partial=False)
            self.receipt = {"version": 1, "case_id": self.case_id, "origin": self.origin,
                            "model": self.model, "trace_ref": "q-" + uuid4().hex,
                            "session_ref": self.session_ref, "work_id": scope[0], "max_order": scope[1],
                            "stop_reason": "completed", "had_injections": False,
                            "turn_count": len(turn), "turn_sha256": _hash(turn), **_decision(turn)}
        except (ValueError, TypeError, KeyError) as exc:
            self.problem = str(exc)
            self.receipt = None

    def seal(self, *, transcript: Path, output: Path) -> Path:
        """process_direct返回后验证原生JSONL已落盘；不把run结束当成持久化成功。"""
        if self.problem or self.receipt is None:
            raise ValueError(self.problem or "没有完整回合收据")
        transcript = _inside(transcript, self.isolated_root)
        output = _inside(output, self.isolated_root)
        if output == transcript or output.exists():
            raise ValueError("收据不能覆盖原始记录或已有文件")
        receipt = {**self.receipt, "transcript_ref": str(transcript.relative_to(self.root))}
        _, messages = _read_transcript(transcript)
        size = self.receipt["turn_count"]
        selected = messages[-size:]
        receipt["message_range"] = [len(messages) - size, len(messages)]
        for message in selected:
            _time(message.get("timestamp"))
        receipt["saved_times_sha256"] = _hash([message["timestamp"] for message in selected])
        _verify(receipt, transcript)
        _atomic_write(output, json.dumps(receipt, ensure_ascii=False, indent=2))
        return output


def _verify(receipt: dict[str, Any], transcript: Path) -> dict[str, Any]:
    if (type(receipt.get("version")) is not int or receipt.get("version") != 1 or receipt.get("stop_reason") != "completed"
            or receipt.get("had_injections") is not False or receipt.get("origin") not in {"synthetic", "agent_trace"}
            or not isinstance(receipt.get("trace_ref"), str) or not receipt["trace_ref"].startswith("q-")):
        raise ValueError("查询收据无效")
    if not isinstance(receipt.get("case_id"), str) or not receipt["case_id"].strip() or len(receipt["case_id"]) > 80:
        raise ValueError("收据案例标识无效")
    if receipt["origin"] == "agent_trace" and receipt.get("model") not in ALLOWED_MODELS:
        raise ValueError("真实收据模型来源不支持")
    header, messages = _read_transcript(transcript)
    if _digest(header.get("key")) != receipt.get("session_ref"):
        raise ValueError("收据与会话身份不一致")
    size = _integer(receipt.get("turn_count"), "回合消息数")
    bounds = receipt.get("message_range")
    if not isinstance(bounds, list) or len(bounds) != 2:
        raise ValueError("收据缺少已落盘消息范围")
    start, end = (_integer(value, "已落盘消息范围") for value in bounds)
    if not 2 <= size <= len(messages) or end - start != size or not 0 <= start < end <= len(messages):
        raise ValueError("收据回合范围无效")
    selected = messages[start:end]
    for message in selected:
        _time(message.get("timestamp"))
    if _hash([message["timestamp"] for message in selected]) != receipt.get("saved_times_sha256"):
        raise ValueError("已落盘消息时间与收据不一致")
    turn = [_canonical(message) for message in selected]
    scope = archived_reading_scope(turn[0], include_partial=False)
    if (_hash(turn) != receipt.get("turn_sha256") or scope != (receipt.get("work_id"), receipt.get("max_order"))
            or type(receipt.get("max_order")) is not int):
        raise ValueError("收据与已保存消息／服务端边界不一致")
    decision = _decision(turn)
    if any(receipt.get(key) != value for key, value in decision.items()):
        raise ValueError("收据与实际工具参数不一致")
    if decision["decision"] == "skip" and (receipt.get("tool_name") or receipt.get("arguments")):
        raise ValueError("无工具决策不能附加搜索参数")
    return {"case_id": receipt["case_id"], "origin": receipt["origin"], "trace_ref": receipt["trace_ref"],
            "work_id": scope[0], "max_order": scope[1], **decision}


def export_query(receipt_path: Path, *, root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    """只读核对一份显式收据，返回算法capture_trace输入；不返回原始聊天。"""
    root = Path(root).resolve()
    receipt_path = _inside(receipt_path, root / "isolated")
    if receipt_path.stat().st_size > 64_000:
        raise ValueError("查询收据超过限额")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict) or not isinstance(receipt.get("transcript_ref"), str):
        raise ValueError("查询收据结构无效")
    transcript = _inside(root / receipt["transcript_ref"], root / "isolated")
    return _verify(receipt, transcript)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = export_query(args.receipt, root=DEFAULT_ROOT)
        output = _inside(args.output, DEFAULT_ROOT / "agent-queries")
        if output.exists():
            raise ValueError("导出不覆盖已有文件，请使用新文件名")
        _atomic_write(output, json.dumps(payload, ensure_ascii=False) + "\n")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps({"exported": 1, "origin": payload["origin"], "decision": payload["decision"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
