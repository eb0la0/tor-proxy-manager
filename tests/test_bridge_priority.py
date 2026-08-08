"""
Регрессионные тесты второго review.

Проверяют свойства, которые легко сломать незаметно: сохранение приоритета
сквозь весь конвейер, детерминизм при параллельной загрузке, семантику
пустого ответа и разделение источников на независимых поставщиков.
"""
import threading
import time
import unittest
import urllib.error
from unittest import mock

from core import bridge_fetcher as bf
from core.bridge_sources import BridgeSource, SOURCES, sources_for
from core.bridge_tester import BridgeTesterThread

from tests.test_bridge_fetch import fake_opener, _FakeResponse


def obfs4(ip: str, fp: str) -> str:
    return (f"obfs4 {ip}:443 {fp} "
            "cert=qUVQ0srL1JI/vO6V6m/24anYXiJD3QP2HgzUKQtQ7GRqqUvs7P+tG43RtAqdhLOALP7DJQ "
            "iat-mode=1")


def src(name, priority, url, provider=None):
    return BridgeSource(name=name, provider=provider or name, priority=priority,
                        paths={"obfs4": "f.txt"}, mirrors=(lambda p, u=url: u,))


# ── Приоритет сквозь весь конвейер ───────────────────────────────────────────

class TestPriorityPreservation(unittest.TestCase):

    def setUp(self):
        self.high = src("HIGH", 100, "https://high.test/f.txt")
        self.mid = src("MID", 50, "https://mid.test/f.txt")
        self.low = src("LOW", 10, "https://low.test/f.txt")

    def _fetch(self, responses, order):
        with mock.patch.object(bf, "sources_for", lambda t: order), \
             mock.patch.object(bf, "_opener", fake_opener(responses)):
            return bf.fetch_bridges("obfs4", fetch_timeout=5)

    def test_merge_order_follows_priority_not_arrival(self):
        responses = {
            "https://high.test/f.txt": obfs4("45.45.45.1", "A" * 40).encode(),
            "https://mid.test/f.txt": obfs4("45.45.45.2", "B" * 40).encode(),
            "https://low.test/f.txt": obfs4("45.45.45.3", "C" * 40).encode(),
        }
        res = self._fetch(responses, [self.high, self.mid, self.low])
        self.assertEqual(
            [b.split()[1] for b in res.bridges],
            ["45.45.45.1:443", "45.45.45.2:443", "45.45.45.3:443"],
        )

    def test_slow_high_priority_still_comes_first(self):
        """Медленный приоритетный источник не должен уступать быстрому слабому."""
        def slow_opener(req, timeout=None):
            url = req.full_url
            if "high" in url:
                time.sleep(0.30)
                return _FakeResponse(obfs4("45.45.45.1", "A" * 40).encode())
            if "mid" in url:
                time.sleep(0.15)
                return _FakeResponse(obfs4("45.45.45.2", "B" * 40).encode())
            return _FakeResponse(obfs4("45.45.45.3", "C" * 40).encode())

        with mock.patch.object(bf, "sources_for",
                               lambda t: [self.high, self.mid, self.low]), \
             mock.patch.object(bf, "_opener", mock.Mock(open=slow_opener)):
            res = bf.fetch_bridges("obfs4", fetch_timeout=5)

        self.assertEqual([b.split()[1] for b in res.bridges],
                         ["45.45.45.1:443", "45.45.45.2:443", "45.45.45.3:443"])

    def test_first_occurrence_wins_on_duplicate_fingerprint(self):
        fp = "D" * 40
        responses = {
            "https://high.test/f.txt": obfs4("45.45.45.1", fp).encode(),
            "https://low.test/f.txt": obfs4("45.45.45.9", fp).encode(),
        }
        res = self._fetch(responses, [self.high, self.low])
        self.assertEqual(len(res.bridges), 1)
        self.assertIn("45.45.45.1", res.bridges[0])

    def test_result_is_a_list_not_a_set(self):
        """set() уничтожил бы порядок и вместе с ним приоритет."""
        res = self._fetch(
            {"https://high.test/f.txt": obfs4("45.45.45.1", "A" * 40).encode()},
            [self.high])
        self.assertIsInstance(res.bridges, list)

    def test_repeated_runs_are_identical(self):
        responses = {
            "https://high.test/f.txt": "\n".join(
                obfs4(f"45.45.1.{i}", f"{i:040X}") for i in range(1, 20)).encode(),
            "https://mid.test/f.txt": "\n".join(
                obfs4(f"45.45.2.{i}", f"{i + 100:040X}") for i in range(1, 20)).encode(),
        }
        runs = [self._fetch(responses, [self.high, self.mid]).bridges for _ in range(8)]
        self.assertTrue(all(r == runs[0] for r in runs))


