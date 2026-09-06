# StoryMemory 接口需求：阅读位置与检索可观察性

- 提出日期：2026-09-06
- 提出方：StoryPal Chatbot
- 优先级：P1（首次阅读陪读体验的前置条件）

## 背景

Chatbot 已能在 `max_order` 下安全检索，但产品不能要求首次读者输入内部 `unit_id` 或数字顺序。当前冻结接口只有 `list_works`、`search`、`get_unit`；无法通过接口获得“用户可读章节 ↔ 单元范围”的稳定映射，也无法知道一次 `retrieval="auto"` 实际落在向量、FTS5 还是扫描降级。

## 希望新增的只读接口

```python
sm.get_reading_locations(work_id) -> {
  "work_id": "wandering_earth",
  "source_version": "<source sha256 或稳定版本>",
  "locations": [
    {
      "location_id": "chapter-01",
      "label": "上篇 刹车时代",
      "kind": "chapter",
      "start_order": 1,
      "end_order": 26,
      "start_line": 1,
      "end_line": 123
    }
  ]
}
```

约束：只从事实源派生；无索引也可工作；`location_id` 可在同一源版本稳定；不返回未来剧情摘要。

## 希望补充的检索诊断

不破坏 `search(...) -> list[Evidence]` 的默认形状。可任选一种兼容方式：

- 为适配器提供只读 `last_search_diagnostics`；或
- 增加可选 `search_with_diagnostics(...)`。

至少包含：`requested_retrieval`、`used_retrieval`（vector/fts/scan）、`fallback_reason`、`candidate_count_before_boundary`、`candidate_count_after_boundary`、`source_version`。诊断仅供 Chatbot 日志、测试和运维显示，不直接暴露给阅读者。

## 后续可选能力（非本次阻塞）

当需要允许用户“读到某段中间”时，再提供带章节/行号的安全位置验证；在此之前，Chatbot 只允许把阅读进度写到一个完整单元或完整章节的末尾。