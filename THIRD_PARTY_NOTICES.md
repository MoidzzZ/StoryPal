# Third-party notices

## HKUDS/nanobot

- Official source: https://github.com/HKUDS/nanobot
- Local reference: `.reference/nanobot`
- Package version: `nanobot-ai 0.3.0`
- Reviewed commit: `9ecdc4533f935bfd7cae9b8cbe651e77eec07cd7`
- License: MIT; see `.reference/nanobot/LICENSE`
- Imported on: 2026-09-02 (Asia/Shanghai)
- Current use: fixed source reference and the runtime base for the StoryPal Chatbot PoC.
- Current modifications: `patches/nanobot/storypal-tool-allowlist.patch` is applied to `.reference/nanobot`, which is installed editable in the `storypal-chatbot` Conda environment. It adds `tools.allowedTools` and filters the registry for every model turn. StoryPal's current allowlist is limited to its five approved state, evidence and Notes tools. The earlier persona-view and Dream-write patches remain replayable artifacts for the disposable runtime source-build copy.
- Product-code reuse: the persona patch provides a read-only viewer for the configured workspace's `SOUL.md`, `AGENTS.md`, and `USER.md`; the Dream patch permits only `SOUL.md`/`USER.md` updates while blocking story memory files; the tool patch removes generic Agent workspace tools from the model-visible surface. All patches include focused regression tests and remain under nanobot's MIT license.

The local clone was populated from the previously downloaded copy of the official repository. Its local `origin` metadata may therefore point to the temporary source path; the official provenance and immutable commit are recorded above.