"""互动经历的一次语义召回；Markdown 为事实源，LanceDB 仅是本地可重建缓存。"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from .episodic_memory import EpisodicMemoryStore, _atomic_write, _digest, _integer, _time


class EpisodicRecallUnavailable(RuntimeError):
    """依赖／模型／索引不可用，不应伪装为没有历史。"""


def estimated_tokens(value: dict[str, Any]) -> int:
    # 按完整 UTF-8 JSON 大小做保守工程估算，并非 provider tokenizer 实测。
    return math.ceil(len(json.dumps(value, ensure_ascii=False).encode("utf-8")) / 3)


def _measure(value: dict[str, Any]) -> None:
    while value["estimated_tokens"] != estimated_tokens(value):
        value["estimated_tokens"] = estimated_tokens(value)


class LocalBgeM3:
    def __init__(self, path: Path) -> None:
        from sentence_transformers import SentenceTransformer

        local_path = str(path.resolve())
        self.model_name = local_path + "#" + hashlib.sha256((path / "config.json").read_bytes()).hexdigest()
        self._model = SentenceTransformer(local_path, local_files_only=True)
        self._lock = RLock()

    def encode(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            rows = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [list(map(float, row)) for row in rows]


@lru_cache(maxsize=1)
def _local_encoder(path: str, config_hash: str) -> LocalBgeM3:
    # 路径／模型配置变更才重新载入，普通调用不反复冷启动。
    return LocalBgeM3(Path(path))


def default_encoder() -> LocalBgeM3:
    path = Path(os.environ.get("STORYPAL_EPISODE_MODEL", "D:/models/BAAI/bge-m3"))
    config = path / "config.json"
    if not path.is_dir() or not config.is_file():
        raise EpisodicRecallUnavailable("本地 BGE-M3 未配置；不会自动联网下载")
    try:
        return _local_encoder(str(path.resolve()), hashlib.sha256(config.read_bytes()).hexdigest())
    except Exception as exc:
        raise EpisodicRecallUnavailable("本地经历向量模型无法加载") from exc


def _vectors(encoder: Any, texts: list[str]) -> list[list[float]]:
    vectors = encoder.encode(texts)
    if len(vectors) != len(texts) or not vectors:
        raise ValueError("经历向量数量无效")
    dimension = len(vectors[0])
    if not dimension or any(len(row) != dimension or not all(math.isfinite(float(v)) for v in row)
                            or not any(float(v) != 0 for v in row) for row in vectors):
        raise ValueError("经历向量维度或数值无效")
    return [list(map(float, row)) for row in vectors]


def _semantic_text(record: dict[str, Any]) -> str:
    # 时间／哈希／消息编号用于溯源，不是语义；避免这些 bookkeeping 稀释讨论内容。
    lines = record["text"].splitlines()
    return "\n".join([lines[0].split("] ", 1)[1], *[
        line for line in lines[1:] if line.startswith(("- 讨论情境：", "- 理解变化：", "- 未解问题："))
    ]])


class EpisodicRecallService:
    def __init__(self, workspace: str | Path, *, encoder_factory: Callable = default_encoder,
                 threshold: float = 0.55, token_budget: int = 1000, candidate_limit: int = 30) -> None:
        if not math.isfinite(threshold) or not -1 <= threshold <= 1:
            raise ValueError("经历召回阈值无效")
        if type(token_budget) is not int or token_budget < 128:
            raise ValueError("经历预算至少 128 个估算 tokens")
        if type(candidate_limit) is not int or not 1 <= candidate_limit <= 100:
            raise ValueError("经历候选池范围无效")
        self.store = EpisodicMemoryStore(workspace)
        self.encoder_factory = encoder_factory
        self.threshold, self.token_budget, self.candidate_limit = threshold, token_budget, candidate_limit
        self._lock = RLock()

    @classmethod
    def from_environment(cls, workspace: str | Path) -> EpisodicRecallService:
        return cls(workspace, threshold=float(os.environ.get("STORYPAL_EPISODE_THRESHOLD", "0.55")),
                   token_budget=int(os.environ.get("STORYPAL_EPISODE_TOKEN_BUDGET", "1000")))

    def _records(self, owner: str) -> list[dict[str, Any]]:
        records = self.store.list_records(owner)
        ids = set()
        for item in records:
            episode_id, session = item.get("id"), item.get("source_session_key")
            if not isinstance(episode_id, str) or not re.fullmatch(r"[0-9a-f]{24}", episode_id) or episode_id in ids:
                raise ValueError("经历标识损坏或重复")
            ids.add(episode_id)
            if item.get("owner_hash") != _digest(owner) or not isinstance(session, str) or not session.strip():
                raise ValueError("经历来源用户／会话损坏")
            bounds, refs = item.get("archive_range"), item.get("source_refs")
            if not isinstance(bounds, list) or len(bounds) != 2:
                raise ValueError("经历归档范围损坏")
            start, end = (_integer(v, "归档范围") for v in bounds)
            if start >= end or not isinstance(refs, list) or not 1 <= len(refs) <= 8:
                raise ValueError("经历来源损坏")
            times = []
            for ref in refs:
                if (not isinstance(ref, dict) or ref.get("role") not in {"user", "assistant", "tool"}
                        or not start <= _integer(ref.get("message_index"), "来源序号") < end
                        or not isinstance(ref.get("quote"), str) or not ref["quote"].strip() or len(ref["quote"]) > 200):
                    raise ValueError("经历来源字段损坏")
                times.append(_time(ref.get("timestamp")))
            if (not any(ref["role"] == "user" for ref in refs)
                    or _time(item.get("time_start")) != min(times) or _time(item.get("time_end")) != max(times)
                    or not isinstance(item.get("text"), str) or not item["text"].startswith(f"## [e-{episode_id}] ")):
                raise ValueError("经历正文或时间损坏")
            work, boundary = item.get("work_id"), item.get("max_seen_order")
            if work is None and boundary is None:
                continue  # 旧无范围记录不参与剧情召回。
            if not isinstance(work, str) or not work.strip():
                raise ValueError("经历作品范围损坏")
            _integer(boundary, "经历已读上界")
        return records

    def recall(self, owner: str, *, work_id: str, max_seen_order: int, query: str) -> dict[str, Any]:
        if not isinstance(work_id, str) or not work_id.strip():
            raise ValueError("经历召回必须绑定当前作品")
        boundary = _integer(max_seen_order, "当前已读边界")
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 240:
            raise ValueError("回忆 query 必须是 1—240 字文本")
        with self._lock:
            try:
                return self._recall(owner, work_id, boundary, query.strip())
            except (ValueError, EpisodicRecallUnavailable):
                raise
            except Exception as exc:
                # 不把可能含内部路径／原文的依赖错误交给模型。
                raise EpisodicRecallUnavailable("经历向量索引暂不可用；未完成回忆检索") from exc

    def _recall(self, owner: str, work: str, boundary: int, query: str) -> dict[str, Any]:
        records = [r for r in self._records(owner) if r.get("work_id") == work]
        eligible = {r["id"]: r for r in records if r["max_seen_order"] <= boundary}
        result = {"status": "empty", "reason": "no_eligible_episodes", "episodes": [],
                  "threshold": self.threshold, "estimated_tokens": 0, "budget_dropped": 0}
        if not eligible:
            _measure(result)
            return result  # 无安全记录时不加载模型，也不查询残留旧索引。
        fingerprint = hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        encoder = self.encoder_factory()
        import lancedb

        cache = self.store.root / _digest(owner) / "index" / _digest(work)
        cache.mkdir(parents=True, exist_ok=True)
        db = lancedb.connect(str(cache / "vectors.lance"))
        metadata_path = cache / "version.json"
        expected = {"version": "episode-vector@2", "source_sha256": fingerprint, "model": encoder.model_name}
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            metadata = None
        try:
            table = db.open_table("episodes") if metadata == expected else None
        except Exception:
            table = None
        if table is None:
            vectors = _vectors(encoder, [_semantic_text(r) for r in records])
            table = db.create_table("episodes", data=[
                {"id": r["id"], "ord": r["max_seen_order"], "vector": vector}
                for r, vector in zip(records, vectors)
            ], mode="overwrite")
            _atomic_write(metadata_path, json.dumps(expected, ensure_ascii=False))
        vector = _vectors(encoder, [query])[0]
        rows = table.search(vector, query_type="vector").metric("cosine").where(
            f"ord <= {boundary}", prefilter=True
        ).limit(self.candidate_limit).to_list()
        result.update(reason="below_threshold", source_version=fingerprint)
        for row in rows:
            record = eligible.get(row.get("id"))
            distance = float(row.get("_distance", float("nan")))
            if record is None or row.get("ord") != record["max_seen_order"] or not math.isfinite(distance):
                raise ValueError("经历索引与 Markdown 范围不一致")
            score = 1.0 - distance
            if score < self.threshold:
                continue
            episode = {"id": record["id"], "score": round(score, 6), "text": record["text"],
                       "time_start": record["time_start"], "time_end": record["time_end"],
                       "source_session_ref": _digest(record["source_session_key"]),
                       "archive_range": record["archive_range"], "source_refs": record["source_refs"]}
            proposed = {**result, "status": "ok", "reason": "matched",
                        "episodes": [*result["episodes"], episode]}
            _measure(proposed)
            if proposed["estimated_tokens"] <= self.token_budget:
                result = proposed
            else:
                result["budget_dropped"] += 1  # 不切掉来源，只整项舍弃，再试更短项。
        if not result["episodes"] and result["budget_dropped"]:
            result["reason"] = "token_budget"
        _measure(result)
        # 数字字段长度变化也计入；极限边界下整体退掉最后一项。
        while result["episodes"] and result["estimated_tokens"] > self.token_budget:
            result["episodes"].pop()
            result["budget_dropped"] += 1
            if not result["episodes"]:
                result.update(status="empty", reason="token_budget")
            _measure(result)
        return result
