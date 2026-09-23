from __future__ import annotations

from evaluate_story_retrieval import HybridRrfAdapter, evaluate, ndcg_at, percentile


class FakeAdapter:
    last_search_diagnostics = {"used_retrieval": "fake"}

    def search(self, work_id, query, *, max_order, top_k):
        assert work_id == "wandering_earth"
        assert query == "测试查询"
        assert max_order == 5
        assert top_k == 5
        return [
            {"unit_id": "x", "order": 1},
            {"unit_id": "a", "order": 2},
            {"unit_id": "b", "order": 3},
        ]


def test_percentile_uses_linear_interpolation() -> None:
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    assert percentile([1, 2, 3, 4], 0.95) == 3.8


def test_ndcg_handles_multiple_gold_units() -> None:
    assert round(ndcg_at(["x", "a", "b"], {"a", "b"}, 5), 4) == 0.6934


def test_evaluate_reports_ranking_safety_and_category_metrics() -> None:
    cases = [
        {
            "编号": "T01",
            "类别": "明确事实",
            "标签": ["明确事实", "事件因果"],
            "用户原话": "测试问题",
            "检索查询": "测试查询",
            "阅读边界": 5,
            "期望单元": ["a", "b"],
        },
        {
            "编号": "T02",
            "类别": "安全边界",
            "用户原话": "结局呢",
            "检索查询": "测试查询",
            "阅读边界": 5,
            "期望单元": [],
        },
    ]

    rows, metrics = evaluate(FakeAdapter(), cases)

    assert rows[0]["前1命中"] is False
    assert rows[0]["前3命中"] is True
    assert rows[0]["召回@3"] == 1.0
    assert rows[0]["MRR贡献"] == 0.5
    assert rows[1]["评测说明"].startswith("无 gold evidence")
    assert metrics["有金标用例数"] == 1
    assert metrics["前3命中率"] == 1.0
    assert metrics["平均召回@3"] == 1.0
    assert metrics["MRR"] == 0.5
    assert metrics["nDCG@5"] == 0.693
    assert metrics["防剧透违规用例数"] == 0
    assert metrics["类别统计"]["事件因果"]["有金标用例数"] == 1
    assert metrics["类别统计"]["安全边界"]["有金标用例数"] == 0

def test_raw_user_query_does_not_use_gold_rewrite() -> None:
    class RecordingAdapter:
        last_search_diagnostics = {}

        def __init__(self) -> None:
            self.query = ""

        def search(self, work_id, query, *, max_order, top_k):
            self.query = query
            return [{"unit_id": "a", "order": 1}]

    adapter = RecordingAdapter()
    evaluate(
        adapter,
        [{
            "编号": "T03",
            "类别": "明确事实",
            "用户原话": "用户实际怎么问",
            "检索查询": "人工补进答案词的改写",
            "阅读边界": 1,
            "期望单元": ["a"],
        }],
        query_source="raw_user",
    )
    assert adapter.query == "用户实际怎么问"

def test_hybrid_rrf_deduplicates_and_filters_spoilers() -> None:
    class Source:
        def __init__(self, hits):
            self.hits = hits
            self.last_search_diagnostics = {"used_retrieval": "fake"}

        def search(self, *_args, **_kwargs):
            return self.hits

    fts = Source([
        {"work_id": "demo", "unit_id": "a", "order": 2, "score": 1.0},
        {"work_id": "demo", "unit_id": "future", "order": 6, "score": 1.0},
    ])
    vector = Source([
        {"work_id": "demo", "unit_id": "b", "order": 3, "score": 1.0},
        {"work_id": "demo", "unit_id": "a", "order": 2, "score": 1.0},
    ])

    adapter = HybridRrfAdapter(fts, vector, candidate_k=5, rrf_k=60)
    result = adapter.search("demo", "查询", max_order=5, top_k=5)

    assert [item["unit_id"] for item in result] == ["a", "b"]
    assert result[0]["retrieval_diagnostics"]["per_source_rank"] == {"fts": 1, "vector": 2}
    assert adapter.last_search_diagnostics["filtered_spoiler_count"] == 1