"""Кеш мостов: форматы, повреждения, отказ затирать рабочий набор."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core import bridge_cache


class _CacheTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "bridges.json"

    def tearDown(self):
        self._dir.cleanup()

    def write(self, text: str, encoding="utf-8"):
        self.path.write_text(text, encoding=encoding)


class TestRoundTrip(_CacheTest):

    def test_save_then_load(self):
        bridges = [("obfs4 1.2.3.4:443 " + "A" * 40, 123.4),
                   ("obfs4 5.6.7.8:443 " + "B" * 40, 210.0)]
        self.assertTrue(bridge_cache.save(bridges, "obfs4", self.path))

        c = bridge_cache.load(self.path)
        self.assertEqual(len(c.bridges), 2)
        self.assertEqual(c.bridge_type, "obfs4")
        self.assertTrue(c.is_fresh())
        self.assertIsNotNone(c.updated_at)

    def test_atomic_write_leaves_no_tmp(self):
        bridge_cache.save([("obfs4 1.2.3.4:443 " + "A" * 40, 1.0)], "obfs4", self.path)
        leftovers = list(self.path.parent.glob("*.tmp"))
        self.assertEqual(leftovers, [])


class TestNeverLoseGoodBridges(_CacheTest):

    def test_empty_save_is_refused(self):
        """Неудачное обновление не должно затирать рабочий набор."""
        good = [("obfs4 1.2.3.4:443 " + "A" * 40, 100.0)]
        bridge_cache.save(good, "obfs4", self.path)

        self.assertFalse(bridge_cache.save([], "obfs4", self.path))

        c = bridge_cache.load(self.path)
        self.assertEqual(len(c.bridges), 1)


class TestCorruption(_CacheTest):

    def test_missing_file(self):
        c = bridge_cache.load(self.path)
        self.assertFalse(c)
        self.assertEqual(c.bridges, [])

    def test_empty_file(self):
        self.write("")
        self.assertFalse(bridge_cache.load(self.path))

    def test_invalid_json(self):
        self.write("{not json at all")
        self.assertFalse(bridge_cache.load(self.path))

    def test_truncated_json(self):
        self.write('{"version": 2, "bridges": [{"bridge": "obfs4 1.2')
        self.assertFalse(bridge_cache.load(self.path))

    def test_unexpected_structure(self):
        self.write('"just a string"')
        self.assertFalse(bridge_cache.load(self.path))

    def test_bridges_not_a_list(self):
        self.write('{"version": 2, "bridges": "oops"}')
        self.assertFalse(bridge_cache.load(self.path))

    def test_broken_entries_are_skipped(self):
        self.write(json.dumps({
            "version": 2, "bridge_type": "obfs4",
            "bridges": [
                {"bridge": "obfs4 1.2.3.4:443", "latency": 10},
                {"bridge": None, "latency": 5},
                {"latency": 5},
                "not a dict",
                {"bridge": "obfs4 5.6.7.8:443", "latency": "not a number"},
                {"bridge": "obfs4 9.9.9.9:443", "latency": None},
            ],
        }))
        c = bridge_cache.load(self.path)
        self.assertEqual(len(c.bridges), 2)   # первый и последний

    def test_bad_timestamp_ignored(self):
        self.write(json.dumps({
            "version": 2, "bridge_type": "obfs4", "updated_at": "yesterday",
            "bridges": [{"bridge": "obfs4 1.2.3.4:443", "latency": 1}],
        }))
        c = bridge_cache.load(self.path)
        self.assertTrue(c)
        self.assertIsNone(c.updated_at)
        self.assertFalse(c.is_fresh())

    def test_wrong_encoding_does_not_crash(self):
        self.path.write_bytes(b'{"version": 2, "bridges": [\xff\xfe]}')
        self.assertFalse(bridge_cache.load(self.path))


class TestLegacyFormat(_CacheTest):

    def test_v1_bare_list_is_readable(self):
        """Кеш старой версии не должен потеряться при обновлении приложения."""
        self.write(json.dumps([
            {"bridge": "obfs4 1.2.3.4:443 " + "A" * 40, "latency": 150.0},
            {"bridge": "obfs4 5.6.7.8:443 " + "B" * 40, "latency": 90.0},
        ]))
        c = bridge_cache.load(self.path)
        self.assertEqual(len(c.bridges), 2)
        self.assertEqual(c.bridge_type, "")
        self.assertIsNone(c.updated_at)

    def test_v1_matches_any_type(self):
        """Тип неизвестен → лучше показать мосты, чем выбросить их."""
        c = bridge_cache.BridgeCache(bridges=[("x", 1.0)], bridge_type="")
        self.assertTrue(c.matches_type("obfs4"))
        self.assertTrue(c.matches_type("webtunnel"))


class TestStaleness(unittest.TestCase):

    def _cache(self, **kw):
        return bridge_cache.BridgeCache(bridges=[("x", 1.0)], **kw)

    def test_fresh(self):
        c = self._cache(updated_at=datetime.now() - timedelta(hours=1))
        self.assertTrue(c.is_fresh())
        self.assertFalse(c.is_expired())

    def test_stale_but_usable(self):
        c = self._cache(updated_at=datetime.now() - timedelta(days=3))
        self.assertFalse(c.is_fresh())
        self.assertFalse(c.is_expired())     # устарел, но всё ещё лучше пустоты

    def test_expired(self):
        c = self._cache(updated_at=datetime.now() - timedelta(days=60))
        self.assertTrue(c.is_expired())

    def test_type_mismatch_detected(self):
        c = self._cache(bridge_type="obfs4")
        self.assertTrue(c.matches_type("obfs4"))
        self.assertFalse(c.matches_type("webtunnel"))

    def test_age_text(self):
        now = datetime.now()
        self.assertEqual(self._cache(updated_at=now).age_text(), "только что")
        self.assertIn("мин", self._cache(updated_at=now - timedelta(minutes=5)).age_text())
        self.assertIn("ч", self._cache(updated_at=now - timedelta(hours=3)).age_text())
        self.assertIn("дн", self._cache(updated_at=now - timedelta(days=2)).age_text())
        self.assertEqual(bridge_cache.BridgeCache().age_text(), "неизвестно")


if __name__ == "__main__":
    unittest.main()
