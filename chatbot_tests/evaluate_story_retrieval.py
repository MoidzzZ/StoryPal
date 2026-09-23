"""在固定故事语料上对检索策略进行中文金标评测。"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "story_mem" / "data"
DEFAULT_PIPELINE = ROOT / "story_mem" / "code"
DEFAULT_CASES = Path(__file__).with_name("story_retrieval_goldens.json")
DEFAULT_RETRIEVALS = ("fts", "vector", "hybrid_rrf")
QUERY_SOURCES = ("gold_rewrite", "raw_user")


def load_adapter(data_root: Path, pipeline_code: Path, retrieval: str):
    if str(pipeline_code) not in sys.path:
        sys.path.insert(0, str(pipeline_code))
    from storymemory.adapter import StoryMemory

    return StoryMemory(data_root, retrieval=retrieval)


class HybridRrfAdapter:
    """仅用于离线消融：显式并行取两路候选，再以 RRF 融合。

    这不是协作方 `auto` 的故障降级链；任一路不可用均让实验失败，避免
    把单路回退误报成 Hybrid。
    """

    retrieval = "hybrid_rrf"

    def __init__(self, fts: Any, vector: Any, *, candidate_k: int = 10, rrf_k: int = 60) -> None:
        if candidate_k <= 0 or rrf_k < 0:
            raise ValueError("candidate_k 必须为正数，rrf_k 不能为负数。")
        self.fts = fts
        self.vector = vector
        self.candidate_k = candidate_k
        self.rrf_k = rrf_k
        self.last_search_diagnostics: dict[str, Any] = {}

    @staticmethod
    def _safe(item: dict[str, Any], *, work_id: str, max_order: int) -> bool:
        try:
            return str(item["work_id"]) == work_id and int(item["order"]) <= max_order
        except (KeyError, TypeError, ValueError):
            return False

    def search(self, work_id: str, query: str, *, max_order: int, top_k: int) -> list[dict[str, Any]]:
        source_hits = {
            "fts": self.fts.search(work_id, query, max_order=max_order, top_k=self.candidate_k),
            "vector": self.vector.search(work_id, query, max_order=max_order, top_k=self.candidate_k),
        }
        merged: dict[str, dict[str, Any]] = {}
        filtered_spoiler_count = 0
        for source, hits in source_hits.items():
            for rank, item in enumerate(hits, start=1):
                if not self._safe(item, work_id=work_id, max_order=max_order):
                    filtered_spoiler_count += 1
                    continue
                unit_id = str(item["unit_id"])
                record = merged.setdefault(unit_id, {
                    "evidence": dict(item),
                    "score": 0.0,
                    "per_source_rank": {},
                })
                record["score"] += 1.0 / (self.rrf_k + rank)
                record["per_source_rank"][source] = rank
        ranked = sorted(
            merged.values(),
            key=lambda record: (
                -float(record["score"]),
                min(record["per_source_rank"].values()),
                str(record["evidence"]["unit_id"]),
            ),
        )
        result: list[dict[str, Any]] = []
        for record in ranked[:top_k]:
            evidence = dict(record["evidence"])
            evidence["score"] = round(float(record["score"]), 8)
            evidence["retrieval_diagnostics"] = {
                "per_source_rank": dict(record["per_source_rank"]),
                "fused_score": evidence["score"],
            }
            result.append(evidence)
        self.last_search_diagnostics = {
            "requested_retrieval": self.retrieval,
            "used_retrieval": self.retrieval,
            "candidate_k": self.candidate_k,
            "rrf_k": self.rrf_k,
            "candidate_count": len(merged),
            "filtered_spoiler_count": filtered_spoiler_count,
            "source_diagnostics": {
                source: dict(getattr(adapter, "last_search_diagnostics", None) or {})
                for source, adapter in (("fts", self.fts), ("vector", self.vector))
            },
        }
        return result


def load_hybrid_adapter(
    data_root: Path, pipeline_code: Path, *, candidate_k: int, rrf_k: int
) -> HybridRrfAdapter:
    return HybridRrfAdapter(
        load_adapter(data_root, pipeline_code, "fts"),
        load_adapter(data_root, pipeline_code, "vector"),
        candidate_k=candidate_k,
        rrf_k=rrf_k,
    )

def percentile(values: Iterable[float], ratio: float) -> float | None:
    """线性插值百分位，样本较小时避免把 P95 误报成均值。"""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return round(ordered[0], 1)
    position = (len(ordered) - 1) * ratio
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 1)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 1)


def reciprocal_rank(result_ids: list[str], expected: set[str]) -> float:
    for rank, unit_id in enumerate(result_ids, start=1):
        if unit_id in expected:
            return 1.0 / rank
    return 0.0


def recall_at(result_ids: list[str], expected: set[str], limit: int) -> float:
    if not expected:
        return 0.0
    return len(expected.intersection(result_ids[:limit])) / len(expected)


def ndcg_at(result_ids: list[str], expected: set[str], limit: int) -> float:
    """二元相关性的 nDCG；每个 gold unit 都是一个独立相关证据。"""
    if not expected:
        return 0.0
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, unit_id in enumerate(result_ids[:limit], start=1)
        if unit_id in expected
    )
    ideal_count = min(len(expected), limit)
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return dcg / ideal_dcg if ideal_dcg else 0.0


def case_query(case: dict[str, Any], query_source: str) -> str:
    """gold_rewrite 衡量检索器上限；raw_user 衡量未经答案词扩写的原始输入。"""
    if query_source == "raw_user":
        return str(case["用户原话"])
    return str(case.get("检索查询", case["用户原话"]))


def case_labels(case: dict[str, Any]) -> list[str]:
    labels = case.get("标签")
    if isinstance(labels, list) and labels:
        return [str(label) for label in labels if str(label).strip()]
    category = str(case.get("类别", "未分类")).strip()
    return [category or "未分类"]


def _empty_totals() -> dict[str, Any]:
    return {
        "scored_cases": 0,
        "hits": {1: 0, 3: 0, 5: 0},
        "recalls": {1: [], 3: [], 5: []},
        "rr": [],
        "ndcg5": [],
        "latencies": [],
        "violations": 0,
    }


def _metric_summary(totals: dict[str, Any], *, include_case_count: int) -> dict[str, Any]:
    scored = int(totals["scored_cases"])
    return {
        "用例数": include_case_count,
        "有金标用例数": scored,
        "前1命中率": round(totals["hits"][1] / scored, 3) if scored else None,
        "前3命中率": round(totals["hits"][3] / scored, 3) if scored else None,
        "前5命中率": round(totals["hits"][5] / scored, 3) if scored else None,
        "平均召回@1": round(statistics.fmean(totals["recalls"][1]), 3) if scored else None,
        "平均召回@3": round(statistics.fmean(totals["recalls"][3]), 3) if scored else None,
        "平均召回@5": round(statistics.fmean(totals["recalls"][5]), 3) if scored else None,
        "MRR": round(statistics.fmean(totals["rr"]), 3) if scored else None,
        "nDCG@5": round(statistics.fmean(totals["ndcg5"]), 3) if scored else None,
        "P50耗时毫秒": percentile(totals["latencies"], 0.50),
        "P95耗时毫秒": percentile(totals["latencies"], 0.95),
        "防剧透违规用例数": int(totals["violations"]),
    }


def evaluate(
    adapter: Any,
    cases: list[dict[str, Any]],
    *,
    work_id: str = "wandering_earth",
    top_k: int = 5,
    query_source: str = "gold_rewrite",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """返回逐例结果和总体/类别指标；空 gold 只参与安全与延迟统计。"""
    if query_source not in QUERY_SOURCES:
        raise ValueError(f"未知查询来源：{query_source}")
    results: list[dict[str, Any]] = []
    totals = _empty_totals()
    category_totals: dict[str, dict[str, Any]] = defaultdict(_empty_totals)
    category_case_count: dict[str, int] = defaultdict(int)

    for case in cases:
        query = case_query(case, query_source)
        started = time.perf_counter()
        hits = adapter.search(
            work_id,
            query,
            max_order=case["阅读边界"],
            top_k=top_k,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        ids = [str(item["unit_id"]) for item in hits]
        expected = {str(unit_id) for unit_id in case.get("期望单元", [])}
        safe = all(int(item["order"]) <= int(case["阅读边界"]) for item in hits)
        labels = case_labels(case)
        diagnostics = dict(getattr(adapter, "last_search_diagnostics", None) or {})
        row: dict[str, Any] = {
            "编号": case["编号"],
            "类别": case.get("类别", "未分类"),
            "标签": labels,
            "用户原话": case["用户原话"],
            "查询来源": query_source,
            "检索查询": query,
            "阅读边界": case["阅读边界"],
            "期望单元": sorted(expected),
            "结果单元": ids,
            "耗时毫秒": elapsed_ms,
            "防剧透通过": safe,
            "检索诊断": diagnostics,
        }

        target_totals = [totals] + [category_totals[label] for label in labels]
        for current in target_totals:
            current["latencies"].append(elapsed_ms)
            current["violations"] += int(not safe)
        for label in labels:
            category_case_count[label] += 1

        if expected:
            first_rank = next((rank for rank, unit_id in enumerate(ids, start=1) if unit_id in expected), None)
            row["首个相关排名"] = first_rank
            row["MRR贡献"] = round(reciprocal_rank(ids, expected), 4)
            row["nDCG@5"] = round(ndcg_at(ids, expected, 5), 4)
            for limit in (1, 3, 5):
                row[f"前{limit}命中"] = bool(expected.intersection(ids[:limit]))
                row[f"召回@{limit}"] = round(recall_at(ids, expected, limit), 4)
            for current in target_totals:
                current["scored_cases"] += 1
                current["rr"].append(reciprocal_rank(ids, expected))
                current["ndcg5"].append(ndcg_at(ids, expected, 5))
                for limit in (1, 3, 5):
                    current["hits"][limit] += int(bool(expected.intersection(ids[:limit])))
                    current["recalls"][limit].append(recall_at(ids, expected, limit))
        else:
            row["评测说明"] = "无 gold evidence：仅统计安全与延迟，不计入排序指标。"
        results.append(row)

    metrics = _metric_summary(totals, include_case_count=len(cases))
    metrics["类别统计"] = {
        label: _metric_summary(category_totals[label], include_case_count=category_case_count[label])
        for label in sorted(category_totals)
    }
    return results, metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--pipeline-code", type=Path, default=DEFAULT_PIPELINE)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-id", default="wandering_earth")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--retrieval", action="append", choices=DEFAULT_RETRIEVALS)
    parser.add_argument("--candidate-k", type=int, default=10)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument(
        "--query-source",
        choices=QUERY_SOURCES,
        default="gold_rewrite",
        help="gold_rewrite 是人工改写检索上限；raw_user 是未经答案词扩写的原始用户问句。",
    )
    args = parser.parse_args()
    if args.top_k <= 0 or args.candidate_k <= 0:
        parser.error("--top-k 和 --candidate-k 必须是正整数")
    if args.rrf_k < 0:
        parser.error("--rrf-k 不能为负数")
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    retrievals = tuple(args.retrieval or DEFAULT_RETRIEVALS)
    report = {
        "用例版本": "story-retrieval@0.2",
        "评测配置": {
            "work_id": args.work_id,
            "top_k": args.top_k,
            "检索策略": retrievals,
            "查询来源": args.query_source,
        },
        "结果": {},
    }
    for retrieval in retrievals:
        adapter = (
            load_hybrid_adapter(
                args.data_root, args.pipeline_code,
                candidate_k=args.candidate_k, rrf_k=args.rrf_k,
            )
            if retrieval == "hybrid_rrf"
            else load_adapter(args.data_root, args.pipeline_code, retrieval)
        )
        rows, metrics = evaluate(
            adapter,
            cases,
            work_id=args.work_id,
            top_k=args.top_k,
            query_source=args.query_source,
        )
        report["结果"][retrieval] = {"指标": metrics, "用例": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: value["指标"] for name, value in report["结果"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()