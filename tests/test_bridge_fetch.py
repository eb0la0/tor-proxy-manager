"""
Загрузка из источников: защита от недоверенного ответа, перебор зеркал,
слияние источников и матрица отказов.

Сеть не используется — HTTP-слой подменяется заглушкой.
"""
import io
import threading
import unittest
import urllib.error
from unittest import mock

from core import bridge_fetcher as bf
from core.bridge_sources import BridgeSource

OBFS4 = (
    "obfs4 192.95.36.142:443 CDF2E852BF539B82BD10E27E9115A31734E378C2 "
    "cert=qUVQ0srL1JI/vO6V6m/24anYXiJD3QP2HgzUKQtQ7GRqqUvs7P+tG43RtAqdhLOALP7DJQ "
    "iat-mode=1"
)


def other_obfs4(ip: str, fp: str) -> str:
    return OBFS4.replace("192.95.36.142", ip).replace(
        "CDF2E852BF539B82BD10E27E9115A31734E378C2", fp)


class _FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, content_type="text/plain"):
        super().__init__(body)
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def fake_opener(responses: dict):
    """responses: url → bytes | Exception | _FakeResponse"""
    def _open(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        item = responses.get(url)
        if item is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, _FakeResponse):
            return item
        return _FakeResponse(item)
    return mock.Mock(open=_open)


# ── Защита от недоверенного содержимого ──────────────────────────────────────

class TestFetchUrlHardening(unittest.TestCase):

    def _fetch(self, body, content_type="text/plain", url="https://example.org/f.txt"):
        with mock.patch.object(bf, "_opener",
                               fake_opener({url: _FakeResponse(body, content_type)})):
            return bf._fetch_url(url)

    def test_plain_text_ok(self):
        lines = self._fetch(f"# comment\n\n{OBFS4}\n".encode())
        self.assertEqual(lines, [OBFS4])

    def test_http_200_with_html_body_rejected(self):
        """Главный случай: 200 OK + HTML-страница ошибки — это НЕ успех."""
        body = b"<!DOCTYPE html>\n<html><body>404 Not Found</body></html>"
        with self.assertRaises(bf.FetchRejected):
            self._fetch(body)

    def test_html_content_type_rejected(self):
        with self.assertRaises(bf.FetchRejected):
            self._fetch(OBFS4.encode(), content_type="text/html; charset=utf-8")

    # Пустой ответ — отдельный случай: источник ответил корректно, просто
    # мостов в файле нет. Это EmptyContent, а не FetchRejected, и на уровне
    # источника трактуется иначе (см. TestEmptyVersusUnavailable).

    def test_empty_response_is_empty_content(self):
        with self.assertRaises(bf.EmptyContent):
            self._fetch(b"")

    def test_whitespace_only_is_empty_content(self):
        with self.assertRaises(bf.EmptyContent):
            self._fetch(b"\n\n   \n")

    def test_comments_only_is_empty_content(self):
        with self.assertRaises(bf.EmptyContent):
            self._fetch(b"# only comments\n# nothing else\n")

    def test_empty_content_is_not_confused_with_rejection(self):
        """HTML — брак зеркала; пустой файл — валидный ответ. Разные классы."""
        self.assertFalse(issubclass(bf.EmptyContent, bf.FetchRejected))
        self.assertFalse(issubclass(bf.FetchRejected, bf.EmptyContent))

    def test_oversized_response_rejected(self):
        big = b"x" * (bf.MAX_RESPONSE_BYTES + 10)
        with self.assertRaises(bf.FetchRejected):
            self._fetch(big)

    def test_non_https_scheme_rejected(self):
        with self.assertRaises(bf.FetchRejected):
            bf._fetch_url("http://example.org/f.txt")
        with self.assertRaises(bf.FetchRejected):
            bf._fetch_url("file:///etc/passwd")

    def test_invalid_utf8_does_not_crash(self):
        body = b"\xff\xfe\x00bad bytes\n" + OBFS4.encode()
        self.assertIn(OBFS4, self._fetch(body))


# ── Перебор зеркал и слияние источников ──────────────────────────────────────

