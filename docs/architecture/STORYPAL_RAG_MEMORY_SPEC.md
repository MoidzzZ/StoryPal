# StoryPal RAG 与 Memory 强化规格（v1）

**状态：** 阶段 A～C 已实施；HistoryMemory v0 已完成技术验证但不作为最终产品边界。当前交付顺序以 [下一阶段交付](STORYPAL_NEXT_DELIVERY.md) 为准。
**更新日期：** 2026-09-23
**交付窗口：** 18 个有效开发小时
**适用范围：** `chatbot/` 的 StoryPal 集成层及其与 `story_mem/` 的只读适配；不改写 StoryMemory 的事实数据或抽取管线。

## 0. 当前执行口径（2026-09-23）

本规格保留完整的历史设计与已核验基线；实现顺序和首版范围以 [下一阶段交付](STORYPAL_NEXT_DELIVERY.md) 为准。旧章节中的最多 2 条、时间过滤、MMR、独立 MemoryNeedGate、多轮改写、复杂工具动态路由等均不是首版验收要求。跨会话情景回忆只使用 owner 硬隔离、一次语义检索、单一相似度阈值和独立 token 预算；条数由预算决定。阈值先通过少量中文正例和难负例校准，未校准前不得宣称有效。先完成阅读进度、Note、阅读手账和按日互动经历的可体验闭环，再做 LanceDB 索引、Embedding、Reranker 和进阶 RAG 的受控实验。早期 18 小时窗口是历史开发目标，不代表后续研究阶段的工期承诺。
## 1. 目标与边界

本轮目标不是扩展更多 Agent 外壳能力，而是将现有陪读原型补强为可复现实验闭环：

```text
结构化 StoryUnit → 检索候选 → ContextPacker → Agent 工具调用 → 已读范围回答
                         ↑                         ↓
                    离线评测                  Trace / task-end distill
                                                   ↓
                                 按日 Episode（Checkpoint 跨会话兜底）
```

完成后应能说明并复跑：基线效果、检索优化的收益与代价、上下文为何被选中，以及用户长期阅读记忆如何与故事事实隔离。

### 1.1 非目标

- 不迁移 Milvus，不在 108 个 StoryUnit 上包装 ANN 优化。
- 不重构为微服务、K8s 或多 Agent，不迁移 nanobot 到 Pi Agent；Pi 仅可作为后续独立 spike。
- 不把 `auto` fallback 描述为 Hybrid。
- 不让 Dream、Note、阅读手账或任何用户记忆保存未读情节、原始工具失败信息或未经核验的故事事实。
- 不在本轮将 FTS5 中文二元词策略直接替换为 jieba；是否引入分词只由失败归因实验决定。

## 2. 已核验基线（实施前事实）

| 层 | 已有能力 | 尚缺能力 |
| --- | --- | --- |
| 语料与稠密检索 | 《流浪地球》108 个结构化 StoryUnit；本地 `BAAI/bge-m3`、1024 维、归一化向量与 LanceDB cosine 检索 | Hybrid 融合、rerank 实验与统一诊断 |
| 稀疏检索 | SQLite FTS5 / BM25；中文查询用二元词 OR 查询 | 更细的中文失败分类；是否需要 jieba 尚未验证 |
| 当前 `auto` | vector 不可用或陈旧时依次 fallback 到 FTS、scan | 它不是 Dense + Sparse 融合 |
| 安全与证据 | `max_seen_order` 查询过滤与线上二次校验；Evidence 含 unit、顺序、原文、摘要、章节、行号等 provenance | Context 选择理由、token 预算与 drop 诊断尚未独立化 |
| 上下文 | `ContextPacker`：最多 3 条主证据 + 1 条低优先级相邻补充、预算与 diagnostics | provider 精确 token 校准、渐进式单元的近重复压缩 |
| 会话与显式记忆 | SessionState、nanobot 原始会话/滚动 checkpoint、Notes、ReadingNotebook、SQLite FTS5 HistoryMemory v0 | 自动 episode distill、删除/保留策略的产品决策 |
| 评测 | 24 条中文对话式金标；已记录 Hit@K、单 case 耗时与剧透违规 | MRR、nDCG@5、P50/P95、分组统计、失败分类与消融报告 |

当前 22 条可判定金标上的已知基线：FTS5/BM25 Hit@1/3/5 为 59.1% / 72.7% / 77.3%，BGE-M3 Vector 为 86.4% / 95.5% / 100%，两者均为 0 次剧透违规。该数字是本轮实验的对照，不应被未来结果覆盖。

