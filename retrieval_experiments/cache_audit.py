"""Model-free contract validation, cached loss audit and budgeted pack controls."""
from __future__ import annotations
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import time

from . import cpu_routes as cpu
from .cached_context_pack import source_evidence, terms, weights, select_coverage4
from .holdout_contract import canonical, source_rows
from .replay import ROOT, RUNTIME, GOLDENS
from .sparse import _jieba, _tokens, _indexed

CONTRACT = ROOT / "docs/research/retrieval/business_tasks_v2_1.json"
LOCK = CONTRACT.with_suffix(".lock.json")
CACHE = RUNTIME / "cpu-routes-20261004-v1.json"
MODES = ("production", "raw_dedup", "source_checked_dedup", "adjacency_first", "complementary")


def validate_business():
    p = json.loads(CONTRACT.read_text(encoding="utf-8"))
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    rows = source_rows()
    if (canonical(p) != lock["contract_canonical_sha256"] or p["source_sha256"] != cpu.digest(cpu.SOURCE)
            or p["development_goldens_sha256"] != cpu.digest(GOLDENS)):
        raise ValueError("Business freeze/source changed")
    old = json.loads(cpu.CONTRACT.read_text(encoding="utf-8"))
    by_id = {t["task_id"]: t for t in p["tasks"]}
    if len(by_id) != len(p["tasks"]):
        raise ValueError("Duplicate business task")
    for t in old["tasks"]:
        current = by_id[t["task_id"]]
        for field in ("split_group", "max_order", "variants", "necessary_unit_candidates", "evidence_checks", "counter_or_unknown"):
            if current[field] != t[field]:
                raise ValueError("Existing frozen task changed")
    variants, units_groups = set(), {}
    for t in p["tasks"]:
        if lock["task_groups"].get(t["task_id"]) != t["split_group"] or len(t["variants"]) not in (2, 3):
            raise ValueError("Business group/variant count changed")
        for v in t["variants"]:
            if (v["variant_id"] in variants or v["split_group"] != t["split_group"]
                    or hashlib.sha256(v["text"].encode()).hexdigest() != lock["variant_sha256"].get(v["variant_id"])):
                raise ValueError("Variant changed or group leak")
            variants.add(v["variant_id"])
        if not 0 < t["max_order"] <= 108 or not t["counter_or_unknown"]:
            raise ValueError("Missing source boundary/unknown")
        needed = t["necessary_unit_candidates"]
        if t["task_domain"] == "story_retrieval":
            if not needed or set(needed) != {e["unit_id"] for e in t["evidence_checks"]}:
                raise ValueError("Story evidence checks missing")
            for e in t["evidence_checks"]:
                r = rows[e["unit_id"]]
                body = r["text"]
                if (hashlib.sha256(body.encode()).hexdigest() != e["raw_text_sha256"]
                        or hashlib.sha256(body[e["char_start"]:e["char_end"]].encode()).hexdigest() != e["span_sha256"]
                        or not 0 <= e["char_start"] < e["char_end"] <= len(body)
                        or r["order"] != e["order"] or [r["start_line"], r["end_line"]] != e["source_line_range"]):
                    raise ValueError("Story span/source changed")
        elif needed or t["acceptable_evidence_sets"]:
            raise ValueError("Reader memory/decision must not be story gold")
        all_ids = set(needed + t["optional_units"])
        for alternative in t["acceptable_evidence_sets"]:
            if not alternative:
                raise ValueError("Empty evidence alternative")
            all_ids.update(alternative)
        for uid in all_ids:
            if uid not in rows or rows[uid]["order"] > t["max_order"]:
                raise ValueError("Business evidence beyond scope")
            if uid in units_groups and units_groups[uid] != t["split_group"]:
                raise ValueError("Shared source crosses groups")
            units_groups[uid] = t["split_group"]
        fixture = t["reader_memory_fixture"]
        for record in fixture["records"]:
            if record["anchor_order"] > t["max_order"]:
                raise ValueError("Reader fixture beyond scope")
            if record.get("content_sha256") and hashlib.sha256(record["content"].encode()).hexdigest() != record["content_sha256"]:
                raise ValueError("Reader fixture content changed")
        for fid in t.get("expected_fixture_ids", []):
            if not any(r["fixture_id"] == fid and r.get("owner") == t["owner"] for r in fixture["records"]):
                raise ValueError("Reader expected source belongs to wrong owner")
    if set(lock["variant_sha256"]) != variants or set(lock["task_groups"]) != set(by_id):
        raise ValueError("Freeze task set differs")
    return {"tasks": len(by_id), "questions": len(variants),
            "domains": dict(Counter(t["task_domain"] for t in p["tasks"])),
            "event_groups": len({t["split_group"] for t in p["tasks"]}),
            "span_checks": sum(len(t["evidence_checks"]) for t in p["tasks"]),
            "formal_independent_gold": 0}