class TestSourceFallback(unittest.TestCase):

    def setUp(self):
        self.src = BridgeSource(
            name="test", provider="test", priority=100,
            paths={"obfs4": "f.txt"},
            mirrors=(
                lambda p: f"https://mirror-a.test/{p}",
                lambda p: f"https://mirror-b.test/{p}",
                lambda p: f"https://mirror-c.test/{p}",
            ),
        )
        self.deadline = float("inf")
        self.cancel = threading.Event()

    def _run(self, responses):
        with mock.patch.object(bf, "_opener", fake_opener(responses)):
            return bf._fetch_source(self.src, "obfs4", 5, self.deadline, self.cancel)

    def test_first_mirror_wins(self):
        r = self._run({"https://mirror-a.test/f.txt": OBFS4.encode()})
        self.assertTrue(r.ok)
        self.assertEqual(r.host, "mirror-a.test")

    def test_falls_through_to_second_mirror(self):
        r = self._run({
            "https://mirror-a.test/f.txt": urllib.error.HTTPError(
                "u", 403, "Forbidden", {}, None),
            "https://mirror-b.test/f.txt": OBFS4.encode(),
        })
        self.assertTrue(r.ok)
        self.assertEqual(r.host, "mirror-b.test")

    def test_html_mirror_is_skipped_not_accepted(self):
        """Зеркало с 200+HTML не должно останавливать перебор."""
        r = self._run({
            "https://mirror-a.test/f.txt": b"<html>rate limit</html>",
            "https://mirror-b.test/f.txt": OBFS4.encode(),
        })
        self.assertTrue(r.ok)
        self.assertEqual(r.host, "mirror-b.test")

    def test_all_mirrors_down(self):
        r = self._run({})
        self.assertFalse(r.ok)
        self.assertEqual(r.lines, [])
        self.assertTrue(r.error)

    def test_network_errors_do_not_raise(self):
        for exc in (TimeoutError("timeout"),
                    ConnectionResetError("reset"),
                    OSError("dns failure"),
                    urllib.error.HTTPError("u", 429, "Too Many", {}, None),
                    urllib.error.HTTPError("u", 503, "Unavailable", {}, None)):
            with self.subTest(exc=type(exc).__name__):
                r = self._run({"https://mirror-a.test/f.txt": exc,
                               "https://mirror-b.test/f.txt": exc,
                               "https://mirror-c.test/f.txt": exc})
                self.assertFalse(r.ok)

    def test_cancellation_stops_immediately(self):
        self.cancel.set()
        r = self._run({"https://mirror-a.test/f.txt": OBFS4.encode()})
        self.assertFalse(r.ok)
        self.assertEqual(r.error, "cancelled")


# ── Матрица отказов на уровне всего обновления ───────────────────────────────

class TestFailureMatrix(unittest.TestCase):

    def setUp(self):
        self.a = BridgeSource(name="A", provider="A", priority=100, paths={"obfs4": "a.txt"},
                              mirrors=(lambda p: f"https://a.test/{p}",))
        self.b = BridgeSource(name="B", provider="B", priority=50, paths={"obfs4": "b.txt"},
                              mirrors=(lambda p: f"https://b.test/{p}",))
        self.c = BridgeSource(name="C", provider="C", priority=10, paths={"obfs4": "c.txt"},
                              mirrors=(lambda p: f"https://c.test/{p}",))

    def _fetch(self, responses):
        with mock.patch.object(bf, "sources_for", lambda t: [self.a, self.b, self.c]), \
             mock.patch.object(bf, "_opener", fake_opener(responses)):
            return bf.fetch_bridges("obfs4", fetch_timeout=5)

    def test_one_source_down_others_carry_update(self):
        res = self._fetch({
            "https://b.test/b.txt": other_obfs4("1.2.3.4", "B" * 40).encode(),
            "https://c.test/c.txt": other_obfs4("5.6.7.8", "C" * 40).encode(),
        })
        self.assertEqual(len(res.ok_sources), 2)
        self.assertEqual(len(res.bridges), 2)

    def test_two_sources_down_one_survives(self):
        res = self._fetch({"https://c.test/c.txt": OBFS4.encode()})
        self.assertEqual(len(res.ok_sources), 1)
        self.assertEqual(res.bridges, [OBFS4])

    def test_all_sources_down_returns_empty_without_crash(self):
        res = self._fetch({})
        self.assertEqual(res.bridges, [])
        self.assertFalse(res.any_success)
        self.assertEqual(len(res.failed_sources), 3)

    def test_source_returning_html_counts_as_failed(self):
        res = self._fetch({
            "https://a.test/a.txt": b"<html>error</html>",
            "https://b.test/b.txt": OBFS4.encode(),
        })
        names_ok = {s.name for s in res.ok_sources}
        self.assertNotIn("A", names_ok)
        self.assertIn("B", names_ok)

    def test_duplicates_across_sources_merged_once(self):
        res = self._fetch({
            "https://a.test/a.txt": OBFS4.encode(),
            "https://b.test/b.txt": OBFS4.encode(),
            "https://c.test/c.txt": OBFS4.encode(),
        })
        self.assertEqual(len(res.bridges), 1)
        self.assertEqual(len(res.ok_sources), 3)

    def test_priority_source_wins_on_conflict(self):
        """Один fingerprint у двух источников → остаётся версия приоритетного."""
        high = OBFS4 + " iat-mode=1"
        low = OBFS4.replace("192.95.36.142", "9.9.9.1")
        res = self._fetch({
            "https://a.test/a.txt": high.encode(),
            "https://b.test/b.txt": low.encode(),
        })
        self.assertEqual(len(res.bridges), 1)
        self.assertEqual(res.bridges[0], high)

    def test_merge_order_is_deterministic(self):
        responses = {
            "https://a.test/a.txt": other_obfs4("1.1.1.2", "A" * 40).encode(),
            "https://b.test/b.txt": other_obfs4("2.2.2.2", "B" * 40).encode(),
            "https://c.test/c.txt": other_obfs4("3.3.3.3", "C" * 40).encode(),
        }
        runs = [self._fetch(responses).bridges for _ in range(5)]
        self.assertTrue(all(r == runs[0] for r in runs))

    def test_garbage_source_yields_no_bridges_but_no_crash(self):
        res = self._fetch({"https://a.test/a.txt": b"just some random text\nmore junk\n"})
        self.assertEqual(res.bridges, [])
        self.assertTrue(res.any_success)      # ответ получен
        self.assertGreater(res.rejected, 0)   # но всё отклонено валидатором


if __name__ == "__main__":
    unittest.main()
