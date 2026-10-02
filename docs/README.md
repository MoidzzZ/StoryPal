# StoryPal 文档导航

本目录保存主项目的设计与决策记录。根目录仅保留项目启动说明、许可证与第三方声明；`story_mem/` 是独立协作仓库，其数据与文档不随主仓库提交。

## 从这里开始

- 想知道整体还差什么、哪些优先或暂缓：查看 [当前能力与 TODO](architecture/STORYPAL_REMAINING_WORK.md)，避免将历史提案误认成当前缺口。
- 想了解应用开发与算法会话的分工、具体实验场景与文件边界：查看 [双线推进契约](architecture/STORYPAL_PARALLEL_TRACKS.md)。
- 想了解跨会话经历如何按日保存、来源和水位怎样校验、哪些尚未接通：查看 [M3 情景记忆](architecture/STORYPAL_EPISODIC_MEMORY.md)。

- 想直接推进《流浪地球》的连续理解功能与检索实验：查看 [连续共读实施清单](architecture/STORYPAL_CONTINUOUS_READING_PLAN.md)，包含首轮接口、压缩记忆与类型覆盖测试。
- 想从场景一路看到上下文、数据和代码改动：查看 [连续共读分层架构图（SVG）](architecture/storypal-continuous-reading-architecture.svg)，已区分已有、本轮待完善和后续 TODO。
- 想看用户手账如何参与讨论，以及 Skill／Tool／Workflow 的区别：查看 [记忆与技能工具详图（SVG）](architecture/storypal-memory-skills-tools.svg)，列出当前 11 项白名单工具。

- 想从产品目标、九类需求、体验流程与验收标准开始讨论：查看 [StoryPal PRD](product/STORYPAL_PRD.md)（v0.1 讨论稿）。
- 想用 5～8 分钟核验新版声音：查看 [口吻快速验收](operations/COMPANION_VOICE_ACCEPTANCE.md)，含可直接输入的虚构故事和四句测试。

- 想运行本地 Chatbot：返回根目录 [README](../README.md)。
- 想了解当前做到哪里：查看 [开发进度](operations/CHATBOT_DEVELOPMENT_PROGRESS.md)。
- 想小规模核验新已读故事视图和观点承接：查看 [连续共读核验](operations/CONTINUOUS_READING_ACCEPTANCE.md)，只需在真实已读范围聊三轮；压缩有一条隔离小样，Skill 已接通，真实决策及真人体验仍待验收。
- 想理解压缩如何保留共读观点：查看 [共读归档补丁](../patches/nanobot/reading-checkpoint.md)，明确模板路径、回退、近期历史和显式手账边界。
- 想体验或设计陪读：从 [初次阅读体验](product/CHATBOT_FIRST_READING_EXPERIENCE.md) 开始。
- 想讨论九类陪伴需求、角色口吻及双脑备选方案：查看 [陪读场景与声音](product/COMPANION_SCENARIOS_AND_VOICE.md)（2026-10-02）。
- 想按真实用户行为验收桌面版：查看 [首次阅读行为验收规范](operations/FIRST_READING_ACCEPTANCE.md)。
- 想了解桌面阅读器的复用补丁：查看 [阅读器补丁说明](../patches/nanobot/reader.md)。
- 想了解接下来做什么：查看 [下一阶段交付](architecture/STORYPAL_NEXT_DELIVERY.md) 和 [RAG/Memory 规格](architecture/STORYPAL_RAG_MEMORY_SPEC.md)。
- 想引用可复跑的实验数字：查看 [结果记录](../result.md)，不要将功能回归等同于真实读者体验。
- 想改 Chatbot 与 StoryMemory 的连接：查看 [接入说明](../chatbot/STORY_PIPELINE_INTEGRATION.md)。

## 目录说明

| 目录 | 内容 |
| --- | --- |
| [product/](product/) | 面向读者的初次阅读陪读设计，以及后续功能优先级。 |
| [architecture/](architecture/) | Online Chatbot 与离线 StoryMemory 的工程契约和边界。 |
| [operations/](operations/) | 持续更新的开发进度、核验记录、已知限制和 TODO。 |
| [research/](research/) | 平台调研、Luna 数据审阅、故事单元可用性分析与已完成的接口需求。 |

## 其他文档位置

- `chatbot/`：StoryPal 自有集成层、人格模板、工具实现说明与测试文档。
- `patches/nanobot/`：对上游 nanobot 的最小补丁及其设计说明。
- `story_mem/`：独立 StoryMemory 仓库；其中的 `WORKFLOW.md` 和 `DESCRIPTION.md` 分别说明数据处理流程与产物。
