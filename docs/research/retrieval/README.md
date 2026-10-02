# 场景契约与离线回放

`scenarios.json` 的 `visible_context` 是实验输入契约，并非真实会话记录。其 `required_units` 表示回答所需的最小已读来源集合；命中任一单元不等于联合证据充分。R21 的空集合表示当前已读边界内没有后果金标，N01 则要求不调用检索；两者含义不同。

本机离线回放示例：

```powershell
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -m retrieval_experiments.replay replay --query-source raw_user --strategy fts --output .runtime/retrieval-experiments/fts-raw.json
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -m retrieval_experiments.replay replay --query-source raw_user --strategy vector --output .runtime/retrieval-experiments/vector-raw.json
```

真实查询需先用独立、经审核的 JSONL 事件输入 `capture`。首版每例只采首次检索决策或首次 `search_story` 调用；后续重试另行分析，不静默挑最优查询。每行示意：

```json
{"case_id":"R14","origin":"agent_trace","trace_ref":"opaque-id","work_id":"wandering_earth","max_order":26,"tool_name":"search_story","arguments":{"query":"实际工具参数"}}
```

未检索的真实事件写 `"decision":"skip"`，并省略 `tool_name/arguments`。采集命令：

```powershell
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -m retrieval_experiments.replay capture --input .runtime/retrieval-experiments/selected-tool-events.jsonl --output .runtime/retrieval-experiments/agent-queries.jsonl
```

工具仅检查输入格式、来源标签与边界一致，不能独自证明事件来自真实 Agent。审核者需保证 `trace_ref` 可在隔离环境回溯到实际工具调用；不得用人工金标文本伪造输入。捕获输出被限制在未跟踪的 `.runtime/retrieval-experiments/`。
