"""The row of choices on the Shrink page: every button the same width, the same in both rows, no jumping when another choice is picked,
and a row that fits the room it has. Needs a screen (Tk); skipped without one."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def have_display():
    try:
        import tkinter
        tkinter.Tk().destroy()
        return True
    except Exception:
        return False


@unittest.skipUnless(have_display(), "needs a display")
class SegmentedTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from pmfstudio import theme
        from pmfstudio.widgets import Segmented
        self.tk, self.Segmented = tk, Segmented
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        theme.set_theme(True)
        self.picture = tk.StringVar(value="0.5")
        self.sound = tk.StringVar(value="keep")
        self.p = Segmented(self.root, [(v, "%s\n%s" % (n, k)) for v, n, k in (
            ("1.0", "As it is", "no change"), ("0.75", "75%", "9,258 kbps"), ("0.5", "50%", "6,172 kbps"), ("0.4", "40%", "4,938 kbps"),
            ("0.3", "30%", "3,703 kbps"), ("0.2", "20%", "2,469 kbps"))], self.picture, pad=12, equal=True)
        self.s = Segmented(self.root, [(v, "%s\n%s" % (n, k)) for v, n, k in (
            ("keep", "As it is", "no change"), ("128", "128 kbps", "high quality"), ("96", "96 kbps", "good"), ("64", "64 kbps", "okay"),
            ("48", "48 kbps", "thin"), ("32", "32 kbps", "lowest"))], self.sound, pad=12, equal=True)
        self.p.pack()
        self.s.pack()

    def widths(self, seg):
        self.root.update()
        return [lab.winfo_width() for lab in seg.items.values()]

    def test_every_button_is_as_wide_as_the_widest_and_both_rows_agree(self):
        self.Segmented.fit_together([self.p, self.s], 2000)
        a, b = self.widths(self.p), self.widths(self.s)
        self.assertEqual(len(set(a + b)), 1, (a, b))

    def test_picking_another_choice_does_not_change_the_row(self):
        self.Segmented.fit_together([self.p, self.s], 2000)
        before = (self.widths(self.p), self.p.winfo_width())
        for v in ("1.0", "0.75", "0.2"):
            self.p.choose(v)
            self.assertEqual((self.widths(self.p), self.p.winfo_width()), before)

    def test_a_row_is_never_wider_than_its_room_when_the_room_allows_it(self):
        for room in (800, 640, 560, 520):
            self.Segmented.fit_together([self.p, self.s], room)
            self.root.update()
            self.assertLessEqual(self.p.winfo_reqwidth(), room, room)
            self.assertLessEqual(self.s.winfo_reqwidth(), room, room)

    def row_room(self, pad, size):
        """the room a row needs at this padding and font size"""
        return max(s.button_width(pad, size) for s in (self.p, self.s)) * 6 + 2

    def test_padding_gives_way_before_the_font_does(self):
        self.Segmented.fit_together([self.p, self.s], 2000)
        self.assertEqual(self.p.size, 10)
        roomy = int(self.p.items["1.0"].cget("padx"))
        self.Segmented.fit_together([self.p, self.s], (self.row_room(12, 10) + self.row_room(2, 10)) // 2)
        self.assertEqual(self.p.size, 10)                                  # still the normal font
        self.assertLess(int(self.p.items["1.0"].cget("padx")), roomy)

    def test_the_font_gets_smaller_only_when_the_padding_is_used_up(self):
        self.assertFalse(self.Segmented.fit_together([self.p, self.s], self.row_room(2, 10) - 1) and self.p.size == 10)
        self.assertLess(self.p.size, 10)
        self.assertTrue(self.Segmented.fit_together([self.p, self.s], self.row_room(2, 10)))
        self.assertEqual(self.p.size, 10)

    def test_a_room_that_is_too_small_for_anything_is_reported_not_hidden(self):
        self.assertFalse(self.Segmented.fit_together([self.p, self.s], 50))
        self.assertEqual(self.p.size, 8)

    def test_a_row_made_the_old_way_still_works(self):
        seg = self.Segmented(self.root, [("a", "One"), ("b", "Two")], self.tk.StringVar(value="a"))
        seg.pack()
        self.root.update()
        seg.choose("b")
        self.assertEqual(seg.var.get(), "b")


if __name__ == "__main__":
    unittest.main()
