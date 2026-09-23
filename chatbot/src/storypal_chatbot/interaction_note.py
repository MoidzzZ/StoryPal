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
        return self._ensure_migrated(owner_key).read_text(encoding="utf-8")

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
        if not normalized or len(normalized) > 800:
            raise ValueError("Note 内容需为 1～800 字的单条交互约定")
        path = self._ensure_migrated(owner_key)
        document = path.read_text(encoding="utf-8")
        for line in document.splitlines():
            match = _NOTE_LINE.fullmatch(line)
            if match and match.group(2) == normalized:
                return {"id": match.group(1), "category": category, "content": normalized, "duplicate": True}
        note_id = uuid4().hex[:12]
        created_at = datetime.now(UTC).isoformat()
        source = f"{_identity(source_session_key)}:{_one_line(source_turn_id)}"
        bullet = f"- [n-{note_id}] {normalized}  <!-- {created_at} / {source} -->"
        heading = f"## {SECTIONS[category]}\n"
        if heading not in document:
            document += f"\n{heading}\n"
        document = document.replace(heading, heading + "\n" + bullet + "\n", 1)
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