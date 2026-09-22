"""Loads targets.yaml, validates it, and runs one scenario at a time.

The file is re-read on every command, so adding/editing bots takes effect
without a restart. Only YAML changes are needed to add a new bot - the
Python code never has to change.
"""

import asyncio
import logging
from pathlib import Path

import yaml
from telethon import TelegramClient

import storage
from interaction import ScenarioRunner

log = logging.getLogger("orchestrator")

TARGETS_PATH = Path(__file__).parent / "targets.yaml"

ACTIONS = ("send", "wait", "click", "extract", "subscribe")


class ConfigError(Exception):
    """targets.yaml is unreadable or malformed. The message is already
    formatted for the control chat: bot id + step + field, e.g.
    "bot-1: step 3: action 'click' requires field 'text'". """


class ScenarioAlreadyRunning(Exception):
    """The same bot_id is still executing its previous scenario."""

    def __init__(self, bot_id: str):
        self.bot_id = bot_id
        super().__init__(f"{bot_id} is already running")


def load_bots(path: Path = TARGETS_PATH) -> dict:
    """Returns the {bot_id: {"username": ..., "steps": [...]}} mapping
    from the "bots:" section of targets.yaml. Reloaded fresh on every
    call, so editing the file takes effect without restarting.
    Raises ConfigError on any structural/YAML problem."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"{path.name} not found") from None
    except OSError as exc:
        raise ConfigError(f"cannot read {path.name}: {exc}") from None

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        detail = str(exc).replace("\n", " ")
        raise ConfigError(f"{path.name} is not valid YAML: {detail}") from None

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name}: top level must be a mapping with a 'bots:' section")
    bots = data.get("bots")
    if bots is None:
        return {}
    if not isinstance(bots, dict):
        raise ConfigError(f"{path.name}: 'bots' must be a mapping of bot-id -> scenario")
    return bots


def validate_bot(bot_id: str, cfg) -> list:
    """Returns a list of human-readable problems for one bot entry
    (empty list means the entry is valid). Errors look like:
    "bot-1: step 3: action 'click' requires field 'text'". """
    if not isinstance(cfg, dict):
        return [f"{bot_id}: must be a mapping with 'username' and 'steps'"]

    errors = []

    username = cfg.get("username")
    if username is None:
        errors.append(f"{bot_id}: missing required field 'username'")
    elif not isinstance(username, str) or not username.strip():
        errors.append(f"{bot_id}: field 'username' must be a non-empty string")

    steps = cfg.get("steps")
    if steps is None:
        errors.append(f"{bot_id}: missing required field 'steps'")
    elif not isinstance(steps, list) or not steps:
        errors.append(f"{bot_id}: field 'steps' must be a non-empty list")
    else:
        for i, step in enumerate(steps, start=1):
            errors.extend(_validate_step(bot_id, i, step))

    return errors


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_step(bot_id: str, index: int, step) -> list:
    prefix = f"{bot_id}: step {index}"

    if not isinstance(step, dict):
        return [f"{prefix}: must be a mapping with an 'action' field"]

    action = step.get("action")
    if action is None:
        return [f"{prefix}: missing required field 'action'"]
    if not isinstance(action, str):
        return [f"{prefix}: field 'action' must be a string"]
    if action not in ACTIONS:
        return [f"{prefix}: unknown action '{action}' "
                f"(expected one of: {', '.join(ACTIONS)})"]

    errors = []

    if action in ("send", "click"):
        text = step.get("text")
        if text is None:
            errors.append(f"{prefix}: action '{action}' requires field 'text'")
        elif not isinstance(text, str) or not text.strip():
            errors.append(f"{prefix}: field 'text' must be a non-empty string")

    if action == "wait":
        seconds = step.get("seconds")
        if seconds is not None and (not _is_number(seconds) or seconds < 0):
            errors.append(f"{prefix}: field 'seconds' must be a number >= 0")

    if action in ("click", "subscribe"):
        timeout = step.get("timeout")
        if timeout is not None and (not _is_number(timeout) or timeout <= 0):
            errors.append(f"{prefix}: field 'timeout' must be a positive number")

    if action == "subscribe":
        chat = step.get("chat")
        invite = step.get("invite")
        if not chat and not invite:
            errors.append(f"{prefix}: action 'subscribe' requires field 'chat' or 'invite'")
        if chat is not None and (not isinstance(chat, str) or not chat.strip()):
            errors.append(f"{prefix}: field 'chat' must be a non-empty string "
                          f'(e.g. "@example_channel")')
        if invite is not None and (not isinstance(invite, str) or not invite.strip()):
            errors.append(f"{prefix}: field 'invite' must be a non-empty invite link "
                          f'(e.g. "https://t.me/+xxxx")')

    return errors


def validate_bots(bots: dict) -> None:
    """Validates every entry; raises ConfigError listing ALL problems."""
    errors = []
    for bot_id, cfg in bots.items():
        errors.extend(validate_bot(str(bot_id), cfg))
    if errors:
        raise ConfigError("\n".join(errors))


# --- per-bot run lock -------------------------------------------------------
# One scenario per bot_id at a time: two concurrent runs against the same
# target would otherwise mix their message handlers/answers. Different
# bot_ids may run in parallel safely (each run registers its own handler
# filtered to its own chat).

_locks: dict = {}


def _lock_for(bot_id: str) -> asyncio.Lock:
    lock = _locks.get(bot_id)
    if lock is None:
        lock = _locks[bot_id] = asyncio.Lock()
    return lock


def is_running(bot_id: str) -> bool:
    """True while a scenario for this bot_id is still executing."""
    return _lock_for(bot_id).locked()


async def run_scenario(client: TelegramClient, bot_id: str, progress_cb=None) -> dict:
    """Runs the named scenario and saves any VLESS links found.
    Returns {"found": n, "saved": n} where found = unique vless:// links
    seen during this run and saved = links that were actually new in the
    database.

    Raises KeyError if bot_id isn't configured, ConfigError if its config
    is invalid, ScenarioAlreadyRunning if it is already running, or
    ScenarioStepError (from interaction.py) if a step fails.
    """
    bots = load_bots()
    if bot_id not in bots:
        raise KeyError(bot_id)

    errors = validate_bot(bot_id, bots[bot_id])
    if errors:
        raise ConfigError("\n".join(errors))

    lock = _lock_for(bot_id)
    if lock.locked():
        raise ScenarioAlreadyRunning(bot_id)

    async with lock:  # no await between locked() and acquire -> no race
        target = bots[bot_id]
        runner = ScenarioRunner(client)
        links = await runner.run(target["username"], list(target["steps"]),
                                 progress_cb=progress_cb)

        saved = 0
        for link in links:
            if storage.save_link(link, source_bot=bot_id):
                saved += 1

        log.info("%s: found %d unique link(s), saved %d new", bot_id, len(links), saved)
        return {"found": len(links), "saved": saved}
