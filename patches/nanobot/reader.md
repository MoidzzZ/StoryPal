# StoryPal 桌面网页阅读器补丁

上游基线：nanobot `9ecdc4533f935bfd7cae9b8cbe651e77eec07cd7`。先应用 `storypal-persona-view.patch`，再应用 `storypal-reader.patch`。后者改 WebUI 入口、阅读组件、连接标识和定向测试，并给 `nanobot/webui/ws_http.py` 增加鉴权只读接口。

原文不随补丁提交。接口通过 `storypal_chatbot.reader.reading_document()` 从当前本地 `story_mem/data` 加载唯一允许的 `wandering_earth` 作品，只回传原文、章节和行号，不回传未读摘要或结构化剧透信息。前端的滚动位置和随机生成的稳定 WebUI `client_id` 保存在浏览器 localStorage；后者用来保持 StoryPal 用户级进度归属，不是鉴权凭据。章节确认复用现有聊天工具流程，不新增网页写入权限。

阅读器入口放在独立的顶部工具栏，不再以绝对定位覆盖聊天页原有按钮；打开后同一位置可收起原文。

本地核验：`chatbot_tests/test_reader.py` 2/2、受影响 WebUI 测试 62/62 通过；WebUI TypeScript 检查和生产构建通过；未认证接口返回 401，已认证接口返回 108 单元、4 章。真实阅读体验需用户再核验。
