"""按日互动经历的 Markdown 事实源；不抽取、不检索、不修改其他记忆。"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from nanobot.runtime_context import public_history_message


SHANGHAI = timezone(timedelta(hours=8))
_META = re.compile(r"^<!-- episode-meta (.+) -->$", re.MULTILINE)


def _digest(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("经历的用户和会话标识不能为空")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} 必须是非负整数")
    return value


def _text(value: Any, label: str, limit: int, *, optional: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} 必须是文本")
    text = " ".join(value.split()).replace("<!--", "＜!--").replace("-->", "--＞")
    if (not optional and not text) or len(text) > limit:
        raise ValueError(f"{label} 内容为空或超过 {limit} 字")
    return text


def _time(value: Any) -> datetime:
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", value):
        raise ValueError("经历来源必须有原消息时间")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("经历来源时间格式无效") from exc
    # 当前 nanobot 原始消息为本机无时区时间；StoryPal 配置为上海时区。
    return (result.replace(tzinfo=SHANGHAI) if result.tzinfo is None else result).astimezone(SHANGHAI)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


class EpisodicMemoryStore:
    """单维护者写入；水位只在所有候选落盘后推进，不把来源验证当语义核验。"""

    def __init__(self, workspace: str | Path) -> None:
        self.root = Path(workspace) / ".storypal" / "episodic_memory"

    def _state_path(self, session_key: str) -> Path:
        return self.root / "_archive_state" / f"{_digest(session_key)}.json"

    def _memory_root(self, owner_key: str) -> Path:
        return self.root / _digest(owner_key) / "memory"

    def bind_session(self, owner_key: str, session_key: str, *, archived: int) -> int:
        """首次从当前水位开始；不静默回扫旧用户历史，已绑定会话不允许换 owner。"""
        archived = _integer(archived, "归档水位")
        path = self._state_path(session_key)
        if path.exists():
            return self.processed(owner_key, session_key)
        state = {"owner_hash": _digest(owner_key), "processed": archived, "source_session_key": session_key}
        _atomic_write(path, json.dumps(state, ensure_ascii=False) + "\n")
        return archived

    def processed(self, owner_key: str, session_key: str) -> int:
        path = self._state_path(session_key)
        if not path.is_file():
            raise ValueError("会话尚未绑定经历维护者")
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("owner_hash") != _digest(owner_key):
            raise ValueError("经历会话 owner 不匹配")
        return _integer(state.get("processed"), "处理水位")

    def list_records(self, owner_key: str) -> list[dict[str, Any]]:
        """读取 Markdown，供后续可重建索引使用；不创建文件或做相似度检索。"""
        records = []
        for path in sorted(self._memory_root(owner_key).glob("????-??-??.md")):
            document = path.read_text(encoding="utf-8")
            for match in _META.finditer(document):
                record = json.loads(match.group(1))
                if not isinstance(record, dict) or record.get("owner_hash") != _digest(owner_key):
                    raise ValueError("经历文件元数据损坏或用户不匹配")
                # 实际检索内容取可读正文，元数据只承担来源／稳定标识。
                begin = document.rfind("\n## [e-", 0, match.start())
                if begin < 0:
                    raise ValueError("经历正文缺失")
                records.append({**record, "text": document[begin + 1:match.start()].strip()})
        return records

    def bound_sessions(self, owner_key: str) -> list[str]:
        """仅枚举已绑定当前用户的来源；不扫描／认领上游所有历史会话。"""
        keys = []
        for path in sorted((self.root / "_archive_state").glob("*.json")):
            state = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or state.get("owner_hash") != _digest(owner_key):
                continue
            key = state.get("source_session_key")
            if isinstance(key, str) and key.strip() and _digest(key) == path.stem:
                keys.append(key)
        return keys

    def commit_archive(
        self, owner_key: str, session_key: str, *, messages: list[dict[str, Any]],
        archived_end: int, candidates: list[dict[str, Any]],
        work_id: str | None = None, max_seen_order: int | None = None,
        validate_only: bool = False,
    ) -> dict[str, Any]:
        """接收抽取器候选；只允许本批已归档原话引用，不接受模型指定进度。"""
        start = self.processed(owner_key, session_key)
        end = _integer(archived_end, "归档末尾")
        if end < start or end > len(messages):
            raise ValueError("归档范围无效，不能包含未归档消息")
        if not isinstance(candidates, list) or len(candidates) > 4:
            raise ValueError("经历候选必须是最多四条的列表")
        if end == start:
            # 已提交的水位不重新解释旧候选，也不覆盖先前落盘内容。
            return {"written": 0, "processed": end, "ids": [], "duplicate": True}
        if work_id is not None:
            work_id = _text(work_id, "作品标识", 120)
            max_seen_order = _integer(max_seen_order, "已读边界")
        elif max_seen_order is not None:
            raise ValueError("已读边界必须关联作品")
        pending = []
        for slot, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                raise ValueError("经历候选格式无效")
            title = _text(candidate.get("title"), "标题", 100)
            context = _text(candidate.get("context"), "讨论情境", 500)
            development = _text(candidate.get("development"), "理解变化", 800)
            question = _text(candidate.get("open_question", ""), "未解问题", 500, optional=True)
            refs = candidate.get("source_refs")
            if not isinstance(refs, list) or not 1 <= len(refs) <= 8:
                raise ValueError("经历必须有一到八条原消息引用")
            sources, times = [], []
            for ref in refs:
                if not isinstance(ref, dict):
                    raise ValueError("来源引用格式无效")
                index = _integer(ref.get("message_index"), "原消息序号")
                if not start <= index < end:
                    raise ValueError("来源必须落在本批已归档范围")
                source = public_history_message(messages[index])
                role, content = source.get("role"), source.get("content")
                quote = ref.get("quote")
                if role not in {"user", "assistant", "tool"} or not isinstance(content, str):
                    raise ValueError("来源角色或原文无效")
                if not isinstance(quote, str) or not quote.strip() or len(quote) > 200 or quote not in content:
                    raise ValueError("来源摘录必须逐字出自原消息且不超过 200 字")
                timestamp = _time(source.get("timestamp"))
                times.append(timestamp)
                sources.append({"message_index": index, "role": role,
                                "timestamp": timestamp.isoformat(), "quote": quote})
            if not any(source["role"] == "user" for source in sources):
                raise ValueError("经历不能只来自助手或工具观察")
            episode_id = _digest(f"{owner_key}\0{session_key}\0{start}:{end}\0{slot}")
            # scope 必须由未来协调器给出该批保守边界，不能采用模型候选字段。
            metadata = {"id": episode_id, "owner_hash": _digest(owner_key),
                        "source_session_key": session_key, "archive_range": [start, end],
                        "time_start": min(times).isoformat(), "time_end": max(times).isoformat(),
                        "source_refs": sources, "work_id": work_id, "max_seen_order": max_seen_order}
            encoded = json.dumps(metadata, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
            body = (f"\n## [e-{episode_id}] {title}\n\n"
                    f"- 发生时间：{metadata['time_start']} — {metadata['time_end']}\n"
                    f"- 讨论情境：{context}\n- 理解变化：{development}\n"
                    f"- 未解问题：{question or '未记录'}\n"
                    f"- 来源：会话 {_digest(session_key)}，消息 "
                    + "、".join(f"m{s['message_index']}" for s in sources)
                    + f"\n\n<!-- episode-meta {encoded} -->\n")
            date = min(times).date().isoformat()
            pending.append((date, episode_id, body))
        if validate_only:
            return {"validated": len(pending), "processed": start}
        # 先验证全部候选，再写文件；中途写失败时水位不变，重试以稳定 ID 去重。
        written = 0
        for date, episode_id, body in pending:
            path = self._memory_root(owner_key) / f"{date}.md"
            document = path.read_text(encoding="utf-8") if path.exists() else f"# {date}｜互动经历\n"
            if f"\n## [e-{episode_id}] " not in document:
                _atomic_write(path, document + body)
                written += 1
        state = {"owner_hash": _digest(owner_key), "processed": end, "source_session_key": session_key,
                 "last_result": {"written": written, "candidates": len(candidates)}}
        _atomic_write(self._state_path(session_key), json.dumps(state, ensure_ascii=False) + "\n")
        return {"written": written, "processed": end, "ids": [item[1] for item in pending]}
