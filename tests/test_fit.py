import unittest

from pmfkit import fit


class FitTests(unittest.TestCase):
    def test_longer_is_never_better(self):
        for target in ("gameboot", "icon"):
            rank = {"good": 0, "soft": 1, "toolong": 2}
            seen = [rank[fit.verdict(target, s)] for s in range(1, 600, 3)]
            self.assertEqual(seen, sorted(seen))

    def test_limits_match_verdicts(self):
        for target in ("gameboot", "icon"):
            good, most = fit.limits(target)
            self.assertLess(0, good)
            self.assertLess(good, most)
            self.assertEqual(fit.verdict(target, good - 0.5), "good")
            self.assertEqual(fit.verdict(target, good + 2), "soft")
            self.assertEqual(fit.verdict(target, most + 2), "toolong")

    def test_two_hour_gameboot_does_not_fit(self):
        self.assertEqual(fit.verdict("gameboot", 7200), "toolong")

    def test_a_different_icon_sound_changes_the_room(self):
        good, most = fit.limits("icon")
        big_good, _ = fit.limits("icon", sound_bytes=300000)         # a big fixed sound leaves less room for a good-looking picture
        small_good, small_most = fit.limits("icon", sound_bytes=100000)
        self.assertLess(big_good, good)
        self.assertGreater(small_good, good)
        self.assertGreater(small_most, most)

    def test_cintro_only_stops_at_fat32(self):
        self.assertEqual(fit.verdict("cintro", 3600), "good")
        self.assertEqual(fit.verdict("cintro", 6 * 3600), "toolong")


if __name__ == "__main__":
    unittest.main()
