"""Manual Luna-backed compaction smoke test using synthetic conversation data only."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from uuid import uuid4

from nanobot import Nanobot


def synthetic_messages() -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for index in range(1, 13):
        messages.extend(
            [
                {
                    "role": "user",
                    "content": f"虚构测试人物阿澄在第 {index} 天记录了编号 FACT-{index:02d}。",
                },
                {
                    "role": "assistant",
                    "content": f"已在合成测试对话中确认 FACT-{index:02d}。",
                },
            ]
        )
    return messages


async def run(config: Path, workspace: Path) -> None:
    session_key = f"storypal:synthetic-compaction:{uuid4().hex[:8]}"
    async with Nanobot.from_config(config, workspace=workspace) as bot:
        await bot.sessions.ingest(
            session_key,
            synthetic_messages(),
            metadata={"synthetic_test": True},
            source="storypal-compaction-smoke",
        )
        summary = await bot.runtime.compact_idle_session(session_key, max_suffix=4)
        snapshot = bot.sessions.get(session_key)
        assert snapshot is not None
        print(f"session={session_key}")
        print(f"summary_created={bool(summary and summary.strip())}")
        print(f"summary_chars={len(summary or '')}")
        print(f"message_count={len(snapshot.messages)}")
        print(f"tail_roles={[message.get('role') for message in snapshot.messages[-4:]]}")
        persisted_summary = snapshot.metadata.get("_last_summary", {})
        print(f"summary_persisted={bool(persisted_summary.get('text'))}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.config.resolve(), args.workspace.resolve()))


if __name__ == "__main__":
    main()
