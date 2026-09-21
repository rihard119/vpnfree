"""Converts a Telegram Desktop 'tdata' folder (an already-logged-in
session) into a Telethon .session file, using Telegram Desktop's own
official api_id/api_hash. This lets you skip registering your own
app on my.telegram.org/apps.

Usage:
    1. Make sure Telegram Desktop is installed and logged in on some
       machine (yours or a VM). Locate its tdata folder:
         Windows: %AppData%\\Telegram Desktop\\tdata
         Linux:   ~/.local/share/TelegramDesktop/tdata
         macOS:   ~/Library/Application Support/Telegram Desktop/tdata
    2. Copy that tdata folder to this machine if needed.
    3. Set TDATA_PATH below.
    4. pip install opentele
    5. Run: python -m vless_collector.tools.convert_tdata
    6. Copy the printed api_id / api_hash into your .env, and set
       TG_USER_SESSION to the session name printed below.
"""

import asyncio

from opentele.api import UseCurrentSession
from opentele.td import TDesktop
from opentele.tl import TelegramClient

TDATA_PATH = r"PUT_PATH_TO_TDATA_HERE"
SESSION_NAME = "user_session"


async def main() -> None:
    tdesk = TDesktop(TDATA_PATH)
    if not tdesk.isLoaded():
        raise RuntimeError(
            "Could not load tdata - check TDATA_PATH and make sure "
            "Telegram Desktop there is fully logged in (not just installed)."
        )

    client: TelegramClient = await tdesk.ToTelethon(session=SESSION_NAME, flag=UseCurrentSession)
    await client.connect()

    me = await client.get_me()
    print(f"Converted session for: {me.first_name} (@{me.username})")
    print(f"api_id:   {client.api.api_id}")
    print(f"api_hash: {client.api.api_hash}")
    print(f"Session file created: {SESSION_NAME}.session")
    print()
    print("Next steps:")
    print(f"  1. In .env set TG_API_ID={client.api.api_id}")
    print(f"  2. In .env set TG_API_HASH={client.api.api_hash}")
    print(f"  3. In .env set TG_USER_SESSION={SESSION_NAME}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