## 3. 不可违反的系统约束

1. **防剧透是数据层硬约束。** 每条候选、扩展邻居、记忆证据均须满足 `order <= max_seen_order`；模型提示词不能替代过滤。
2. **来源隔离。** StoryMemory 只存作品事实；`Note.md` 暂存非剧情交互约定、偏好、认知纠正和开放观察；阅读手账只存当前作品的反应、问题和预测；`SOUL.md` / `USER.md` 只接收 Dream 整理后的稳定内容。
3. **原始 Trace 不等于长期记忆。** 工具参数、返回、重试和失败保留给审计/重放，不默认注入上下文，也不自动写入 Note、阅读手账或 Dream 结果。
4. **所有优化必须可回退。** 新检索模式通过显式配置选择；`auto` 的原有 fallback 语义保持不变。
5. **中文优先。** 金标、失败标签、测试说明和面向用户的错误信息均使用中文。

### 3.1 2026-09-21 架构收敛决策

1. **nanobot 保持主 Agent Loop。** StoryPal 不重复实现模型调用、structured tool calling、会话锁、checkpoint 和 WebUI；只补产品状态、策略、记忆、剧情检索与必要工作流。
2. **取消独立 ProfileStore。** `Note.md` 是 Agent 自维护、每轮全量注入的热认知工作区：既保存当前有效的约定、纠正、偏好和共同结论，也容纳待验证的开放观察；Dream 只把已稳定内容进一步整理进 `SOUL.md` / `USER.md`。Note 顶层维度保持稳定，但允许在“开放观察”下创建自由主题；开放观察只能作为弱提示，不能当作已确认事实。
3. **HistoryMemory v0 降为技术原型。** 已实现的 SQLite/FTS5、隔离和幂等能力保留为可复用代码与实验记录，但最终用户记忆收敛为 Note、阅读手账和按日情景记忆，不继续暴露通用 `write_memory` / `search_memory` 产品概念。
4. **工具按副作用拆分。** 不用一个 `action` 同时承载查询、确认和写入；查询策略可继续使用 `focus` / `detail` 等枚举。目标模型可见工具为 `resolve_reading_location`、`set_reading_progress`、`search_story`、`get_story_context`、`search_reading_journal`、`save_journal_entry`、`update_journal_entry`、`delete_journal_entry`、`record_interaction_note`、`forget_interaction_note`、`recall_interaction_history`。其中回忆工具首版只做一次受阈值约束的检索；多轮改写、扩大候选和迭代搜索仍后置。
5. **首版使用对话式确认。** 需要确认的操作先写入会话级 `PendingAction`，下一轮仅在同一用户、同一会话给出明确确认后执行；WebUI 确认卡片、可信点击事件和刷新恢复列为体验增强 TODO，不阻塞核心功能。
6. **工作流边界。** 第一批同步工作流只有“更新阅读进度”和“记录阅读手账”；旧预测在阅读进度增加后异步检查，不作为阻塞当前对话的同步工作流。
7. **Skill 边界。** 首版只新增“首次阅读陪伴”和“剧情事实核验”两个 Skill；阅读手账由陪伴 Skill 的识别规则、手账工具和确认工作流共同实现，不再重复建立同名 Skill。
8. **Note 独立维护。** 增加异步 Note Curator，在压缩边界、Note 超过长度阈值、重复主题累积或 Dream 运行前触发；它只负责去重、合并、降级过期观察和创建开放主题，不得把内容提升进 `SOUL.md` / `USER.md`，也不得修改故事记忆。
9. **Note 是热认知视图。** `Note.md` 不只是等待 Dream 的暂存区；当前有效的行为约束、认知纠正、偏好、共同目标/约定/结论，以及尚未稳定但可能有价值的开放观察，都应在 Note 中以 Markdown 维护并每轮全量注入。相同内容后续可以被 Dream 深化到其他层，但必须保留来源与新旧状态，发生冲突时以用户当轮表达和 Note 中较新的明确修正为准。
10. **情景记忆与 Checkpoint 同源。** 普通消息平时留在活动 context；当 nanobot 因 token 压力或空闲触发压缩时，对即将归档的稳定消息区间同时生成 continuation checkpoint 和重要 episode，后者写入 `memory/YYYY-MM-DD.md`。本阶段不使用 `MEMORY.md`，只把它登记为未来的多级汇总 TODO。
11. **不建立独立 ToolMemory。** 工具调用的原始参数、返回、重试与失败只属于 trace/checkpoint，用于恢复、审计和调试；工具写成的阅读进度、Note、手账属于各自权威状态；只有对用户关系、共同任务或后续行为产生持续影响的工具结果，才抽取为带来源引用的 episode。剧情检索结果不得仅因被工具返回就进入长期记忆。

