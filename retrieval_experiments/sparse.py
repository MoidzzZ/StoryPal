"""Isolated jieba-tokenized FTS5 experiment; never touches StoryMem's index."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime" / "retrieval-experiments"
VENDOR = RUNTIME / "vendor"
DATA = ROOT / "story_mem" / "data"
DB = RUNTIME / "jieba-fts" / "story.db"
META = RUNTIME / "jieba-fts" / "meta.json"


def _jieba() -> Any:
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))
    try:
        import jieba
    except ImportError as exc:
        raise RuntimeError("jieba==0.42.1 is required in the isolated runtime vendor directory") from exc
    cache = RUNTIME / "jieba-cache"
    cache.mkdir(parents=True, exist_ok=True)
    jieba.dt.tmp_dir = str(cache)
    jieba.dt.cache_file = str(cache / "jieba.cache")
    return jieba


def _tokens(value: str, jieba: Any) -> list[str]:
    seen = set()
    tokens = []
    for part in jieba.cut(value, cut_all=False):
        term = part.strip().lower()
        if term and all(ch.isalnum() for ch in term) and term not in seen:
            seen.add(term)
            tokens.append(term)
    return tokens


def _indexed(value: str, jieba: Any) -> str:
    # Keep repetitions for BM25 term frequency; use spaces as token boundaries.
    return " ".join(part.strip().lower() for part in jieba.cut(value, cut_all=False)
                    if part.strip() and all(ch.isalnum() for ch in part.strip()))


def ensure_index(work_id: str = "wandering_earth") -> dict[str, Any]:
    source = DATA / work_id / "03_extracted" / "units_extracted.jsonl"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    jieba = _jieba()
    version = getattr(jieba, "__version__", "unknown")
    if DB.exists() and META.exists():
        meta = json.loads(META.read_text(encoding="utf-8"))
        if (meta.get("source_sha256"), meta.get("jieba_version"), meta.get("work_id")) == (digest, version, work_id):
            return meta
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as conn:
        conn.execute("DROP TABLE IF EXISTS units_fts")
        conn.execute("CREATE VIRTUAL TABLE units_fts USING fts5("
                     "unit_id UNINDEXED, ord UNINDEXED, body, summary, tokenize='unicode61')")
        conn.executemany("INSERT INTO units_fts (unit_id, ord, body, summary) VALUES (?, ?, ?, ?)",
                         [(row["unit_id"], int(row["order"]), _indexed(row.get("text", ""), jieba),
                           _indexed(row.get("summary", ""), jieba)) for row in rows])
    meta = {"work_id": work_id, "source_sha256": digest, "jieba_version": version,
            "unit_count": len(rows), "index": "fts5-unicode61-over-jieba-terms"}
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


class JiebaFtsAdapter:
    def __init__(self, mode: str) -> None:
        if mode not in ("or", "and", "phrase"):
            raise ValueError(mode)
        self.mode = mode
        self.jieba = _jieba()
        self.meta = ensure_index()
        self.last_search_diagnostics: dict[str, Any] = {}

    def search(self, work_id: str, query: str, *, max_order: int, top_k: int) -> list[dict[str, Any]]:
        if work_id != self.meta["work_id"]:
            raise ValueError("Index is for a different work")
        terms = _tokens(query, self.jieba)
        if not terms:
            return []
        quoted = ['"' + term.replace('"', '""') + '"' for term in terms]
        expr = (" OR " if self.mode == "or" else " AND ").join(quoted)
        if self.mode == "phrase":
            expr = '"' + " ".join(terms).replace('"', '""') + '"'
        with sqlite3.connect(f"{DB.as_uri()}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT unit_id, ord FROM units_fts WHERE units_fts MATCH ? AND ord <= ? "
                "ORDER BY bm25(units_fts) LIMIT ?",
                (expr, max_order, top_k),
            ).fetchall()
        self.last_search_diagnostics = {"used_retrieval": "jieba_" + self.mode,
                                        "query_term_count": len(terms), "candidate_count": len(rows),
                                        "source_version": self.meta["source_sha256"]}
        return [{"work_id": work_id, "unit_id": uid, "order": int(order)}
                for uid, order in rows]
