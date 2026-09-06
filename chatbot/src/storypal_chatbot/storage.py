"""Small local stores used by the first StoryPal chatbot prototype.

These stores intentionally avoid making assumptions about the future Story Store.
They only own conversational state and explicit user notes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _session_id(session_key: str) -> str:
    return hashlib.sha256(session_key.encode("utf-8")).hexdigest()[:24]


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


class SessionStateStore:
    """Persist the minimal, per-conversation story navigation state."""

    def __init__(self, workspace: str | Path) -> None:
        self.root = Path(workspace) / ".storypal" / "session_state"

    def _path(self, session_key: str) -> Path:
        return self.root / f"{_session_id(session_key)}.json"

    def get(self, session_key: str) -> dict[str, Any]:
        value = _read_json(self._path(session_key), {})
        return {
            "active_work": value.get("active_work"),
            "current_anchor": value.get("current_anchor"),
            "max_seen_order": value.get("max_seen_order"),
        }

    def set(
        self,
        session_key: str,
        *,
        active_work: str | None = None,
        current_anchor: str | None = None,
        max_seen_order: int | None = None,
    ) -> dict[str, Any]:
        previous = self.get(session_key)
        state = dict(previous)

        if active_work is not None and active_work != previous["active_work"]:
            state = {
                "active_work": active_work,
                "current_anchor": None,
                "max_seen_order": None,
            }
        elif active_work is not None:
            state["active_work"] = active_work

        if current_anchor is not None:
            state["current_anchor"] = current_anchor

        old_order = state.get("max_seen_order")
        if max_seen_order is not None:
            if old_order is not None and max_seen_order < old_order:
                raise ValueError("max_seen_order cannot move backwards; clear the state first")
            state["max_seen_order"] = max_seen_order

        _atomic_write_json(self._path(session_key), state)
        return state

    def clear(self, session_key: str) -> dict[str, Any]:
        path = self._path(session_key)
        if path.exists():
            path.unlink()
        return self.get(session_key)


class NotesStore:
    """Persist notes created by explicit user intent, scoped to one sender."""

    def __init__(self, workspace: str | Path) -> None:
        self.root = Path(workspace) / ".storypal" / "notes"

    def _path(self, owner_key: str) -> Path:
        return self.root / f"{_session_id(owner_key)}.json"

    def list(self, owner_key: str) -> list[dict[str, Any]]:
        value = _read_json(self._path(owner_key), [])
        return value if isinstance(value, list) else []

    def add(
        self,
        owner_key: str,
        *,
        content: str,
        title: str | None,
        source_session_key: str,
    ) -> dict[str, Any]:
        note = {
            "id": uuid4().hex[:12],
            "title": (title or "").strip() or None,
            "content": content.strip(),
            "created_at": datetime.now(UTC).isoformat(),
            "source_session_key": source_session_key,
        }
        notes = self.list(owner_key)
        notes.append(note)
        _atomic_write_json(self._path(owner_key), notes)
        return note

    def delete(self, owner_key: str, note_id: str) -> bool:
        notes = self.list(owner_key)
        kept = [note for note in notes if note.get("id") != note_id]
        if len(kept) == len(notes):
            return False
        _atomic_write_json(self._path(owner_key), kept)
        return True


class ReadingNotebookStore:
    """Persist user-confirmed reading reactions, questions and predictions separately from Notes."""

    VALID_ENTRY_TYPES = {"reaction", "question", "prediction"}

    def __init__(self, workspace: str | Path) -> None:
        self.root = Path(workspace) / ".storypal" / "reading_notebook"

    def _path(self, owner_key: str) -> Path:
        return self.root / f"{_session_id(owner_key)}.json"

    def list(
        self, owner_key: str, *, active_work: str, max_seen_order: int
    ) -> list[dict[str, Any]]:
        value = _read_json(self._path(owner_key), [])
        if not isinstance(value, list):
            return []
        return [
            entry
            for entry in value
            if entry.get("active_work") == active_work
            and isinstance(entry.get("anchor_order"), int)
            and entry["anchor_order"] <= max_seen_order
        ]

    def add(
        self,
        owner_key: str,
        *,
        active_work: str,
        anchor_order: int,
        anchor_text: str | None,
        entry_type: str,
        content: str,
        source_session_key: str,
    ) -> dict[str, Any]:
        if entry_type not in self.VALID_ENTRY_TYPES:
            raise ValueError("entry_type 只能是 reaction、question 或 prediction")
        entry = {
            "id": uuid4().hex[:12],
            "active_work": active_work,
            "anchor_order": anchor_order,
            "anchor_text": (anchor_text or "").strip() or None,
            "entry_type": entry_type,
            "content": content.strip(),
            "status": "open",
            "created_at": datetime.now(UTC).isoformat(),
            "source_session_key": source_session_key,
        }
        value = _read_json(self._path(owner_key), [])
        entries = value if isinstance(value, list) else []
        entries.append(entry)
        _atomic_write_json(self._path(owner_key), entries)
        return entry

    def delete(self, owner_key: str, entry_id: str) -> bool:
        value = _read_json(self._path(owner_key), [])
        entries = value if isinstance(value, list) else []
        kept = [entry for entry in entries if entry.get("id") != entry_id]
        if len(kept) == len(entries):
            return False
        _atomic_write_json(self._path(owner_key), kept)
        return True