### 3.2 情景记忆与工具结果准入

一次工具调用只能产生以下一种或多种明确效果，不能笼统标记为“写入工具记忆”：

| `memory_effect` | 去向 | 典型例子 |
| --- | --- | --- |
| `trace_only` | 会话 JSONL / checkpoint，按保留期清理 | 剧情检索候选、工具参数、失败、重试 |
| `state_change` | 对应权威状态库 | 更新阅读进度、创建 PendingAction |
| `note_write` | `Note.md` | 用户确认的交互约定、认知修正、当前共同目标 |
| `journal_write` | 当前作品阅读手账 | 感受、问题、预测及后续校验结果 |
| `episode_candidate` | 经准入判断后写入 `memory/YYYY-MM-DD.md` | 一次讨论形成持续有效的共同结论；一次状态变化改变了后续陪读方式 |

情景条目至少记录：发生时间、抽取时间、会话与来源消息引用、触发场景、发生了什么及其未来影响；不复制原始工具输出。只有满足“未来可能复用、不是权威状态的重复副本、来源可信、无未读剧情、时间与 provenance 完整”时才准入。冲突、替代和有效期判断不属于首版准入职责。

### 3.3 Checkpoint 联动、语义索引与时间元数据

#### 生命周期与写入

1. **热上下文阶段：** 未被压缩的原始对话继续由 session context 使用；`Note.md` 仍每轮注入。普通对话不额外执行情景抽取，避免每轮增加模型调用。
2. **逐次 Trace / 运行时 checkpoint：** nanobot 原有会话 JSONL 记录消息与工具事件；运行时 checkpoint 在 `awaiting_tools`、`tools_completed`、最终响应和错误等阶段更新，用于中断恢复。它们可以频繁写入，但都不触发情景抽取，也不等于长期语义记忆。
3. **压缩 checkpoint / 统一记忆抽取：** token consolidation 和 idle auto-compact 都会捕获 `[last_archived, archive_end)` 的稳定消息区间并生成 continuation summary。StoryPal 只在这个压缩边界运行一次 Memory Extractor，同时产出 `note_ops` 与 `episodes`；二者共享对原始消息、summary 和来源引用的理解，但分别经过 Note 与情景记忆准入规则。
4. **互相补全：** checkpoint summary 只负责当前会话继续执行所需的目标、状态、结果、阻塞和下一步；按日 episode 负责跨会话找回经历、认识变化与重要互动。两者来自同一消息区间，但服务不同用途。
5. **可靠提交：** episode 使用 `owner + session_key + archive_start + archive_end + source_refs` 生成稳定 ID。抽取失败不得阻塞必要的上下文压缩，而是保存待重试游标；再次处理同一区间必须幂等。
6. **显式写入例外：** 用户明确要求记录的 Note、阅读手账和权威状态立即进入对应同步流程，不等待压缩；其中 Note 仍必须经过统一 Note Extractor，再应用结构化 `note_ops`，不能由 Agent 直接拼接 Markdown。后续 episode 只引用这次变化，不复制一份权威状态。

首版通过 nanobot consolidation hook 接入，不改写普通 Agent Loop。独立的 StoryPal Memory Extractor 消费已捕获消息区间和 checkpoint summary，一次结构化输出 `note_ops[]` 与 `episodes[]`，避免改变 nanobot continuation summary 的格式与恢复语义。显式与自动 Note 写入共享同一 Note Extractor：显式路径由 `record_interaction_note` 同步调用，自动路径在压缩边界批量调用；二者只在授权来源、触发时机和是否阻塞当前回复上不同。阅读手账仍是独立权威状态，用户明确要求时直接走手账写工具。

#### 本阶段不使用 `MEMORY.md`

- 不创建、不注入、不索引 `MEMORY.md`，现有设计只保留为未来 TODO。
- `memory/YYYY-MM-DD.md` 是当前唯一的情景记忆 Markdown 事实源，也是旧消息退出活动上下文后的 checkpoint 跨会话兜底。
- 等每日文件数量和真实回忆任务证明需要多级汇总时，再评估周/月节点或 TiMem 式层级；不得提前把复杂汇总流程作为已实现能力。

