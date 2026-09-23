# 第三方代码声明

## HKUDS/nanobot

- 上游地址：https://github.com/HKUDS/nanobot
- 本地参考源码：`.reference/nanobot`
- 包版本：`nanobot-ai 0.3.0`
- 核对的 commit：`9ecdc4533f935bfd7cae9b8cbe651e77eec07cd7`
- 许可证：MIT；原文见上游仓库的 `LICENSE`
- 引入时间：2026-09-02（Asia/Shanghai）
- 用途：StoryPal Chatbot 的 Agent 运行时与 WebUI 基座。
- 本地修改：工具白名单补丁作用于当前可编辑安装的源码；人格浏览、Dream 写入限制与桌面阅读器以 `patches/nanobot/` 下的可重放补丁维护。阅读器原文从 Git 忽略的本地 `story_mem/data` 读取，不随补丁或前端 bundle 提交。所有扩展仍遵循 nanobot 的 MIT 许可证。

本地参考副本由此前下载的上游代码建立，其 `origin` 元数据可能指向临时路径；上方记录了正式来源与固定 commit。
