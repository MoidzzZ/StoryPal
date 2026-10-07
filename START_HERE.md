# StoryPal：另一台电脑从这里开始

更新：2026-10-08。此页汇总整个项目：应用、StoryMemory、检索研究和部署。首次接手先读本页，再按[新电脑详细指南](docs/operations/WORK_COMPUTER_QUICKSTART.md)恢复环境。

## 1. 用五分钟跟上

StoryPal 是跟着读者已确认阅读位置讨论小说的共读 Agent。基座为固定版本 nanobot；主项目实现阅读进度、业务工具、连续理解与用户记忆，独立 StoryMemory 仓库提供已读范围内的原文、结构历史与渐进视图。首版桌面浏览器支持《流浪地球》。

| 部分 | 已完成 | 接下来 |
| --- | --- | --- |
| 应用 | 阅读器与选段、段尾进度提议/确认、服务端已读过滤、渐进故事视图、12项工具白名单 | 真人完整共读链验收，处理体验反馈 |
| 连续记忆 | 共读压缩、临时 Note、显式手账修订/删除、按日经历抽取与跨会话回忆；可选旧预测复核默认关闭 | 自然压缩调度、真实语义回忆与观点归属；未提取历史不应冒充可回忆经历 |
| StoryMemory | 独立仓库只读接口、结构历史/渐进快照、Evidence 名称线索；数据与索引在本地 | 核验抽取质量、复杂因果与跨作品；当前不是完整因果图 |
| 检索优化 | 冻结30业务目标/60表达，六路召回、五种装包、严格57问/570对Qwen同池重排，记录增益、坏例及成本 | 独立核验必要证据集合，再比较最终理解回答；生产默认未替换 |

最新结果要分清分母：

- 应用：2026-10-04受影响程序测试52/52；单独授权15次真实模型请求验证六类**合成**行为，真人体验仍待核验。
- 检索：新9故事目标18问，Dense默认材料齐13/18、固定RRF11/18、RRF Top5词项互补12/18。
- 同池Qwen：旧14故事目标28问，固定Top10输入装包18→21/28；6个改善、3个损失，CPU每问10对纯评分中位17.66秒。新18问不在Qwen范围。
- 检索程序测试51/51；标签仍provisional、独立语义金标0。材料齐备和程序通过都不能称为最终回答准确率。两线测试集合有重叠，不能相加。

## 2. 阅读顺序

1. [新电脑安装、数据恢复与启动](docs/operations/WORK_COMPUTER_QUICKSTART.md)：可照着执行；包含两个项目仓库及固定 nanobot 的恢复步骤。
2. [整个项目的讲述主线](docs/product/STORYPAL_PROJECT_STORY.md)：需求→架构→业务状态→记忆→验证。
3. [检索优化经历](docs/research/retrieval/EXPERIENCE.md)及[最新实验过程/结果](docs/research/retrieval/HEAVY_CPU_2026_10_05.md)：任务、比较方法、坏例与采纳判断。
4. [真人验收指南](docs/operations/STAGE1_USER_ACCEPTANCE_GUIDE.md)、[应用进度](docs/operations/CHATBOT_DEVELOPMENT_PROGRESS.md)、[剩余工作](docs/architecture/STORYPAL_REMAINING_WORK.md)。
5. [全部文档导航](docs/README.md)、[版本与私有产物哈希清单](docs/operations/WORK_COMPUTER_MANIFEST.json)、[公开检索聚合结果](docs/research/retrieval/RESULTS_SNAPSHOT_2026_10_05.json)。

## 3. 下一步具体推进

应用先完成真人已读故事讨论：首句抓点→连续纠正→必要查证→进度确认→手账/Note生命周期。检索先人工核验H21-b、H23/H24和旧H12/H13的必要集合、人物归属与问法等价性，再锁定基线/优化组。后续模拟用户仍用GPT-6 Sol，角色扮演/复核用GPT-6 Luna，尽量对齐主应用的人格、工具、已读边界、迭代与上下文预算；新增模型实验需登记新批次范围和次数，不把电脑迁移当成重置旧预算。

## 4. GitHub 与本机各保存什么

代码、测试、设计文档、全部九个 nanobot 补丁、冻结任务、实验报告和聚合指标在 GitHub。StoryMemory 在[独立仓库](https://github.com/Pilgrimage19/offline-story-pipeline)，主仓库不会把它再次复制提交。

小说数据/索引、模型权重、真实聊天、个人手账/Note、运行分数与预算账本、登录信息仍在本机；详细指南有完整私下迁移清单。只想了解和继续开发可先克隆代码；想续接原来阅读和记忆，需要同时恢复这些本地资料及浏览器用户标识。
