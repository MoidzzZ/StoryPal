# StoryPal persona document viewer

Upstream: nanobot commit `9ecdc4533f935bfd7cae9b8cbe651e77eec07cd7`.

Purpose: add a read-only, allowlisted WebUI page for the configured workspace's
`SOUL.md`, `AGENTS.md`, and `USER.md`. The backend refuses paths outside the
workspace and limits displayed content to 128,000 characters per document.

Apply from the root of a clean nanobot checkout:

```powershell
git apply D:\StoryPal\patches\nanobot\storypal-persona-view.patch
```

Then rebuild the WebUI and install the local wheel.

## Patch

The adjacent `storypal-persona-view.patch` is the replayable source patch.