# ── Выборка тестировщика ─────────────────────────────────────────────────────

class TestSamplingProperties(unittest.TestCase):

    def _bridges(self, n):
        return [obfs4(f"45.{i // 65536 % 200 + 30}.{i // 256 % 256}.{i % 256}", f"{i:040X}") for i in range(n)]

    def test_no_error_for_any_size(self):
        for n in (0, 1, 2, 149, 150, 151, 249, 250, 251, 5000):
            with self.subTest(n=n):
                sample = BridgeTesterThread(self._bridges(n)).bridges
                self.assertEqual(len(sample), min(n, BridgeTesterThread.MAX_SAMPLE))

    def test_head_is_always_present_over_many_runs(self):
        """1000 прогонов: приоритетная голова обязана попадать в выборку всегда."""
        bridges = self._bridges(5000)
        head_n = int(BridgeTesterThread.MAX_SAMPLE * BridgeTesterThread.HEAD_RATIO)
        head = set(bridges[:head_n])
        for _ in range(1000):
            sample = set(BridgeTesterThread(bridges).bridges)
            if not head.issubset(sample):
                self.fail("приоритетная голова потеряна при выборке")

    def test_priority_bridges_selected_far_more_often_than_tail(self):
        bridges = self._bridges(5000)
        head_n = int(BridgeTesterThread.MAX_SAMPLE * BridgeTesterThread.HEAD_RATIO)
        head_hits = tail_hits = 0
        probe_head, probe_tail = bridges[0], bridges[-1]
        for _ in range(200):
            sample = set(BridgeTesterThread(bridges).bridges)
            head_hits += probe_head in sample
            tail_hits += probe_tail in sample
        self.assertEqual(head_hits, 200)          # голова — всегда
        self.assertLess(tail_hits, 40)            # хвост — изредка

    def test_tail_actually_varies(self):
        bridges = self._bridges(5000)
        head_n = int(BridgeTesterThread.MAX_SAMPLE * BridgeTesterThread.HEAD_RATIO)
        tails = {tuple(BridgeTesterThread(bridges).bridges[head_n:]) for _ in range(20)}
        self.assertGreater(len(tails), 15)

    def test_sample_never_contains_duplicates(self):
        for n in (300, 1000, 5000):
            with self.subTest(n=n):
                sample = BridgeTesterThread(self._bridges(n)).bridges
                self.assertEqual(len(set(sample)), len(sample))


# ── Пустой ответ ≠ недоступный источник ──────────────────────────────────────

class TestEmptyVersusUnavailable(unittest.TestCase):

    def setUp(self):
        self.s = BridgeSource(name="S", provider="S", priority=100,
                              paths={"obfs4": "f.txt"},
                              mirrors=(lambda p: "https://a.test/f.txt",
                                       lambda p: "https://b.test/f.txt"))

    def _run(self, responses):
        with mock.patch.object(bf, "_opener", fake_opener(responses)):
            return bf._fetch_source(self.s, "obfs4", 5, float("inf"), threading.Event())

    def test_empty_body_is_a_valid_answer_not_a_failure(self):
        r = self._run({"https://a.test/f.txt": b"",
                       "https://b.test/f.txt": b""})
        self.assertTrue(r.ok)
        self.assertTrue(r.empty)
        self.assertEqual(r.lines, [])

    def test_comments_only_is_empty_not_failure(self):
        r = self._run({"https://a.test/f.txt": b"# nothing here\n",
                       "https://b.test/f.txt": b"# nothing here\n"})
        self.assertTrue(r.ok)
        self.assertTrue(r.empty)

    def test_empty_mirror_does_not_stop_search_for_data(self):
        """Пустое зеркало не должно маскировать зеркало с данными."""
        r = self._run({"https://a.test/f.txt": b"",
                       "https://b.test/f.txt": obfs4("45.45.45.1", "A" * 40).encode()})
        self.assertTrue(r.ok)
        self.assertFalse(r.empty)
        self.assertEqual(len(r.lines), 1)

    def test_html_is_still_a_failure_not_empty(self):
        r = self._run({"https://a.test/f.txt": b"<html>429</html>",
                       "https://b.test/f.txt": b"<html>429</html>"})
        self.assertFalse(r.ok)
        self.assertFalse(r.empty)

    def test_unreachable_is_a_failure(self):
        r = self._run({})
        self.assertFalse(r.ok)
        self.assertFalse(r.empty)


