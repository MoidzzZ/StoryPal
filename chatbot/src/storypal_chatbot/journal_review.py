"""进度推进后准备旧问题／预测；不调用模型，不判定预测对错。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .storage import ReadingNotebookStore, _atomic_write_json, _read_json, _session_id


class JournalReviewObserver:
    def __init__(self, workspace: str | Path) -> None:
        self.root = Path(workspace) / ".storypal" / "journal_review"
        self.journal = ReadingNotebookStore(workspace)

    def observe(self, owner_key: str, state: dict[str, Any]) -> dict[str, Any] | None:
        work = state.get("active_work")
        order = state.get("max_seen_order")
        if not work or type(order) is not int or order < 0:
            return None
        path = self.root / f"{_session_id(owner_key)}.json"
        cursors = _read_json(path, {})
        if not isinstance(cursors, dict):
            cursors = {}
        previous = cursors.get(work)
        # 首次观察仅建立基线；不回扫启用前全部手账，不因每轮请求重复触发。
        if previous == order:
            return None
        candidates = []
        if type(previous) is int and order > previous:
            for entry in reversed(self.journal.list(owner_key, active_work=work, max_seen_order=order)):
                if (entry.get("entry_type") not in {"question", "prediction"}
                        or entry.get("status") != "open" or entry["anchor_order"] > previous):
                    continue
                candidates.append({key: entry.get(key) for key in
                                   ("id", "entry_type", "content", "anchor_order", "anchor_text", "created_at", "updated_at")})
                if len(candidates) == 3:
                    break
        # 候选是待讨论的用户观点，长度控制只影响提示，不改正文或查全文。
        bounded = []
        characters = 0
        for entry in candidates:
            if characters + len(entry["content"]) <= 1800:
                bounded.append(entry)
                characters += len(entry["content"])
        _atomic_write_json(path, {**cursors, work: order})
        if not bounded:
            return None
        return {"work_id": work, "previous_order": previous, "max_order": order,
                "newly_read_orders": [previous + 1, order], "entries": bounded}
