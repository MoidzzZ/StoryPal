# nanobot patches

Keep this directory minimal. StoryPal maintains three replayable nanobot patches:

- `storypal-persona-view.patch`: a read-only WebUI viewer for `SOUL.md`, `AGENTS.md`, and `USER.md`;
- `persona-view.md`: provenance, safety boundary, and replay instructions;
- `storypal-dream-write-allowlist.patch`: configurable Dream durable-file writes;
- `dream-write-allowlist.md`: StoryPal's two-file policy and regression-test notes;
- `storypal-tool-allowlist.patch`: per-turn configuration-driven tool allowlist;
- `tool-allowlist.md`: allowlist policy, replay steps and regression-test notes.

Before adding a patch:

1. demonstrate that configuration, the Python SDK, native tools, hooks, or runtime context cannot implement the requirement;
2. add a StoryPal regression test;
3. record the upstream commit and reason;
4. keep the change minimal and update `THIRD_PARTY_NOTICES.md`.