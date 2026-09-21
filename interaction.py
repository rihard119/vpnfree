"""Runs the configured step sequence against one target bot and returns
the text of the most relevant reply, for the parser to scan.

Step types supported in targets.yaml:
  - send_text:   {"type": "send_text", "value": "/start"}
  - wait:        {"type": "wait", "seconds": 2}
  - click_button:{"type": "click_button", "text": "Get free trial"}

This is a first cut: real bots vary a lot, so expect to adjust the
step list (and possibly this engine) per target after testing.
"""

import asyncio
import logging
from typing import Optional

from telethon import TelegramClient, events

log = logging.getLogger("interaction")


class BotInteraction:
    def __init__(self, client: TelegramClient):
        self.client = client

    async def run_target(self, target: dict) -> Optional[str]:
        username = target["username"]
        steps = target.get("steps", [])
        timeout = target.get("response_timeout", 20)

        entity = await self.client.get_entity(username)
        last_reply: Optional[str] = None

        for step in steps:
            step_type = step["type"]

            if step_type == "send_text":
                await self.client.send_message(entity, step["value"])
                last_reply = await self._wait_for_reply(entity, timeout)

            elif step_type == "wait":
                await asyncio.sleep(step.get("seconds", 1))

            elif step_type == "click_button":
                last_reply = await self._click_button(entity, step["text"], timeout)

            else:
                log.warning("Unknown step type in target %s: %s", username, step_type)

        return last_reply

    async def _wait_for_reply(self, entity, timeout: int) -> Optional[str]:
        loop = asyncio.get_event_loop()
        future = loop.create_future()

        async def handler(event):
            if not future.done():
                future.set_result(event.message.message)

        self.client.add_event_handler(handler, events.NewMessage(from_users=entity))
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            log.warning("Timed out waiting for reply from %s", entity)
            return None
        finally:
            self.client.remove_event_handler(handler)

    async def _click_button(self, entity, button_text: str, timeout: int) -> Optional[str]:
        async for message in self.client.iter_messages(entity, limit=5):
            if not message.buttons:
                continue
            for row in message.buttons:
                for button in row:
                    if button_text.lower() in (button.text or "").lower():
                        await message.click(text=button.text)
                        return await self._wait_for_reply(entity, timeout)
        log.warning("Button '%s' not found for %s", button_text, entity)
        return None
