# StoryPal Chatbot integration

This directory contains the StoryPal-owned integration layer for nanobot. It does
not copy or modify the upstream nanobot source.

Planned responsibilities:

- `storypal-chatbot-configure`: applies bounded local defaults without changing
  provider credentials;
- versioned `AGENTS.md` / `SOUL.md` / `USER.md` persona templates;
- `story_state`: persisted per-session state plus per-turn runtime context;
- `read_notes` / `write_note`: explicit, user-scoped notes;
- nanobot tool entry points, so no upstream patch is required.

Current PoC environment: Conda environment `storypal-chatbot` (Python 3.12).
The minimal environment declaration is `environment.yml`. nanobot is installed
separately from the fixed `.reference/nanobot` source so a same-numbered PyPI
release cannot silently replace the audited commit.

Install this integration in editable mode:

```powershell
conda activate storypal-chatbot
python -m pip install -e .\chatbot
```

After a fresh nanobot WebUI has created a config and workspace, apply StoryPal
defaults:

```powershell
storypal-chatbot-configure --config <config.json> --workspace <workspace>
```

To use Codex OAuth and make GPT-5.6 Luna the sole configured model preset:

```powershell
storypal-chatbot-configure --config <config.json> --workspace <workspace> --luna-only
```

This removes configured model fallbacks and keeps the `my` self-modification tool
disabled. The `story_state` runtime-context provider also rejects a turn before
the model call if its resolved model is anything except
`openai-codex/gpt-5.6-luna`. The OAuth account must still expose Luna in its
online model catalog.

The configurator sets the tool iteration limit to 6, disables Heartbeat and
general command/file tools for the companion prototype, and keeps the WebUI
local to nanobot's safe defaults. Dream is enabled every two hours but may
modify only the persona and confirmed-user files; story memory remains
unwritable. Existing provider settings and secrets are preserved.

Do not place upstream nanobot source here. Prefer its public Python SDK and extension points. If a core modification becomes unavoidable, record a minimal patch under `patches/nanobot` and add a regression test first.

## Current local WebUI

The StoryPal WebUI is currently available only on this computer:

- Chat UI: `http://127.0.0.1:8765`
- Gateway health: `http://127.0.0.1:18790/health`
- Config: `D:\StoryPal\.runtime\nanobot\storypal\config.json`
- Workspace: `D:\StoryPal\.runtime\nanobot\storypal\workspace`

The gateway runs in explicit background mode, so closing the launcher terminal does
not stop it. To open the authenticated WebUI again without printing or copying its
secret URL manually:

```powershell
conda activate storypal-chatbot
nanobot webui --yes --config D:\StoryPal\.runtime\nanobot\storypal\config.json --workspace D:\StoryPal\.runtime\nanobot\storypal\workspace
```

Pressing Ctrl+C after the browser opens only detaches the log viewer. Stop the
background gateway explicitly when it is no longer needed:

```powershell
nanobot gateway stop --config D:\StoryPal\.runtime\nanobot\storypal\config.json --workspace D:\StoryPal\.runtime\nanobot\storypal\workspace
```

The UI and gateway bind to `127.0.0.1`; they are not exposed to the LAN or public
internet.

## Request flow

```text
Browser WebUI
  -> local WebSocket gateway
  -> resolve session and the Luna-only runtime
  -> assemble persona + recent turns + checkpoint + StoryPal session state
  -> GPT-5.6 Luna
  -> optional bounded tool calls (at most 6 iterations)
  -> stream the final response to the browser
  -> persist the raw messages, tool records, and session metadata locally
```

## Context and memory layers

1. `AGENTS.md`, `SOUL.md`, and `USER.md` are stable prompt layers rebuilt for
   each turn. They are not replaced by conversation summaries.
2. `active_work`, `current_anchor`, and `max_seen_order` are persisted by user
   and work, then injected as data-only runtime context. The last field is the
   confirmed spoiler boundary; browser scrolling never advances it.
3. The current session stores its raw message/tool history. The active prompt uses
   a recent verbatim tail plus a rolling checkpoint when older turns are compacted.
4. Idle compaction is configured after 15 minutes. The verified replay tail is 8
   messages (4 user/assistant rounds); the original JSONL transcript remains on
   disk and is not overwritten by the summary.
5. Each user has an editable `Note.md` for non-story interaction agreements.
   Explicit note and forget requests take effect across sessions; the current
   Note is injected once per turn. Archived user messages may also be processed
   in the background for Note candidates, with source checks; this automatic
   path still needs real-conversation false-write evaluation. The reading
   journal separately stores reactions, questions, and predictions by work.
6. Dream runs under a constrained prompt and may update only `SOUL.md` and
   `USER.md`. It cannot modify `MEMORY.md`, notes, StoryPal state, or story
   storage.

Not implemented yet: the planned daily episodic memory and semantic recall of
shared experiences. Existing session history and checkpoint do not provide that
cross-session behavior. Story retrieval already uses the local StoryMemory
adapter with a confirmed reading boundary; its private source data is not
included in the public repository.
