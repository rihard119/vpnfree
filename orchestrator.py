import asyncio
import logging
from pathlib import Path

import yaml
from telethon import TelegramClient

import storage
from interaction import BotInteraction
from parser import extract_vless_links

log = logging.getLogger("orchestrator")

TARGETS_PATH = Path(__file__).parent / "targets.yaml"


def load_targets(path: Path = TARGETS_PATH) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("targets", [])


async def run_collection(client: TelegramClient) -> dict:
    storage.init_db()
    interaction = BotInteraction(client)
    targets = load_targets()

    results = {"new_links": 0, "duplicates": 0, "failures": []}

    for target in targets:
        name = target.get("name", target["username"])
        try:
            reply_text = await interaction.run_target(target)
            links = extract_vless_links(reply_text or "")

            if not links:
                results["failures"].append(f"{name}: no VLESS link found")
            else:
                for link in links:
                    if storage.save_link(link, source_bot=name):
                        results["new_links"] += 1
                    else:
                        results["duplicates"] += 1

        except Exception as exc:  # keep one bad target from killing the run
            log.exception("Error running target %s", name)
            results["failures"].append(f"{name}: {exc}")

        await asyncio.sleep(target.get("delay_after", 5))

    return results