#### 语义索引

关键词检索不作为情景记忆的主召回。Markdown 仍是可审阅事实源，派生索引使用单独的 LanceDB 表 `episodic_memory` 和本地官方 `BAAI/bge-m3`：

- 每个 episode 生成一个 1024 维归一化向量，`embedding_text` 由场景、事件、变化、未来影响和实体组成，不嵌入原始工具输出。
- 表中同时保存 `episode_id`、owner、scope、`occurred_at`、`recorded_at`、来源引用、文件路径、内容哈希和 embedding 版本；owner/scope/时间范围先过滤，再做 cosine TopK。
- 文件成功写入后按 `episode_id` upsert；启动时以内容哈希增量补索引，LanceDB 可从 Markdown 全量重建。
- 精确 ID、日期和 scope 使用元数据过滤；FTS5 仅保留为可选诊断/降级，不参与首版主召回。后续用真实改写问题评估 Recall@K、时间过滤正确率与跨用户隔离。

模型只看到一个只读工具 `recall_interaction_history(query, time_hint?, scope?, intent?)`：查询经 BGE-M3 编码后检索 episode，只把达到 `T_auto` 的最多 2 条返回给 Agent，并附内容、发生时间、记录时间和 provenance。候选池大小和阈值由系统配置，不能由模型覆盖。

#### 时间与可追溯性

首版不承担通用的信息冲突消解，只保证每条 episode 至少包含：

- `occurred_at`：事件实际发生时间；
- `recorded_at`：系统抽取和写入时间；
- `owner_id`、`session_key`、`scope`；
- `source_message_refs`（session key + message index/range），以及确有必要时的 `source_tool_call_ids`；
- `extractor_version`、`content_hash` 和原始 Markdown 路径。

后来写入的条目可以描述更早发生的事情，因此检索结果不得把 `recorded_at` 当作事实发生顺序。是否矛盾、是否替代以及当前应采信哪条，留到后续基于真实案例设计；当前只要求返回时间和来源，让上层 Agent 有证据判断或向用户澄清。

### 3.4 交互延迟、连续插话与检索编排

`Note.md` 的当前完整内容无条件注入每轮上下文，不再先调用读取工具。Note 内允许“临时上下文”区，条目用 Markdown 标注来源、创建时间、适用 scope 和失效条件。每轮注入前只运行无模型的失效条件检查；阅读进度变化后再检查与章节/位置绑定的临时项。语义不明确的过期判断不自动删除，而是在压缩边界、Note 超过长度阈值、重复主题再次出现或 Dream 前交给 Note Curator，必要时降级为开放观察。开放观察不在每轮执行 LLM 复核；它在同主题再次出现、下一次压缩、Note 达阈值或 Dream 前合并、增强、降级或归档，未经用户确认或充分重复证据不得升级为硬约束。显式 Note 由统一 Note Extractor 同步抽取和原子应用；自动 Note 在压缩边界使用同一抽取器后台处理。阅读手账和阅读进度仍在回复确认前同步原子写。

nanobot 已支持同一会话的 mid-turn injection：生成中的新消息先进入 pending queue，在工具执行后、一次模型响应结束后或错误边界注入下一轮；`/stop` 才会取消当前任务、子任务和 exec。StoryPal 保留该安全边界语义，不把它宣传为 token 级即时抢占。

检索采用按意图选源和两阶段取证，不对所有数据源每轮全查：

| 需求 | 首选数据源 | 默认动作 |
| --- | --- | --- |
| 当前约定、偏好、纠正 | 热 context + `Note.md` / `USER.md` | 不调用检索工具 |
| 剧情事实、人物、设定 | StoryMemory | `search_story`，先取 compact evidence |
| 已命中单元的原文或邻接细节 | StoryMemory | 必要时再 `get_story_context` |
| 当前作品的感受、问题、预测 | 阅读手账 | `search_reading_journal` |
| 跨会话互动经历 | 按日情景记忆 | 主 Agent 按需调用一次 `recall_interaction_history`；只返回达到 `T_auto` 的最多 2 条 |
| 当前阅读位置 | ReadingState | 直接读取权威状态，不做语义检索 |

普通问题只走一路，按日情景记忆不再无条件自动检索。首版不建立独立分类器式 MemoryNeedGate：主 Agent 在第一次模型调用中同时看到 recent context、完整 Note 和只读 `recall_interaction_history` 工具；不调用该工具即表示当前上下文足够，调用则表示需要跨会话情景记忆。工具参数中的 `query`、`time_hint`、`scope` 与 `intent` 同时承担 Query Rewrite，不再增加独立的改写模型调用。系统自动附加原始用户消息并把工具选择、改写参数、候选和最终采用证据写入 trace。

