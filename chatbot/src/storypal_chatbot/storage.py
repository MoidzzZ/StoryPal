"""Small local stores used by the first StoryPal chatbot prototype.

These stores intentionally avoid making assumptions about the future Story Store.
They only own conversational state and explicit user notes.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
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


class ReadingProgressStore:
    """Persist the confirmed reading boundary by user, across conversations."""

    def __init__(self, workspace: str | Path) -> None:
        self.root = Path(workspace) / ".storypal" / "reading_progress"
        self.legacy = SessionStateStore(workspace)

    def _path(self, owner_key: str) -> Path:
        return self.root / f"{_session_id(owner_key)}.json"

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {"active_work": None, "current_anchor": None, "max_seen_order": None}

    def _document(self, owner_key: str) -> dict[str, Any]:
        value = _read_json(self._path(owner_key), {})
        if not isinstance(value, dict):
            return {"active_work": None, "works": {}}
        works = value.get("works")
        return {
            "active_work": value.get("active_work"),
            "works": works if isinstance(works, dict) else {},
        }

    def get(
        self, owner_key: str, *, legacy_session_key: str | None = None
    ) -> dict[str, Any]:
        path = self._path(owner_key)
        if not path.is_file() and legacy_session_key:
            old = self.legacy.get(legacy_session_key)
            if old["active_work"]:
                return self.set(
                    owner_key,
                    active_work=old["active_work"],
                    current_anchor=old["current_anchor"],
                    max_seen_order=old["max_seen_order"],
                )
        document = self._document(owner_key)
        active_work = document["active_work"]
        if not isinstance(active_work, str) or not active_work:
            return self._empty()
        state = document["works"].get(active_work)
        if not isinstance(state, dict):
            state = {}
        return {
            "active_work": active_work,
            "current_anchor": state.get("current_anchor"),
            "max_seen_order": state.get("max_seen_order"),
        }

    def set(
        self,
        owner_key: str,
        *,
        active_work: str | None = None,
        current_anchor: str | None = None,
        max_seen_order: int | None = None,
        source_session_key: str | None = None,
    ) -> dict[str, Any]:
        document = self._document(owner_key)
        work_id = active_work or document["active_work"]
        if not work_id:
            raise ValueError("设置阅读位置前必须指定作品")
        works = document["works"]
        previous = works.get(work_id)
        state = dict(previous) if isinstance(previous, dict) else {}
        old_order = state.get("max_seen_order")
        if max_seen_order is not None:
            if old_order is not None and max_seen_order < old_order:
                raise ValueError("max_seen_order cannot move backwards; clear the state first")
            state["max_seen_order"] = max_seen_order
        if current_anchor is not None:
            state["current_anchor"] = current_anchor
        state["updated_at"] = datetime.now(UTC).isoformat()
        if source_session_key:
            state["source_session_key"] = source_session_key
        works[work_id] = state
        document["active_work"] = work_id
        _atomic_write_json(self._path(owner_key), document)
        return self.get(owner_key)

    def clear(self, owner_key: str) -> dict[str, Any]:
        document = self._document(owner_key)
        active_work = document["active_work"]
        if active_work:
            document["works"].pop(active_work, None)
        document["active_work"] = None
        _atomic_write_json(self._path(owner_key), document)
        return self._empty()

class PendingReadingProgressStore:
    """One short-lived, session-bound reading progress confirmation."""

    def __init__(self, workspace: str | Path) -> None:
        self.root = Path(workspace) / ".storypal" / "pending_reading_progress"

    def _path(self, session_key: str) -> Path:
        return self.root / f"{_session_id(session_key)}.json"

    def propose(
        self,
        session_key: str,
        owner_key: str,
        *,
        work_id: str,
        location_id: str,
        label: str,
        end_order: int,
        source_turn_id: str,
    ) -> dict[str, Any]:
        pending = {
            "pending_id": uuid4().hex[:16],
            "owner_id": _session_id(owner_key),
            "work_id": work_id,
            "location_id": location_id,
            "label": label,
            "end_order": end_order,
            "source_turn_id": source_turn_id,
            "created_at": datetime.now(UTC).isoformat(),
        }
        _atomic_write_json(self._path(session_key), pending)
        return {key: value for key, value in pending.items() if key not in {"owner_id", "source_turn_id"}}

    def get(
        self, session_key: str, owner_key: str, pending_id: str
    ) -> dict[str, Any] | None:
        pending = _read_json(self._path(session_key), {})
        if not isinstance(pending, dict):
            return None
        if pending.get("owner_id") != _session_id(owner_key):
            return None
        if pending.get("pending_id") != pending_id:
            return None
        try:
            created_at = datetime.fromisoformat(str(pending["created_at"]))
        except (KeyError, TypeError, ValueError):
            return None
        if created_at.tzinfo is None or datetime.now(UTC) - created_at > timedelta(minutes=30):
            return None
        return pending

    def clear(self, session_key: str, owner_key: str, pending_id: str) -> bool:
        if self.get(session_key, owner_key, pending_id) is None:
            return False
        _atomic_write_json(self._path(session_key), {})
        return True

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
            "anchor_status": "unconfirmed" if anchor_order == 0 else "confirmed",
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

class HistoryMemoryStore:
    """可检索的跨会话阅读 episode；只保存显式写入的用户侧记忆。"""

    VALID_MEMORY_TYPES = {"prediction", "reflection", "preference", "conclusion"}

    def __init__(self, workspace: str | Path) -> None:
        self.path = Path(workspace) / ".storypal" / "history_memory" / "memories.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    anchor_order INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    entities_json TEXT NOT NULL,
                    source_session TEXT NOT NULL,
                    source_trace TEXT,
                    evidence_refs_json TEXT NOT NULL,
                    outcome TEXT,
                    idempotency_key TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memories_scope
                    ON memories(owner_id, scope, anchor_order, created_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_idempotency
                    ON memories(owner_id, idempotency_key)
                    WHERE idempotency_key IS NOT NULL;
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                    USING fts5(memory_id UNINDEXED, content, entities, tokenize='unicode61');
                """
            )

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "memory_id": row["memory_id"],
            "memory_type": row["memory_type"],
            "scope": row["scope"],
            "anchor_order": row["anchor_order"],
            "content": row["content"],
            "entities": json.loads(row["entities_json"]),
            "source_session": row["source_session"],
            "source_trace": row["source_trace"],
            "evidence_refs": json.loads(row["evidence_refs_json"]),
            "outcome": row["outcome"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _fts_query(query: str) -> str:
        """生成受限 FTS 查询；不把用户文本解释为 FTS 运算符。"""
        normalized = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff]+", " ", query).strip()
        terms = re.findall(r"[0-9A-Za-z_]+|[\u4e00-\u9fff]+", normalized)
        return " OR ".join(f'"{term}"' for term in terms[:12])

    def add(
        self,
        owner_key: str,
        *,
        memory_type: str,
        scope: str,
        anchor_order: int,
        content: str,
        entities: list[str] | None,
        source_session_key: str,
        source_trace: str | None,
        evidence_refs: list[str] | None,
        outcome: str | None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if memory_type not in self.VALID_MEMORY_TYPES:
            raise ValueError("memory_type 不受支持")
        if not scope.strip() or anchor_order < 0 or not content.strip():
            raise ValueError("记忆必须包含作品范围、已读位置和正文")
        if source_trace and ("\n" in source_trace or "\r" in source_trace):
            raise ValueError("source_trace 只能保存单行 trace 引用，不能写入原始工具内容")
        owner_id = _session_id(owner_key)
        normalized_entities = [value.strip() for value in (entities or []) if value and value.strip()]
        normalized_refs = [value.strip() for value in (evidence_refs or []) if value and value.strip()]
        memory_id = uuid4().hex[:16]
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            if idempotency_key:
                existing = connection.execute(
                    "SELECT * FROM memories WHERE owner_id = ? AND idempotency_key = ?",
                    (owner_id, idempotency_key),
                ).fetchone()
                if existing is not None:
                    return self._decode(existing)
            connection.execute(
                """
                INSERT INTO memories (
                    memory_id, owner_id, memory_type, scope, anchor_order, content,
                    entities_json, source_session, source_trace, evidence_refs_json,
                    outcome, idempotency_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    owner_id,
                    memory_type,
                    scope.strip(),
                    anchor_order,
                    content.strip(),
                    json.dumps(normalized_entities, ensure_ascii=False),
                    _session_id(source_session_key),
                    (source_trace or "").strip() or None,
                    json.dumps(normalized_refs, ensure_ascii=False),
                    (outcome or "").strip() or None,
                    (idempotency_key or "").strip() or None,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO memory_fts(memory_id, content, entities) VALUES (?, ?, ?)",
                (memory_id, content.strip(), " ".join(normalized_entities)),
            )
            row = connection.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,)).fetchone()
        assert row is not None
        return self._decode(row)

    def search(
        self,
        owner_key: str,
        *,
        scope: str,
        max_seen_order: int,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not scope.strip() or max_seen_order < 0 or limit <= 0:
            return []
        owner_id = _session_id(owner_key)
        fts_query = self._fts_query(query)
        with self._connect() as connection:
            rows: list[sqlite3.Row] = []
            if fts_query:
                rows = connection.execute(
                    """
                    SELECT memories.*, bm25(memory_fts) AS rank
                    FROM memory_fts
                    JOIN memories ON memories.memory_id = memory_fts.memory_id
                    WHERE memory_fts MATCH ?
                      AND memories.owner_id = ?
                      AND memories.scope = ?
                      AND memories.anchor_order <= ?
                    ORDER BY rank, memories.created_at DESC
                    LIMIT ?
                    """,
                    (fts_query, owner_id, scope, max_seen_order, limit),
                ).fetchall()
            if not rows:
                pattern = f"%{query.strip()}%"
                rows = connection.execute(
                    """
                    SELECT * FROM memories
                    WHERE owner_id = ? AND scope = ? AND anchor_order <= ?
                      AND (content LIKE ? OR entities_json LIKE ?)
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (owner_id, scope, max_seen_order, pattern, pattern, limit),
                ).fetchall()
        return [self._decode(row) for row in rows]

    def delete(self, owner_key: str, memory_id: str) -> bool:
        owner_id = _session_id(owner_key)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT memory_id FROM memories WHERE memory_id = ? AND owner_id = ?",
                (memory_id, owner_id),
            ).fetchone()
            if existing is None:
                return False
            connection.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
            connection.execute("DELETE FROM memories WHERE memory_id = ? AND owner_id = ?", (memory_id, owner_id))
        return True
