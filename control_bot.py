"""Admin-only control bot. Register these handlers on a Bot-API client
(separate from the userbot client used to talk to the trial bots).

Scenario commands (/bot-1, /bot-2, ...) are matched dynamically against
whatever is currently in targets.yaml - no code change or restart
needed to pick up a newly added bot entry.

Every failure (config error, Telegram error, timeout, missing button,
unexpected exception) is converted into a short human-readable reply in
the control chat. Tracebacks and sensitive details (filesystem paths,
tokens) only go to the server-side log, never to the user.
"""

import logging
import os
import re
import tempfile
from pathlib import Path

from telethon import TelegramClient, events

import storage
from interaction import ScenarioStepError
from orchestrator import (ConfigError, ScenarioAlreadyRunning, is_running,
                          load_bots, run_scenario, validate_bot, validate_bots)

log = logging.getLogger("control_bot")

MAX_MESSAGE_CHARS = 3500
MAX_REASON_CHARS = 500
COMMAND_RE = re.compile(r"^/([\w-]+)(?:@\w+)?$")

# Commands with their own handlers (or built into Telegram). They are never
# treated as scenario ids - even if someone names a bot "count" in yaml.
RESERVED_COMMANDS = {"count", "links", "export", "status", "list", "start", "help"}

HELP_TEXT = (
    "Commands:\n"
    "/bot-1, /bot-2, ... - run the matching scenario from targets.yaml\n"
    "/list - show configured scenarios\n"
    "/links - list collected VLESS links\n"
    "/count - how many links are stored\n"
    "/export - send all links as a .txt file\n"
    "/status - liveness check"
)

# Windows drive paths, unix-like absolute paths, Telegram bot tokens.
_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s'\"]+|/(?:[\w.-]+/)+[\w.-]+")
_TOKEN_RE = re.compile(r"\d{6,}:[A-Za-z0-9_-]{25,}")


def _redact(text) -> str:
    """Removes anything sensitive from text that is about to be shown in
    the control chat: filesystem paths (last component only) and
    token-like strings. Newlines are preserved."""
    text = str(text)
    text = _TOKEN_RE.sub("[redacted]", text)
    text = _PATH_RE.sub(
        lambda m: m.group(0).replace("\\", "/").rstrip("\"'").rsplit("/", 1)[-1],
        text,
    )
    return text


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _progress_line(idx: int, total: int, step: dict, note=None) -> str:
    if note:
        return f"[{idx}/{total}] {note}"
    action = step.get("action")
    if action == "send":
        text = f'Sending "{step.get("text")}"'
    elif action == "wait":
        text = f"Waiting {step.get('seconds', 1)} seconds"
    elif action == "click":
        text = f'Clicking "{step.get("text")}"'
    elif action == "subscribe":
        text = f"Subscribing to {step.get('chat') or step.get('invite')}"
    elif action == "extract":
        text = "Extracting VLESS links"
    else:
        text = str(action or "?")
    return f"[{idx}/{total}] {text}"


async def _respond(event, text: str) -> None:
    """Best-effort reply: a failed send is logged, never raised, so a
    Telegram API hiccup can not kill a running scenario or the bot."""
    try:
        await event.respond(text)
    except Exception:
        log.exception("Could not send a reply to the control chat")