首版只保留一个候选返回阈值 `T_auto`：回忆工具检索到的候选达到阈值时最多向 Agent 返回 2 条，低于阈值的候选全部丢弃，不暴露弱相关提示，也不触发第二轮搜索。`T_auto` 通过中文真实对话评测集校准，至少包含需要回忆、无需回忆、Note 已足够、仅需剧情检索、表面相似但实际无关和时间范围回忆六类；同时报告工具选择召回率/精确率、有效记忆返回率、错误干扰率、TopK Recall/nDCG、回答增益、平均上下文 token 与 P50/P95。选型以返回精确率优先，并保留原始用户消息与 Agent 改写 query 的消融对照。

首版中，用户明确追问过去经历时由主 Agent 选择 `recall_interaction_history`；低于 `T_auto` 时工具只返回结构化 `no_reliable_memory`，Agent 应说明暂未找到可靠记录，不得看到或引用弱相关候选。这里是单次工具检索，不等同于完整 agentic search；扩大 TopK、根据 Observation 再次改写、迭代搜索与复杂时间过滤仍后置。确属“剧情事实 + 我过去怎么想”的混合问题时，才同时读取 StoryMemory 与手账/情景记忆。不同来源的分数不直接比较或做 RRF，而是各自 TopK 后由统一 ContextPacker 按意图分配预算、去重并保留 provenance。

本地优化包括：BGE-M3 模型进程内共享、query embedding LRU、以 query/owner/work/阅读边界/索引版本组成缓存键、先返回短证据再按需取原文。首版不引入 Redis；以工具选择准确率、每轮工具数、P50/P95、无效检索率和最终回答证据充分性共同验收。
#### MemoryNeedGate 与主 Agent 工具选择合并

首版不训练独立分类器，也不要求或保存模型的自由文本 Chain-of-Thought。MemoryNeedGate 被实现为主 Agent 的结构化工具选择结果：`recall_interaction_history` 未被调用表示“不需要”；被调用表示“需要”，而工具参数就是可审计的最小决策产物。建议参数为 `query`、`time_hint`、`scope`、`intent`，原始用户消息、owner、active work 和权限边界由运行时自动补充，不能交给模型伪造。

Jev 保留为以后与主 Agent 工具选择做离线对照的 Router/Gate 后端，不进入首版关键路径。它只适合返回结构化判断，不负责 Query Rewrite 或答案生成；由于它是独立外部服务并突破当前 Luna-only 与数据边界，只有用户明确批准后才能在线接入。
### 3.5 写工具与内部写入职责

模型可见写工具必须原子、窄职责，并声明确认、幂等、同步性与 `memory_effect`：

| 工具 | 参数要点 | 授权/确认 | 执行与后续 |
| --- | --- | --- | --- |
| `set_reading_progress` | `work_id`、`location_id`、`expected_version`、`idempotency_key` | 用户明确报告进度可直接执行；Agent 推断必须先建 PendingAction | 同步写用户级 ReadingProgress；异步触发旧预测可回看检查 |
| `save_journal_entry` | `entry_type`、`content`、阅读锚点、`idempotency_key` | 用户说“记下来”即授权；Agent 主动建议需确认 | 同步写阅读手账 |
| `update_journal_entry` | `entry_id`、允许修改的正文/状态、`expected_version` | 内容或结论变化需用户确认；系统只可自动标记 `reviewable` | 同步更新，保留更新时间与来源 |
| `delete_journal_entry` | `entry_id`、`expected_version` | 必须由用户明确要求或确认 | 同步删除或软删除，不由模型自行决定 |
| `record_interaction_note` | 原始用户表达、scope、授权来源、`idempotency_key` | 用户主动要求记录时同步执行；自动检测只在压缩边界执行 | 两条路径都先调用统一 Note Extractor，产出 section、规范化文本、临时性、失效条件、confidence 与来源，再原子应用 `note_ops` |
| `forget_interaction_note` | 稳定 `note_ref`、reason | 必须由用户明确要求或确认 | 同步移除当前 Note；来源 episode/trace 不连带删除，另走隐私删除流程 |

不向模型暴露通用 `write_memory`、原始 Markdown 写文件工具或 LanceDB 写工具。以下是内部 workflow writer，不参与模型工具选择：

