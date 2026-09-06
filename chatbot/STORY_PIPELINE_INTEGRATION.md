# Story Pipeline 接入说明

> 状态：已完成接口审阅，可开始单篇联调。最后核对：2026-09-05。

## 结论

可以接入，并且不应复制或耦合 Pipeline 的内部 SQLite 表。合作者仓库已经
提供 StoryMemory 作为 Chatbot 唯一读取入口。它的核心测试 11 项已在本机
storypal-chatbot Conda 环境通过。

参考副本位于 story_mem/offline-story-pipeline，受 .gitignore 保护，只用于
开发核对；它不是 StoryPal 的运行时依赖副本。

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

## 推荐实施顺序

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

- [ ] 实现只读 StoryMemory Protocol 与两个 native tools。
- [ ] 增加临时数据根目录配置和缺数据的安全提示。
- [ ] 与合作者给出的单篇数据跑首轮联调测试。
- [ ] 共同确认 release manifest 与 unit ID 漂移的处理方式。
- [ ] 基于 bad cases 决定是否启用向量检索或混合排序。
