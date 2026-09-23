"""Checkpoint-triggered, non-blocking extraction of user interaction notes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from loguru import logger
from nanobot import RequestContext
from nanobot.session.manager import JsonlSessionStore

from .interaction_note import InteractionNoteStore


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


class ArchivedNoteCoordinator:
    """Watch the committed archive watermark; never scan live/tool messages."""

    def __init__(self, workspace: str | Path, *, sessions_root: Path | None = None) -> None:
        self.workspace = Path(workspace)
        self.notes = InteractionNoteStore(self.workspace)
        self.sessions = JsonlSessionStore(self.workspace, sessions_root=sessions_root)
        self.state_root = self.workspace / ".storypal" / "interaction_notes" / "_archive_state"
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def _state_path(self, session_key: str) -> Path:
        return self.state_root / f"{_digest(session_key)}.json"

    def _read_state(self, session_key: str) -> dict[str, Any] | None:
        path = self._state_path(session_key)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError):
            return None

    def _write_state(self, session_key: str, state: dict[str, Any]) -> None:
        path = self._state_path(session_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def observe(self, request: RequestContext) -> None:
        """At prompt build, schedule work only if a prior checkpoint committed."""
        if os.getenv("STORYPAL_AUTO_NOTE", "1").lower() in {"0", "false", "off"}:
            return
        if (
            request.channel != "websocket"
            or not request.session_key
            or not request.sender_id
            or not request.turn_id
            or not (request.original_user_text or "").strip()
            or request.runtime is None
        ):
            return

        session_key = request.session_key
        if session_key in self._tasks:
            return
        session = self.sessions.load(session_key)
        archived = session.last_archived if session is not None else 0
        owner_hash = _digest(request.sender_id)
        state = self._read_state(session_key)
        if state is None:
            # Do not reinterpret old archives under an unverified new owner.
            self._write_state(session_key, {"owner_hash": owner_hash, "processed": archived})
            return
        if state.get("owner_hash") != owner_hash or state.get("disabled"):
            state["disabled"] = True
            self._write_state(session_key, state)
            return
        processed = state.get("processed")
        if not isinstance(processed, int) or processed < 0 or processed > archived:
            state["disabled"] = True
            self._write_state(session_key, state)
            return
        if archived == processed or session is None:
            return

        messages: list[dict[str, str]] = []
        advance = archived
        for index in range(processed, archived):
            entry = session.messages[index]
            if entry.get("role") != "user" or not isinstance(entry.get("content"), str):
                continue
            content = entry["content"].strip()
            if not content:
                continue
            if len(messages) >= 8:
                advance = index
                break
            messages.append({
                "source_id": f"m{index}",
                "text": content[:800],
                "timestamp": str(entry.get("timestamp") or ""),
            })
        if not messages:
            state["processed"] = advance
            self._write_state(session_key, state)
            return

        task = asyncio.create_task(
            self._extract(
                session_key,
                request.sender_id,
                request.runtime,
                messages,
                advance,
                state,
            )
        )
        self._tasks[session_key] = task
        task.add_done_callback(lambda _task: self._tasks.pop(session_key, None))

    async def _extract(
        self,
        session_key: str,
        owner_key: str,
        runtime: Any,
        messages: list[dict[str, str]],
        advance: int,
        state: dict[str, Any],
    ) -> None:
        sources = {item["source_id"]: item for item in messages}
        prompt = (
            "你只负责从已归档的真实用户原话提取非剧情交互笔记。"
            "不要从助手、工具、小说情节、用户猜测或情绪反应推断人格。"
            "只保留未来对话确实有帮助且原话直接支持的行为约束、纠错、偏好、共同约定或开放观察。临时事项目前没有可靠失效条件，不要自动写入。开放观察必须以待验证语气记录。"
            "不确定就返回空数组；开放观察必须标明为待验证的单条原话，不得写成确定结论。"
            "只返回 JSON 对象 {\"note_ops\":[{\"category\":\"preference\",\"content\":\"...\","
            "\"source_id\":\"m0\",\"source_quote\":\"逐字摘自原话\"}]}，最多 4 条。"
            "category 只能是 constraint、correction、preference、agreement、observation。"
            "source_quote 必须是对应 source_id 的 text 原样连续子串。"
        )
        try:
            response = await runtime.provider.chat_with_retry(
                model=runtime.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(messages, ensure_ascii=False)},
                ],
                tools=[],
                temperature=0.1,
                max_tokens=1200,
                reasoning_effort=runtime.generation.reasoning_effort,
            )
            if response.finish_reason in {"error", "length"} or response.has_tool_calls:
                raise ValueError("Note 抽取未完整结束")
            payload = json.loads(response.content or "")
            operations = payload.get("note_ops") if isinstance(payload, dict) else None
            if not isinstance(operations, list) or len(operations) > 4:
                raise ValueError("Note 抽取格式无效")
            rejected = 0
            written = 0
            for operation in operations:
                if not isinstance(operation, dict):
                    rejected += 1
                    continue
                source_id = operation.get("source_id")
                source = sources.get(source_id) if isinstance(source_id, str) else None
                if source is None:
                    rejected += 1
                    continue
                category = operation.get("category")
                if category == "temporary":
                    rejected += 1
                    continue
                content = operation.get("content")
                if category == "observation" and isinstance(content, str) and not content.startswith("待验证："):
                    content = "待验证：" + content
                try:
                    item = self.notes.apply_candidate(
                        owner_key,
                        category=category,
                        content=content,
                        source_quote=operation.get("source_quote"),
                        source_text=source["text"],
                        source_session_key=session_key,
                        source_turn_id=f"archive:{source['source_id']}:{source['timestamp']}",
                    )
                    if not item["duplicate"]:
                        written += 1
                except (TypeError, ValueError):
                    rejected += 1
            state["processed"] = advance
            state["last_result"] = {"written": written, "rejected": rejected}
            self._write_state(session_key, state)
        except (OSError, ValueError, RuntimeError, TypeError) as exc:
            logger.warning("StoryPal auto Note extraction deferred for {}: {}", _digest(session_key), exc)
        except Exception as exc:
            logger.warning("StoryPal auto Note provider failed for {}: {}", _digest(session_key), exc)