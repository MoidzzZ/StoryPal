"""Offline four-configuration replay from fixed jieba OR and Dense Top10 reports.

The two RRF weights are fixed in code. No parameter search, model inference,
story text export, or production index mutation occurs here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from .replay import DATA, PIPELINE, ROOT, RUNTIME, _percentile

CHATBOT_SRC = ROOT / "chatbot" / "src"
SOURCE = DATA / "wandering_earth" / "03_extracted" / "units_extracted.jsonl"
RRF_K = 60
CONFIGS = ("jieba_or", "dense", "rrf_equal", "rrf_dense2_sparse1")


def _source_units() -> tuple[str, dict[str, tuple[str, int]]]:
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    units = {}
    for line in SOURCE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            units[str(row["unit_id"])] = (str(row["work_id"]), int(row["order"]))
    return digest, units


def _cases(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cases = {row["case_id"]: row for row in report["cases"]}
    if len(cases) != 29 or len(report["cases"]) != 29:
        raise ValueError("Expected 29 unique read-only golden cases")
    return cases


def validate_inputs(dense: dict[str, Any], sparse: dict[str, Any],
                    *, source: str, digest: str, units: dict[str, tuple[str, int]]) -> tuple[dict, dict]:
    for name, report in (("vector", dense), ("jieba_or", sparse)):
        if (report.get("schema") != "retrieval-replay@2"
                or report.get("case_set") != "goldens29"
                or report.get("strategy") != name
                or report.get("query_source") != source
                or report.get("source_sha256") != digest
                or report.get("candidate_k") != 10
                or report.get("top_k") != 5):
            raise ValueError(f"Source report is not the fixed {name} Top10 replay")
    dcases, scases = _cases(dense), _cases(sparse)
    if dcases.keys() != scases.keys():
        raise ValueError("Dense and sparse case IDs differ")
    for case_id in dcases:
        d, s = dcases[case_id], scases[case_id]
        if any(d.get(key) != s.get(key) for key in
               ("max_order", "query_sha256", "required_units", "status")):
            raise ValueError("Case query, boundary or gold differs: " + case_id)
        if d.get("status") != "searched" or not d.get("boundary_ok") or not s.get("boundary_ok"):
            raise ValueError("Source path missing or unsafe: " + case_id)
        for row in (d, s):
            ids = row.get("candidate_units")
            if not isinstance(ids, list) or len(ids) > 10 or len(ids) != len(set(ids)):
                raise ValueError("Invalid candidate budget or duplicate: " + case_id)
            if any(units.get(uid, (None, 10**9))[0] != "wandering_earth"
                   or units[uid][1] > d["max_order"] for uid in ids):
                raise ValueError("Candidate crosses story/read boundary: " + case_id)
    return dcases, scases


def rank_candidates(dense_ids: list[str], sparse_ids: list[str],
                    config: str) -> list[dict[str, Any]]:
    if config not in CONFIGS:
        raise ValueError(config)
    dr = {uid: rank for rank, uid in enumerate(dense_ids, 1)}
    sr = {uid: rank for rank, uid in enumerate(sparse_ids, 1)}
    if config == "dense":
        return [{"unit_id": uid, "source_ranks": {"dense": rank}}
                for rank, uid in enumerate(dense_ids, 1)]
    if config == "jieba_or":
        return [{"unit_id": uid, "source_ranks": {"jieba_or": rank}}
                for rank, uid in enumerate(sparse_ids, 1)]
    dense_weight = 2 if config == "rrf_dense2_sparse1" else 1
    items = []
    for uid in dr.keys() | sr.keys():
        score = dense_weight / (RRF_K + dr[uid]) if uid in dr else 0.0
        score += 1 / (RRF_K + sr[uid]) if uid in sr else 0.0
        ranks = {name: mapping[uid] for name, mapping in
                 (("dense", dr), ("jieba_or", sr)) if uid in mapping}
        items.append({"unit_id": uid, "source_ranks": ranks, "rrf_score": score})
    items.sort(key=lambda item: (-item["rrf_score"], min(item["source_ranks"].values()),
                                 item["unit_id"]))
    for item in items[:10]:
        item["rrf_score"] = round(item["rrf_score"], 9)
    return items[:10]


def replay(dense: dict[str, Any], sparse: dict[str, Any], *, source: str) -> dict[str, Any]:
    digest, units = _source_units()
    dcases, scases = validate_inputs(dense, sparse, source=source, digest=digest, units=units)
    if str(PIPELINE) not in sys.path:
        sys.path.insert(0, str(PIPELINE))
    if str(CHATBOT_SRC) not in sys.path:
        sys.path.insert(0, str(CHATBOT_SRC))
    from storymemory.adapter import StoryMemory
    from storypal_chatbot.context_packer import ContextPacker
    memory = StoryMemory(DATA, retrieval="fts")
    packer = ContextPacker()
    evidence_cache: dict[str, dict[str, Any]] = {}
    output: dict[str, Any] = {
        "schema": "fixed-fusion-replay@1", "query_source": source,
        "source_sha256": digest, "source_case_set": "goldens29",
        "candidate_per_source": 10, "fused_candidate_limit": 10,
        "evidence_limit": 5, "rrf_k": RRF_K,
        "configurations": {},
    }
    for config in CONFIGS:
        rows = []
        for case_id, d in dcases.items():
            s = scases[case_id]
            started = time.perf_counter()
            ranked = rank_candidates(d["candidate_units"], s["candidate_units"], config)
            ranking_ms = round((time.perf_counter() - started) * 1000, 3)
            top5 = [item["unit_id"] for item in ranked[:5]]
            gold = set(d["required_units"])
            started_pack = time.perf_counter()
            for uid in top5:
                if uid not in evidence_cache:
                    evidence = memory.get_unit("wandering_earth", uid)
                    if evidence is None:
                        raise ValueError("Candidate has no source evidence: " + uid)
                    evidence_cache[uid] = evidence
            packed = packer.pack([evidence_cache[uid] for uid in top5],
                                 work_id="wandering_earth", max_seen_order=d["max_order"])
            packing_ms = round((time.perf_counter() - started_pack) * 1000, 3)
            anchor_ids = [x["unit_id"] for x in packed.anchors]
            adjacent_ids = [x["unit_id"] for x in packed.adjacent_context]
            packed_ids = anchor_ids + adjacent_ids
            first = next((rank for rank, uid in enumerate(top5, 1) if uid in gold), None)
            source_union = set(d["candidate_units"]) | set(s["candidate_units"])
            rows.append({
                "case_id": case_id, "max_order": d["max_order"],
                "required_units": sorted(gold), "source_union_count": len(source_union),
                "source_union_joint": gold.issubset(source_union) if gold else None,
                "ranking": ranked, "result_units": top5,
                "candidate_joint": gold.issubset(x["unit_id"] for x in ranked) if gold else None,
                "hit_at_3": bool(gold.intersection(top5[:3])) if gold else None,
                "joint_at_3": gold.issubset(top5[:3]) if gold else None,
                "hit_at_5": bool(gold.intersection(top5)) if gold else None,
                "joint_at_5": gold.issubset(top5) if gold else None,
                "first_gold_rank": first, "mrr": round(1 / first, 3) if first else (0.0 if gold else None),
                "anchor_units": anchor_ids, "adjacent_units": adjacent_ids,
                "packed_joint": gold.issubset(packed_ids) if gold else None,
                "anchor_joint": gold.issubset(anchor_ids) if gold else None,
                "pack_loss": bool(gold and gold.issubset(top5) and not gold.issubset(packed_ids)),
                "packer_drops": packed.dropped, "estimated_tokens": packed.token_estimate,
                "ranking_ms": ranking_ms, "packing_ms": packing_ms,
                "source_latency_ms": {"dense": d["latency_ms"], "jieba_or": s["latency_ms"]},
                "boundary_ok": all(units[uid][1] <= d["max_order"]
                                   for uid in [x["unit_id"] for x in ranked] + packed_ids),
            })
        scored = [row for row in rows if row["required_units"]]
        singles = [row for row in scored if len(row["required_units"]) == 1]
        def count(field: str) -> int:
            return sum(row[field] is True for row in scored)
        metrics = {
            "cases": len(rows), "scored": len(scored), "multi_unit_cases": len(scored) - len(singles),
            "source_union_joint": count("source_union_joint"),
            "candidate_joint": count("candidate_joint"),
            "hit_at_3": count("hit_at_3"), "joint_at_3": count("joint_at_3"),
            "hit_at_5": count("hit_at_5"), "joint_at_5": count("joint_at_5"),
            "anchor_joint": count("anchor_joint"), "packed_joint": count("packed_joint"),
            "pack_loss_cases": [row["case_id"] for row in scored if row["pack_loss"]],
            "single_hit_at_1": sum(row["first_gold_rank"] == 1 for row in singles),
            "single_mrr": round(statistics.fmean(row["mrr"] for row in singles), 3),
            "all_mrr": round(statistics.fmean(row["mrr"] for row in scored), 3),
            "boundary_violations": sum(not row["boundary_ok"] for row in rows),
            "drop_reasons": dict(Counter(drop["reason"] for row in rows for drop in row["packer_drops"])),
            "ranking_p50_ms": _percentile([row["ranking_ms"] for row in rows], .5),
            "packing_p50_ms": _percentile([row["packing_ms"] for row in rows], .5),
        }
        output["configurations"][config] = {"metrics": metrics, "cases": rows}
    output["latency_note"] = (
        "Ranking/packing timings are local replay overhead only; cached source latencies "
        "came from separate processes and are not measured end-to-end fusion latency."
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query-source", choices=("raw_user", "gold_rewrite"), required=True)
    parser.add_argument("--dense-report", type=Path, required=True)
    parser.add_argument("--sparse-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(RUNTIME.resolve()):
        parser.error("Fusion replay output must stay under .runtime/retrieval-experiments/")
    dense = json.loads(args.dense_report.read_text(encoding="utf-8"))
    sparse = json.loads(args.sparse_report.read_text(encoding="utf-8"))
    result = replay(dense, sparse, source=args.query_source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: value["metrics"] for name, value in result["configurations"].items()},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
