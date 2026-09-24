# StoryPal

## 启动本机 Chatbot

以下命令针对已配置的本地开发环境。公开仓库不包含 `.runtime/`、`.reference/`、`story_mem/` 或小说原文；新克隆需要先准备 nanobot 基座、应用 [StoryPal 补丁](patches/nanobot/README.md)，并按 [StoryMemory 接入说明](chatbot/STORY_PIPELINE_INTEGRATION.md) 放置本地数据。

启动前确认 Conda 中的 `nanobot-ai` 是从**已应用全部 StoryPal 补丁的源码副本**安装，而非仅从上游参考目录安装。只更新网页资源、不切换 Python 安装源，会导致“人格与规则”页面有三个卡片却无法显示文档。当前本机补丁副本为 `.runtime/nanobot/source-build/`；其准备与安装顺序见补丁说明。

在 PowerShell 中执行：

```powershell
conda activate storypal-chatbot
nanobot gateway --background --config D:\StoryPal\.runtime\nanobot\storypal\config.json --workspace D:\StoryPal\.runtime\nanobot\storypal\workspace
nanobot webui --yes --config D:\StoryPal\.runtime\nanobot\storypal\config.json --workspace D:\StoryPal\.runtime\nanobot\storypal\workspace
```

浏览器打开 http://127.0.0.1:8765 。

在桌面浏览器的聊天页点击右上角「阅读原文」，可在同一页阅读《流浪地球》并划选段落带入聊天。滚动位置仅保存在本机浏览器，用于下次续读；浏览器也保留一个本机标识，让聊天侧已确认进度在刷新后仍对应同一用户。滚动和选中原文不会更改防剧透边界。读完一章可点「我已读完本章」，然后在聊天中完成进度确认。首版暂不适配手机。

WebUI 的登录密码不写入项目文档；本机配置位置是：

`D:\StoryPal\.runtime\nanobot\storypal\config.json`

其中 `channels.websocket.tokenIssueSecret` 是密码，
`channels.websocket.websocketRequiresToken` 决定是否要求密码。

停止服务：

```powershell
conda activate storypal-chatbot
nanobot gateway stop --config D:\StoryPal\.runtime\nanobot\storypal\config.json --workspace D:\StoryPal\.runtime\nanobot\storypal\workspace
```

## 本地 Story Memory

`story_mem/` 是本地联调目录，当前含合作者的 offline-story-pipeline
参考副本。它被 Git 忽略，不会提交；实际作品数据导出也应放在这里。

StoryMemory 接入设计见 `chatbot/STORY_PIPELINE_INTEGRATION.md`。

## 文档导航

完整文档地图见 [docs/README.md](docs/README.md)：

- `docs/product/`：读者体验、产品场景与后续功能规划；
- `docs/architecture/`：Chatbot 与 StoryMemory 的工程契约；
- `docs/operations/`：持续开发进度、核验记录和 TODO；
- `docs/research/`：调研、模型审阅、数据可用性分析和历史接口需求。