def business_question_input(task, variant):
    if variant not in task["variants"]:
        raise ValueError("Variant does not belong to task")
    memory = task["reader_memory_fixture"]
    return {"question": variant["text"], "visible_context": task["visible_context"],
            "work_id": task["work_id"], "max_order": task["max_order"], "owner": task.get("owner"),
            "reader_memory_fixture": {"origin": memory["origin"], "available": memory["available"],
                "records": [{key: r[key] for key in ("fixture_id", "anchor_order", "content", "status", "owner", "revision") if key in r}
                            for r in memory["records"]]}}



def raw_key(e):
    return re.sub(r"\s+", "", e["raw_text"])


def prepare(ids, evidence, mode):
    chosen, drops, seen = [], [], set()
    for uid in ids:
        e = evidence[uid]
        if mode == "source_checked_dedup" and not any(c.isalnum() for c in e["raw_text"]):
            drops.append({"unit_id": uid, "reason": "separator_only_source"})
            continue
        if mode in ("raw_dedup", "source_checked_dedup"):
            key = raw_key(e)
            if key in seen:
                drops.append({"unit_id": uid, "reason": "duplicate_original"})
                continue
            seen.add(key)
        chosen.append(uid)
    return chosen, drops


def select(ids, evidence, query, mode, packer, tokenize):
    if mode not in MODES:
        raise ValueError("Unknown pack rule")
    filtered, drops = prepare(ids, evidence, mode)
    if mode in ("production", "raw_dedup", "source_checked_dedup"):
        packed = packer.pack([evidence[uid] for uid in filtered], work_id="wandering_earth",
                             max_seen_order=max((evidence[uid]["order"] for uid in ids), default=1))
        return ([e["unit_id"] for e in packed.anchors + packed.adjacent_context],
                packed.token_estimate, drops + packed.dropped)
    chosen, remaining, covered, used = [], list(filtered), set(), 0
    documents = {uid: tokenize(evidence[uid]["raw_text"]) for uid in filtered}
    query_terms = tokenize(query)
    idf = weights(documents, query_terms)
    while remaining and len(chosen) < 4:
        fitting = [uid for uid in remaining if used + packer._estimate_tokens(evidence[uid]) <= 2400]
        if not fitting:
            drops.extend({"unit_id": uid, "reason": "token_budget"} for uid in remaining)
            break
        if not chosen:
            next_uid = fitting[0]
        elif mode == "adjacency_first":
            adjacent = [uid for uid in fitting if any(
                evidence[uid]["metadata"].get("chapter") == evidence[x]["metadata"].get("chapter")
                and abs(evidence[uid]["order"] - evidence[x]["order"]) == 1 for x in chosen)]
            next_uid = (adjacent or fitting)[0]
        else:
            next_uid = min(fitting, key=lambda uid: (
                -sum(idf[t] for t in (documents[uid] & query_terms) - covered), ids.index(uid)))
        chosen.append(next_uid)
        covered |= documents[next_uid]
        used += packer._estimate_tokens(evidence[next_uid])
        remaining.remove(next_uid)
    drops.extend({"unit_id": uid, "reason": "selection_limit_or_budget"} for uid in remaining)
    return chosen, used, drops


def packing_metrics(rows):
    output = {}
    for group in ("prospective", "development", "stage", "negative"):
        all_rows = [r for r in rows if r["set"] == group]
        scored = [r for r in all_rows if r["eligible"]]
        tasks = {r["task_id"] for r in scored}
        output[group] = {"rows": len(all_rows), "denominator": len(scored),
                         "packed_joint": sum(r["packed_joint"] for r in scored),
                         "tasks_all_variants_complete": sum(all(r["packed_joint"] for r in scored if r["task_id"] == t) for t in tasks),
                         "task_denominator": len(tasks),
                         "budget_drops": sum(any(d["reason"] == "token_budget" for d in r["drops"]) for r in all_rows),
                         "separator_selected_rows": sum(bool(r["separator_only"]) for r in all_rows),
                         "duplicate_original_selected_rows": sum(r["raw_duplicates_selected"] for r in all_rows),
                         "maximum_tokens": max((r["tokens"] for r in all_rows), default=0)}
    return output