- `apply_note_ops`：应用压缩时抽取出的合并、增加临时项或开放观察；
- `append_daily_episodes`：按稳定来源区间幂等追加 `memory/YYYY-MM-DD.md`；
- `upsert_episode_embeddings`：后台更新 LanceDB；
- `dream_promote`：以后从 Note 深化到 `USER.md` / `SOUL.md`，必须保留审阅记录；
- nanobot 自有 Trace/session/runtime checkpoint writer：持续保存执行证据，不进入语义写工具集合。

同一回合有多个写操作时按依赖顺序串行执行：先确认/校验 ReadingState，再写手账或 Note，最后投递派生后台任务；只读检索可以并行，写工具不并行修改同一资源。
### 3.6 用户级阅读进度与动态工具组

当前实现的 `StorySessionState` 已将 `active_work/current_anchor/max_seen_order` 原子写入本地 `.storypal/session_state/<session_key 哈希>.json`，因此同一 session 重启后可恢复；但它按 session 而不是按用户存储，新 session 不能可靠继承阅读进度，不能称为“用户绑定”。目标实现新增 `ReadingProgressStore(owner_id, work_id)`：保存位置、最大已读顺序、版本、更新时间和来源 session；session state 只保留当前作品指针。首次迁移时仅在用户级记录不存在时吸收旧 session 状态，默认禁止进度倒退，纠正/重置走明确确认。WebUI 单用户阶段可使用稳定 `local-user`，以后登录身份必须映射到稳定 `owner_id`。

模型工具按领域分组并在每个 Agent 回合开始前动态裁剪，而不是把全部 schema 常驻上下文：

| 工具组 | 模型可见工具 | 典型触发 |
| --- | --- | --- |
| `progress` | `resolve_reading_location`、`set_reading_progress` | “读到哪里”“刚读完某章” |
| `story` | `search_story`、`get_story_context` | 剧情核验、人物/设定、已读原文证据 |
| `journal` | `search_reading_journal`、`save_journal_entry`、`update_journal_entry`、`delete_journal_entry` | 感受、问题、预测、手账回看 |
| `core_recall` | `recall_interaction_history` | 始终可见的只读单次回忆；同时承担 MemoryNeedGate 与 Query Rewrite |
| `interaction_memory` | `record_interaction_note`、`forget_interaction_note` | 交互约定与纠正写入，按意图暴露 |
| `meta` | 后续可加入 `load_tool_group` | agentic search 阶段用于渐进加载，首版不启用 |

所有工具在进程级 registry 中静态注册；`core_recall` 始终可见，其余由无副作用的 `ToolGroupResolver` 根据用户意图、当前 Skill、PendingAction 与 active workflow 选择 1–2 个组，再通过每回合 allowlist/过滤视图动态暴露给模型，不执行真实的反复注册与注销。已选择的集合在整个回合、工具迭代和中断恢复期间保持稳定，并把组名、schema 版本与策略版本写入 runtime checkpoint/trace。首版不启用 `load_tool_group`；多轮 agentic search 仍后置。工具组只是减少 schema token 和误选，不是权限边界；写操作仍由 ToolPolicy、确认、owner 隔离、版本和幂等键约束。
## 4. 18 小时实施阶段

时间为有效开发时间估计；每阶段结束都要运行相关测试、记录结果，并更新 `docs/operations/CHATBOT_DEVELOPMENT_PROGRESS.md`。

### 阶段 A：先补离线评测与失败归因（2.5h）

- 扩展 `chatbot_tests/evaluate_story_retrieval.py`：在现有 Hit/Recall@K、单 case latency、spoiler violation 之外输出 MRR、nDCG@5、P50/P95。
- 为金标增加中文类别：明确事实、口语改写、人物关系、事件因果、长程回顾、指代/上下文依赖、边界防剧透。
- 每条失败写固定归因：`未召回`、`排序靠后`、`查询歧义`、`语料/标注问题`、`边界过滤`、`工具或索引异常`。
- 输出可版本化 JSON/Markdown 报告，保留单 case 结果，不能只写总体均值；主指标固定使用 `raw_user`，`gold_rewrite` 只作为人工改写后的检索上限对照。

**DoD：** 同一命令可复跑 FTS 与 Vector；所有指标按 overall 和类别输出；任一安全违规立即显式失败；基线差异必须说明数据/索引版本。

### 阶段 B：离线 Hybrid RRF（3h）

