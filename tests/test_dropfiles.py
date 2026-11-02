import os
import tempfile
import unittest

from pmfstudio import dropfiles


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="pmf_drop_")

    def test_kinds(self):
        for name, kind in (("a.pbp", "pbp"), ("A.PMF", "pmf"), ("t.ctf", "ctf"), ("s.at3", "at3"), ("m.MKV", "video"), ("s.mp3", "audio"),
                           ("p.png", "image"), ("x.rco", "rco"), ("g.cso", "disc"), ("G.ISO", "disc"), ("notes.txt", "other")):
            self.assertEqual(dropfiles.classify(os.path.join(self.d, name)), kind, name)
        self.assertEqual(dropfiles.classify(self.d), "folder")

    def test_where_things_go(self):
        r = lambda name, mode="gameboot": dropfiles.route([os.path.join(self.d, name)], mode)[:2]      # noqa: E731
        self.assertEqual(r("g.pbp"), ("icon", "eboot"))
        self.assertEqual(r("m.mp4"), ("gameboot", "movie"))
        self.assertEqual(r("m.mp4", "cintro"), ("cintro", "movie"))
        self.assertEqual(r("m.mp4", "icon"), ("icon", "movie"))
        self.assertEqual(r("m.mp4", "at3"), ("at3", "sound"))
        self.assertEqual(r("m.mp4", "extract"), ("gameboot", "movie"))
        self.assertEqual(r("s.wav"), ("at3", "sound"))
        self.assertEqual(r("s.at3", "player"), ("player", None))
        self.assertEqual(r("x.pmf"), ("player", None))
        self.assertEqual(r("x.pmf", "extract"), ("extract", "src"))
        self.assertEqual(r("x.pmf", "shrink"), ("shrink", "src"))
        self.assertEqual(r("t.ctf"), ("extract", "src"))
        for mode in ("gameboot", "player", "shrink", "icon"):
            self.assertEqual(r("g.cso", mode), ("shrink", "src"), mode)                        # a game disc is for Shrink, whichever page is open
        self.assertEqual(r("g.iso"), ("shrink", "src"))
        self.assertEqual(r("x.rco"), ("gameboot", "rco"))
        self.assertEqual(r("p.png", "gameboot"), ("gameboot", "preview"))
        self.assertEqual(dropfiles.route([self.d], "icon")[:2], ("shrink", "src"))

    def test_unusable_files_get_a_sentence(self):
        page, box, _, text = dropfiles.route([os.path.join(self.d, "notes.txt")], "gameboot")
        self.assertIsNone(page)
        self.assertIn("can't use", text)
        page, _, _, text = dropfiles.route([os.path.join(self.d, "p.png")], "icon")
        self.assertIsNone(page)
        self.assertTrue(text)

    def test_several_movies_point_to_the_folder(self):
        paths = [os.path.join(self.d, "a.pmf"), os.path.join(self.d, "b.pmf")]
        page, box, path, text = dropfiles.route(paths, "gameboot")
        self.assertEqual((page, box, path), ("shrink", "src", paths[0]))
        self.assertIn("folder", text)


if __name__ == "__main__":
    unittest.main()
