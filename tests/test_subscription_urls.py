"""Тесты извлечения VLESS-ссылок и subscription URL."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from telethon.tl import types

import storage
from interaction import ScenarioRunner
from parser import extract_links, extract_vless_links


class ExtractLinksTests(unittest.TestCase):
    def test_01_vless_link(self):
        link = "vless://user@example.com:443?type=ws#profile"
        self.assertEqual(extract_links(link), [link])
        self.assertEqual(extract_vless_links(link), [link])

    def test_02_known_subscription_url(self):
        url = "https://midas-vpn.org/sub?id=C6OiHkRq8IkGmVWcBVoLUQ"
        self.assertEqual(extract_links(url), [url])

    def test_03_unknown_domain_with_sub(self):
        url = "https://random-domain.net/sub?token=XYZ"
        self.assertEqual(extract_links(url), [url])

    def test_04_api_sub_path(self):
        url = "https://vpn.example.org/api/sub/123"
        self.assertEqual(extract_links(url), [url])

    def test_05_nested_sub_path_with_query(self):
        url = "https://another-vpn.com/path/sub?id=456"
        self.assertEqual(extract_links(url), [url])

    def test_06_subscribe_is_not_subscription(self):
        self.assertEqual(extract_links("https://example.com/subscribe"), [])

    def test_07_submit_is_not_subscription(self):
        self.assertEqual(extract_links("https://example.com/submit"), [])

    def test_08_ordinary_http_links_are_ignored(self):
        text = "\n".join((
            "https://google.com",
            "https://youtube.com",
            "https://t.me/example",
            "https://example.com/about",
        ))
        self.assertEqual(extract_links(text), [])

    def test_09_markdown_link(self):
        url = "https://midas-vpn.org/sub?id=ABC123"
        text = f"[Получить подписку]({url})"
        self.assertEqual(extract_links(text), [url])

    def test_10_query_parameters_are_preserved(self):
        urls = (
            "https://example.com/sub?id=ABC123",
            "https://example.com/sub?token=XYZ",
            "https://example.com/sub?client=123&key=ABC",
        )
        self.assertEqual(extract_links("\n".join(urls)), list(urls))

    def test_11_surrounding_punctuation_is_removed(self):
        url = "https://example.com/sub?id=ABC123"
        text = "\n".join((f"{url}.", f"({url})"))
        self.assertEqual(extract_links(text), [url])

    def test_12_duplicate_subscription_url_is_returned_once(self):
        url = "https://example.com/sub?id=ABC123"
        self.assertEqual(extract_links(f"{url}\n{url}"), [url])

    def test_13_vless_and_subscription_in_one_message(self):
        vless = "vless://user@example.com:443#config"
        subscription = "https://example.net/sub?id=123"
        self.assertEqual(
            extract_links(f"{subscription}\n{vless}"),
            [subscription, vless],
        )

    def test_sub_must_be_a_complete_segment(self):
        text = "\n".join((
            "https://sub.example.com/path",
            "https://example.com/download?next=/sub",
            "https://example.com/submission",
        ))
        self.assertEqual(extract_links(text), [])


class _FakeClient:
    def __init__(self, messages):
        self.entity = types.User(id=1001, bot=True, first_name="Target")
        self.messages = messages
        self.handlers = []

    async def get_entity(self, _username):
        return self.entity

    def add_event_handler(self, handler, _builder=None):
        self.handlers.append(handler)

    def remove_event_handler(self, handler):
        self.handlers = [item for item in self.handlers if item is not handler]

    async def send_message(self, _entity, _text):
        for message in self.messages:
            event = SimpleNamespace(
                chat_id=self.entity.id,
                message=SimpleNamespace(message=message),
            )
            for handler in list(self.handlers):
                await handler(event)


class ScenarioHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_14_extract_scans_messages_from_whole_scenario(self):
        vless = "vless://one@example.com:443#one"
        first_subscription = "https://domain1.com/sub?id=1"
        second_subscription = "https://domain2.com/api/sub/2"
        client = _FakeClient([
            f"first: {vless}",
            f"second: {first_subscription}",
            f"third: {second_subscription}",
        ])

        links = await ScenarioRunner(client).run(
            "target_bot",
            [{"action": "send", "text": "/start"}, {"action": "extract"}],
        )

        self.assertEqual(links, [vless, first_subscription, second_subscription])
        self.assertEqual(client.handlers, [])


class StorageCompatibilityTests(unittest.TestCase):
    def test_subscription_uses_existing_unique_links_table(self):
        url = "https://example.com/sub?id=ABC123"
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "links.db"
            storage.init_db(db_path)
            self.assertTrue(storage.save_link(url, "bot-1", db_path=db_path))
            self.assertFalse(storage.save_link(url, "bot-1", db_path=db_path))
            self.assertEqual(storage.count_links(db_path=db_path), 1)


if __name__ == "__main__":
    unittest.main()