# ── Независимость поставщиков ────────────────────────────────────────────────

class TestProviderIndependence(unittest.TestCase):

    def _fetch(self, responses, order):
        with mock.patch.object(bf, "sources_for", lambda t: order), \
             mock.patch.object(bf, "_opener", fake_opener(responses)):
            return bf.fetch_bridges("obfs4", fetch_timeout=5)

    def test_two_lists_of_one_repo_count_as_one_provider(self):
        a = src("repo/tested", 80, "https://a.test/f.txt", provider="repo")
        b = src("repo/full", 50, "https://b.test/f.txt", provider="repo")
        res = self._fetch({
            "https://a.test/f.txt": obfs4("45.45.45.1", "A" * 40).encode(),
            "https://b.test/f.txt": obfs4("45.45.45.2", "B" * 40).encode(),
        }, [a, b])
        self.assertEqual(len(res.ok_sources), 2)
        self.assertEqual(res.total_providers, 1)      # не 2!
        self.assertEqual(res.ok_providers, {"repo"})

    def test_provider_is_down_only_when_all_its_sources_are_down(self):
        a = src("repo/tested", 80, "https://a.test/f.txt", provider="repo")
        b = src("repo/full", 50, "https://b.test/f.txt", provider="repo")
        res = self._fetch({"https://b.test/f.txt": obfs4("45.45.45.2", "B" * 40).encode()},
                          [a, b])
        self.assertEqual(res.ok_providers, {"repo"})

    def test_real_registry_has_fewer_providers_than_sources(self):
        """Реальный реестр не должен выдавать зеркала за независимых поставщиков."""
        srcs = sources_for("obfs4")
        providers = {s.provider for s in srcs}
        self.assertLess(len(providers), len(srcs))
        self.assertGreaterEqual(len(providers), 3)

    def test_every_source_declares_a_provider(self):
        for s in SOURCES:
            with self.subTest(source=s.name):
                self.assertTrue(s.provider)

    def test_every_source_has_at_least_one_mirror_per_declared_type(self):
        for s in SOURCES:
            for btype in s.paths:
                with self.subTest(source=s.name, type=btype):
                    self.assertTrue(s.urls_for(btype))

    def test_githack_only_used_for_paths_it_can_actually_proxy(self):
        """
        githack проксирует только файлы с распознаваемым расширением; путь без
        расширения он редиректит обратно на GitHub, то есть как обход блокировки
        не работает. Такое «зеркало» создаёт ложное чувство запаса.
        """
        for s in SOURCES:
            for btype, path in s.paths.items():
                uses_githack = any("githack" in u for u in s.urls_for(btype))
                if uses_githack:
                    with self.subTest(source=s.name, path=path):
                        self.assertIn(".", path.rsplit("/", 1)[-1],
                                      f"{path}: githack не проксирует пути без расширения")

    def test_non_github_mirrors_come_first(self):
        """Порядок зеркал — это и есть защита от блокировки GitHub."""
        for s in SOURCES:
            urls = s.urls_for("obfs4")
            hosts = [bf._source_label(u) for u in urls]
            non_gh = [i for i, h in enumerate(hosts) if "githubusercontent" not in h]
            gh = [i for i, h in enumerate(hosts) if "githubusercontent" in h]
            if non_gh and gh:
                with self.subTest(source=s.name):
                    self.assertLess(max(non_gh), min(gh))


# ── Безопасность редиректов ──────────────────────────────────────────────────

class TestRedirectPolicy(unittest.TestCase):

    def _redirect(self, from_url, to_url):
        handler = bf._StrictRedirectHandler()
        req = urllib.request.Request(from_url)
        return handler.redirect_request(req, None, 302, "Found", {}, to_url)

    def test_cross_host_redirect_rejected(self):
        with self.assertRaises(bf.FetchRejected):
            self._redirect("https://good.test/f.txt", "https://evil.example/f.txt")

    def test_downgrade_to_http_rejected(self):
        with self.assertRaises(bf.FetchRejected):
            self._redirect("https://good.test/f.txt", "http://good.test/f.txt")

    def test_same_host_redirect_allowed(self):
        req = self._redirect("https://good.test/a.txt", "https://good.test/b.txt")
        self.assertIsNotNone(req)


if __name__ == "__main__":
    unittest.main()
