# StoryPal 聊天机器人测试

本目录保存由 StoryPal 维护的单元测试与集成测试。首轮基线覆盖有界配置、人格文件安装、按会话隔离的故事状态、防剧透运行时上下文，以及仅在用户明确要求时写入的用户笔记。

上游 nanobot 测试位于 .reference/nanobot/tests；它们只用于验证依赖基线，不能替代 StoryPal 的行为测试。

- 当前检索金标与主评测事实源：[story_retrieval_goldens.json](story_retrieval_goldens.json)；`story_retrieval_cases.md` 仅保留为历史说明。
- `test_note_maintenance.py`核验会话临时scope、开放观察修订／停用、版本保护、审计／重试和原生Loop旧快照过滤；合成夹具／替身provider，不验证模型语义。

- `test_continuous_discussion_skill.py` 验证原生 Skill 安装／注入、无文件工具的 Loop 输入、名称线索到结构历史及证据回取、边界和预算；全部使用临时合成数据／替身 provider，不评估模型理解或真实工具选择。
- 连续共读行为规范：[CONTINUOUS_READING_ACCEPTANCE.md](../docs/operations/CONTINUOUS_READING_ACCEPTANCE.md)。真实模型与真人结果另记；不能把单元测试数量当业务准确率。
