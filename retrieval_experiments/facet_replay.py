"""Local BGE query-clause and evidence-reservation ablation; no dialogue calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from .fusion_replay import CHATBOT_SRC, _source_units
from .replay import RUNTIME, _adapter, _percentile, load_cases

CONFIGS = ("dense_single", "clause_rrf", "clause_heads")
RULE_VERSION = "punctuation-question-v1"
QUESTION = re.compile(r"为什么|为何|怎么|怎样|什么|是否|是不是|吗")


def split_query(query: str) -> list[str]:
    """At most two explicit questions, preserving non-question prefix/suffix.

    No case IDs, literary labels, source units or gold evidence are consulted.
    This deliberately does not resolve omitted subjects or references.
    """
    parts = [part.strip() for part in re.split(r"[，,。！？!?；;]+", query) if part.strip()]
    questions: list[str] = []
    pending: list[str] = []
    for part in parts:
        if QUESTION.search(part):
            questions.append("，".join(pending + [part]))
            pending = []
        else:
            pending.append(part)
    if pending and questions:
        questions[-1] += "，" + "，".join(pending)
    return questions if len(questions) == 2 else [query]


def rank_clauses(routes: list[list[str]], *, reserve_heads: bool) -> list[str]:
    if not 1 <= len(routes) <= 2:
        raise ValueError("Expected one or two clause routes")
    limit = 10 if len(routes) == 1 else 5
    if any(len(route) > limit or len(set(route)) != len(route) for route in routes):
        raise ValueError("Route exceeds total ten result slots or duplicates")
    if len(routes) == 1:
        return list(routes[0])
    ranks = [{uid: rank for rank, uid in enumerate(route, 1)} for route in routes]
    union = set().union(*routes)
    ranked = sorted(union, key=lambda uid: (
        -sum(1 / (60 + route[uid]) for route in ranks if uid in route),
        min(route[uid] for route in ranks if uid in route), uid))
    heads = list(dict.fromkeys(route[0] for route in routes if route)) if reserve_heads else []
    return heads + [uid for uid in ranked if uid not in heads]


def _safe(items: list[dict[str, Any]], max_order: int) -> None:
    if any(item.get("work_id") != "wandering_earth" or type(item.get("order")) is not int
           or not 0 < item["order"] <= max_order for item in items):
        raise ValueError("Candidate crosses story/read boundary")


def replay(cases: list[dict[str, Any]] | None = None, *, query_source: str = "algorithmic_raw_user",
           case_set: str = "goldens29") -> dict[str, Any]:
    cases = load_cases("goldens29") if cases is None else cases
    digest, units = _source_units()
    adapter = _adapter("vector", 10)
    if str(CHATBOT_SRC) not in sys.path:
        sys.path.insert(0, str(CHATBOT_SRC))
    from storypal_chatbot.context_packer import ContextPacker
    packer = ContextPacker()
    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in CONFIGS}
    for case in cases:
        query = case["raw_user"]
        clauses = split_query(query)
        started = time.perf_counter()
        original = adapter.search("wandering_earth", query, max_order=case["max_order"], top_k=10)
        baseline_ms = round((time.perf_counter() - started) * 1000, 2)
        if adapter.last_search_diagnostics.get("used_retrieval") != "vector":
            raise RuntimeError("Local vector route unavailable")
        _safe(original, case["max_order"])
        clause_ms = baseline_ms
        route_hits = [original]
        if len(clauses) == 2:
            started = time.perf_counter()
            route_hits = []
            for clause in clauses:
                found = adapter.search("wandering_earth", clause, max_order=case["max_order"], top_k=5)
                if adapter.last_search_diagnostics.get("used_retrieval") != "vector":
                    raise RuntimeError("Local clause vector route unavailable")
                _safe(found, case["max_order"])
                route_hits.append(found)
            clause_ms = round((time.perf_counter() - started) * 1000, 2)
        routes = [[item["unit_id"] for item in route] for route in route_hits]
        evidence = {item["unit_id"]: item for route in [original] + route_hits for item in route}
        gold = set(case["required_units"])
        for config in CONFIGS:
            started = time.perf_counter()
            ids = ([item["unit_id"] for item in original] if config == "dense_single" else
                   rank_clauses(routes, reserve_heads=config == "clause_heads"))
            ranking_ms = round((time.perf_counter() - started) * 1000, 3)
            top5 = ids[:5]
            started = time.perf_counter()
            packed = packer.pack([evidence[uid] for uid in top5], work_id="wandering_earth",
                                 max_seen_order=case["max_order"])
            packing_ms = round((time.perf_counter() - started) * 1000, 3)
            anchors = [item["unit_id"] for item in packed.anchors]
            adjacent = [item["unit_id"] for item in packed.adjacent_context]
            packed_ids = anchors + adjacent
            if any(units[uid][0] != "wandering_earth" or not 0 < units[uid][1] <= case["max_order"]
                   for uid in ids + packed_ids):
                raise ValueError("Source metadata crosses boundary")
            first = next((rank for rank, uid in enumerate(top5, 1) if uid in gold), None)
            grouped[config].append({
                "case_id": case["case_id"], "max_order": case["max_order"],
                "gold_status": case.get("gold_status", "existing_gold"),
                "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
                "clause_sha256": [hashlib.sha256(c.encode()).hexdigest() for c in clauses],
                "split": len(clauses) == 2, "required_units": sorted(gold),
                "candidate_units": ids, "route_units": routes if config != "dense_single" else [ids],
                "result_units": top5, "anchor_units": anchors, "adjacent_units": adjacent,
                "candidate_joint": gold.issubset(ids) if gold else None,
                "joint_at_3": gold.issubset(top5[:3]) if gold else None,
                "joint_at_5": gold.issubset(top5) if gold else None,
                "packed_joint": gold.issubset(packed_ids) if gold else None,
                "first_gold_rank": first, "mrr": round(1 / first, 3) if first else (0 if gold else None),
                "packer_drops": packed.dropped, "estimated_tokens": packed.token_estimate,
                "boundary_ok": True, "retrieval_ms": baseline_ms if config == "dense_single" else clause_ms,
                "ranking_ms": ranking_ms, "packing_ms": packing_ms,
            })
    configurations = {}
    for name, rows in grouped.items():
        scored = [row for row in rows if row["required_units"] and row["gold_status"] != "provisional"]
        singles = [row for row in scored if len(row["required_units"]) == 1]
        times = [row["retrieval_ms"] for row in rows]
        configurations[name] = {"cases": rows, "metrics": {
            "cases": len(rows), "scored": len(scored),
            "provisional_cases": [row["case_id"] for row in rows if row["gold_status"] == "provisional"],
            "split_cases": [row["case_id"] for row in rows if row["split"]],
            **{field: sum(row[field] is True for row in scored) for field in
               ("candidate_joint", "joint_at_3", "joint_at_5", "packed_joint")},
            "single_hit_at_1": sum(row["first_gold_rank"] == 1 for row in singles),
            "single_scored": len(singles), "all_mrr": round(statistics.fmean(row["mrr"] for row in scored), 3),
            "boundary_violations": sum(not row["boundary_ok"] for row in rows),
            "first_query_ms": times[0], "warm_p50_ms": _percentile(times[1:], .5),
            "warm_p95_ms": _percentile(times[1:], .95),
            "split_retrieval_p50_ms": _percentile([row["retrieval_ms"] for row in rows if row["split"]], .5),
        }}
    return {"schema": "clause-replay@1", "query_source": query_source,
            "source_sha256": digest, "case_set": case_set, "rule_version": RULE_VERSION,
            "rrf_k": 60, "total_result_slots": 10, "evidence_limit": 5,
            "configurations": configurations,
            "latency_note": "Two clauses use two sequential local embeddings/searches with five slots each. "
                            "The ten-slot limit equalizes returned candidates, not compute or index scan cost. "
                            "Clause RRF and heads share the same retrieval; their times must not be added."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(RUNTIME.resolve()) or output.exists():
        parser.error("Output must be a new file under the isolated runtime")
    result = replay()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: value["metrics"] for name, value in result["configurations"].items()},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
