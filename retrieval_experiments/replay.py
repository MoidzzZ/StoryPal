"""Capture verified Agent tool queries and replay bounded retrieval offline.

Reports contain IDs and metrics only. No story text, live session or model call
is read by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GOLDENS = ROOT / "chatbot_tests" / "story_retrieval_goldens.json"
CONTRACT = ROOT / "docs" / "research" / "retrieval" / "scenarios.json"
DATA = ROOT / "story_mem" / "data"
PIPELINE = ROOT / "story_mem" / "code"
RUNTIME = ROOT / ".runtime" / "retrieval-experiments"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_cases(case_set: str = "focused") -> list[dict[str, Any]]:
    goldens = {row["编号"]: row for row in json.loads(GOLDENS.read_text(encoding="utf-8"))}
    if case_set == "goldens29":
        return [{"case_id": row["编号"], "work_id": "wandering_earth",
                 "max_order": int(row["阅读边界"]), "raw_user": row["用户原话"],
                 "gold_rewrite": row["检索查询"],
                 "required_units": list(row["期望单元"]),
                 "retrieval_decision": "search"}
                for row in goldens.values()]
    if case_set != "focused":
        raise ValueError("Unknown case set: " + case_set)
    cases = json.loads(CONTRACT.read_text(encoding="utf-8"))
    for case in cases:
        base = goldens.get(case["case_id"])
        if base:
            if int(base["阅读边界"]) != case["max_order"] or base["期望单元"] != case["required_units"]:
                raise ValueError("Scenario differs from read-only gold: " + case["case_id"])
            case["gold_rewrite"] = base["检索查询"]
    return cases


def capture_trace(records: list[dict[str, Any]], cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize manually selected real tool calls; reject oracle or synthetic origin.

    Input JSONL: case_id, origin=agent_trace, trace_ref (opaque), work_id,
    max_order, tool_name=search_story, arguments={query:...}. For a genuine
    no-search decision use decision=skip and omit tool_name/arguments.
    """
    by_id = {c["case_id"]: c for c in cases}
    output = []
    seen: set[str] = set()
    for item in records:
        case_id = str(item.get("case_id", ""))
        case = by_id.get(case_id)
        if not case or item.get("origin") != "agent_trace":
            raise ValueError("Unknown case or unverified origin: " + case_id)
        if case_id in seen:
            raise ValueError("Only the first decision/tool call per case is supported: " + case_id)
        seen.add(case_id)
        if item.get("work_id") != case["work_id"] or item.get("max_order") != case["max_order"]:
            raise ValueError("Reading boundary mismatch: " + case_id)
        trace_ref = str(item.get("trace_ref", "")).strip()
        if not trace_ref:
            raise ValueError("Missing opaque trace_ref: " + case_id)
        if item.get("decision") == "skip":
            if item.get("tool_name") or item.get("arguments"):
                raise ValueError("Skip must not contain a tool call: " + case_id)
            query = None
        else:
            args = item.get("arguments")
            if item.get("tool_name") != "search_story" or not isinstance(args, dict):
                raise ValueError("Expected actual search_story arguments: " + case_id)
            query = args.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ValueError("Missing actual tool query: " + case_id)
            query = query.strip()
        output.append({"case_id": case_id, "query_source": "agent_query", "query": query,
                       "decision": "skip" if query is None else "search",
                       "work_id": case["work_id"], "max_order": case["max_order"],
                       "trace_ref": trace_ref})
    return output


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * ratio
    lo, hi = math.floor(pos), math.ceil(pos)
    return round(values[lo] * (hi - pos) + values[hi] * (pos - lo), 2) if lo != hi else round(values[lo], 2)


class StrictFtsAdapter:
    """Current FTS query and index, with empty MATCH kept empty instead of scan."""

    def __init__(self, story_memory: Any) -> None:
        self.story_memory = story_memory
        self.last_search_diagnostics: dict[str, Any] = {}

    def search(self, work_id: str, query: str, *, max_order: int, top_k: int) -> list[dict[str, Any]]:
        units = self.story_memory._load_units(work_id)
        by_id = {unit.unit_id: unit for unit in units}
        rows = self.story_memory._fts_rank(work_id, query, max_order, "") or []
        self.last_search_diagnostics = {"used_retrieval": "fts_strict", "candidate_count": len(rows)}
        return [self.story_memory._to_evidence(by_id[uid], score).to_dict()
                for uid, score in rows[:top_k] if uid in by_id]


