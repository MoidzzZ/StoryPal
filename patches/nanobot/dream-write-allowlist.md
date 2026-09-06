# StoryPal Dream write allowlist

Upstream: nanobot commit `9ecdc4533f935bfd7cae9b8cbe651e77eec07cd7`.

Purpose: make Dream's durable editable files configurable while preserving the
upstream default. StoryPal configures the allowlist to `SOUL.md` and `USER.md`,
so Dream cannot write or Git-stage `memory/MEMORY.md`. StoryPal story state and
Notes under `.storypal/` were already outside Dream's write scope.

Apply from the root of a clean nanobot checkout:

```powershell
git apply D:\StoryPal\patches\nanobot\storypal-dream-write-allowlist.patch
```

The adjacent patch includes a regression test that proves a restricted Dream
can update `USER.md` while a write to `memory/MEMORY.md` is rejected.
