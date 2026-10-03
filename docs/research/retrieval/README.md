# 场景契约与离线回放

下一轮预登记、Sol／Luna 分工、与主进程的参数对齐及预算执行限制见 [NEXT_EXPERIMENT.md](NEXT_EXPERIMENT.md)；完整推进顺序见 [PLAN.md](PLAN.md)。

`scenarios.json` 的 `visible_context` 是实验输入契约，并非真实会话记录。其 `required_units` 表示回答所需的最小已读来源集合；命中任一单元不等于联合证据充分。R21 的空集合表示当前已读边界内没有后果金标，N01 则要求不调用检索；两者含义不同。

本机离线回放示例：

```powershell
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -m retrieval_experiments.replay replay --query-source raw_user --strategy fts --output .runtime/retrieval-experiments/fts-raw.json
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -m retrieval_experiments.replay replay --query-source raw_user --strategy vector --output .runtime/retrieval-experiments/vector-raw.json
```

jieba 单因素对照仅写隔离索引。首次准备依赖：

```powershell
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -m pip install --disable-pip-version-check --no-input --target .runtime/retrieval-experiments/vendor jieba==0.42.1
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -m retrieval_experiments.replay replay --query-source raw_user --strategy jieba_or --output .runtime/retrieval-experiments/jieba-or.json
```

将 `jieba_or` 改为 `jieba_and`、`jieba_phrase` 即可在同一隔离索引上对照。严格现有 FTS5 可用 `fts_strict`；`fts` 是含 Python 扫描回退的实际 StoryMem 路径。结果只存编号、来源哈希、查询哈希及耗时，不存故事文本。

既有 29 例的复跑使用 `--case-set goldens29 --candidate-k 10 --top-k 5`。逐个替换 `--strategy` 为 `fts`、`fts_strict`、`jieba_or`、`jieba_and`、`jieba_phrase`、`vector`、`rrf`；逐个替换 `--query-source` 为 `raw_user` 与 `gold_rewrite`。例如：

```powershell
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -m retrieval_experiments.replay replay --case-set goldens29 --query-source raw_user --strategy jieba_or --candidate-k 10 --top-k 5 --output .runtime/retrieval-experiments/29-raw-jieba_or.json
```

各策略都最多向指标层交付 10 条候选，再取前 5 条输出；RRF 先从每路各取 10 条，算力成本不与单路相同。完整 29 例只复用既有金标，未附加首批 P01/N01 的探索标注。采集真实查询时可给 `capture` 指定相同的 `--case-set`。

固定真 Sparse 融合直接复用上面的两个源报告，不重新加载模型：

```powershell
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -m retrieval_experiments.fusion_replay --query-source raw_user --dense-report .runtime/retrieval-experiments/29-raw-vector.json --sparse-report .runtime/retrieval-experiments/29-raw-jieba_or.json --output .runtime/retrieval-experiments/29-raw-fixed-fusion.json
```

人工改写对照将 `raw_user` 改成 `gold_rewrite`，三个文件名中的 `29-raw-` 改成 `29-gold-`。脚本只运行四组预置配置，严格核对源哈希、查询哈希、边界和候选预算，并在本机内存调用应用原有 `ContextPacker`。输出只含单元 ID、来源排名、装包结果及计时；不写原文。融合计时是缓存回放开销，不代表双路实际服务延迟。

自动分句与同候选首位保留消融（本地 BGE，不调用 Sol／Luna）：

```powershell
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -m retrieval_experiments.facet_replay --output .runtime/retrieval-experiments/29-raw-clauses-v1.json
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -m pytest chatbot_tests/test_retrieval_experiments_facets.py -q -p no:cacheprovider
```

输出路径必须是隔离目录中的新文件；重跑换一个文件名。三组固定配置的拆分规则、候选槽位和成本差异均见预登记文档。其 query 来源为 `algorithmic_raw_user`，不记作真实 `agent_query`。

真实查询需先用独立、经审核的 JSONL 事件输入 `capture`。首版每例只采首次检索决策或首次 `search_story` 调用；后续重试另行分析，不静默挑最优查询。每行示意：

```json
{"case_id":"R14","origin":"agent_trace","trace_ref":"opaque-id","work_id":"wandering_earth","max_order":26,"tool_name":"search_story","arguments":{"query":"实际工具参数"}}
```

未检索的真实事件写 `"decision":"skip"`，并省略 `tool_name/arguments`。采集命令：

```powershell
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -m retrieval_experiments.replay capture --input .runtime/retrieval-experiments/selected-tool-events.jsonl --output .runtime/retrieval-experiments/agent-queries.jsonl
```

工具仅检查输入格式、来源标签与边界一致，不能独自证明事件来自真实 Agent。审核者需保证 `trace_ref` 可在隔离环境回溯到实际工具调用；不得用人工金标文本伪造输入。捕获输出被限制在未跟踪的 `.runtime/retrieval-experiments/`。
