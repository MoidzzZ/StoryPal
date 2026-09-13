# StoryPal

## 启动本机 Chatbot

在 PowerShell 中执行：

```powershell
conda activate storypal-chatbot
nanobot gateway --background --config D:\StoryPal\.runtime\nanobot\storypal\config.json --workspace D:\StoryPal\.runtime\nanobot\storypal\workspace
nanobot webui --yes --config D:\StoryPal\.runtime\nanobot\storypal\config.json --workspace D:\StoryPal\.runtime\nanobot\storypal\workspace
```

浏览器打开 http://127.0.0.1:8765 。

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
