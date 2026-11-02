"""The bundled scrapers load, every configured board names a known scraper, and the publish-side leak scan works."""
import json, os, sys, unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPTS = os.path.join(ROOT, "skills", "find-jobs", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(ROOT, "tools"))


class Scrapers(unittest.TestCase):
    def test_registry(self):
        import ats
        for name in ("greenhouse", "lever", "ashby", "workday", "oraclehcm", "icims", "eightfold_pcsx", "phenom", "successfactors", "apple", "google"):
            self.assertIn(name, ats.FETCHERS)

    def test_board_list(self):
        import ats
        with open(os.path.join(SCRIPTS, "companies.json")) as f:
            cfgs = json.load(f)
        self.assertGreater(len(cfgs), 500)
        for c in cfgs:
            self.assertIn(c["ats"], ats.FETCHERS, c)
            self.assertNotEqual(c["ats"], "amazon")
            self.assertNotIn("store_only", c)

    def test_us_filter(self):
        import ats
        for loc in ("Austin, TX", "Remote - US", "New York, NY", "Seattle, Washington, United States"):
            self.assertTrue(ats.is_us(loc), loc)
        for loc in ("London, UK", "Toronto, ON, Canada", "Bangalore, India", "Tel Aviv, IL"):
            self.assertFalse(ats.is_us(loc), loc)

    def test_row_shape(self):
        import ats
        r = ats.row({"company": "Acme Co"}, "greenhouse", 12, "Engineer", "Austin, TX", "Eng", "2026-10-01T00:00:00Z", "https://x", "text")
        self.assertEqual(r["id"], "acme-co:12")
        self.assertEqual(r["posted"], "2026-10-01")

    def test_leak_scan(self):
        import sync_code
        self.assertTrue(sync_code.leaks('KEY = "sk-abcdefghijklmnopqrstuvwxyz123456"'))
        self.assertTrue(sync_code.leaks("path = '/home/someone/x'"))
        self.assertTrue(sync_code.leaks("contact me@gmail.com"))
        self.assertFalse(sync_code.leaks("tok = ats.get(url)['csrfToken']"))

    def test_shipped_files_are_clean(self):
        import sync_code
        for base, _, files in os.walk(os.path.join(ROOT, "skills")):
            for n in files:
                if n.endswith((".py", ".json", ".md")):
                    with open(os.path.join(base, n), encoding="utf-8") as f:
                        text = f.read()
                    self.assertEqual(sync_code.leaks(text), [], os.path.join(base, n))


if __name__ == "__main__":
    unittest.main()
