"""Валидация и парсинг строк мостов."""
import unittest

from core.bridge_validator import validate
from core.bridge_fetcher import _bridge_key, _bridge_ip, _add_bridge

OBFS4 = (
    "obfs4 192.95.36.142:443 CDF2E852BF539B82BD10E27E9115A31734E378C2 "
    "cert=qUVQ0srL1JI/vO6V6m/24anYXiJD3QP2HgzUKQtQ7GRqqUvs7P+tG43RtAqdhLOALP7DJQ "
    "iat-mode=1"
)
WEBTUNNEL = (
    "webtunnel [2001:db8:135d:123e:527a:c63b:5eb0:b322]:443 "
    "54BF1146B161573185FBA0299B0DC3A8F7D08111 "
    "url=https://d3pyjtpvxs6z0l.cloudfront.net/Exam webtunnelver=0.0.1"
)
VANILLA = "5.42.221.118:16000 1A60FE3FAE97BD5FAE8E8F2E9B94AA697D9467F8"


class TestValidFormats(unittest.TestCase):

    def test_obfs4_accepted(self):
        self.assertTrue(validate(OBFS4)[0])

    def test_webtunnel_accepted(self):
        self.assertTrue(validate(WEBTUNNEL)[0])

    def test_vanilla_accepted(self):
        self.assertTrue(validate(VANILLA)[0])

    def test_bridge_prefix_tolerated(self):
        self.assertTrue(validate("Bridge " + OBFS4)[0])


class TestInvalidFormats(unittest.TestCase):

    def test_rejects_garbage(self):
        for bad in (
            "<html>",
            "<!DOCTYPE html><html><body>404</body></html>",
            "random text without anything useful",
            "",
            "   ",
            "# comment line",
            "obfs4 192.95.36.142:443",                    # нет fingerprint
            "obfs4 CDF2E852BF539B82BD10E27E9115A31734E378C2",  # нет адреса/cert
            "partial line 1A60FE3FAE97BD5FAE8E8F2E9B94AA697D9467F8",
        ):
            with self.subTest(bad=bad):
                self.assertFalse(validate(bad)[0])

    def test_obfs4_missing_cert(self):
        line = "obfs4 1.2.3.4:443 " + "A" * 40 + " iat-mode=0"
        ok, reason = validate(line)
        self.assertFalse(ok)
        self.assertIn("cert", reason)

    def test_obfs4_missing_iat_mode(self):
        line = "obfs4 1.2.3.4:443 " + "A" * 40 + " cert=" + "x" * 60
        ok, reason = validate(line)
        self.assertFalse(ok)
        self.assertIn("iat-mode", reason)

    def test_rejects_bogon_and_blacklisted_ips(self):
        fp = "1A60FE3FAE97BD5FAE8E8F2E9B94AA697D9467F8"
        for ip in ("8.8.8.8", "127.0.0.1", "192.168.1.10", "10.0.0.5", "169.254.1.1"):
            with self.subTest(ip=ip):
                self.assertFalse(validate(f"{ip}:443 {fp}")[0])

    def test_rejects_invalid_port(self):
        self.assertFalse(validate("5.42.221.118:99999 " + "A" * 40)[0])

    def test_never_raises(self):
        for weird in ("\x00\x01", "обфс4 мост", "a" * 10000, "::::", "1.2.3.4:"):
            with self.subTest(weird=weird):
                self.assertIsInstance(validate(weird), tuple)


class TestDeduplication(unittest.TestCase):

    def test_key_prefers_fingerprint(self):
        self.assertEqual(_bridge_key(OBFS4), "CDF2E852BF539B82BD10E27E9115A31734E378C2")

    def test_key_case_insensitive(self):
        self.assertEqual(_bridge_key(OBFS4.lower()), _bridge_key(OBFS4.upper()))

    def test_ip_extraction(self):
        self.assertEqual(_bridge_ip(OBFS4), "192.95.36.142")
        self.assertIsNone(_bridge_ip(WEBTUNNEL))   # webtunnel IP фиктивный

    def test_same_fingerprint_added_once(self):
        unique, ips, rejected = {}, set(), []
        self.assertTrue(_add_bridge(OBFS4, unique, ips, rejected))
        self.assertFalse(_add_bridge(OBFS4, unique, ips, rejected))
        self.assertEqual(len(unique), 1)

    def test_same_ip_different_fingerprint_rejected(self):
        unique, ips, rejected = {}, set(), []
        other = OBFS4.replace("CDF2E852BF539B82BD10E27E9115A31734E378C2", "B" * 40)
        self.assertTrue(_add_bridge(OBFS4, unique, ips, rejected))
        self.assertFalse(_add_bridge(other, unique, ips, rejected))

    def test_invalid_lines_do_not_enter(self):
        unique, ips, rejected = {}, set(), []
        for line in ("<html>", "junk", ""):
            _add_bridge(line, unique, ips, rejected)
        self.assertEqual(unique, {})
        self.assertEqual(len(rejected), 3)

    def test_mixed_input(self):
        """Валидные принимаются, мусор отбрасывается, ничего не падает."""
        unique, ips, rejected = {}, set(), []
        for line in ("<html>", OBFS4, "", WEBTUNNEL, "broken", VANILLA, OBFS4):
            _add_bridge(line, unique, ips, rejected)
        self.assertEqual(len(unique), 3)


if __name__ == "__main__":
    unittest.main()
