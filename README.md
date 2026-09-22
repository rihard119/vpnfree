# VLESS Trial Collector

Telegram userbot that runs named scenarios (`/bot-1`, `/bot-2`, ...)
against VPN-trial bots defined in `targets.yaml`, extracts only
`vless://` links seen during the whole scenario, dedupes them in
SQLite, and reports progress/results through a separate control bot.

## Setup

1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in:
   - `TG_API_ID` / `TG_API_HASH` from https://my.telegram.org/apps
   - `TG_BOT_TOKEN` - create a bot via @BotFather (this is the control bot you talk to)
   - `TG_ADMIN_ID` - your numeric Telegram user ID (e.g. via @userinfobot)
   - Optional `PROXY_*` vars if the userbot needs to connect through a SOCKS5 proxy
3. Edit `targets.yaml` - each key under `bots:` becomes a command
   (`bot-1` -> `/bot-1`). See the file for the step format
   (`send` / `wait` / `click` / `subscribe` / `extract`).
4. Run: `python main.py`
   - First run asks for your phone number and login code (this is your
     real account - treat the `.session` file like a password).
   - `targets.yaml` is validated at startup; problems are also reported
     by the control bot before any scenario starts.

## Using it

Message your control bot from your admin account:

- `/bot-1`, `/bot-2`, ... - run the matching scenario from `targets.yaml`,
  with live step-by-step progress and a found/saved summary at the end
- `/list` - show every configured scenario command and its target username
- `/links` - list all collected VLESS links
- `/count` - how many are stored
- `/export` - sends a `.txt` file of all links
- `/status` - quick liveness check
- `/help` - command overview

Editing `targets.yaml` takes effect immediately - no restart needed,
since it's re-read on every command. Commands that are **not** in
`targets.yaml` never start anything (you just get a hint to use `/list`).

## Step actions (targets.yaml)

```yaml
bots:
  bot-1:
    username: example_vpn_bot
    steps:
      - action: send
        text: "/start"
      - action: wait
        seconds: 2
      - action: subscribe          # optional: join a channel first
        chat: "@example_channel"
        timeout: 20                # optional, default 20s
      - action: wait
        seconds: 2
      - action: click
        text: "Получить VPN"
        timeout: 20        # optional, seconds to wait for the button to appear
      - action: wait
        seconds: 3
      - action: extract     # scans every message seen so far for vless:// links
```

- `send` - sends a text message/command to the target bot
- `wait` - sleeps for N seconds
- `click` - waits (up to `timeout`, default 20s) for one of the target
  bot's recent messages to contain an inline button whose visible text
  **contains** the configured string, case-insensitively
  (`"Получить"` matches `Получить VPN`, `Получить конфиг`, `получить КЛЮЧ`),
  then clicks exactly that button. Buttons of other bots are never clicked.
  If no matching button appears within the timeout, the scenario fails
  with a `ScenarioStepError` naming the step and the button.
- `subscribe` - joins `chat:` (public `@username`) or `invite:` (private
  `https://t.me/+hash` link) **with the userbot account**, but only when the
  userbot is not already a member; membership is verified afterwards.
  The control bot prints e.g. `[3/7] Subscribing to @vpn_news` followed by
  `[3/7] Already subscribed` or `[3/7] Successfully subscribed`.
  Whole action is bounded by `timeout` (default 20s). FloodWait, expired
  invites, approval-required channels, etc. stop the scenario with a clear
  reason - nothing is ever retried in a loop and no access control is
  bypassed. Only chats explicitly listed in `targets.yaml` are joined.
- `extract` - searches **every** message received from the target bot
  during this scenario run (not just the latest one, and nothing from
  other chats) for `vless://` links, dedupes them within the run and
  saves them via `storage.save_link()`. The final report shows
  `Found:` (unique links in this run) and `Saved:` (links that were new
  in the database).

If any step fails (button not found, timeout, Telegram error, etc.),
the control bot reports exactly which step and why, e.g.:

```
bot-1 failed.

Step: 3/7
Action: click
Button: "Получить VPN"
Reason: button matching 'Получить VPN' not found within 20s
```

Config errors are caught **before** the scenario starts:

```
Config error:
bot-1: step 3: action 'click' requires field 'text'
```

## Concurrency

- Different `bot_id`s may run at the same time (each run has its own
  message handler, filtered to its own target chat).
- The **same** `bot_id` cannot be started a second time while its previous
  run is still executing - you get `"... is already running"` instead.
- Message handlers are always removed when a scenario ends - on success,
  on error and on cancellation.

## Failure handling

No scenario failure can take down the control bot. Handled explicitly:
Telegram API/RPC errors (incl. FloodWait), timeouts, missing target bot,
impossible sends, missing buttons, malformed YAML, missing/invalid
required fields, and arbitrary unexpected exceptions. Tracebacks go only
to the server-side log; replies in the control chat are short and have
filesystem paths / token-like strings redacted.

## Notes / limitations

- Trial bots are generally meant for one claim per person - keep the
  target list modest and avoid running scenarios aggressively against
  the same bots repeatedly, since that's likely to violate their terms.
- A `click` step matches the **first** button (newest message first,
  up to 10 messages back) whose visible text contains the given string.
  If a bot reuses similar button text across different menus, make the
  match string more specific.
- If a bot sends its VLESS link as a *button* rather than message text
  (deep link, WebApp button, etc.), `extract` won't see it - only
  plain message text is scanned.
- `subscribe` requires the chat to be joinable by a normal user (public
  username, or a valid invite link). Chats needing manual approval stop
  the scenario with a clear error instead of trying to bypass it.
- The userbot session is your real Telegram account. Keep the VPS/PC
  it runs on secured, and keep `.env` and `.session` files out of
  version control (`.gitignore` already covers `.env`, `*.session`,
  `*.db`; if `venv311/` was ever committed, untrack it once with
  `git rm -r --cached venv311`).
- No secrets live in the Python code - everything comes from `.env`.
