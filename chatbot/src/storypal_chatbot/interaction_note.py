"""User-scoped Markdown notes for current interaction agreements."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .storage import NotesStore


SECTIONS = {
    "constraint": "行为约束",
    "correction": "认知修正",
    "preference": "偏好设置",
    "agreement": "共同约定",
    "temporary": "临时事项",
    "observation": "开放观察",
}

_NOTE_LINE = re.compile(r"^- \[n-([0-9a-f]+)\] (.*?)  <!-- (.*?) -->$")
_NOTE_ID = re.compile(r"^[0-9a-f]{8,32}$")
_MAINTENANCE_HEADING = "\n## 维护记录（不注入）\n"


def _identity(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _one_line(value: str) -> str:
    return " ".join(value.split()).replace("<!--", "＜!--").replace("-->", "--＞").strip()


class InteractionNoteStore:
    """Keep Note.md as the auditable source of current non-story interaction notes."""

    def __init__(self, workspace: str | Path) -> None:
        self.root = Path(workspace) / ".storypal" / "interaction_notes"
        self.legacy = NotesStore(workspace)

    def _path(self, owner_key: str) -> Path:
        return self.root / _identity(owner_key) / "Note.md"

    @staticmethod
    def _empty_document() -> str:
        return "# Note.md｜当前交互笔记\n\n" + "".join(
            f"## {heading}\n\n" for heading in SECTIONS.values()
        ) + "## 旧版明确笔记\n"

    def _ensure_migrated(self, owner_key: str) -> Path:
        path = self._path(owner_key)
        if path.is_file():
            return path
        document = self._empty_document()
        legacy = self.legacy.list(owner_key)
        if legacy:
            lines = []
            for item in legacy:
                content = _one_line(str(item.get("content") or ""))
                if not content:
                    continue
                note_id = str(item.get("id") or uuid4().hex[:12])
                if not _NOTE_ID.fullmatch(note_id):
                    note_id = uuid4().hex[:12]
                created_at = str(item.get("created_at") or "旧版记录")
                source = _identity(str(item.get("source_session_key") or "unknown"))
                lines.append(f"- [n-{note_id}] {content}  <!-- {created_at} / {source} -->")
            document += "\n".join(lines) + "\n"
        self._write(path, document)
        return path

    @staticmethod
    def _write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".md.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    def read(self, owner_key: str) -> str:
        document = self._ensure_migrated(owner_key).read_text(encoding="utf-8")
        return document.partition(_MAINTENANCE_HEADING)[0]

    @staticmethod
    def _entries(document: str) -> list[dict[str, str]]:
        category, entries = None, []
        headings = {f"## {value}": key for key, value in SECTIONS.items()}
        for line in document.partition(_MAINTENANCE_HEADING)[0].splitlines():
            if line.startswith("## "):
                category = headings.get(line)
            match = _NOTE_LINE.fullmatch(line)
            if match and category:
                entries.append({"note_id": match[1], "category": category, "content": match[2],
                                "metadata": match[3], "line": line,
                                "revision": hashlib.sha256(line.encode()).hexdigest()})
        return entries

    def read_for_context(self, owner_key: str, *, session_key: str) -> str:
        """全量注入当前有效Note；临时项只属于创建会话，未知scope不猜测。"""
        document = self.read(owner_key)
        category, kept = None, []
        for line in document.splitlines(keepends=True):
            if line.startswith("## "):
                category = "temporary" if line.strip() == "## 临时事项" else None
            if category == "temporary" and line.strip() and not line.startswith("## "):
                match = _NOTE_LINE.fullmatch(line.rstrip("\r\n"))
                source = re.search(r" / ([0-9a-f]{24}):", match[3]) if match else None
                if not source or source[1] != _identity(session_key):
                    continue
            kept.append(line)
        return "".join(kept)

    def review_snapshot(self, owner_key: str) -> list[dict[str, str]]:
        """最多4条／2400字开放观察；不创建文件，不读其他用户。"""
        path = self._path(owner_key)
        if not path.is_file():
            return []
        selected, used = [], 0
        for entry in self._entries(path.read_text(encoding="utf-8")):
            if entry["category"] != "observation" or used + len(entry["content"]) > 2400:
                continue
            selected.append(entry)
            used += len(entry["content"])
            if len(selected) == 4:
                break
        return selected

    def apply_reviews(self, owner_key: str, reviews: list[dict[str, Any]], *,
                      snapshot: list[dict[str, str]], validate_only: bool = False) -> dict[str, int]:
        """仅修订／停用已有观察；来源逐字校验、目标版本校验，单MD原子替换。"""
        if not isinstance(reviews, list) or len(reviews) > 4:
            raise ValueError("开放观察复核格式无效")
        if not reviews:
            return {"reviewed": 0}
        path = self._path(owner_key)
        if not path.is_file():
            raise ValueError("开放观察目标不存在")
        document = path.read_text(encoding="utf-8")
        active, separator, history = document.partition(_MAINTENANCE_HEADING)
        expected = {entry["note_id"]: entry for entry in snapshot}
        entries = self._entries(active)
        current = {entry["note_id"]: entry for entry in entries}
        planned, seen = [], set()
        for review in reviews:
            if not isinstance(review, dict):
                raise ValueError("开放观察复核格式无效")
            note_id, action = review.get("note_id"), review.get("action")
            if not isinstance(note_id, str) or note_id in seen or action not in {"revise", "retire"}:
                raise ValueError("开放观察复核目标／动作无效")
            seen.add(note_id)
            entry = expected.get(note_id)
            if not entry or entry["category"] != "observation":
                raise ValueError("只能维护本次快照中的开放观察")
            quote, text = review.get("source_quote"), review.get("source_text")
            if not isinstance(quote, str) or not quote.strip() or not isinstance(text, str) or quote not in text:
                raise ValueError("复核必须引用本批用户原话")
            session, turn = review.get("source_session_key"), review.get("source_turn_id")
            if not isinstance(session, str) or not session or not isinstance(turn, str) or not turn:
                raise ValueError("复核来源身份无效")
            content = review.get("content", "")
            if action == "revise":
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("修订内容为空")
                content = _one_line(content)
                if not content.startswith("待验证："):
                    content = "待验证：" + content
                if len(content) > 800:
                    raise ValueError("修订内容过长")
            elif content:
                raise ValueError("停用观察不能添加新内容")
            review_id = _identity(f"{note_id}|{session}|{turn}|{action}|{content}")
            marker = f"[r-{review_id}]"
            if marker in history:
                continue  # 同一操作重试不重复修改／归档。
            actual = current.get(note_id)
            if (not actual or actual["category"] != "observation" or actual["revision"] != entry["revision"]
                    or sum(item["note_id"] == note_id for item in entries) != 1):
                raise ValueError("复核期间Note目标已变化，保留当前记录")
            new_line = ""
            now = datetime.now(UTC).isoformat()
            if action == "revise":
                metadata = f"{now} / {_identity(session)}:{_one_line(turn)}"
                new_line = f"- [n-{note_id}] {content}  <!-- {metadata} -->\n"
            audit = (f"- {marker} {action} n-{note_id}；{now}；来源 {_identity(session)}:{_one_line(turn)}；"
                     f"用户摘录：{_one_line(quote)}\n  旧记录：{entry['line']}\n")
            planned.append((entry["line"], new_line, audit))
        if not validate_only and planned:
            replacements = {old: new for old, new, _audit in planned}
            active = "".join(replacements.get(line.rstrip("\r\n"), line)
                             for line in active.splitlines(keepends=True))
            for _old, _new, audit in planned:
                history += audit
            self._write(path, active.rstrip() + "\n" + _MAINTENANCE_HEADING + history)
        return {"reviewed": len(planned)}

    def apply_candidate(
        self,
        owner_key: str,
        *,
        category: str,
        content: str,
        source_quote: str,
        source_text: str,
        source_session_key: str,
        source_turn_id: str,
    ) -> dict[str, Any]:
        """Shared admission path for synchronous and archived note extraction."""
        if not isinstance(source_quote, str) or not source_quote.strip() or source_quote not in source_text:
            raise ValueError("Note 来源必须逐字出自对应的用户原话")
        if not isinstance(content, str):
            raise ValueError("Note 内容格式无效")
        return self.add(
            owner_key,
            category=category,
            content=content,
            source_session_key=source_session_key,
            source_turn_id=source_turn_id,
        )
    def add(
        self,
        owner_key: str,
        *,
        category: str,
        content: str,
        source_session_key: str,
        source_turn_id: str,
    ) -> dict[str, Any]:
        if category not in SECTIONS:
            raise ValueError("不支持的 Note 分类")
        normalized = _one_line(content)
        if not normalized:
            raise ValueError("Note 内容为空")
        if category == "observation" and not normalized.startswith("待验证："):
            normalized = "待验证：" + normalized
        if not normalized or len(normalized) > 800:
            raise ValueError("Note 内容需为 1～800 字的单条交互约定")
        path = self._ensure_migrated(owner_key)
        document = path.read_text(encoding="utf-8")
        active, separator, history = document.partition(_MAINTENANCE_HEADING)
        for entry in self._entries(active):
            if entry["category"] == category and entry["content"] == normalized:
                if category == "temporary":
                    source = re.search(r" / ([0-9a-f]{24}):", entry["metadata"])
                    if not source or source[1] != _identity(source_session_key):
                        continue
                return {"id": entry["note_id"], "category": category, "content": normalized, "duplicate": True}
        note_id = uuid4().hex[:12]
        created_at = datetime.now(UTC).isoformat()
        source = f"{_identity(source_session_key)}:{_one_line(source_turn_id)}"
        if category == "temporary":
            source += " / scope=session"
        bullet = f"- [n-{note_id}] {normalized}  <!-- {created_at} / {source} -->"
        heading = f"## {SECTIONS[category]}\n"
        if heading not in active:
            active += f"\n{heading}\n"
        active = active.replace(heading, heading + "\n" + bullet + "\n", 1)
        document = active + separator + history
        self._write(path, document)
        return {
            "id": note_id,
            "category": category,
            "content": normalized,
            "created_at": created_at,
            "duplicate": False,
        }

    def forget(self, owner_key: str, note_id: str) -> bool:
        if not _NOTE_ID.fullmatch(note_id):
            return False
        path = self._ensure_migrated(owner_key)
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        kept = [line for line in lines if not line.startswith(f"- [n-{note_id}] ")]
        if len(kept) == len(lines):
            return False
        self._write(path, "".join(kept))
        return True
