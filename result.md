# StoryPal 实验结果与面试数据卡

> 仅记录已经实际运行的结果。计划、推测和未完成实验不写成事实。
> 最后更新：2026-09-23（Asia/Shanghai）

## 1. 实验目标

验证面向长篇叙事陪读的检索是否能在**不越过阅读进度**的前提下，处理真实中文问句；并比较稀疏检索、稠密检索和 Hybrid RRF 的质量/延迟权衡。

## 2. 固定实验条件

| 项目 | 取值 |
| --- | --- |
| 作品与语料 | 《流浪地球》108 个结构化 StoryUnit |
| 稠密检索 | 本地 `BAAI/bge-m3`，1024 维、归一化、LanceDB cosine |
| 稀疏检索 | SQLite FTS5 / BM25，`unicode61` 索引；query 清洗后使用中文二元词 OR |
| 金标 | 29 条中文首次阅读场景；27 条含 gold evidence，2 条为纯防剧透负例 |
| 安全约束 | 每路检索均带 `max_order = max_seen_order`；结果侧再次核验 order |
| Hybrid | FTS Top10 + Vector Top10，按 `unit_id` 去重，RRF `k=60`；仅离线实验 |

### 两种查询口径

- **`raw_user`（主指标）**：直接使用用户原话，反映未经答案词扩写的检索下限。
- **`gold_rewrite`（上限对照）**：使用人工消歧后的检索词，评估检索器在理想 query 下的上限；不作为对外主结果。

## 3. 主结果：原始用户问句（raw_user）

| 策略 | Hit@1 | Hit@3 | Hit@5 | MRR | nDCG@5 | P50 / P95 | 最大单次耗时 | 剧透违规 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FTS5 / BM25 | 48.1% | 66.7% | 74.1% | 0.586 | 0.611 | 10.4 / 11.7ms | 57.9ms | 0 |
| BGE-M3 Vector | 81.5% | 100% | 100% | 0.895 | 0.919 | 57.7 / 108.8ms | 15.28s | 0 |
| Hybrid RRF | 66.7% | 92.6% | 96.3% | 0.787 | 0.828 | 71.0 / 123.1ms | 15.67s | 0 |

说明：向量/Hybrid 的约 15 秒最大值来自本次进程首次加载本地 embedding 模型；P50/P95 描述后续请求的稳定区间，不能替代首次响应耗时。

## 4. 人工改写上限对照（gold_rewrite）

| 策略 | Hit@1 | Hit@3 | Hit@5 | MRR | nDCG@5 | P50 / P95 | 剧透违规 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FTS5 / BM25 | 66.7% | 77.8% | 77.8% | 0.722 | 0.708 | 10.6 / 12.6ms | 0 |
| BGE-M3 Vector | 92.6% | 100% | 100% | 0.963 | 0.968 | 56.5 / 103.1ms | 0 |
| Hybrid RRF | 77.8% | 96.3% | 100% | 0.861 | 0.897 | 72.3 / 118.8ms | 0 |

## 5. 已证实的结论与决策

1. **BGE-M3 是当前最优线上检索主路。** 在原始中文问句上仍达到 100% Hit@3，且排序指标显著领先 FTS。
2. **`gold_rewrite` 会高估稀疏检索。** FTS 的 Hit@3 从 raw-user 的 66.7% 提升到 77.8%，因此只能作为理想消歧上限，不能冒充真实用户体验。
3. **Hybrid RRF 是一次有效的负向消融。** 在两种口径下均低于纯 Vector，且增加约 13～16ms 的稳定查询延迟；保留实验与代码用于解释“为什么没有上线”，不接入 `auto`。
4. **防剧透边界有效。** 全部四组实验均为 0 违规；R21（阅读到 order 56）与 R29（阅读到 order 57）构成仅差一个单元的边界对照。
5. **当前不急于替换 FTS5。** 稀疏检索仍是 vector 不可用时的安全降级；是否引入 jieba 或新 BM25 实现须由按类别坏例和消融验证决定。

## 6. 当前局限与下一步实验

- 单作品、29 条用例，不能推断到所有中文长篇小说；需要后续多作品扩展。
- `raw_user` 没有模拟 Luna 在真实 Agent loop 中的上下文消歧与 query 改写；它是保守下限，而非完整端到端 Agent 成绩。
- P95 不能代表首次模型加载，应单独报告冷启动/预热策略。
- 尚未测试 cross-encoder reranker；它只能改排序，不能弥补候选池未召回的 gold evidence。
- 下一阶段先实现 ContextPacker，确保检索结果进入模型前有 token budget、去重、drop reason 与 provenance。

## 7. 可用于面试的 30 秒表述

> 我先把防剧透作为检索层硬约束，用 29 条中文首次阅读金标评估 Dense、Sparse 和融合策略。BGE-M3 在原始问句上达到 100% Hit@3、MRR 0.895；RRF 融合反而把 MRR 降到 0.787 且增加延迟，所以我没有为了堆技术栈上线它，而是保留为负向消融。后续我把重点转到可解释 ContextPacker 和跨会话记忆，保证检索结果真正能安全进入 Agent 上下文。

## 8. 中文分词与 query 链路核验

### 当前链路

```text
用户原话 / Agent 生成的消歧 query
├─ FTS5：去标点与空白 → 逐字停用字过滤 → 去重中文二元词 → OR MATCH → BM25
└─ Vector：原 query → BGE-M3 embedding → 向量归一化 → LanceDB cosine
```

