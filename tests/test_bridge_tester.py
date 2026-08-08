"""Выборка мостов для тестирования и разбор адресов."""
import unittest

from core.bridge_tester import BridgeTesterThread, _extract_addr


class TestSampling(unittest.TestCase):

    def _sample(self, n):
        bridges = [f"obfs4 1.2.3.{i % 256}:443 {i:040X} cert=x iat-mode=0"
                   for i in range(n)]
        thread = BridgeTesterThread(bridges)
        return bridges, thread.bridges

    def test_small_list_used_entirely(self):
        bridges, sample = self._sample(10)
        self.assertEqual(sample, bridges)

    def test_sample_capped(self):
        _, sample = self._sample(5000)
        self.assertEqual(len(sample), BridgeTesterThread.MAX_SAMPLE)

    def test_priority_head_always_included(self):
        """Курируемые мосты из головы списка не должны теряться в выборке."""
        bridges, sample = self._sample(5000)
        head_n = int(BridgeTesterThread.MAX_SAMPLE * BridgeTesterThread.HEAD_RATIO)
        self.assertEqual(sample[:head_n], bridges[:head_n])

    def test_sample_has_random_tail(self):
        """Хвост выборки меняется между запусками — мосты не «залипают»."""
        bridges = [f"obfs4 1.2.3.{i % 256}:443 {i:040X}" for i in range(5000)]
        tails = {tuple(BridgeTesterThread(bridges).bridges[150:]) for _ in range(5)}
        self.assertGreater(len(tails), 1)

    def test_no_duplicates_in_sample(self):
        _, sample = self._sample(5000)
        self.assertEqual(len(set(sample)), len(sample))

    def test_empty_input(self):
        self.assertEqual(BridgeTesterThread([]).bridges, [])


class TestExtractAddr(unittest.TestCase):

    def test_obfs4_ipv4(self):
        host, port = _extract_addr("obfs4 192.95.36.142:443 " + "A" * 40)
        self.assertEqual((host, port), ("192.95.36.142", 443))

    def test_vanilla(self):
        host, port = _extract_addr("5.42.221.118:16000 " + "A" * 40)
        self.assertEqual((host, port), ("5.42.221.118", 16000))

    def test_webtunnel_uses_url_host_not_placeholder_ip(self):
        line = ("webtunnel [2001:db8:135d:123e:527a:c63b:5eb0:b322]:443 " + "A" * 40 +
                " url=https://example.cloudfront.net/Exam")
        host, port = _extract_addr(line)
        self.assertEqual((host, port), ("example.cloudfront.net", 443))

    def test_placeholder_ipv6_rejected(self):
        host, _ = _extract_addr("[2001:db8::1]:443 " + "A" * 40)
        self.assertIsNone(host)

    def test_garbage_returns_none(self):
        for line in ("", "junk", "<html>"):
            with self.subTest(line=line):
                self.assertEqual(_extract_addr(line), (None, None))


if __name__ == "__main__":
    unittest.main()
