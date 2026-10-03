"""Completely local CPU routes; evidence labels are evaluation-only.

No provider or production device settings are changed. CLI phases persist
separate artifacts and refuse overwriting. Rankings never receive gold.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time

from .holdout_contract import canonical, source_rows, validate, reranker_pair, rerank_scored
from .replay import ROOT, DATA, PIPELINE, RUNTIME, GOLDENS, load_cases, StrictFtsAdapter
from .fusion_replay import SOURCE, CHATBOT_SRC, rank_candidates

CONTRACT = ROOT / "docs/research/retrieval/prospective_tasks_v1_1.json"
LOCK = CONTRACT.with_suffix(".lock.json")
VECTOR_DB = DATA / "wandering_earth/05_index/vectors.lance"
BGE = Path("D:/models/BAAI/bge-m3")
QWEN = Path("D:/models/Qwen/Qwen3-Reranker-0.6B")
LEDGER = RUNTIME / "isolated/sol-luna-20261003-01/requests.jsonl"
PILOT = ("H04", "H06", "H09", "H12", "H14")
STAGES = {"H06": [59, 60, 61], "H09": [74, 75, 77], "H10": [81, 83],
          "H11": [84, 87, 88], "H14": [104, 106]}
CONFLICT_IDS = ["we-0035", "we-0038", "we-0072", "we-0073", "we-0074", "we-0078"]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cpu_environment():
    # Must be set before torch/transformers imports; no CUDA call/initialization.
    os.environ.update(CUDA_VISIBLE_DEVICES="", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false",
                      OMP_NUM_THREADS="4", MKL_NUM_THREADS="4")


def memory_stats():
    # Windows native counters, no new third-party dependency or process spawning.
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (field, ctypes.c_size_t) for field in
                ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                 "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                 "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return {"rss_bytes": counters.WorkingSetSize,
                "peak_working_set_bytes": counters.PeakWorkingSetSize,
                "private_bytes": counters.PrivateUsage, "source": "Windows GetProcessMemoryInfo"}
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {"rss_bytes": peak * 1024, "peak_working_set_bytes": peak * 1024,
            "source": "resource peak, RSS upper bound"}



def cases():
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    validate(payload, lock, source_rows(), digest(SOURCE), digest(GOLDENS))
    output = []
    for t in payload["tasks"]:
        for v in t["variants"]:
            item = {"case_id": v["variant_id"], "task_id": t["task_id"], "set": "prospective",
                    "group": t["split_group"], "query": v["text"], "max_order": t["max_order"],
                    "required_units": t["necessary_unit_candidates"], "provisional": True,
                    "decision": "skip_missing_memory" if t["task_id"] == "H15" else "search",
                    "categories": t["categories"], "source_status": t["annotation_status"]}
            output.append(item)
            for scope in STAGES.get(t["task_id"], []):
                stage = dict(item, case_id=f"{v['variant_id']}@{scope}", set="stage",
                             max_order=scope, duplicate_of_main=scope == t["max_order"])
                if t["task_id"] == "H09" and scope == 77:
                    stage["required_units"] = ["we-0074", "we-0075", "we-0077"]
                    stage["stage_goal"] = "verify completed outcome, requires77; otherwise original plan/progress goal"
                output.append(stage)
    for t in load_cases("goldens29"):
        output.append({"case_id": t["case_id"], "task_id": t["case_id"], "set": "development",
                       "group": "existing_development", "query": t["raw_user"],
                       "max_order": t["max_order"], "required_units": t["required_units"],
                       "provisional": False, "decision": "search", "source_status": "existing_gold"})
    pause = next(t for t in load_cases() if t["case_id"] == "N01")
    output.append({"case_id": "N01", "task_id": "N01", "set": "negative",
                   "group": "pause", "query": pause["raw_user"], "max_order": pause["max_order"],
                   "required_units": [], "provisional": True, "decision": "skip_pause",
                   "source_status": "fixed_offline_decision_not_agent"})
    return output


def safe_ids(ids, scope, rows):
    if len(ids) != len(set(ids)) or len(ids) > 10:
        raise ValueError("Duplicate or overbudget candidates")
    if any(uid not in rows or rows[uid]["work_id"] != "wandering_earth"
           or not 0 < rows[uid]["order"] <= scope for uid in ids):
        raise ValueError("Candidate exceeds source or reading boundary")
    return ids


def dense():
    cpu_environment()
    import torch
    from sentence_transformers import SentenceTransformer
    sys.path.insert(0, str(PIPELINE))
    from storypipe.vector_index import read_vector_meta, search_vector_index
    torch.set_num_threads(4)
    meta = read_vector_meta(VECTOR_DB)
    if (meta.get("source_sha256") != digest(SOURCE) or meta.get("dimension") != 1024
            or Path(meta.get("model", "")).resolve() != BGE.resolve()):
        raise ValueError("Dense index differs from fixed source/model")
    all_cases = cases()
    texts = list(dict.fromkeys(c["query"] for c in all_cases if c["decision"] == "search"))
    start = time.perf_counter()
    model = SentenceTransformer(str(BGE), device="cpu", local_files_only=True)
    if any(p.device.type != "cpu" for p in model.parameters()):
        raise ValueError("Embedding not completely on CPU")
    load_ms = (time.perf_counter() - start) * 1000
    vectors, batches = {}, []
    for i in range(0, len(texts), 2):
        started = time.perf_counter()
        batch = texts[i:i + 2]
        values = model.encode(batch, batch_size=2, normalize_embeddings=True,
                              show_progress_bar=False, device="cpu")
        elapsed = (time.perf_counter() - started) * 1000
        for text, vector in zip(batch, values):
            vectors[text] = list(map(float, vector))
        batches.append({"query_sha256": [hashlib.sha256(t.encode()).hexdigest() for t in batch],
                        "encode_ms": elapsed})
        print(f"CPU encoding {min(i + 2, len(texts))}/{len(texts)}", flush=True)
    rows, reports, cache = source_rows(), [], {}
    for c in all_cases:
        if c["decision"] != "search":
            reports.append({"case_id": c["case_id"], "decision": c["decision"], "candidate_units": [],
                            "search_executed": False})
            continue
        key = (c["query"], c["max_order"])
        reused = key in cache
        if not reused:
            started = time.perf_counter()
            found = search_vector_index(VECTOR_DB, vectors[c["query"]], max_order=c["max_order"], limit=10)
            ids = safe_ids([uid for uid, _ in found], c["max_order"], rows)
            cache[key] = {"candidate_units": ids, "scores": [s for _, s in found],
                          "search_ms": (time.perf_counter() - started) * 1000}
        reports.append({"case_id": c["case_id"], "query_sha256": hashlib.sha256(c["query"].encode()).hexdigest(),
                        "max_order": c["max_order"], "reused_scope_search": reused, **cache[key]})
    if torch.cuda.is_initialized():
        raise ValueError("CUDA was initialized")
    return {"schema": "cpu-dense@1", "device": "cpu", "threads": 4,
            "source_sha256": digest(SOURCE), "contract_sha256": canonical(json.loads(CONTRACT.read_text(encoding="utf-8"))),
            "vector_metadata": meta, "load_ms": load_ms, "query_encodings": len(texts),
            "scope_searches": len(cache), "batch_size": 2, "encode_batches": batches,
            "cached_query_vectors": {hashlib.sha256(t.encode()).hexdigest(): v for t, v in vectors.items()},
            "memory": memory_stats(), "cuda_initialized": False, "cases": reports}


def choose_navigation(query, scope, rows, tokens):
    eligible = [r for r in rows.values() if r["order"] <= scope]
    names = {str(u.get("name", "")).strip() for r in eligible for u in r.get("entity_updates", [])
             if str(u.get("name", "")).strip()}
    matches = [n for n in names if n in query]
    if matches:
        matches.sort(key=lambda n: (-len(n), query.index(n), n))
        return [{"kind": "entity", "query": n} for n in matches[:2]]
    titles = {str(u.get("title", "")).strip() for r in eligible for u in r.get("plotline_updates", [])
              if str(u.get("title", "")).strip()}
    terms = set(tokens(query))
    scored = [(len(terms & set(tokens(t))), query.find(t) if t in query else len(query), t) for t in titles]
    scored = [s for s in scored if s[0] > 0]
    scored.sort(key=lambda s: (-s[0], s[1], s[2]))
    return [{"kind": "plotline", "query": t} for _, _, t in scored[:2]]


def structure(query, scope, rows, tokens, service):
    requests = choose_navigation(query, scope, rows, tokens)
    history, lengths = [], []
    for request in requests:
        result = service.structured_context(work_id="wandering_earth", max_seen_order=scope, **request)
        entries = result.get("history", [])
        lengths.append({"kind": request["kind"], "query": request["query"], "records": len(entries)})
        for entry in entries:
            uid = entry["unit_id"]
            if uid not in rows or rows[uid]["order"] != entry["order"] or not 0 < entry["order"] <= scope:
                raise ValueError("Structured provenance exceeds boundary")
        history.extend(entries)
    history.sort(key=lambda r: (-r["order"], r["unit_id"],
                               json.dumps(r.get("update", {}), ensure_ascii=False, sort_keys=True)))
    chosen, used = [], 0
    for entry in history:
        estimated = max(1, math.ceil(len(json.dumps(entry, ensure_ascii=False)) / 1.6))
        if len(chosen) >= 20 or used + estimated > 1800:
            break
        chosen.append(entry)
        used += estimated
    ids = list(dict.fromkeys(e["unit_id"] for e in chosen))[:10]
    # Check with actual service and original hashes, not its abstract update text.
    for uid in ids[:5]:
        evidence = service.get_evidence(work_id="wandering_earth", unit_id=uid, max_seen_order=scope)
        if hashlib.sha256(evidence["raw_text"].encode()).hexdigest() != hashlib.sha256(rows[uid]["text"].encode()).hexdigest():
            raise ValueError("Navigation raw source mismatch")
    return safe_ids(ids, scope, rows), {"requests": lengths, "unbounded_history_records": len(history),
                                      "history_records_kept": len(chosen), "history_estimated_tokens": used,
                                      "history_dropped": len(history) - len(chosen),
                                      "unbudgeted_history_ids": list(dict.fromkeys(e["unit_id"] for e in history)),
                                      "note": "deterministic local routing; not real Agent"}


def evaluate(c, ids, rows, memory, packer):
    safe_ids(ids, c["max_order"], rows)
    evidence = [memory.get_unit("wandering_earth", uid) for uid in ids[:5]]
    if any(e is None for e in evidence):
        raise ValueError("Missing candidate original")
    started = time.perf_counter()
    packed = packer.pack(evidence, work_id="wandering_earth", max_seen_order=c["max_order"])
    packed_ids = [e["unit_id"] for e in packed.anchors + packed.adjacent_context]
    safe_ids(packed_ids, c["max_order"], rows)
    required = set(c["required_units"])
    visible = {uid for uid in required if rows[uid]["order"] <= c["max_order"]}
    hidden = sorted(required - visible)
    valid = bool(required) and not hidden
    first = next((i for i, uid in enumerate(ids[:5], 1) if uid in visible), None)
    failure = ("no_story_search_fixed_fixture" if c["decision"] != "search" else
               "no_required_gold_scope_unknown" if not required else
               "incomplete_scope" if hidden else
               "empty_candidates" if not ids else
               "candidate_missing" if not required.issubset(ids) else
               "top5_loss" if not required.issubset(ids[:5]) else
               "packer_loss" if not required.issubset(packed_ids) else "complete_candidate_set")
    return {"case_id": c["case_id"], "task_id": c["task_id"], "set": c["set"], "group": c["group"],
            "max_order": c["max_order"], "provisional": c["provisional"], "decision": c["decision"],
            "query_sha256": hashlib.sha256(c["query"].encode()).hexdigest(),
            "required_units": sorted(required), "visible_required_units": sorted(visible),
            "unread_required_units": hidden, "eligible_for_full_set_diagnostic": valid,
            "candidate_units": ids, "result_units": ids[:5], "packed_units": packed_ids,
            "joint_at_10": required.issubset(ids) if valid else None,
            "joint_at_3": required.issubset(ids[:3]) if valid else None,
            "joint_at_5": required.issubset(ids[:5]) if valid else None,
            "packed_joint": required.issubset(packed_ids) if valid else None,
            "visible_packed_joint": visible.issubset(packed_ids) if visible else None,
            "mrr": 1 / first if first else 0.0,
            "boundary_ok": True, "failure_type": failure,
            "packer_drops": packed.dropped, "estimated_tokens": packed.token_estimate,
            "packing_ms": (time.perf_counter() - started) * 1000,
            "selected_known_summary_conflicts": sorted(set(packed_ids) & set(CONFLICT_IDS)),
            "selected_separator_only": [uid for uid in packed_ids if not any(x.isalnum() for x in rows[uid]["text"])]}


def summarize(reports):
    output = {}
    for group in ("prospective", "development", "stage", "negative"):
        rows = [r for r in reports if r["set"] == group]
        scored = [r for r in rows if r["eligible_for_full_set_diagnostic"]]
        tasks = sorted({r["task_id"] for r in scored})
        output[group] = {"rows": len(rows), "diagnostic_denominator": len(scored),
                         "joint_at_10": sum(bool(r["joint_at_10"]) for r in scored),
                         "joint_at_3": sum(bool(r["joint_at_3"]) for r in scored),
                         "joint_at_5": sum(bool(r["joint_at_5"]) for r in scored),
                         "packed_joint": sum(bool(r["packed_joint"]) for r in scored),
                         "mrr": round(statistics.mean(r["mrr"] for r in scored), 4) if scored else None,
                         "tasks_both_variants_packed": sum(all(r["packed_joint"] for r in scored if r["task_id"] == t) for t in tasks),
                         "task_denominator": len(tasks),
                         "event_groups": sorted({r["group"] for r in rows}),
                         "failure_types": dict(Counter(r["failure_type"] for r in rows)),
                         "selected_summary_conflict_rows": sum(bool(r["selected_known_summary_conflicts"]) for r in rows),
                         "separator_only_rows": sum(bool(r["selected_separator_only"]) for r in rows),
                         "boundary_violations": sum(not r["boundary_ok"] for r in rows),
                         "max_pack_tokens": max((r["estimated_tokens"] for r in rows), default=0)}
    return output


def routes(dense_path):
    base = json.loads(dense_path.read_text(encoding="utf-8"))
    if base["source_sha256"] != digest(SOURCE) or base["contract_sha256"] != canonical(json.loads(CONTRACT.read_text(encoding="utf-8"))):
        raise ValueError("Dense artifact changed source/contract")
    sys.path.insert(0, str(PIPELINE))
    sys.path.insert(0, str(CHATBOT_SRC))
    from storymemory.adapter import StoryMemory
    from storypal_chatbot.story_memory import PipelineStoryMemoryBackend, StoryMemoryService
    from storypal_chatbot.context_packer import ContextPacker
    from .sparse import JiebaFtsAdapter, _tokens
    started = time.perf_counter()
    sparse = JiebaFtsAdapter("or")
    sparse_init_ms = (time.perf_counter() - started) * 1000
    memory = StoryMemory(DATA, retrieval="fts")
    strict = StrictFtsAdapter(memory)
    service = StoryMemoryService(PipelineStoryMemoryBackend(data_root=DATA, pipeline_code_path=PIPELINE, retrieval="fts"))
    packer, rows = ContextPacker(), source_rows()
    cached_dense = {c["case_id"]: c for c in base["cases"]}
    configurations = {name: [] for name in ("dense", "jieba_or", "fts_strict", "fts_actual",
                                           "rrf_dense2_sparse1", "structure")}
    local_cache = {}
    for c in cases():
        d = cached_dense[c["case_id"]]
        if c["decision"] != "search":
            for config in configurations:
                r = evaluate(c, [], rows, memory, packer)
                configurations[config].append(dict(r, search_ms=0, search_executed=False))
            continue
        key = (c["query"], c["max_order"])
        if key not in local_cache:
            values = {}
            for config, adapter in (("jieba_or", sparse), ("fts_strict", strict), ("fts_actual", memory)):
                started = time.perf_counter()
                found = adapter.search("wandering_earth", c["query"], max_order=c["max_order"], top_k=10)
                values[config] = ([e["unit_id"] for e in found],
                                  {"search_ms": (time.perf_counter() - started) * 1000,
                                   "diagnostics": adapter.last_search_diagnostics})
            started = time.perf_counter()
            ids, info = structure(c["query"], c["max_order"], rows, lambda q: _tokens(q, sparse.jieba), service)
            values["structure"] = (ids, dict(info, search_ms=(time.perf_counter() - started) * 1000))
            local_cache[key] = values
        values = local_cache[key]
        values = dict(values)
        values["dense"] = (d["candidate_units"], {"search_ms": d["search_ms"], "encode_cost_separate": True})
        started = time.perf_counter()
        ranked = rank_candidates(d["candidate_units"], values["jieba_or"][0], "rrf_dense2_sparse1")
        fusion_ms = (time.perf_counter() - started) * 1000
        values["rrf_dense2_sparse1"] = ([r["unit_id"] for r in ranked],
                                      {"search_ms": d["search_ms"] + values["jieba_or"][1]["search_ms"] + fusion_ms,
                                       "fusion_ms": fusion_ms, "encode_cost_separate": True,
                                       "source_union_units": sorted(set(d["candidate_units"]) | set(values["jieba_or"][0]))})
        for config, (ids, info) in values.items():
            r = evaluate(c, ids, rows, memory, packer)
            configurations[config].append(dict(r, **info, search_executed=True))
    previous = json.loads((RUNTIME / "29-raw-vector.json").read_text(encoding="utf-8"))
    old = {c["case_id"]: c["candidate_units"] for c in previous["cases"]}
    changed = [r["case_id"] for r in configurations["dense"] if r["set"] == "development" and r["candidate_units"] != old[r["case_id"]]]
    return {"schema": "cpu-multiroute@1", "source_sha256": digest(SOURCE), "contract_sha256": base["contract_sha256"],
            "dense_artifact_sha256": digest(dense_path), "sparse_initialization_ms": sparse_init_ms,
            "dense_development_top10_differs_from_old": changed,
            "configurations": {k: {"summary": summarize(v), "cases": v} for k, v in configurations.items()},
            "new_provider_requests": 0, "real_agent_navigation": False, "formal_new_gold_count": 0}


def reranker(route_path):
    cpu_environment()
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    torch.set_num_threads(4)
    report = json.loads(route_path.read_text(encoding="utf-8"))
    if report["source_sha256"] != digest(SOURCE) or report["contract_sha256"] != canonical(json.loads(CONTRACT.read_text(encoding="utf-8"))):
        raise ValueError("Routes source/contract differs")
    output = {"schema": "cpu-reranker@1", "device": "cpu", "dtype": "float32", "threads": 4,
              "route_artifact_sha256": digest(route_path), "pilot_tasks": list(PILOT),
              "candidate_pool": "same dense Top10", "max_length": 4096, "batch_size": 1,
              "load_status": "not_started", "pairs": [], "cases": [], "new_provider_requests": 0}
    started = time.perf_counter()
    try:
        tokenizer = AutoTokenizer.from_pretrained(str(QWEN), local_files_only=True, padding_side="left")
        model = AutoModelForCausalLM.from_pretrained(str(QWEN), local_files_only=True,
                                                    torch_dtype=torch.float32, attn_implementation="eager").to("cpu").eval()
        if any(p.device.type != "cpu" for p in model.parameters()):
            raise ValueError("Reranker not completely on CPU")
        output.update(load_status="loaded", load_ms=(time.perf_counter() - started) * 1000, load_memory=memory_stats())
        true_ids = tokenizer.encode("yes", add_special_tokens=False)
        false_ids = tokenizer.encode("no", add_special_tokens=False)
        if len(true_ids) != 1 or len(false_ids) != 1:
            raise ValueError("yes/no are not single tokens")
        prefix = '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
        suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
        prefix_ids = tokenizer.encode(prefix, add_special_tokens=False)
        suffix_ids = tokenizer.encode(suffix, add_special_tokens=False)
        output["yes_no_token_ids"] = {"yes": true_ids[0], "no": false_ids[0]}
        sys.path.insert(0, str(PIPELINE))
        sys.path.insert(0, str(CHATBOT_SRC))
        from storymemory.adapter import StoryMemory
        from storypal_chatbot.context_packer import ContextPacker
        memory, packer, rows = StoryMemory(DATA, retrieval="fts"), ContextPacker(), source_rows()
        dense_cases = {r["case_id"]: r for r in report["configurations"]["dense"]["cases"]}
        scoring_seconds, stop = 0.0, None
        for c in [c for c in cases() if c["set"] == "prospective" and c["task_id"] in PILOT]:
            ids, scores, rejected = dense_cases[c["case_id"]]["candidate_units"], {}, []
            for uid in ids:
                evidence = memory.get_unit("wandering_earth", uid)
                pair = reranker_pair(c["query"], evidence, max_order=c["max_order"])
                encoded = prefix_ids + tokenizer.encode(pair, add_special_tokens=False) + suffix_ids
                if len(encoded) > 4096:
                    rejected.append({"unit_id": uid, "tokens": len(encoded), "reason": "too_long_no_truncation"})
                    continue
                inputs = torch.tensor([encoded], dtype=torch.long, device="cpu")
                begin = time.perf_counter()
                with torch.inference_mode():
                    logits = model(input_ids=inputs, attention_mask=torch.ones_like(inputs),
                                   use_cache=False, logits_to_keep=1).logits[0, -1, :]
                    score = torch.softmax(torch.stack([logits[false_ids[0]], logits[true_ids[0]]]).float(), dim=0)[1].item()
                elapsed = time.perf_counter() - begin
                scoring_seconds += elapsed
                mem = memory_stats()
                scores[uid] = score
                output["pairs"].append({"case_id": c["case_id"], "unit_id": uid, "tokens": len(encoded),
                                        "score": score, "inference_ms": elapsed * 1000, "memory": mem})
                print(f"CPU reranker {c['case_id']} {uid}: {elapsed:.2f}s", flush=True)
                if elapsed > 20 or scoring_seconds > 600 or mem["rss_bytes"] > 12 * 1024 ** 3:
                    stop = "cost_limit_single20s_total600s_rss12GiB"
                    break
            if set(scores) == set(ids) and ids:
                ranked = rerank_scored(ids, scores)
                r = evaluate(c, ranked, rows, memory, packer)
                output["cases"].append(dict(r, status="complete", dense_baseline=dense_cases[c["case_id"]]))
            else:
                output["cases"].append({"case_id": c["case_id"], "status": "incomplete",
                                        "scored_ids": list(scores), "rejected": rejected, "stop": stop,
                                        "dense_pool": ids})
            if stop:
                output["stop_reason"] = stop
                break
        output["scoring_seconds"] = scoring_seconds
        output["summary"] = summarize([r for r in output["cases"] if r["status"] == "complete"])
        output["final_memory"] = memory_stats()
        output["cuda_initialized"] = torch.cuda.is_initialized()
        if output["cuda_initialized"]:
            raise ValueError("CUDA initialized")
    except Exception as exc:
        output.update(load_status="failed" if output["load_status"] != "loaded" else "execution_failed",
                      error_type=type(exc).__name__, error=str(exc), elapsed_ms=(time.perf_counter() - started) * 1000,
                      failure_memory=memory_stats())
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("dense", "routes", "reranker"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(RUNTIME.resolve()) or output.exists():
        parser.error("Use a new file inside isolated retrieval runtime")
    if args.phase != "dense" and (args.input is None or not args.input.is_file()):
        parser.error("Phase requires completed local input artifact")
    before = digest(LEDGER)
    if args.phase == "dense":
        report = dense()
    elif args.phase == "routes":
        report = routes(args.input)
    else:
        report = reranker(args.input)
    if before != digest(LEDGER):
        raise RuntimeError("Previous request ledger changed")
    report["unchanged_previous_request_ledger_sha256"] = before
    report["new_provider_requests"] = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"phase": args.phase, "output": str(output), "status": report.get("load_status", "complete")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
