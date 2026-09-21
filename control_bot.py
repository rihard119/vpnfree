"""Admin-only control bot. Register these handlers on a Bot-API client
(separate from the userbot client used to talk to the trial bots)."""

import logging

from telethon import TelegramClient, events

import storage
from orchestrator import run_collection

log = logging.getLogger("control_bot")

MAX_MESSAGE_CHARS = 3500


def register_handlers(bot: TelegramClient, user_client: TelegramClient, admin_id: int) -> None:
    def is_admin(event) -> bool:
        return event.sender_id == admin_id

    @bot.on(events.NewMessage(pattern="/count"))
    async def count_handler(event):
        if not is_admin(event):
            return
        await event.respond(f"Collected links: {storage.count_links()}")

    @bot.on(events.NewMessage(pattern="/links"))
    async def links_handler(event):
        if not is_admin(event):
            return
        rows = storage.get_all_links()
        if not rows:
            await event.respond("No links collected yet.")
            return

        chunk, length = [], 0
        for link, source, ts in rows:
            line = f"{link}  ({source}, {ts})"
            if length + len(line) > MAX_MESSAGE_CHARS:
                await event.respond("\n".join(chunk))
                chunk, length = [], 0
            chunk.append(line)
            length += len(line)
        if chunk:
            await event.respond("\n".join(chunk))

    @bot.on(events.NewMessage(pattern="/export"))
    async def export_handler(event):
        if not is_admin(event):
            return
        rows = storage.get_all_links()
        if not rows:
            await event.respond("No links collected yet.")
            return
        path = "/tmp/vless_export.txt"
        with open(path, "w", encoding="utf-8") as f:
            for link, _, _ in rows:
                f.write(link + "\n")
        await bot.send_file(event.chat_id, path, caption="Exported VLESS links")

    @bot.on(events.NewMessage(pattern="/run"))
    async def run_handler(event):
        if not is_admin(event):
            return
        await event.respond("Running collection pass...")
        results = await run_collection(user_client)
        msg = (
            f"Done.\nNew links: {results['new_links']}\n"
            f"Duplicates skipped: {results['duplicates']}\n"
        )
        if results["failures"]:
            msg += "Failures:\n" + "\n".join(results["failures"])
        await event.respond(msg)

    @bot.on(events.NewMessage(pattern="/status"))
    async def status_handler(event):
        if not is_admin(event):
            return
        await event.respond(f"Alive. Links stored: {storage.count_links()}")