def _adapter(strategy: str, candidate_k: int) -> Any:
    if strategy.startswith("jieba_"):
        from .sparse import JiebaFtsAdapter
        return JiebaFtsAdapter(strategy.removeprefix("jieba_"))
    if str(PIPELINE) not in sys.path:
        sys.path.insert(0, str(PIPELINE))
    from storymemory.adapter import StoryMemory
    if strategy == "fts_strict":
        return StrictFtsAdapter(StoryMemory(DATA, retrieval="fts"))
    if strategy == "rrf":
        from chatbot_tests.evaluate_story_retrieval import HybridRrfAdapter
        return HybridRrfAdapter(StoryMemory(DATA, retrieval="fts"),
                                StoryMemory(DATA, retrieval="vector"), candidate_k=candidate_k)
    return StoryMemory(DATA, retrieval=strategy)


def _queries(source: str, cases: list[dict[str, Any]], trace: Path | None) -> dict[str, str | None]:
    if source == "raw_user":
        return {c["case_id"]: c["raw_user"] for c in cases}
    if source == "gold_rewrite":
        return {c["case_id"]: c["gold_rewrite"] for c in cases if "gold_rewrite" in c}
    if source != "agent_query" or trace is None:
        raise ValueError("agent_query requires an explicit captured --trace")
    rows = read_jsonl(trace)
    result: dict[str, str | None] = {}
    by_id = {c["case_id"]: c for c in cases}
    for row in rows:
        case_id = row.get("case_id")
        case = by_id.get(case_id)
        if row.get("query_source") != "agent_query" or case_id in result or not case:
            raise ValueError("Trace must contain unique captured agent_query rows")
        if row.get("work_id") != case["work_id"] or row.get("max_order") != case["max_order"] or not row.get("trace_ref"):
            raise ValueError("Captured trace lacks source or boundary provenance")
        query = row.get("query")
        if query is not None and (not isinstance(query, str) or not query.strip()):
            raise ValueError("Captured query must be nonempty text or null skip")
        result[case_id] = query
    return result


