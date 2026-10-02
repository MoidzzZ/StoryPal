# 共读会话归档模板覆盖

固定上游：`9ecdc4533f935bfd7cae9b8cbe651e77eec07cd7`。在既有七组补丁之后应用 `storypal-reading-checkpoint.patch`。只修改 `nanobot/agent/memory.py`，复用 Dream 补丁已导入的 workspace_prompts 安全读取函数。

## 契约

- 每次归档依次读取已解析项目工作区、全局工作区的 `prompts/consolidator_archive.md`；均不可用则回退上游内置模板。修改模板下次归档生效，不强制覆盖用户定制。
- 沿用共享 32000 字符上限，过长截断并对同一路径告警一次；空文件、不可读或非 UTF-8 时回退。无新增工具、模型、数据库或每轮维护请求。
- Token 压力和 idle 共用该入口。已有摘要与新增稳定消息区间生成替换摘要；不是固定块追加。原始会话 JSONL、水位提交、至少 8 条近期回放、原始归档兜底保持上游行为。
- StoryPal 中文模板保留读者观点、AI 暂定解释、已有依据、观点修正与原因、未解问题及续聊入口；工具只保存相关观察结论和来源。失败、空结果或越界拒绝不得升格为已查证。
- 这是同一会话的工作记忆，不自动写手账、Note、USER、SOUL，不等于完整跨会话语义记忆。摘要规则本身不能保证零遗忘或消除模型幻觉。

## 安装与验证

源模板为 `chatbot/src/storypal_chatbot/persona/prompts/consolidator_archive.md`，正常新安装由 install_persona 复制。已有工作区只补缺失的同名模板，不为此重跑初始化或 force 覆盖人格。Python 补丁首次部署需重启 gateway；网页无需重建。

补丁已在固定上游 memory.py 加既有 Dream 改动后 check/apply 并与当前运行源码逐字比较。定向测试见 `chatbot_tests/test_reading_checkpoint.py` 和 `test_note_consolidation.py`；替身 provider 验证的是链路，不证明模型能正确保留文学解读。真实两请求隔离验收待发送授权，见连续共读核验文档。
