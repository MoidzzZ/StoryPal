# 检索算法线进度

## 2026-10-03：首包

- 核对双线契约、当前 TODO、主评测 29 条、StoryMem 实际检索与结构历史。两仓库已 fetch：StoryPal HEAD/远端均为 d4403ae，StoryMem 均为 f60c987；开工时工作区、暂存区为空，未 pull 或改分支。
- 固定 9 例场景契约；7 条继承既有金标，新增 P01 结构导航、N01 无需检索。P01 的结构历史在 max_order=22 返回真实更新单元 we-0018～we-0022；名称线索不是 unit 边。
- 实现只读离线回放、来源分离与显式 Agent 工具事件采集格式。当前 `agent_query` 仍缺失；没有模型调用、原文外发或真实聊天读取。
- 在隔离运行目录完成当前稀疏路径与本地 BGE-M3 小样本；结果和失败分析见 [RESULT.md](RESULT.md)。本机模型索引元数据指向本地 BGE-M3，实际向量回放已跑通。jieba 未安装，未下载。
- 定向测试：`chatbot_tests/test_retrieval_experiments_replay.py`，4/4 通过。回放样本不是最终文学理解验收。

## 下一步

1. 采一小批经授权的真实 Agent tool call/skip 事件；当前不能把人工改写充作真实 Agent query。
2. 用隔离索引比较 jieba OR/AND/短语与严格 FTS bigram，区别扫描回退。
3. 对齐候选数和证据预算后复验 RRF 与一个 reranker，输出 bad cases。
4. P01 和必要证据解释待 GPT-6 Luna 小范围只读核验；新增真实模型调用/原文外发须先报样本与预算获得授权。
