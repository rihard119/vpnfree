"""Executes a target bot's step list from targets.yaml (the "bots:"
format) and returns every VPN link found during the whole run.

Supported step actions - all configured in targets.yaml, no code changes:
  - send:      {"action": "send", "text": "/start"}
  - wait:      {"action": "wait", "seconds": 2}
  - click:     {"action": "click", "text": "Get free trial", "timeout": 20}
  - subscribe: {"action": "subscribe", "chat": "@example_channel", "timeout": 20}
               {"action": "subscribe", "invite": "https://t.me/+xxxx"}
  - extract:   {"action": "extract"}   # scans everything received so far

Reliability rules:
  * The message handler is registered BEFORE the first send, so even an
    instant reply from the target bot cannot be missed, and it is removed
    in `finally` - on success, on error and on cancellation.
  * Only messages the target bot sent in its own chat are buffered;
    other chats/groups are ignored entirely.
  * `click` polls the target bot's recent history until a matching inline
    button appears (max `timeout` seconds, default DEFAULT_STEP_TIMEOUT),
    then clicks exactly that button. Matching is case-insensitive
    substring match on the button text.
  * `extract` scans EVERY message buffered during this run (not just the
    last one) and deduplicates links within the run.
  * Every step failure becomes ScenarioStepError with bot-readable detail.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from telethon import TelegramClient, errors as tg_errors, events, utils
from telethon.tl import functions, types

from parser import extract_links

log = logging.getLogger("interaction")

DEFAULT_STEP_TIMEOUT = 20      # seconds; click/subscribe default when no timeout given
CLICK_POLL_INTERVAL = 0.5      # how often to re-scan history while waiting for a button
CLICK_HISTORY_LIMIT = 10       # how far back click looks for the button


class ScenarioStepError(Exception):
    """Raised when a scenario step fails, carrying enough detail for
    the control bot to report exactly what went wrong."""

    def __init__(self, step_index: int, total_steps: int, action: str, reason: str,
                 button_text: Optional[str] = None, chat: Optional[str] = None):
        self.step_index = step_index
        self.total_steps = total_steps
        self.action = action
        self.reason = reason
        self.button_text = button_text
        self.chat = chat  # subscribe target ("chat" or "invite" from the step)
        super().__init__(f"Step {step_index}/{total_steps} ({action}) failed: {reason}")


@dataclass
class _RunState:
    messages: list = field(default_factory=list)
    new_message_event: asyncio.Event = field(default_factory=asyncio.Event)


def _describe_error(exc: BaseException) -> str:
    """Short, single-line, user-safe description of an exception."""
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    if isinstance(exc, tg_errors.FloodWaitError):
        return f"telegram flood wait: retry in {exc.seconds}s"
    if isinstance(exc, tg_errors.RPCError):
        return str(exc) or type(exc).__name__
    text = str(exc).strip()
    return text if text else type(exc).__name__


def _join_error_reason(exc: BaseException, chat: str) -> str:
    """Clear reason for a failed join/invite, without retrying anything."""
    if isinstance(exc, tg_errors.FloodWaitError):
        return f"telegram flood wait: retry in {exc.seconds}s"
    if isinstance(exc, (tg_errors.InviteHashExpiredError, tg_errors.InviteHashInvalidError)):
        return "unable to join channel: invite link is invalid or expired"
    if isinstance(exc, tg_errors.InviteRequestSentError):
        return ("unable to join channel: a join request was sent and needs "
                "approval - can not complete automatically")
    if isinstance(exc, tg_errors.ChannelPrivateError):
        return f"unable to join channel '{chat}': it is private or requires approval"
    if isinstance(exc, tg_errors.UsersTooMuchError):
        return f"unable to join channel '{chat}': participant limit reached"
    if isinstance(exc, tg_errors.UsernameNotOccupiedError):
        return f"unable to join channel: '{chat}' does not exist"
    return f"unable to join channel: {_describe_error(exc)}"


class ScenarioRunner:
    def __init__(self, client: TelegramClient):
        self.client = client

    async def run(self, username: str, steps: list, progress_cb=None) -> list[str]:
        """Runs the full step list against `username`. Returns the
        deduped list of VPN links found via any `extract` steps.
        Raises ScenarioStepError on the first failing step.

        progress_cb, if given, is called as
        ``await progress_cb(idx, total, step)`` before each step and as
        ``await progress_cb(idx, total, step, note="...")`` for extra
        status lines (e.g. subscribe results)."""

        try:
            entity = await self.client.get_entity(username)
        except Exception as exc:
            raise ScenarioStepError(
                0, len(steps), "connect",
                f"could not resolve bot '{username}': {_describe_error(exc)}",
            )

        state = _RunState()
        target_chat_id = utils.get_peer_id(entity)

        async def handler(event):
            # Only messages the target bot sent in its own chat with us.
            # Anything from other chats/groups is never buffered.
            if event.chat_id != target_chat_id:
                return
            if event.message.message:
                state.messages.append(event.message.message)
            state.new_message_event.set()

        # Registered BEFORE the first send so a fast reply cannot be missed;
        # removed in the finally block below - on success, error or cancel.
        self.client.add_event_handler(handler, events.NewMessage(from_users=entity))

        total = len(steps)
        collected_links: list[str] = []
        seen: set[str] = set()

        try:
            for idx, step in enumerate(steps, start=1):
                action = step.get("action")

                if progress_cb:
                    await progress_cb(idx, total, step)

                async def notify(note: str) -> None:
                    if progress_cb:
                        await progress_cb(idx, total, step, note=note)

                try:
                    if action == "send":
                        state.new_message_event.clear()
                        await self.client.send_message(entity, step["text"])

                    elif action == "wait":
                        await asyncio.sleep(step.get("seconds", 1))

                    elif action == "click":
                        await self._click(entity, state, step, notify)

                    elif action == "subscribe":
                        await self._subscribe(step, notify)

                    elif action == "extract":
                        for link in extract_links("\n".join(state.messages)):
                            if link not in seen:
                                seen.add(link)
                                collected_links.append(link)

                    else:
                        raise RuntimeError(f"unknown action '{action}'")

                except ScenarioStepError:
                    raise
                except Exception as exc:
                    button_text = step.get("text") if action == "click" else None
                    chat = None
                    if action == "subscribe":
                        chat = step.get("chat") or step.get("invite")
                    raise ScenarioStepError(
                        idx, total, action or "?", _describe_error(exc),
                        button_text=button_text, chat=chat,
                    )

            return collected_links

        finally:
            self.client.remove_event_handler(handler)

    # ---------------------------------------------------------------- click

    async def _click(self, entity, state: _RunState, step: dict, notify) -> None:
        """Waits up to `timeout` seconds for a matching inline button to
        appear in the target bot's recent messages, clicks it, then briefly
        waits (best-effort) for the bot's reply.

        Matching is a case-insensitive substring test against the visible
        button text: config "Получить" matches "Получить VPN",
        "Получить конфиг", "получить КЛЮЧ". Only the target bot's own
        messages are scanned, so buttons of other bots are never clicked."""
        needle = str(step["text"]).lower()
        timeout = step.get("timeout", DEFAULT_STEP_TIMEOUT)
        deadline = time.monotonic() + timeout

        while True:
            button = await self._find_button(entity, needle)
            if button is not None:
                state.new_message_event.clear()
                try:
                    await button.click()
                except Exception as exc:
                    raise RuntimeError(f"failed to click button: {_describe_error(exc)}")
                # Best-effort wait for the reaction: the reply is buffered
                # regardless (the handler stays registered), so a missing
                # reaction never fails the step - a later `wait`/`extract`
                # still sees the message.
                try:
                    await asyncio.wait_for(state.new_message_event.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    log.info("No reply after clicking %r - continuing", step["text"])
                return

            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"button matching '{step['text']}' not found within {timeout:g}s"
                )
            await asyncio.sleep(CLICK_POLL_INTERVAL)

    async def _find_button(self, entity, needle: str):
        """Returns the first matching button in the target bot's recent
        messages (newest first), or None. Scans only this bot's history."""
        async for message in self.client.iter_messages(entity, limit=CLICK_HISTORY_LIMIT):
            if not message.buttons:
                continue
            for row in message.buttons:
                for button in row:
                    text = (getattr(button, "text", None) or "").lower()
                    if needle in text:
                        return button
        return None

    # ------------------------------------------------------------ subscribe

    async def _subscribe(self, step: dict, notify) -> None:
        """Joins the configured chat with the USERBOT account (never the
        control bot), only if not already a member. The whole action -
        membership check, join and verification - is bounded by `timeout`
        (default DEFAULT_STEP_TIMEOUT). Any failure raises an error that
        becomes ScenarioStepError with a clear reason.

        Access control is never bypassed: if Telegram requires approval,
        CAPTCHA or any manual action, a clear error is returned instead."""
        target = step.get("chat") or step.get("invite")
        timeout = step.get("timeout", DEFAULT_STEP_TIMEOUT)
        try:
            await asyncio.wait_for(self._do_subscribe(step, notify), timeout=timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(f"subscribe to {target} timed out after {timeout:g}s")

    async def _do_subscribe(self, step: dict, notify) -> None:
        invite = step.get("invite")
        if invite:
            await self._subscribe_via_invite(str(invite), notify)
            return

        chat = str(step.get("chat"))
        username = chat[1:] if chat.startswith("@") else chat
        try:
            entity = await self.client.get_entity(username)
        except Exception as exc:
            raise RuntimeError(f"unable to resolve '{chat}': {_describe_error(exc)}")

        if isinstance(entity, types.User):
            raise RuntimeError(f"'{chat}' is a user account, not a channel/group")

        # 1. Already a member? -> success, no repeated join attempt.
        if await self._membership(entity) == "joined":
            await notify("Already subscribed")
            return

        # 2. Not a member -> join (only chats explicitly listed in the step).
        if not isinstance(entity, types.Channel):
            # Basic groups have no public username; they are reachable
            # through invite links only.
            raise RuntimeError(f"unable to join '{chat}': use an invite link for a basic group")
        try:
            await self.client(functions.channels.JoinChannelRequest(entity))
        except tg_errors.UserAlreadyParticipantError:
            await notify("Already subscribed")
            return
        except Exception as exc:
            raise RuntimeError(_join_error_reason(exc, chat))

        # 3. Verify the userbot really is a member now (best effort).
        membership = await self._membership(entity)
        if membership == "not_joined":
            raise RuntimeError(
                f"joined '{chat}' but the userbot is still not a member "
                f"(the channel may require approval)"
            )
        await notify("Successfully subscribed")

    async def _subscribe_via_invite(self, invite: str, notify) -> None:
        match = re.search(r"(?:\+|joinchat/)([A-Za-z0-9_-]+)", invite)
        if not match:
            raise RuntimeError(
                f"unsupported invite link '{invite}' (expected https://t.me/+hash)"
            )
        invite_hash = match.group(1)

        try:
            resp = await self.client(functions.messages.CheckChatInviteRequest(invite_hash))
        except Exception as exc:
            raise RuntimeError(f"unable to join channel: {_describe_error(exc)}")

        # 1. Already a member? -> success, no repeated join attempt.
        if isinstance(resp, types.ChatInviteAlready):
            await notify("Already subscribed")
            return

        # 2. Not a member -> import the invite (this performs the join).
        try:
            resp = await self.client(functions.messages.ImportChatInviteRequest(invite_hash))
        except tg_errors.UserAlreadyParticipantError:
            await notify("Already subscribed")
            return
        except Exception as exc:
            raise RuntimeError(_join_error_reason(exc, invite))

        # 3. Verify membership (best effort).
        chats = getattr(resp, "chats", None) or []
        if chats:
            membership = await self._membership(chats[0])
            if membership == "not_joined":
                raise RuntimeError(
                    f"joined '{invite}' but the userbot is still not a member "
                    f"(approval may be required)"
                )
        await notify("Successfully subscribed")

    async def _membership(self, entity) -> str:
        """Best-effort membership check: 'joined' / 'not_joined' / 'unknown'.

        Uses the dialog list (every joined chat is always present there).
        Falls back to the channel's `left` flag if the scan fails. Never
        bypasses any access control."""
        try:
            target = utils.get_peer_id(entity)
            async for dialog in self.client.iter_dialogs():
                if dialog.id == target:
                    return "joined"
            return "not_joined"
        except tg_errors.FloodWaitError:
            raise  # must reach ScenarioStepError - do not retry silently
        except Exception as exc:
            log.debug("membership check failed for %s: %s",
                      getattr(entity, "id", "?"), _describe_error(exc))
            if getattr(entity, "left", None) is True:
                return "not_joined"
            return "unknown"