- 新增仅供评测与显式配置启用的 `hybrid_rrf`；分别获取 FTS TopN 与 Vector TopN。
- 以 `unit_id` 去重，用 `score = Σ 1 / (k + rank)` 融合，初始 `k=60`；TopN 与 RRF k 均可配置并写入报告。
- 在候选阶段先做 `max_seen_order` 过滤，再融合并保留每路 rank、融合分数和来源。
- 以 Vector、FTS、Hybrid 三路同表对比候选 Recall、Hit@K、MRR、nDCG、P50/P95 与安全违规。

**DoD：** `auto` 仍表示 vector → FTS → scan fallback；Hybrid 无重复 unit、无越界候选；报告能解释 Dense、Sparse 或共同支撑；只有稳定收益且零违规时才讨论线上接入。

### 阶段 C：ContextPacker 可解释化（3h）

- 从 `StoryMemoryService` / tool 逻辑抽出纯函数或独立模块 `ContextPacker`。
- 输入为候选 Evidence、当前阅读边界、token budget 和相邻扩展策略；输出为证据包与 diagnostics。
- 固化顺序：越界过滤 → unit 去重/近重复压缩 → 主证据按相关性优先 → 同章相邻扩展 → token budget 截断。
- 每条未入选证据记录 `drop_reason`：`spoiler_boundary`、`duplicate`、`lower_relevance`、`not_adjacent`、`token_budget`。

**DoD：** 测试覆盖越界、重复、同章/跨章邻居、预算耗尽与稳定排序；结果不含越界单元；trace 可见 selected、dropped、原因和 token 估算；现有 Top3 体验不无故回退。

### 阶段 D：HistoryMemory v0 技术原型（5h，已验证、待产品收敛）

- 用 SQLite + FTS5 新建 StoryPal 自有 HistoryMemory，不引入第二个向量数据库。
- 最小记录字段：`memory_id`、`owner_id`、`memory_type`、`scope`、`content`、`entities`、`source_session`、`source_trace`、`evidence_refs`、`outcome`、`created_at`。
- 仅在 task-end distill 或用户明确确认时写入高价值 episode，例如预测、观点变化、长期偏好、已完成的讨论结论。
- `source_trace` 只保存可定位 trace 的引用；工具失败、重试、临时搜索结果和 working step 一律不写入长期记忆。
- 增加白名单内的 `search_memory`，按 owner、作品 scope、阅读边界与类型过滤；默认按需调用，不将全部记忆无差别塞回 prompt。
- Notes 和 ReadingNotebook 的语义、物理存储与工具名保持独立。

**DoD：** 跨会话能找回用户此前确认的预测/观点及其来源；跨用户、跨作品、越过阅读边界的内容均不可见；失败工具不污染记忆；覆盖写入、检索、隔离、无结果、来源可追溯测试。

### 阶段 D v0 实施记录（2026-09-20）

- 已落地 `.storypal/history_memory/memories.sqlite3` 与 SQLite FTS5；记录保存 type、作品 scope、锚点 order、正文、实体、会话/trace 的不透明引用、证据引用、结果与创建时间。
- `search_memory` 仅检索同一用户、同一作品且 `anchor_order <= max_seen_order` 的记录；`write_memory` 只接受显式确认的 `prediction`、`reflection`、`preference`、`conclusion`，支持幂等键与本用户删除。
- 当前 **不做自动抽取**：原始对话、工具 Observation、失败和重试不写入长期记忆；自动沉淀的触发条件、跨作品回忆和保留期限仍须用户决定。
### 阶段 E：Rerank 对照与交付整理（4h）

- 仅对 Vector 与 Hybrid 的候选池执行 cross-encoder rerank；模型版本、候选 N、设备和耗时必须记录。
- 同时报告 candidate Recall@N 与 reranked MRR/nDCG，避免把排序提升误称为召回提升。
- 若模型权重、依赖或性能不具备条件，标记为阻塞并保留其余可复跑实验，不静默跳过。
- 产出 retrieval ablation 表、bad-case taxonomy、Memory/Context 架构图和一页数据卡；运行 Chatbot 与 StoryMemory 全量回归。

**DoD：** 对照表含 FTS、Vector、Hybrid、Vector+Rerank、Hybrid+Rerank（不可用项须说明原因）；每个候选方案都有延迟与 0 剧透检查；文档只陈述已测结论。

## 5. 核心接口草案

### 5.1 RetrievalDiagnostics

```text
mode, candidate_count, per_source_rank, fused_score,
index_version, model_id, filtered_spoiler_count, latency_ms
```

