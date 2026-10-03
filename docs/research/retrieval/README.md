# 场景契约与离线回放

## 当前入口：30业务任务与缓存漏损审计

当前契约是[business_tasks_v2_1.json](business_tasks_v2_1.json)，累计30任务／60表达／16事件组：23故事、4记忆、3不检索，全部仍待独立语义复核。新9故事任务18问未排名；缓存方法成绩仍只取既有14故事任务28问与29开发案例，阶段／记忆／skip单列。

[缓存审计与扩展报告](CACHE_AUDIT_AND_EXPANSION_2026_10_04.md)记录60组公平装包、索引来源反例、失败和资源成本；[经历材料](EXPERIENCE.md)给出可直接讲述的完整过程。RRF Top5词项互补18→20/28、旧开发26→27/27是待验证的正信号，相对Dense仍有两个坏例，不能作为上线收益。

无模型复现只读取既有缓存，输出必须换新名字；不运行下面历史CPU模型命令来复现本包：

```powershell
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -X utf8 -m retrieval_experiments.cache_audit --output .runtime/retrieval-experiments/cache-audit-local-new.json
```

既有最终审计产物绑定v2快照；v2.1只修订从未评分的H23-b，旧14故事／29开发问法、标签和分组不变。本机原文／排名缓存／账本／模型文件不随Git提交，缺失应明确补齐对应本地依赖，不伪造缓存。

严格Qwen队列已创建为`.runtime/retrieval-experiments/qwen-expanded-20261004.queue.json`，57问570对，新严格评分0；旧100对不满足完整模型SHA证明，不能追认。分析现有队列不加载模型：

```powershell
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -X utf8 -m retrieval_experiments.score_queue analyze --queue .runtime/retrieval-experiments/qwen-expanded-20261004.queue.json --output .runtime/retrieval-experiments/qwen-analysis-local-new.json
```

仅在本机从未准备该包、预算账本也不存在时，可用`score_queue prepare --output <新的隔离队列文件>`准备；prepare只做文件哈希，不给新队列新预算。已有队列及全局持久账本不得换名／清零以恢复耗尽预算。

重推理尚未执行。**只有WebUI验收资源窗口确实释放后**才可运行：`score_queue run --queue .runtime/retrieval-experiments/qwen-expanded-20261004.queue.json --batch-index 0 --resource-window-clear --output .runtime/retrieval-experiments/qwen-expanded-batch0-new.json`。后续batch-index为1～5，每包100对，最后70对；不是每包600尝试。全包共享600尝试／1200秒、单对20秒／RSS12GiB预算，CPU float32线程2，已有评分逐对验SHA再复用；失败／中断持久计数，未完成池不计通过或失败。阈值在单对结束检查，native forward可能使最后一对超阈，必须如实记录并停止。进程结束后释放模型，没有常驻worker或自动下载。

新9个Luna数据核验＋可选9个Sol问法模拟仅为未授权额度草案，不复用六场景剩余额度。六场景已经18/24次完成，此次材料授权确认不触发重跑。定向测试当前51项通过；程序约束不是理解正确性证明。

## 最新运行包

2026-10-04已完成[CPU扩展对照](CPU_ROUTES_2026_10_04.md)，源核验修订见[SOURCE_REVIEW_2026_10_04.json](SOURCE_REVIEW_2026_10_04.json)。新问题30、开发29、阶段26分别报告，14新故事任务标签仍provisional。Qwen真实CPU小批已评分100对，但不运行远程provider或最终回答。以下旧包说明按各自日期理解。

下一轮预登记、Sol／Luna 分工、与主进程的参数对齐及预算执行限制见 [NEXT_EXPERIMENT.md](NEXT_EXPERIMENT.md)；完整推进顺序见 [PLAN.md](PLAN.md)。

首批模型实验已完成：6 场景、18/24 次物理请求，5 条真实 Agent query、1 条真实无工具暂停。过程和逐例结果见 [MODEL_BATCH_2026_10_03.md](MODEL_BATCH_2026_10_03.md)，可讲述的探索经历见 [EXPERIENCE.md](EXPERIENCE.md)。模型原始材料及会话只存忽略的隔离目录。

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

## 六场景批次实现与本地复现

`model_batch.py` 的 generate／roleplay 阶段均要求显式 `--execute-authorized-batch`；只有与 run-root 绑定的材料授权、问题意图 SHA 和固定人格快照满足时才运行陪读。现有批次已经完成，授权不扩展到另一个 run-root 或新的材料范围；阅读本文不触发额外模型调用。执行器禁用重试／压缩／后台 LLM，在每次物理传输前持久计数。

`generated_replay.py --run-root ...` 只用本地 BGE 回放经审核的 Sol 问法，排除 N01 强制检索、单列 P01 暂定标签。`batch_analysis.py --run-root ...` 重导出原生回执，审计实际原文边界并回放五条真实 query；两者拒绝覆盖原有产物。`literary_review.py` 是另一次受计数限制的 P01 模型核验，已经完成，不当作 Agent query 或人类金标。

复用现有实际查询做无新增对话模型调用的稀疏回放（输出请换新文件名）：

```powershell
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -m retrieval_experiments.replay replay --query-source agent_query --trace .runtime/retrieval-experiments/isolated/sol-luna-20261003-01/agent-queries.jsonl --strategy jieba_or --case-id R14 --case-id R25 --case-id R26 --case-id R21 --candidate-k 10 --top-k 5 --output .runtime/retrieval-experiments/agent-jieba-local-rerun.json
```