def register_handlers(bot: TelegramClient, user_client: TelegramClient, admin_id: int) -> None:
    def is_admin(event) -> bool:
        return event.sender_id == admin_id

    @bot.on(events.NewMessage(pattern="/count"))
    async def count_handler(event):
        if not is_admin(event):
            return
        await _respond(event, f"Collected links: {storage.count_links()}")

    @bot.on(events.NewMessage(pattern="/links"))
    async def links_handler(event):
        if not is_admin(event):
            return
        rows = storage.get_all_links()
        if not rows:
            await _respond(event, "No links collected yet.")
            return
        chunk, length = [], 0
        for link, source, ts in rows:
            line = f"{link}  ({source}, {ts})"
            if length + len(line) > MAX_MESSAGE_CHARS:
                await _respond(event, "\n".join(chunk))
                chunk, length = [], 0
            chunk.append(line)
            length += len(line)
        if chunk:
            await _respond(event, "\n".join(chunk))

    @bot.on(events.NewMessage(pattern="/export"))
    async def export_handler(event):
        if not is_admin(event):
            return
        rows = storage.get_all_links()
        if not rows:
            await _respond(event, "No links collected yet.")
            return
        path = Path(tempfile.gettempdir()) / "vless_export.txt"
        try:
            path.write_text("\n".join(link for link, _, _ in rows) + "\n",
                            encoding="utf-8")
            await bot.send_file(event.chat_id, path, caption="Exported VLESS links")
        except Exception:
            log.exception("Export failed")
            await _respond(event, "Export failed - see the server log for details.")

    @bot.on(events.NewMessage(pattern="/status"))
    async def status_handler(event):
        if not is_admin(event):
            return
        await _respond(event, f"Alive. Links stored: {storage.count_links()}")

    @bot.on(events.NewMessage(pattern="/list"))
    async def list_bots_handler(event):
        if not is_admin(event):
            return
        try:
            bots = load_bots()
        except ConfigError as exc:
            await _respond(event, f"targets.yaml error:\n{_redact(str(exc))}")
            return
        if not bots:
            await _respond(event, "No target bots configured in targets.yaml.")
            return
        lines = [f"/{bot_id} -> {cfg.get('username') if isinstance(cfg, dict) else '?'}"
                 for bot_id, cfg in bots.items()]
        try:
            validate_bots(bots)
        except ConfigError as exc:
            lines.append("")
            lines.append("Config errors:")
            lines.append(_redact(str(exc)))
        await _respond(event, "Available scenarios:\n" + "\n".join(lines))

    @bot.on(events.NewMessage(pattern=COMMAND_RE))
    async def scenario_handler(event):
        if not is_admin(event):
            return

        command = event.pattern_match.group(1)

        if command in ("start", "help"):
            await _respond(event, HELP_TEXT)
            return
        if command in RESERVED_COMMANDS:
            return  # has its own handler - never run as a scenario

        # Re-read targets.yaml on every command.
        try:
            bots = load_bots()
        except ConfigError as exc:
            await _respond(event, f"targets.yaml error:\n{_redact(str(exc))}")
            return

        if command not in bots:
            # Not configured -> never launch anything.
            await _respond(event, f"Unknown scenario '/{command}'.\n"
                                  f"Use /list to see configured scenarios.")
            return

        errors = validate_bot(command, bots[command])
        if errors:
            await _respond(event, "Config error:\n"
                                  + "\n".join(_redact(e) for e in errors))
            return

        if is_running(command):
            await _respond(event, f"{command} is already running - "
                                  f"wait for it to finish.")
            return

        async def progress_cb(idx, total_steps, step, note=None):
            await _respond(event, _progress_line(idx, total_steps, step, note))

        username = bots[command]["username"]
        await _respond(event, f"Starting {command} (target @{username})...")

        try:
            result = await run_scenario(user_client, command, progress_cb=progress_cb)

        except ScenarioAlreadyRunning:
            await _respond(event, f"{command} is already running - "
                                  f"wait for it to finish.")
            return

        except ConfigError as exc:
            await _respond(event, f"Config error:\n{_redact(str(exc))}")
            return

        except KeyError:
            await _respond(event, f"'{command}' disappeared from targets.yaml - "
                                  f"try again.")
            return

        except ScenarioStepError as exc:
            lines = [
                f"{command} failed.",
                "",
                f"Step: {exc.step_index}/{exc.total_steps}",
                f"Action: {exc.action}",
            ]
            if exc.button_text:
                lines.append(f'Button: "{_redact(str(exc.button_text))}"')
            if exc.chat:
                lines.append(f"Chat: {_redact(str(exc.chat))}")
            lines.append(f"Reason: {_clip(_redact(exc.reason), MAX_REASON_CHARS)}")
            await _respond(event, "\n".join(lines))
            return

        except Exception as exc:
            # Catch-all so one bad target never takes down the control bot.
            # Full traceback goes to the server log only; the chat gets a
            # short message with paths/tokens redacted.
            log.exception("Unexpected error running scenario %s", command)
            detail = _clip(_redact(f"{type(exc).__name__}: {exc}"), MAX_REASON_CHARS)
            await _respond(event, f"{command} failed.\n\nUnexpected error: {detail}")
            return

        await _respond(
            event,
            f"Found: {result['found']}\n"
            f"Saved: {result['saved']}\n\n"
            f"{command} completed successfully.",
        )
