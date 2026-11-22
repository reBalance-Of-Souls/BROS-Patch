"""Adventure progress (dcbossrush_records.txt / dcbossrush_events.txt) is a player's own state: it never counts toward
the online pool, the leftovers step never moves it, and a copy an older launcher quarantined is put back."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import content_pool as cp  # noqa: E402
import leftovers as lo     # noqa: E402


class ProgressKept(unittest.TestCase):
    def test_not_counted(self):
        for n in ("dcbossrush_records.txt", "dcbossrush_events.txt", "DCBOSSRUSH_RECORDS.TXT"):
            self.assertFalse(cp.counts("ReBalanceOfSouls/" + n), n)
        self.assertTrue(cp.counts("ReBalanceOfSouls/dcreborn.txt"))

    def test_not_moved_and_put_back(self):
        with tempfile.TemporaryDirectory() as g:
            pd = os.path.join(g, "ReBalanceOfSouls"); os.makedirs(pd)
            open(os.path.join(pd, "dcbossrush_events.txt"), "w").write("cleared x\n")
            for st, txt in (("20261110-211601", "old"), ("20261114-003511", "lv1 clear")):
                q = os.path.join(g, "_launcher_quarantine", "leftovers", st, "ReBalanceOfSouls"); os.makedirs(q)
                open(os.path.join(q, "dcbossrush_records.txt"), "w").write(txt)
                os.utime(os.path.join(q, "dcbossrush_records.txt"), (time.time() + len(txt), time.time() + len(txt)))
            lo._t0[0] = None
            self.assertEqual(lo.plan(g, [], []), [])
            moved = lo.clean(g, [], [], log=lambda *a: None)
            self.assertEqual(moved, [])
            self.assertEqual(open(os.path.join(pd, "dcbossrush_records.txt")).read(), "lv1 clear")
            self.assertEqual(open(os.path.join(pd, "dcbossrush_events.txt")).read(), "cleared x\n")


if __name__ == "__main__":
    unittest.main()