将 strategy 改成 fts／fts_strict 可核对扫描与严格零命中的区别。正式排序分母为 3，R21 空集合只审边界；不要额外纳入 P01 的 provisional 集合。原始批次的账本／会话／原文及材料授权文件均留在忽略的隔离目录。

定向回归覆盖输入不含金标、审核 SHA 不可复用、持久预算与物理重发限制、隔离真实 AgentLoop 接线、候选／装包及暂定分母。测试 provider 是替身，不计真实模型结果：

```powershell
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -m pytest chatbot_tests/test_retrieval_experiments_replay.py chatbot_tests/test_retrieval_experiments_fusion.py chatbot_tests/test_retrieval_experiments_facets.py chatbot_tests/test_retrieval_experiments_model_batch.py chatbot_tests/test_retrieval_experiments_generated.py -q -p no:cacheprovider --basetemp .runtime/retrieval-experiments/tests-final-new
```

basetemp 每次使用新目录；模型运行无需作为回归测试重跑。

## 缓存内完整语境与证据选择（CPU）

预登记与结果见 [CACHED_CONTEXT_PACK_2026_10_03.md](CACHED_CONTEXT_PACK_2026_10_03.md)。脚本只读现有 Dense 排名、原文和实际 query 缓存；无 adapter 搜索、Embedding、对话模型、模型下载或 GPU。原话／人工改写／实际 query 分开出报告，P01 provisional、N01 skip；输出只含词项与 ID，不含故事原文。它不检验新 query 的 Dense 召回。

```powershell
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -m retrieval_experiments.cached_context_pack --batch-root .runtime/retrieval-experiments/isolated/sol-luna-20261003-01 --output .runtime/retrieval-experiments/cached-frame-pack-local-new.json
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -m pytest chatbot_tests/test_retrieval_experiments_cached.py -q -p no:cacheprovider --basetemp .runtime/retrieval-experiments/tests-cached-pack-local-new
```

使用新输出／测试目录。v1.1 修正误删阶段词的停词表，初跑仍在忽略目录保留；最终代码权重固定，不按金标调参。四种查询处理只在相同 Top10 内重排，三个 packer 固定每组 Top5、2400 估算 tokens、最多4单元。运行末检查真实模型账本未变，进程没有导入模型／GPU库。缓存初始化、原文分词和原始检索不计入报告的选择开销。

## 拟留出理解任务：契约核对，不运行新排名

当前新增任务、数据局限、四路协议和预算见[PROSPECTIVE_TASKS_2026_10_03.md](PROSPECTIVE_TASKS_2026_10_03.md)。版本契约和锁先于新检索固定；14个任务只达到原文证据候选状态，另1个缺读者记忆，尚无独立语义金标。任务问法不接收预期结论／必要单元，旧预测合成fixture与真实读者记忆分开。

以下命令只检查契约、既有缓存可用性、本地模型文件元数据及生产只读历史接口，不运行Dense／jieba检索或加载神经模型；手动名称和已知证据ID的可达性探查不是正式导航结果：

```powershell
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -X utf8 -m retrieval_experiments.holdout_contract --output .runtime/retrieval-experiments/prospective-preflight-local-new.json
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -X utf8 -m pytest chatbot_tests/test_retrieval_experiments_holdout.py -q -p no:cacheprovider --basetemp .runtime/retrieval-experiments/tests-holdout-local-new
```

每次用新输出路径。本机前置条件是同SHA的原文、原有开发金标、StoryMem只读结构数据、既有Dense缓存／批次审计与18请求账本；忽略运行材料不会随Git复制，缺失时应明确准备对应本地fixture，不伪造缓存。模型文件缺失会记录可用性，不自动下载；文件存在也不证明加载和CPU性能。当前33项定向回归涵盖本包与既有实验，真实新评分为0。


## 完全离线CPU扩展复现

先固定v1.1契约与版本锁，阅读CPU报告中的小批、成本停止和标签限制。依赖／权重都必须在本机，缺失不自动安装下载；不修改正式服务设备设置。每阶段输出必须用新名字，输入为同源、同契约的完成文件：

```powershell
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -X utf8 -m retrieval_experiments.cpu_routes dense --output .runtime/retrieval-experiments/cpu-dense-local-new.json
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -X utf8 -m retrieval_experiments.cpu_routes routes --input .runtime/retrieval-experiments/cpu-dense-local-new.json --output .runtime/retrieval-experiments/cpu-routes-local-new.json
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -X utf8 -m retrieval_experiments.cpu_routes reranker --input .runtime/retrieval-experiments/cpu-routes-local-new.json --output .runtime/retrieval-experiments/cpu-reranker-local-new.json
D:/Void/Tools/conda/envs/storypal-chatbot/python.exe -X utf8 -m pytest chatbot_tests/test_retrieval_experiments_cpu.py -q -p no:cacheprovider --basetemp .runtime/retrieval-experiments/tests-cpu-local-new
```

Dense显式CPU、local_files_only、小batch2和4线程；Qwen显式CPU/float32、batch1，无CUDA初始化。两模型分进程执行；reranker只能重排固定Dense Top10，不支持自己补候选。Qwen失败／成本停止保存已完成结果并标未完成，不能给缺分造值。报告含来源ID／查询SHA／向量缓存／相关分数，未包含原文或真实聊天。旧账本检查只约束算法线原批次，不代表应用线没有其自身授权调用。
