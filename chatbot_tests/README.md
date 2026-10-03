# StoryPal 聊天机器人测试

本目录保存由 StoryPal 维护的单元测试与集成测试。首轮基线覆盖有界配置、人格文件安装、按会话隔离的故事状态、防剧透运行时上下文，以及仅在用户明确要求时写入的用户笔记。

- 新增`test_continuous_memory_workflow.py`：21项跨模块完整链／故障／后台时序测试，不手动设置归档水位；原生压缩、存储、工具和LanceDB真实，LLM与向量替身，不评价模型语义。行为规范见[连续记忆测试](../docs/operations/CONTINUOUS_MEMORY_TEST_PROTOCOL.md)。
- `manual_memory_acceptance.py`是单独获批的最多12 Luna＋3 Sol合成验收入口，缺省离线预算自检；参数不是通用外发授权，运行结果另记根result。没有小说／正式用户资料或GPU加载。

上游 nanobot 测试位于 .reference/nanobot/tests；它们只用于验证依赖基线，不能替代 StoryPal 的行为测试。

- 当前检索金标与主评测事实源：[story_retrieval_goldens.json](story_retrieval_goldens.json)；`story_retrieval_cases.md` 仅保留为历史说明。
- `test_journal_recheck.py`有24项合成后台复核测试，覆盖来源／边界／版本、恢复与取消、坏输出、分隔符正文、独立结果和单次通知；本轮受影响73项通过，不是业务准确率，不加载模型或GPU。
- `manual_journal_recheck.py`是需独立用户授权的手动真实验收入口，缺省仅离线预算检查；真实模式新建合成工作区、禁重发、每步骤1次／总2次GPT-6 Luna。`test_manual_journal_recheck.py`只测预算与替身传输，无网络／凭据访问。2026-10-03已执行授权小样，记录见根result；命令参数不是长期外发授权。
- `test_note_maintenance.py`核验会话临时scope、开放观察修订／停用、版本保护、审计／重试和原生Loop旧快照过滤；合成夹具／替身provider，不验证模型语义。
- `test_journal_lifecycle.py`核验明确修订／删除、不同版本阅读边界、来源／owner／作品、重试、进度回看候选及原生Loop不重复回放；本轮定向49项，只有合成数据和替身，不调用模型／Embedding。真人步骤见[手账核验](../docs/operations/READING_JOURNAL_ACCEPTANCE.md)。

- `test_continuous_discussion_skill.py` 验证原生 Skill 安装／注入、无文件工具的 Loop 输入、名称线索到结构历史及证据回取、边界和预算；全部使用临时合成数据／替身 provider，不评估模型理解或真实工具选择。
- 连续共读行为规范：[CONTINUOUS_READING_ACCEPTANCE.md](../docs/operations/CONTINUOUS_READING_ACCEPTANCE.md)。真实模型与真人结果另记；不能把单元测试数量当业务准确率。
