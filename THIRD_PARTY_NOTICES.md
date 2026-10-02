# 第三方代码声明

## HKUDS/nanobot

- 上游地址：https://github.com/HKUDS/nanobot
- 本地参考源码：`.reference/nanobot`
- 包版本：`nanobot-ai 0.3.0`
- 核对的 commit：`9ecdc4533f935bfd7cae9b8cbe651e77eec07cd7`
- 许可证：MIT；原文见上游仓库的 `LICENSE`
- 引入时间：2026-09-02（Asia/Shanghai）
- 2026-10-03 新增 `storypal-empty-tool-registry.patch`：修正 loop 中三处将空注册表误回退成默认全集的行为，保持 None 的默认兼容语义；真实隔离测试发现，无小说或凭据。
- 2026-10-03 新增 `storypal-reading-checkpoint.patch`：仅为 MemoryArchiver 增加通用工作区归档模板覆盖，复用已有安全读取与大小限制，不含小说或用户对话；中文业务模板属于 StoryPal 自有内容。
- 2026-10-03 新增 `storypal-runtime-context-replay.patch`：通用逐来源临时上下文历史回放策略、消息合并和 provider 私有状态失效，不含 StoryPal 业务名、小说或凭据。
- 2026-10-02 新增 `storypal-codex-model-catalog.patch`：将目录查询版本从 `0.144.0` 更新至已核验的 `0.159.2`；补丁不含凭据，运行默认与 Luna 白名单由 StoryPal 自有代码维护。
- 用途：StoryPal Chatbot 的 Agent 运行时与 WebUI 基座。
- 本地修改：工具白名单补丁作用于当前可编辑安装的源码；人格浏览、Dream 写入限制、桌面阅读器及段尾标记以 `patches/nanobot/` 下的可重放补丁维护。阅读器原文从 Git 忽略的本地 `story_mem/data` 读取，不随补丁或前端 bundle 提交。所有扩展仍遵循 nanobot 的 MIT 许可证。

本地参考副本由此前下载的上游代码建立，其 `origin` 元数据可能指向临时路径；上方记录了正式来源与固定 commit。