def run(checkpoint=None):
    counts = validate_business()
    evidence, original = source_evidence(), source_rows()
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    if cache["source_sha256"] != cpu.digest(cpu.SOURCE):
        raise ValueError("Ranking cache source changed")
    case_by_id = {c["case_id"]: c for c in cpu.cases()}
    sys.path.insert(0, str(cpu.CHATBOT_SRC))
    from storypal_chatbot.context_packer import ContextPacker
    packer = ContextPacker()
    tokenizer = _jieba()
    lexical = lambda q: terms(q, tokenizer)
    variants, diagnostics = {}, []
    for route, config in cache["configurations"].items():
        if {r["case_id"] for r in config["cases"]} != set(case_by_id):
            raise ValueError("Ranking cache case set changed")
        for input_k in (5, 10):
            for mode in MODES:
                reports = []
                for r in config["cases"]:
                    c = case_by_id[r["case_id"]]
                    if (r["query_sha256"] != hashlib.sha256(c["query"].encode()).hexdigest()
                            or r["max_order"] != c["max_order"] or r["required_units"] != sorted(c["required_units"])):
                        raise ValueError("Ranking query/scope/label changed")
                    ids = cpu.safe_ids(r["candidate_units"][:input_k], c["max_order"], original)
                    start = time.perf_counter()
                    selected, tokens, drops = select(ids, evidence, c["query"], mode, packer, lexical)
                    elapsed_ms = (time.perf_counter() - start) * 1000
                    cpu.safe_ids(selected, c["max_order"], original)
                    if len(selected) > 4 or tokens > 2400:
                        raise ValueError("Pack exceeds fixed budget")
                    if input_k == 5 and mode == "production" and (selected != r["packed_units"] or tokens != r["estimated_tokens"]):
                        raise ValueError("Baseline pack differs from observed cache")
                    required = set(r["required_units"])
                    valid = r["eligible_for_full_set_diagnostic"]
                    reports.append({"case_id": c["case_id"], "task_id": c["task_id"], "set": c["set"], "group": c["group"],
                                    "max_order": c["max_order"], "eligible": valid, "packed_units": selected,
                                    "packed_joint": required.issubset(selected) if valid else None,
                                    "baseline_packed_joint": r["packed_joint"], "tokens": tokens, "drops": drops,
                                    "packing_ms": elapsed_ms,
                                    "raw_duplicates_selected": len(selected) != len({raw_key(evidence[u]) for u in selected}),
                                    "separator_only": [u for u in selected if not any(x.isalnum() for x in evidence[u]["raw_text"])],
                                    "known_summary_conflicts": sorted(set(selected) & set(cpu.CONFLICT_IDS))})
                key = f"{route}/top{input_k}/{mode}"
                scored = [r for r in reports if r["set"] == "prospective" and r["eligible"]]
                variants[key] = {"summary": packing_metrics(reports),
                                 "new_gains": [r["case_id"] for r in scored if r["packed_joint"] and not r["baseline_packed_joint"]],
                                 "new_losses": [r["case_id"] for r in scored if not r["packed_joint"] and r["baseline_packed_joint"]],
                                 "cases": reports}
        for r in config["cases"]:
            visible = set(r["visible_required_units"])
            drop_map = {d["unit_id"]: d["reason"] for d in r["packer_drops"]}
            lost = []
            for uid in sorted(visible - set(r["packed_units"])):
                reason = ("pool_absent" if uid not in r["candidate_units"] else
                          "top5_truncation" if uid not in r["result_units"] else
                          drop_map.get(uid, "unknown_rule"))
                lost.append({"unit_id": uid, "observed_loss_stage": reason})
            diagnostics.append({"route": route, "case_id": r["case_id"], "set": r["set"],
                                "unread_required": r["unread_required_units"], "losses": lost,
                                "candidate_joint": r["joint_at_10"], "top5_joint": r["joint_at_5"],
                                "packed_joint": r["packed_joint"], "known_summary_conflicts": r["selected_known_summary_conflicts"],
                                "separator_only": r["selected_separator_only"], "causal_attribution": "observed pipeline stage, not unique semantic cause"})
    if checkpoint is not None:
        with checkpoint.open("x", encoding="utf-8") as stream:
            json.dump({"schema": "cache-pack-checkpoint@1", "ranking_cache_sha256": cpu.digest(CACHE),
                       "pack_configurations": variants, "observed_loss_diagnostics": diagnostics},
                      stream, ensure_ascii=False, indent=2)
    source_profiles = source_alignment(evidence, original, case_by_id, cache, packer, tokenizer)
    if any(name in sys.modules for name in ("torch", "transformers", "sentence_transformers", "openai")):
        raise RuntimeError("Model-free audit imported neural/provider libraries")
    return {"schema": "cache-loss-pack-audit@1", "business_counts": counts,
            "source_sha256": cpu.digest(cpu.SOURCE), "ranking_cache_sha256": cpu.digest(CACHE),
            "business_contract_sha256": canonical(json.loads(CONTRACT.read_text(encoding="utf-8"))),
            "pack_configurations": variants, "observed_loss_diagnostics": diagnostics,
            "sparse_source_alignment": source_profiles,
            "new_embedding_queries": 0, "new_reranker_pairs": 0, "new_provider_requests": 0,
            "heavy_models_loaded": False, "formal_new_gold": 0}