def replay(*, source: str, strategy: str, top_k: int = 5, candidate_k: int = 10,
           trace: Path | None = None, case_ids: set[str] | None = None,
           case_set: str = "focused") -> dict[str, Any]:
    if top_k <= 0 or candidate_k < top_k:
        raise ValueError("candidate_k must be >= positive top_k")
    cases = load_cases(case_set)
    queries = _queries(source, cases, trace)
    adapter = _adapter(strategy, candidate_k)
    rows = []
    for case in cases:
        case_id = case["case_id"]
        if case_ids is not None and case_id not in case_ids:
            continue
        query = queries.get(case_id)
        if case["retrieval_decision"] == "skip" or query is None:
            rows.append({"case_id": case_id, "status": "expected_skip" if case["retrieval_decision"] == "skip"
                         else "query_unavailable", "query_available": query is not None})
            continue
        started = time.perf_counter()
        candidates = adapter.search(case["work_id"], query, max_order=case["max_order"], top_k=candidate_k)
        latency = round((time.perf_counter() - started) * 1000, 2)
        hits = candidates[:top_k]
        ids = [str(hit["unit_id"]) for hit in hits]
        candidate_ids = [str(hit["unit_id"]) for hit in candidates]
        gold = set(case["required_units"])
        diagnostics = dict(getattr(adapter, "last_search_diagnostics", None) or {})
        if strategy == "vector" and diagnostics.get("used_retrieval") != "vector":
            raise RuntimeError("Vector unavailable: " + case_id)
        if strategy == "fts" and diagnostics.get("used_retrieval") not in ("fts", "scan"):
            raise RuntimeError("Sparse path unavailable: " + case_id)
        safe = all(hit.get("work_id") == case["work_id"] and
                   type(hit.get("order")) is int and 0 < hit["order"] <= case["max_order"]
                   for hit in candidates)
        first = next((rank for rank, uid in enumerate(ids, 1) if uid in gold), None)
        rows.append({"case_id": case_id, "status": "searched", "max_order": case["max_order"],
                     "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
                     "required_units": sorted(gold), "result_units": ids,
                     "candidate_units": candidate_ids, "candidate_count": len(candidates),
                     "candidate_hit": bool(gold.intersection(candidate_ids)) if gold else None,
                     "candidate_recall": round(len(gold.intersection(candidate_ids)) / len(gold), 3) if gold else None,
                     "candidate_joint": gold.issubset(candidate_ids) if gold else None,
                     "hit_at_3": bool(gold.intersection(ids[:3])) if gold else None,
                     "recall_at_3": round(len(gold.intersection(ids[:3])) / len(gold), 3) if gold else None,
                     "joint_at_3": gold.issubset(ids[:3]) if gold else None,
                     "hit_at_5": bool(gold.intersection(ids[:5])) if gold else None,
                     "recall_at_5": round(len(gold.intersection(ids[:5])) / len(gold), 3) if gold else None,
                     "joint_at_5": gold.issubset(ids[:5]) if gold else None,
                     "mrr": round(1 / first, 3) if first else (0.0 if gold else None),
                     "non_gold_at_5": sum(uid not in gold for uid in ids[:5]) if gold else None,
                     "boundary_ok": safe, "latency_ms": latency,
                     "used_retrieval": diagnostics.get("used_retrieval"),
                     "source_paths": {name: d.get("used_retrieval") for name, d in
                                      diagnostics.get("source_diagnostics", {}).items()},
                     "fallback_reason": diagnostics.get("fallback_reason")})
    scored = [r for r in rows if r.get("status") == "searched" and r["hit_at_3"] is not None]
    searched = [r for r in rows if r.get("status") == "searched"]
    latency = [r["latency_ms"] for r in searched]
    def avg(field: str) -> float | None:
        return round(statistics.fmean(r[field] for r in scored), 3) if scored else None
    metrics = {"cases": len(rows), "searched": len(searched), "scored": len(scored),
               "candidate_hit": avg("candidate_hit"),
               "candidate_recall": avg("candidate_recall"),
               "candidate_joint": avg("candidate_joint"),
               "hit_at_3": avg("hit_at_3"), "recall_at_3": avg("recall_at_3"),
               "joint_at_3": avg("joint_at_3"), "hit_at_5": avg("hit_at_5"),
               "recall_at_5": avg("recall_at_5"), "joint_at_5": avg("joint_at_5"),
               "mrr": avg("mrr"), "boundary_violations": sum(not r["boundary_ok"] for r in searched),
               "scan_fallback_cases": [r["case_id"] for r in searched if
                                       r["used_retrieval"] == "scan" or
                                       "scan" in r["source_paths"].values()],
               "p50_ms": _percentile(latency, .5), "p95_ms": _percentile(latency, .95)}
    source_file = DATA / "wandering_earth" / "03_extracted" / "units_extracted.jsonl"
    source_sha256 = hashlib.sha256(source_file.read_bytes()).hexdigest() if source_file.exists() else None
    vector_meta = DATA / "wandering_earth" / "05_index" / "vectors.lance" / "_meta.json"
    index_meta = json.loads(vector_meta.read_text(encoding="utf-8")) if vector_meta.exists() else {}
    return {"schema": "retrieval-replay@2", "case_set": case_set,
            "query_source": source, "strategy": strategy,
            "top_k": top_k, "candidate_k": candidate_k, "source_sha256": source_sha256,
            "vector_index_model": index_meta.get("model"),
            "vector_index_source_sha256": index_meta.get("source_sha256"),
            "metrics": metrics, "cases": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("--input", type=Path, required=True)
    cap.add_argument("--output", type=Path, required=True)
    cap.add_argument("--case-set", choices=("focused", "goldens29"), default="focused")
    run = sub.add_parser("replay")
    run.add_argument("--query-source", choices=("raw_user", "gold_rewrite", "agent_query"), required=True)
    run.add_argument("--strategy", choices=("fts", "fts_strict", "jieba_or", "jieba_and",
                                            "jieba_phrase", "vector", "rrf"), required=True)
    run.add_argument("--trace", type=Path)
    run.add_argument("--top-k", type=int, default=5)
    run.add_argument("--candidate-k", type=int, default=10)
    run.add_argument("--case-id", action="append")
    run.add_argument("--case-set", choices=("focused", "goldens29"), default="focused")
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "capture":
        if not args.output.resolve().is_relative_to(RUNTIME.resolve()):
            parser.error("Captured queries must remain under .runtime/retrieval-experiments/")
        payload = capture_trace(read_jsonl(args.input), load_cases(args.case_set))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in payload), encoding="utf-8")
        print(json.dumps({"captured": len(payload), "output": str(args.output)}, ensure_ascii=False))
    else:
        payload = replay(source=args.query_source, strategy=args.strategy, top_k=args.top_k,
                         candidate_k=args.candidate_k, trace=args.trace,
                         case_ids=set(args.case_id) if args.case_id else None,
                         case_set=args.case_set)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload["metrics"], ensure_ascii=False))


if __name__ == "__main__":
    main()
