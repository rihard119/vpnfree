# VLESS Trial Collector

Telegram userbot that visits a list of VPN-trial bots, extracts only
`vless://` links from their replies, dedupes them in SQLite, and lets
you retrieve them through a separate control bot.

## Setup

1. `pip install -r requirements.txt`
2. Get `TG_API_ID` / `TG_API_HASH` one of two ways:
   - **Normal way:** register at https://my.telegram.org/apps
   - **tdata way** (if that form errors out for you): use an existing,
     already-logged-in Telegram Desktop install and convert its
     session directly - see "Using tdata instead of my.telegram.org" below.
     This skips the registration form entirely.
3. Fill in the rest of `.env`:
   - `TG_BOT_TOKEN` - create a bot via @BotFather (this is the control bot you talk to)
   - `TG_ADMIN_ID` - your numeric Telegram user ID (e.g. via @userinfobot)
4. Edit `targets.yaml` with the real VPN-trial bots you want to use and their actual flows (button text, commands). You'll likely need to test each one manually first to see its exact steps.
5. Run once from the parent directory: `python -m vless_collector.main`
   - If you registered normally, first run will ask for your phone number and login code.
   - If you used the tdata conversion, the session is already authorized - it will just connect.
   - Either way, this is your real account - treat the `.session` file like a password.

## Using tdata instead of my.telegram.org

If the registration form on my.telegram.org keeps erroring, you can
reuse an already-logged-in Telegram Desktop installation instead:

1. Log in to Telegram Desktop somewhere (your PC, or a fresh install)
   and find its `tdata` folder:
   - Windows: `%AppData%\Telegram Desktop\tdata`
   - Linux: `~/.local/share/TelegramDesktop/tdata`
   - macOS: `~/Library/Application Support/Telegram Desktop/tdata`
2. Copy that folder to the machine running this project if it's not
   already there.
3. Open `tools/convert_tdata.py` and set `TDATA_PATH` to that folder's path.
4. Run: `python -m vless_collector.tools.convert_tdata`
5. It prints an `api_id` / `api_hash` (Telegram Desktop's own official
   ones) and creates a `.session` file. Put those values into `.env`
   as `TG_API_ID`, `TG_API_HASH`, and `TG_USER_SESSION`.
6. Run `python -m vless_collector.main` as usual - no phone/code prompt needed, it's already authorized.

Note: this reuses Telegram Desktop's official app credentials rather
than your own registered app. It's a common workaround, but it does
mean the userbot is presenting itself as Telegram Desktop under the
hood - worth knowing in case that ever matters for how the account behaves.

## Using it

Message your control bot (the `TG_BOT_TOKEN` one) from your admin account:

- `/run` - runs through all targets in `targets.yaml` once, reports new/duplicate/failed
- `/links` - lists all collected VLESS links
- `/count` - how many are stored
- `/export` - sends a `.txt` file of all links
- `/status` - quick liveness check

## Scheduling

For periodic runs, add a cron job or systemd timer that sends `/run`
to the control bot, or extend `main.py` with an `asyncio` loop that
calls `run_collection()` directly on a schedule instead of waiting for
a manual `/run`.

## Notes / limitations

- Each target bot's `steps` in `targets.yaml` is a best-effort script.
  Real bots vary (multi-step menus, captchas, delays) - expect to
  adjust `interaction.py` or the steps for tricky ones.
- Only `vless://...` text is ever extracted or stored - any other
  protocol/config in a reply is ignored.
- Trial bots are generally meant for one claim per person - keep the
  target list modest and avoid running it aggressively against the
  same bots repeatedly, since that's likely to violate their terms.
- The userbot session is your real Telegram account. Keep the VPS it
  runs on secured, and keep `.env` and the `.session` files out of
  version control.