def source_alignment(evidence, rows, cases, cache, packer, tokenizer):
    fields = {
        "body": {u: e["raw_text"] for u, e in evidence.items()},
        "summary": {u: e["summary"] for u, e in evidence.items()},
        "structure": {u: json.dumps({k: r.get(k, []) for k in
                                     ("characters", "locations", "key_terms", "entity_updates", "plotline_updates")},
                                    ensure_ascii=False, sort_keys=True) for u, r in rows.items()}}
    output = {}
    selected = [c for c in cases.values() if c["set"] == "prospective" and c["task_id"] in cpu.PILOT]
    with sqlite3.connect(":memory:") as conn:
        for profile, texts in fields.items():
            start = time.perf_counter()
            table = "source_" + profile
            conn.execute(f"CREATE VIRTUAL TABLE {table} USING fts5(unit_id UNINDEXED, ord UNINDEXED, body, tokenize='unicode61')")
            conn.executemany(f"INSERT INTO {table} VALUES(?,?,?)",
                             [(u, rows[u]["order"], _indexed(text, tokenizer)) for u, text in texts.items()])
            build_ms = (time.perf_counter() - start) * 1000
            results = []
            for c in selected:
                query_terms = _tokens(c["query"], tokenizer)
                expr = " OR ".join('"' + t.replace('"', '""') + '"' for t in query_terms)
                start = time.perf_counter()
                found = conn.execute(f"SELECT unit_id FROM {table} WHERE {table} MATCH ? AND ord<=? ORDER BY bm25({table}) LIMIT 10",
                                     (expr, c["max_order"])).fetchall() if expr else []
                search_ms = (time.perf_counter() - start) * 1000
                ids = cpu.safe_ids([f[0] for f in found], c["max_order"], rows)
                result = cpu.evaluate(c, ids, rows,
                                      type("Memory", (), {"get_unit": staticmethod(lambda work, uid: evidence[uid])})(),
                                      packer)
                results.append(dict(result, search_ms=search_ms))
            output[profile] = {"index_build_ms": build_ms, "mean_index_chars": sum(map(len, texts.values())) / len(texts),
                               "source_units": len(texts), "query_count": len(results),
                               "summary": cpu.summarize(results), "cases": results,
                               "note": "Different fields change BM25 statistics; not same-information algorithm-only comparison."}
    return output


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    target = args.output.resolve()
    if not target.is_relative_to(RUNTIME.resolve()) or target.exists():
        p.error("Use a new isolated runtime output file")
    before = cpu.digest(cpu.LEDGER)
    started = time.perf_counter()
    result = run(target.with_suffix(".packs.json"))
    result["run_wall_seconds"] = time.perf_counter() - started
    result["process_memory"] = cpu.memory_stats()
    if cpu.digest(cpu.LEDGER) != before:
        raise RuntimeError("Previous model ledger changed")
    result["unchanged_previous_request_ledger_sha256"] = before
    with target.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"counts": result["business_counts"], "pack_variants": len(result["pack_configurations"]),
                      "new_models_loaded": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
