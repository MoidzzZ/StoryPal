# StoryPal 文档导航

本目录保存主项目的设计与决策记录。根目录仅保留项目启动说明、许可证与第三方声明；`story_mem/` 是独立协作仓库，其数据与文档不随主仓库提交。

## 从这里开始

- 想运行本地 Chatbot：返回根目录 [README](../README.md)。
- 想了解当前做到哪里：查看 [开发进度](operations/CHATBOT_DEVELOPMENT_PROGRESS.md)。
- 想体验或设计陪读：从 [初次阅读体验](product/CHATBOT_FIRST_READING_EXPERIENCE.md) 开始。
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
