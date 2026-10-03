"""CPU-only query-frame/packing exploration over frozen retrieval caches.

No adapter, provider, embedding, GPU, network or index mutation is used.
Labels are read only by evaluation, never by query/ranking/packing functions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys
import time
from typing import Callable

from .facet_replay import split_query
from .fusion_replay import CHATBOT_SRC, SOURCE
from .replay import GOLDENS, ROOT, RUNTIME, load_cases
from .sparse import _jieba, _tokens

RANKERS = ("cached_dense", "clause_terms", "frame_terms", "guard_context_terms")
PACKERS = ("production", "top4", "coverage4")
VERSION = "cached-frame-pack-v1.1"
STOP = set("我 你 他 她 它 我们 你们 的 了 呢 吗 呀 啊 是 在 有 和 与 又 就 都 这 那 那个 这个 "
           "这里 到底 大概 为什么 为何 怎么 怎样 什么 是否 是不是 记错 看懂 好像 所以".split())
META_QUESTION = re.compile(r"^(?:我)?(?:是不是|是否)?(?:记错了?|记得不对了?|弄错了?)(?:吗)?$")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def query_sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def terms(value: str, tokenizer) -> set[str]:
    return set(_tokens(value, tokenizer)) - STOP


def frame(query: str, context: str, mode: str, tokenize: Callable[[str], set[str]]) -> dict:
    if mode not in RANKERS:
        raise ValueError("Unknown query processing")
    clauses = split_query(query)
    if mode == "guard_context_terms" and len(clauses) == 2:
        clauses = [clause for clause in clauses if not META_QUESTION.fullmatch(clause)]
    active = mode != "cached_dense" and (len(clauses) == 2 or
                                        (mode == "guard_context_terms" and bool(context)))
    # Full original relations/subjects/stages remain visible, no literary facts added.
    full = query + (" " + context if mode == "guard_context_terms" else "")
    return {"active": active, "clause_terms": [tokenize(clause) for clause in clauses],
            "frame_terms": tokenize(full), "clause_count": len(clauses),
            "context_used": mode == "guard_context_terms" and bool(context)}


def weights(documents: dict[str, set[str]], vocabulary: set[str]) -> dict[str, float]:
    return {term: 1 + math.log((len(documents) + 1) /
                              (1 + sum(term in doc for doc in documents.values())))
            for term in vocabulary}


def coverage(query_terms: set[str], doc: set[str], idf: dict[str, float]) -> float:
    total = sum(idf[term] for term in query_terms)
    return sum(idf[term] for term in query_terms & doc) / total if total else 0.0


def rank(ids: list[str], documents: dict[str, set[str]], representation: dict, mode: str) -> list[str]:
    if not representation["active"]:
        return list(ids)
    clauses, full = representation["clause_terms"], representation["frame_terms"]
    idf = weights(documents, full | set().union(*clauses))

    def score(uid: str) -> float:
        local = statistics.fmean(coverage(clause, documents[uid], idf) for clause in clauses)
        return local if mode == "clause_terms" else .75 * local + .25 * coverage(full, documents[uid], idf)

    # Tie by cached rank, not source chronology or gold IDs.
    return sorted(ids, key=lambda uid: (-score(uid), ids.index(uid)))


def select_coverage4(ids: list[str], evidence: dict[str, dict], documents: dict[str, set[str]],
                     query_terms: set[str], estimate: Callable[[dict], int], budget: int = 2400) -> list[str]:
    if len(ids) > 5 or len(ids) != len(set(ids)):
        raise ValueError("Packing must use the same distinct Top5")
    idf = weights({uid: documents[uid] for uid in ids}, query_terms)
    selected, covered, used = [], set(), 0
    remaining = list(ids)
    while remaining and len(selected) < 4:
        fitting = [uid for uid in remaining if used + estimate(evidence[uid]) <= budget]
        if not fitting:
            break
        if not selected and ids[0] in fitting:
            chosen = ids[0]
        else:
            chosen = min(fitting, key=lambda uid: (
                -sum(idf[term] for term in (documents[uid] & query_terms) - covered), ids.index(uid)))
        selected.append(chosen)
        used += estimate(evidence[chosen])
        covered |= documents[chosen] & query_terms
        remaining.remove(chosen)
    return selected


def source_evidence() -> dict[str, dict]:
    evidence = {}
    for line in SOURCE.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        refs = []
        for value in row.get("context_refs", []):
            name = value.get("entity") if isinstance(value, dict) else value
            if isinstance(name, str) and name.strip() and name.strip() not in refs:
                refs.append(name.strip())
        metadata = {"chapter": row.get("chapter_name", ""),
                    **{key: row.get(key) for key in
                       ("chapter_idx", "start_line", "end_line", "characters", "locations", "key_terms")}}
        if refs:
            metadata["context_refs"] = refs
        evidence[row["unit_id"]] = {"unit_id": row["unit_id"], "work_id": row["work_id"],
                                     "order": row["order"], "summary": row.get("summary", ""),
                                     "raw_text": row.get("text", ""), "score": 0.0, "metadata": metadata}
    return evidence


def validate_cache(report: dict, expected: list[dict], evidence: dict[str, dict], digest: str) -> None:
    if report.get("source_sha256") != digest or len(report["cases"]) != len(expected):
        raise ValueError("Cache source/case set differs")
    rows = {row["case_id"]: row for row in report["cases"]}
    if len(rows) != len(expected) or rows.keys() != {case["case_id"] for case in expected}:
        raise ValueError("Cache duplicate/missing cases")
    for case in expected:
        row = rows[case["case_id"]]
        if (row["max_order"] != case["max_order"] or row["query_sha256"] != query_sha(case["query"])
                or set(row["required_units"]) != set(case["required_units"])):
            raise ValueError("Cache query, boundary or evaluation labels differ")
        ids = row["candidate_units"]
        if len(ids) > 10 or len(ids) != len(set(ids)):
            raise ValueError("Cache violates distinct Top10")
        if any(uid not in evidence or evidence[uid]["work_id"] != "wandering_earth"
               or type(evidence[uid]["order"]) is not int
               or not 0 < evidence[uid]["order"] <= case["max_order"] for uid in ids):
            raise ValueError("Cache evidence crosses source/read boundary")


def inputs(batch: Path) -> list[tuple[str, list[dict], dict]]:
    gold = json.loads(GOLDENS.read_text(encoding="utf-8"))
    contexts = {row["编号"]: row.get("对话上下文", "") for row in gold}
    output = []
    for label, field, filename in (("raw_user", "raw_user", "29-raw-vector.json"),
                                   ("human_gold_rewrite", "gold_rewrite", "29-gold-vector.json")):
        cases = [{**case, "query": case[field], "context": contexts[case["case_id"]],
                  "gold_status": "existing_gold"} for case in load_cases("goldens29")]
        report = json.loads((RUNTIME / filename).read_text(encoding="utf-8"))
        if (report.get("schema") != "retrieval-replay@2" or report.get("strategy") != "vector"
                or report.get("candidate_k") != 10 or report.get("top_k") != 5
                or report.get("query_source") != ("gold_rewrite" if label == "human_gold_rewrite" else label)):
            raise ValueError("Not a frozen Dense Top10 cache")
        output.append((label, cases, report))
    audit = json.loads((batch / "batch-audit.json").read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (batch / "agent-queries.jsonl").read_text(encoding="utf-8").splitlines()]
    searches = {row["case_id"]: row for row in events if row["decision"] == "search"}
    if len(searches) != 5 or len(events) != 6 or not any(
            row["case_id"] == "N01" and row["decision"] == "skip" for row in events):
        raise ValueError("Actual batch decisions changed")
    cases = [{**row, "query": searches[row["case_id"]]["query"], "context": ""}
             for row in audit["cases"] if row["decision"] == "search"]
    output.append(("agent_query", cases, {**audit, "cases": cases}))
    return output


def metrics(rows: list[dict]) -> dict:
    scored = [row for row in rows if row["required_units"] and row["gold_status"] == "existing_gold"]
    return {"cases": len(rows), "scored": len(scored),
            "provisional_cases": [row["case_id"] for row in rows if row["gold_status"] == "provisional"],
            **{field: sum(row[field] is True for row in scored) for field in
               ("candidate_joint", "joint_at_3", "joint_at_5", "packed_joint")},
            "mrr": round(statistics.fmean(row["mrr"] for row in scored), 3),
            "max_pack_units": max(len(row["packed_units"]) for row in rows),
            "max_estimated_tokens": max(row["estimated_tokens"] for row in rows),
            "boundary_violations": sum(not row["boundary_ok"] for row in rows),
            "active_queries": [row["case_id"] for row in rows if row["query_processing_active"]],
            "local_p50_ms": round(statistics.median(row["local_ms"] for row in rows), 3)}


def replay(batch: Path) -> dict:
    if not batch.resolve().is_relative_to((RUNTIME / "isolated").resolve()):
        raise ValueError("Only a selected isolated batch is allowed")
    if str(CHATBOT_SRC) not in sys.path:
        sys.path.insert(0, str(CHATBOT_SRC))
    from storypal_chatbot.context_packer import ContextPacker
    default = ContextPacker()
    four = ContextPacker(primary_limit=4, adjacent_limit=0)
    digest, evidence = sha(SOURCE), source_evidence()
    tokenizer = _jieba()
    tokenizer.initialize()
    tokenize = lambda text: terms(text, tokenizer)
    token_cache = {}
    result = {"schema": "cached-context-pack@1", "rule_version": VERSION, "device": "cpu",
              "source_sha256": digest, "new_model_requests": 0, "embedding_calls": 0,
              "candidate_limit": 10, "pack_input_limit": 5, "pack_unit_limit": 4,
              "estimated_token_budget": 2400, "datasets": {}}
    previous = json.loads((RUNTIME / "29-raw-clauses-v1.json").read_text(encoding="utf-8"))
    frozen_pack = {row["case_id"]: row for row in previous["configurations"]["dense_single"]["cases"]}
    for label, cases, report in inputs(batch):
        validate_cache(report, cases, evidence, digest)
        rows_by_id = {row["case_id"]: row for row in report["cases"]}
        groups = {ranking + "/" + packing: [] for ranking in RANKERS for packing in PACKERS}
        for case in cases:
            ids = rows_by_id[case["case_id"]]["candidate_units"]
            for uid in ids:
                if uid not in token_cache:
                    token_cache[uid] = tokenize(evidence[uid]["summary"] + " " + evidence[uid]["raw_text"])
            docs = {uid: token_cache[uid] for uid in ids}
            # Packing question remains fixed across packers, including explicit context if provided.
            packing_terms = tokenize(case["query"] + " " + case["context"])
            for ranking in RANKERS:
                representation = frame(case["query"], case["context"], ranking, tokenize)
                started = time.perf_counter()
                ranked = rank(ids, docs, representation, ranking)
                rank_ms = (time.perf_counter() - started) * 1000
                top5 = ranked[:5]
                for packing in PACKERS:
                    started = time.perf_counter()
                    chosen = (select_coverage4(top5, evidence, docs, packing_terms, default._estimate_tokens)
                              if packing == "coverage4" else top5)
                    pack = (default if packing == "production" else four).pack(
                        [evidence[uid] for uid in chosen], work_id="wandering_earth", max_seen_order=case["max_order"])
                    packed = [row["unit_id"] for row in pack.anchors + pack.adjacent_context]
                    if len(packed) > 4 or pack.token_estimate > 2400 or set(ranked) != set(ids):
                        raise ValueError("Ablation changed frozen candidate or packing budget")
                    if label == "raw_user" and ranking == "cached_dense" and packing == "production":
                        prior = frozen_pack[case["case_id"]]
                        if (packed != prior["anchor_units"] + prior["adjacent_units"]
                                or pack.token_estimate != prior["estimated_tokens"]):
                            raise ValueError("Source normalization differs from prior production packing")
                    if label == "agent_query" and ranking == "cached_dense" and packing == "production":
                        if set(packed) != set(case["original_evidence_units"]):
                            raise ValueError("Actual query default differs from actual tool evidence")
                    gold = set(case["required_units"])
                    first = next((n for n, uid in enumerate(top5, 1) if uid in gold), None)
                    groups[ranking + "/" + packing].append({
                        "case_id": case["case_id"], "max_order": case["max_order"],
                        "query_sha256": query_sha(case["query"]), "gold_status": case["gold_status"],
                        "required_units": sorted(gold), "candidate_units": ranked, "result_units": top5,
                        "packed_units": packed, "anchor_units": [row["unit_id"] for row in pack.anchors],
                        "adjacent_units": [row["unit_id"] for row in pack.adjacent_context],
                        "estimated_tokens": pack.token_estimate, "packer_drops": pack.dropped,
                        "candidate_joint": gold.issubset(ranked) if gold else None,
                        "joint_at_3": gold.issubset(top5[:3]) if gold else None,
                        "joint_at_5": gold.issubset(top5) if gold else None,
                        "packed_joint": gold.issubset(packed) if gold else None,
                        "mrr": 1 / first if first else (0 if gold else None),
                        "query_processing_active": representation["active"],
                        "clause_count": representation["clause_count"],
                        "context_used": representation["context_used"],
                        "frame_terms": sorted(representation["frame_terms"]),
                        "clause_terms": [sorted(value) for value in representation["clause_terms"]],
                        "boundary_ok": all(0 < evidence[uid]["order"] <= case["max_order"] for uid in ranked + packed),
                        "local_ms": round(rank_ms + (time.perf_counter() - started) * 1000, 3)})
        baseline = {row["case_id"]: row for row in groups["cached_dense/production"]}
        configs = {}
        for name, rows in groups.items():
            scored = [row for row in rows if row["required_units"] and row["gold_status"] == "existing_gold"]
            summary = metrics(rows)
            summary["packed_gains"] = [row["case_id"] for row in scored if row["packed_joint"]
                                        and not baseline[row["case_id"]]["packed_joint"]]
            summary["packed_losses"] = [row["case_id"] for row in scored if not row["packed_joint"]
                                         and baseline[row["case_id"]]["packed_joint"]]
            configs[name] = {"metrics": summary, "cases": rows}
        result["datasets"][label] = {"configurations": configs}
    result["decision_note"] = "Five actual first queries only; N01 preserved as genuine skip, not searched. P01 remains provisional."
    result["limits"] = "Candidate-internal lexical exploration, not new Dense retrieval or a neural reranker. Cached query sources/candidate pools differ. Timings exclude original retrieval, token initialization and answer generation."
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(RUNTIME.resolve()) or output.exists():
        parser.error("Output must be a new isolated runtime file")
    ledger = args.batch_root / "requests.jsonl"
    before = sha(ledger)
    result = replay(args.batch_root)
    if before != sha(ledger) or any(name in sys.modules for name in ("torch", "sentence_transformers", "openai")):
        raise RuntimeError("Unexpected model/GPU library or request ledger change")
    result["unchanged_model_ledger_sha256"] = before
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({dataset: {name: group["metrics"] for name, group in value["configurations"].items()}
                      for dataset, value in result["datasets"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