仅用于日志、评测和开发调试，不要求模型向用户解释内部排序。

### 5.2 ContextPackResult

```text
selected: Evidence[]
dropped: [{ unit_id, reason }]
token_estimate: int
source_anchors: [{ work_id, unit_id, order, chapter, line_range }]
```

### 5.3 HistoryMemoryRecord

```text
memory_id, owner_id, memory_type, scope, content, entities,
source_session, source_trace, evidence_refs, outcome, created_at
```

`content` 是面向未来检索的简短事实或 episode，不得复写整段聊天或工具 Observation。

## 6. 验收场景

1. 用户问已读剧情事实：检索与 ContextPacker 只返回已读单元，回答可追溯 source anchors。
2. 用户口语化追问：比较 Dense、Sparse、Hybrid 的候选和排序差异。
3. 用户试探后续：结果为空或明确边界说明，diagnostics 出现 `spoiler_boundary`，不泄露后文。
4. 用户数日后问“我当时猜什么”：`search_memory` 只找回该用户、该作品、已读范围内的 prediction episode。
5. 工具超时或检索失败：trace 有记录；HistoryMemory、Notes、ReadingNotebook 不产生伪记忆。

## 7. 延后决策与触发条件

| 项目 | 当前决定 | 重新进入范围的条件 |
| --- | --- | --- |
| jieba / 新 BM25 库 | 暂不替换 FTS5 二元词 | 失败分类显示稀疏中文分词是主要瓶颈，且 Hybrid 不能弥补 |
| Milvus / ANN | 独立 benchmark，不接 StoryPal 线上 | 用 10^5～10^6 规模向量证明 recall-latency trade-off |
| Pi Agent | 不迁移主链 | ToolSpec、Policy、HistoryMemory 已稳定，且独立 spike 证明更低改造成本 |
| 向量化 HistoryMemory | v0 不做 | FTS5 的跨会话回忆用例稳定失败，且已有足够 memory corpus |
| 自动画像 / Dream 扩权 | 不做 | 有明确用户授权、可审阅写入链路与误写回滚方案 |
| 真实 Agent query 改写评测 | 后续优化，不以人工改写替代线上轨迹 | 已记录足够 Luna tool-call trace，并建立原话/上下文/query/evidence 对照金标 |

## 8. 推进沟通、Luna 数据核验与用户参与

### 8.1 每阶段开始与结束的固定汇报

每次开始推进一个阶段，先向用户说明三件事：**接下来做什么、预期得到什么结果、需要用户核验或决定什么**。阶段结束时再同步真实代码/数据改动、测试证据、失败项和下一阶段建议；不能把计划写成完成。

### 8.2 Luna 的职责

涉及 StoryUnit 内容、检索金标、gold evidence、阅读边界、失败案例归因和新增阅读场景的**数据查验**，优先交由 Luna 独立只读审阅。Luna 的结论是审阅意见：主开发仍需以实际数据、测试结果和防剧透约束复核后才能落入金标或代码。

### 8.3 用户参与检查点

| 阶段 | 希望用户参与的决定 | 不需要用户介入的工作 |
| --- | --- | --- |
| A. 评测 | 确认新增金标是否像真实首次阅读问题；确认失败分类是否有解释力 | 指标实现、报告生成、基线运行 |
| B. Hybrid RRF | 根据质量、延迟和坏例决定是否允许候选融合进入线上工具 | 离线融合、消融实验、回归测试 |
| C. ContextPacker | 确认回答展示多少证据、默认上下文预算和相邻内容的阅读体验 | 过滤、去重、诊断与单元测试 |
| D. HistoryMemory | 确认哪些 episode 可以自动沉淀、是否允许跨作品回忆、何时删除 | SQLite/FTS5、隔离、来源和失败防污染测试 |
| E. 交付 | 确认项目对外表述、演示场景和面试重点 | 数据卡、图表、复跑与文档整理 |

任何影响用户可见交互、记忆写入策略、隐私保留范围、工具权限或 StoryMemory 接口契约的改动，都要先给出方案、收益、风险和可选项，请用户参与决定；纯内部重构、评测和回归不等待确认。
## 9. 阶段完成后的交付物

- 可复跑的中文检索评测及原始结果；
- 一张含质量、延迟、安全指标的 retrieval ablation 表；
- ContextPacker 单元测试与 provenance diagnostics；
- HistoryMemory 跨会话演示、隔离测试和失败防污染测试；
- bad-case taxonomy、架构图与更新后的项目数据卡。
