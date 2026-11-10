import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_build():
    spec = importlib.util.spec_from_file_location("pmf_build_release", os.path.join(ROOT, "packaging", "build_release.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ReleaseSourceTests(unittest.TestCase):
    def test_every_atracdenc_patch_goes_into_the_release(self):
        """the shipped atracdenc.exe is built with all patches; its licence needs the release to carry every one of them"""
        build = load_build()
        folder = os.path.join(ROOT, "tools", "atracdenc")
        shipped = build.atracdenc_source_files(folder)
        on_disk = sorted(f for f in os.listdir(folder) if f.endswith(".patch"))
        self.assertTrue(on_disk)
        for p in on_disk:
            self.assertIn(p, shipped)
        self.assertIn("adaptive-precision.patch", shipped)

    def test_the_notices_name_every_patch(self):
        text = open(os.path.join(ROOT, "packaging", "THIRD_PARTY_NOTICES.txt"), encoding="utf8").read()
        for p in os.listdir(os.path.join(ROOT, "tools", "atracdenc")):
            if p.endswith(".patch"):
                self.assertIn(p[:-len(".patch")], text, p)

    def test_the_glibc_version_is_read_from_old_and_new_objdump_output(self):
        build = load_build()
        new = "0000 g    DF .text  0000 (GLIBC_2.2.5) memcpy\n0000 g    DF .text  0000 (GLIBC_2.38)  fmod\n0000 g DF .text 0000 (GLIBC_2.17) clock_gettime\n"
        old = "0000 g    DF .text  0000  GLIBC_2.2.5 memcpy\n0000 g    DF .text  0000  GLIBC_2.28   fmod\n0000 g DF .text 0000 GLIBC_PRIVATE _dl_x\n"
        self.assertEqual(build.highest_glibc(new), (2, 38))
        self.assertEqual(build.highest_glibc(old), (2, 28))
        self.assertEqual(build.highest_glibc("no version symbols here"), (0,))
        self.assertGreater(build.highest_glibc(new), build.OLDEST_GLIBC)       # such a program would stop the build
        self.assertLessEqual(build.highest_glibc(old), build.OLDEST_GLIBC)

    def test_the_personal_mail_pattern(self):
        build = load_build()
        self.assertTrue(build.PERSONAL_MAIL.search(b"contact someone.name@gmail.com for help"))
        self.assertTrue(build.PERSONAL_MAIL.search(b"x@Outlook.com"))
        self.assertFalse(build.PERSONAL_MAIL.search(b"27747370+Mr-Shizzy@users.noreply.github.com"))
        self.assertFalse(build.PERSONAL_MAIL.search(b"ffmpeg-devel@ffmpeg.org"))


if __name__ == "__main__":
    unittest.main()