- FTS5 索引为 `unicode61`，连续中文会按单字切分；为避免长句被过强的 AND 条件卡死，当前实现使用二元词 OR 来提高召回。
- 这一方案的代价是：逐字删停用字可能把原本不相邻的字拼接成二元词，多个 OR 项也容易扩大常见词组的噪声。
- Chatbot 不存在独立 Query Analyzer。Agent 根据对话自行构造 `search_story(query)` 的 query，工具原样转交给检索层。`gold_rewrite` 是人工写的理想查询，不是线上工具调用日志。

### 当前判断与验证设计

现有结果只能说明**当前二元词 FTS 排序弱于 BGE-M3，且 RRF 会把该弱排序带入融合**；不能证明“分词就是唯一根因”。因此暂不直接替换 FTS5 或引入 BM25 库。

下一轮稀疏检索消融应在同一批 `raw_user` 金标上比较：现有二元词 OR、jieba 词项 OR、jieba 词项 AND/短语组合；索引端和查询端采用同一分词器。指标包括 Recall@K、MRR、nDCG@5、零结果率、P50/P95，以及实体名、因果问句、短问句、否定/时序问题四类坏例。只有稀疏路稳定改善后，才重新验证 Hybrid 是否受益。
## 9. 复跑入口

```powershell
# 主口径：原始用户问句
D:\Void\Tools\conda\envs\storypal-chatbot\python.exe chatbot_tests\evaluate_story_retrieval.py --query-source raw_user --output tmp\stage-a-raw-user.json

# Hybrid 离线对照
D:\Void\Tools\conda\envs\storypal-chatbot\python.exe chatbot_tests\evaluate_story_retrieval.py --retrieval hybrid_rrf --query-source raw_user --candidate-k 10 --rrf-k 60 --output tmp\stage-b-hybrid-raw-user.json
```
## 10. Context 与 HistoryMemory 实施核验

- `ContextPacker` 已固定为最多 3 条主证据、2400 个字符估算 token、最多 1 条同章直接相邻的低优先级补充；同时输出 selected、dropped reason 与 token estimate。相关 Context/StoryMemory 定向回归为 **11/11 通过**。
- HistoryMemory v0 使用 StoryPal 自有 SQLite FTS5，不与 StoryMemory 的 LanceDB 混用。`search_memory` / `write_memory` 已纳入运行时显式白名单；当前只支持用户明确确认的 prediction、reflection、preference、conclusion，不自动抽取聊天或工具调用。
- HistoryMemory 的工具、配置和安全隔离定向回归为 **22/22 通过**，运行时插件发现与 Agent Loop allowlist 回归为 **2/2 通过**。覆盖跨会话找回、同用户/同作品/已读边界过滤、幂等重试、删除与失败防污染。
- 这些是功能/契约核验，不应误写为真实读者满意度或端到端模型质量成绩。当前 2400 token 是估算值，自动 episode 沉淀、跨作品回忆和保留策略仍待产品决策。

## 11. 阅读进度、手账与 Note.md 功能回归（2026-09-23）

- 定向测试：`test_interaction_note.py`、`test_tools.py`、`test_story_memory.py`、`test_bootstrap.py`、`test_nanobot_tool_allowlist.py`、`test_plugin_loading.py`，**30/30 通过**，耗时 4.20 秒。使用项目内独立 pytest 临时目录，未进行全量 Chatbot 回归。
- 覆盖：用户级阅读边界迁移/隔离、跨回合进度确认、未确认锚点预测、手账回看、旧 JSON Notes 迁移、Note.md 去重/跨会话注入/用户隔离/删除、本轮用户原话来源校验、模型实际可见工具白名单。
- Gateway `/health` 与 WebUI 首页 HTTP 均为 **200**。这只说明服务和页面可达，**不代表真实 Luna 对话与读者体验通过**。真实体验待用户核验；自动 Note 整理、按日情景记忆及语义回忆尚无结果。

## 12. 压缩后自动 Note 试作（2026-09-23）

- 定向回归：`test_note_consolidation.py`、`test_interaction_note.py`、`test_tools.py`、`test_story_memory.py`、`test_bootstrap.py`、`test_nanobot_tool_allowlist.py`、`test_plugin_loading.py`，**34/34 通过**，耗时 5.82 秒。覆盖归档水位、owner 绑定、工具输出排除、非 WebUI 排除、临时项拒绝、开放观察弱标签、单次 Note 注入及原有业务工具。
- 隔离目录的本地 **GPT-5.6 Luna** 三条合成样本：明确的聊天偏好写入 1 条；剧情猜测和明确标为引用的工具输出各 1 条，均未写入。输出的 Note 保留了“聊小说时，先接住感受，再给原文证据”的范围和顺序。这是冒烟测试，不能推算误写率或漏写率。
- **GPT-6 Luna** 仅对给定的三条样本和结果做独立判读，认为准入合理；其只读工具启动失败，未审阅源码。提出后续难例：引用/粘贴内容误认、单次状态泛化、改写丢失适用范围与先后顺序。
- 隔离的合成会话又完成一次**真实链路验收**：nanobot 的闲置压缩成功归档 2 条消息；StoryPal 后台抽取写入 1 条 Note（`written=1,rejected=0`）；随后一次运行时上下文读取确实包含该条笔记。模型把“先回应我的感受，再引用原文来分析”规范为“先回应用户的感受，再引用原文进行分析”，保留了作品范围和先后顺序。首次按用户原句精确匹配显示 false，按实际笔记内容复核为 true，属于断言过严，不是注入失败。
- 这仍是隔离目录的合成会话，不是用户在正式 WebUI 的自然对话；成规模中文正反例评测也未完成。不得把 34 项回归或这次链路验收写成真实用户体验成绩。
