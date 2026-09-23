"""Извлечение VLESS-ссылок и URL подписок VPN-сервисов из текста."""

import re
from urllib.parse import urlsplit

# Останавливаемся на пробельных символах и обратных кавычках: Telegram
# часто отправляет конфигурации в code block.
VLESS_RE = re.compile(r"vless://[^\s`]+")
LINK_RE = re.compile(r"(?:vless|https?)://[^\s`]+", re.IGNORECASE)

_TRAILING_PUNCTUATION = ".,;:!?…'\""
_CLOSING_BRACKETS = {")": "(", "]": "[", "}": "{"}


def _trim_url_punctuation(url: str) -> str:
    """Убирает пунктуацию вокруг URL, не обрезая сбалансированные скобки."""
    previous = None
    while url != previous:
        previous = url
        url = url.rstrip(_TRAILING_PUNCTUATION)
        for closing, opening in _CLOSING_BRACKETS.items():
            while url.endswith(closing) and url.count(closing) > url.count(opening):
                url = url[:-1]
    return url


def _is_subscription_url(url: str) -> bool:
    """Проверяет домен и наличие отдельного path-сегмента ``sub``."""
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme.lower() in ("http", "https")
            and bool(parsed.hostname)
            and any(segment.casefold() == "sub" for segment in parsed.path.split("/"))
        )
    except ValueError:
        return False


def extract_vless_links(text: str) -> list[str]:
    """Извлекает только VLESS-ссылки (сохранённый интерфейс API)."""
    if not text:
        return []
    return VLESS_RE.findall(text)


def extract_links(text: str) -> list[str]:
    """Извлекает VLESS-ссылки и HTTP(S)-URL подписок без повторов.

    Subscription URL принимается, только если ``sub`` является отдельным
    сегментом пути. Домен и query string не ограничиваются. Порядок первого
    появления ссылок в тексте сохраняется.
    """
    if not text:
        return []

    links = []
    seen = set()
    for match in LINK_RE.finditer(text):
        link = _trim_url_punctuation(match.group())
        is_vless = link.lower().startswith("vless://")
        if not is_vless and not _is_subscription_url(link):
            continue
        if link not in seen:
            seen.add(link)
            links.append(link)

    return links
