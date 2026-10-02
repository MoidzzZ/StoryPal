# 空工具注册表不回退

固定上游：`9ecdc4533f935bfd7cae9b8cbe651e77eec07cd7`。第九组 `storypal-empty-tool-registry.patch` 在此前八组之后应用。仅修正 loop.py 三处工具选择：只在参数为 None 时用默认工具，空注册表仍为空。

## 真实测试发现的问题

原白名单入口正确将 allowedTools=[] 变成空注册表，但 ToolRegistry 定义了 __len__，空对象为假。后续 `tools or self.tools` 又拿回默认工具，模型可见并调用了 read_session；运行时来源选择也有相同回退。空白名单或禁用后恰好没有剩余工具时会失效；当前 StoryPal 非空的 11 项白名单不等于此次空集合场景。

补丁在恢复、运行时材料收集、AgentRunner 三个入口统一区分 None 和空对象。不新增注册或工具，不更改默认 None 的兼容行为。这是工具能力收紧，不是通用系统沙箱。

定向测试 `chatbot_tests/test_empty_tool_registry.py` 通过真实 AgentLoop + 替身模型验证空列表、全部名称未注册、每轮空覆盖、非空列表、未配置、以及模型自行提出未授权调用时不执行；同时检查工具拥有的运行时来源不会泄漏。补丁从固定 commit 加既有 Dream／白名单／临时上下文差分生成，check/apply/逐字重放通过。

真实补充请求中工具定义 0、调用 0，复用旧摘要完成续聊。旧摘要的语义偏差仍可能传递，不能因工具隔离修复而宣称所有记忆问题已解决。首次部署需重启 gateway，无需重建网页或改用户配置。
