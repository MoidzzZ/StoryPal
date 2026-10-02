# Codex 模型目录版本

- 上游基线：`9ecdc4533f935bfd7cae9b8cbe651e77eec07cd7`。
- 补丁：`storypal-codex-model-catalog.patch`，仅修改目录 GET 的 `client_version`；不修改 OAuth、推理接口或 originator。
- 2026-10-02 实测：同账号、同目录接口，`0.144.0` 不列出 GPT-6 Luna，`0.159.2` 列出；现有 provider 可直接调用 GPT-6 Luna。
- 在独立源码副本应用：`git apply D:/StoryPal/patches/nanobot/storypal-codex-model-catalog.patch`，然后重启 gateway。不修改 `.reference/nanobot` 基线。
- 回归：`chatbot_tests/test_model_selection.py` 与上游 `tests/providers/test_oauth_model_catalog.py` 的 Codex 目录用例。
- 这是固定兼容版本，不依赖每次启动调用本机 Codex；将来目录再次缺新型号时，需重新核验版本参数，不能将目录遗漏等同于账号不支持。
