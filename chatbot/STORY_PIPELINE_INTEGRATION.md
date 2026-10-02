# Story Pipeline 接入说明

> 状态：原文／结构历史／渐进视图／名称线索已接入。最后核对：2026-10-03。以下早期实施顺序保留沿革，当前 TODO 见文末。

## 结论

可以接入，并且不应复制或耦合 Pipeline 的内部 SQLite 表。合作者仓库已经
提供 StoryMemory 作为 Chatbot 唯一读取入口。它的核心测试 11 项已在本机
storypal-chatbot Conda 环境通过。

协作仓库直接位于 `story_mem/`，受主仓库 .gitignore 保护；当前本机使用其
`code` 目录作为联调后端，作品数据不随两个公开代码仓库提交。

## 已确认的契约

StoryMemory 提供三个稳定入口：

- list_works()：返回作品 ID、标题、单元数量和索引可用性。
- search(work_id, query, max_order, top_k, filters)：检索统一 Evidence。
- get_unit(work_id, unit_id)：按单元读取统一 Evidence。

Evidence 至少包括 work_id、unit_id、order、raw_text、summary、score，以及
章节、原文起止行、人物、地点和关键词等 metadata。Pipeline 以 JSONL 为
事实源，检索顺序为可用本地向量、SQLite FTS5、纯 Python 扫描；因此首版
不安装向量依赖也能运行。

## 与当前 Chatbot 的映射

| Pipeline | StoryPal 当前状态 | 接入规则 |
| --- | --- | --- |
| work_id | active_work | 每次 Story 查询必须指定当前作品 |
| max_order | max_seen_order | 作为硬过滤条件传入，绝不由模型自行放宽 |
| Evidence.order | current_anchor | 回答后可用来提示用户确认阅读进度，不自动推进 |
| raw_text 和行号 | 工具观察结果 | 仅返回长度受限的证据，保留引用锚点用于追溯 |

## 2026-10-03 当前已读视图接入

现有原文检索和结构查询之外，新增公开 `get_progressive_view(work_id, max_order=完整已读顺序)`；需要同步 StoryMem 代码，不能从 adapter 私有加载函数绕过接口。返回 work_id／max_order／source_version／snapshot_order／status／reason／snapshot／provenance。仅 status=ok 可消费；缺数据与无效快照不注入，不退回最终全书状态。

本轮协作接口提交为 `1248bba`（Pilgrimage19/offline-story-pipeline）；新部署至少需要包含此接口版本，不要求同步本机 data 到公开仓库。

StoryPal Service 重验来源与顺序；ReadingContextProjector 以 1500 估算 token 投影人物、对象、地点、情节线、事件、背景缓冲、累计背景。复用已确认阅读状态提供器，不改工具数量。旧版本后端明确报缺接口，保留基本聊天与阅读状态。

nanobot 必须应用第七组 runtime-context-replay 补丁：新视图只保留当前模型输入，磁盘原始历史仍保留。来源文件 path／mtime_ns／size 变化时 adapter 重新加载并计算 SHA-256；它不是文件监听，不防御人为保持相同 stat 的改写。结果及未验收范围见根目录 result.md 与连续共读实施清单。

## 2026-10-03 证据名称线索接入

StoryMem `f60c987` 增加可选 `Evidence.metadata.context_refs`：有效字符串／旧 entity 对象规范化为名称列表，空值省略；原 Evidence 字段及 max_order 过滤不变。消费者可查询实体更新历史，取得真实 unit_id 后回取原文；名称未命中不等于原文没有，不能将名称当引用图或因果边。

此改动无需重抽取或重建索引。StoryPal 的 ContextPacker 将新增名称序列化长度计入现有正文预算；其他元数据／完整 JSON／诊断尚非总预算范围，估算不等于 provider 实测 tokens。结构契约与 Skill 接线测试通过，不证明模型实际工具决策。

## 原始推荐实施顺序（保留设计沿革）

1. 在 StoryPal 建立只读 Protocol，并实现 search_story 和
   get_story_evidence 两个 native tools。数据根目录通过本机配置传入；未导入
   数据时应明确报空，不能猜测剧情。
2. 首先联调流浪地球：事实查询、前文回忆、章节过滤、进度不足时的防剧透。
   每条用例均断言没有 Evidence.order 超过 max_seen_order。
3. 固定双方 release manifest：数据根目录、work_id、数据版本和 unit ID
   迁移说明。稳定 ID 方案完成前，保存引用时同时保存 order 与原文行号。
4. 等检索评测、LLM 抽取质量和 state snapshot 成熟后，再加入 state_at(order)、
   实体状态、剧情线与更强故事理解。这些都不阻塞聊天和简单证据检索上线。

## 责任边界

- Pipeline 负责原文、切分、抽取、索引和 Evidence 的真实性。
- StoryPal 负责会话进度、工具参数、防剧透执行、回答约束和工具轨迹。
- Dream 不得访问或写入 Pipeline 产物、StoryPal story state、Notes 或故事记忆。

## 当前待办

- [x] 实现只读 StoryMemory Protocol 与两个 native tools，并接入结构历史和安全视图。
- [x] 增加数据根目录配置和缺数据的安全提示。
- [x] 与合作者的《流浪地球》数据联调，开展 FTS5／BGE-M3／RRF 离线对照。
- [ ] 共同确认 release manifest 与 unit ID 漂移的处理方式。
- [ ] 采集真实 Agent query；基于同边界 bad cases 评估中文分词、混合排序和 reranker，不把离线 RRF 原型当线上胜出方案。
