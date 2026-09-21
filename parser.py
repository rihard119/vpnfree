"""Extracts only vless:// links from a message. Everything else is ignored."""

import re

# Stops at whitespace or a backtick (Telegram often wraps configs in code blocks).
VLESS_RE = re.compile(r"vless://[^\s`]+")


def extract_vless_links(text: str) -> list[str]:
    if not text:
        return []
    return VLESS_RE.findall(text)
