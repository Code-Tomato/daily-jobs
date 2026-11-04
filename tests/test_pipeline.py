"""End to end without the network: a fake store goes through publish.export and publish.lists, and jobs.py searches,
shows, judges, tracks and builds a board from the result (release downloads are served from the export folder)."""
import contextlib, gzip, importlib, io, json, os, re, shutil, sys, tempfile, unittest
from datetime import date

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "skills", "find-jobs", "scripts"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

TODAY = date.today().isoformat()
STORE = {
    "acme": [
        {"id": "acme:1", "company": "Acme", "ats": "greenhouse", "title": "Software Engineer Intern, Summer 2027", "location": "Austin, TX",
         "category": "Engineering", "posted": TODAY, "url": "https://example.com/1", "seen": TODAY,
         "description": "Requirements\nPursuing a BS in Computer Science\nPython or C++\nVisa sponsorship is not available.\nPay: $45/hour",
         "basic": "", "preferred": ""},
        {"id": "acme:2", "company": "Acme", "ats": "greenhouse", "title": "Senior Software Engineer", "location": "Remote - US",
         "category": "Engineering", "posted": "2026-09-01", "url": "https://example.com/2", "seen": "2026-09-02",
         "description": "Requirements\n7+ years of experience building distributed systems\nBachelor's degree", "basic": "", "preferred": ""},
    ],
    "globex": [
        {"id": "globex:9", "company": "Globex", "ats": "workday", "title": "Mechanical Engineer I", "location": "Houston, Texas",
         "category": "", "posted": TODAY, "url": "https://example.com/9", "seen": TODAY,
         "description": "Qualifications\nBachelor's in Mechanical Engineering\n0-2 years of experience\nMust be a U.S. citizen.",
         "basic": "", "preferred": ""},
        {"id": "amazon:5", "company": "Amazon", "ats": "amazon", "title": "SDE Intern", "location": "Seattle, WA", "category": "",
         "posted": TODAY, "url": "https://example.com/a", "seen": TODAY, "description": "x", "basic": "", "preferred": ""},
    ],
}

README = "# daily-jobs\n\n<!-- stats -->\nold\n<!-- /stats -->\n\nmore text\n"


class FakeResp(io.BytesIO):
    def __init__(self, data, status):
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        store = os.path.join(cls.tmp, "store")
        os.makedirs(store)
        for name, rows in STORE.items():
            with open(os.path.join(store, name + ".jsonl"), "w") as f:
                f.writelines(json.dumps(r) + "\n" for r in rows)
        json.dump({"Acme": {"status": "ok", "full": TODAY + "T08:00:00"}, "Globex": {"status": "failed", "error": "x"}},
                  open(os.path.join(store, "_status.json"), "w"))
        os.environ["DAILY_JOBS_STATE"] = os.path.join(cls.tmp, "state")
        os.environ["DAILY_JOBS_CACHE"] = os.path.join(cls.tmp, "cache")
        os.environ["JOBS_WORKSPACE"] = os.path.join(cls.tmp, "ws")
        import publish
        cls.publish = importlib.reload(publish)
        cls.out = os.path.join(cls.tmp, "out")
        cls.meta = cls.publish.export(store, cls.out, workers=1)
        cls.repo = os.path.join(cls.tmp, "repo")
        os.makedirs(cls.repo)
        open(os.path.join(cls.repo, "README.md"), "w").write(README)
        cls.publish.lists(cls.out, repo=cls.repo)
        import jobs
        cls.jobs = importlib.reload(jobs)

        def fake_get(url, headers=None, timeout=120):
            name = url.rsplit("/", 1)[1]
            data = open(os.path.join(cls.out, name), "rb").read()
            rng = (headers or {}).get("Range")
            if rng:
                a, b = map(int, rng.split("=")[1].split("-"))
                return FakeResp(data[a:b + 1], 206)
            return FakeResp(data, 200)
        cls.jobs._get = fake_get

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.jobs.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_1_export(self):
        self.assertEqual(self.meta["postings"], 3)  # Amazon is excluded
        self.assertEqual(self.meta["boards"]["Globex"]["status"], "failed")
        rows = [json.loads(l) for l in gzip.open(os.path.join(self.out, "jobs.jsonl.gz"), "rt")]
        intern = next(r for r in rows if r["id"] == "acme:1")
        self.assertEqual(intern["level"], "intern")
        self.assertEqual(intern["term"], "Summer 2027")
        self.assertTrue(intern["no_sponsor"])
        self.assertEqual(intern["pay"], [45, 45, "hour"])
        self.assertEqual(next(r for r in rows if r["id"] == "globex:9")["states"], ["TX"])

    def test_2_lists_and_readme(self):
        readme = open(os.path.join(self.repo, "README.md")).read()
        open(os.path.join(self.repo, "README.md"), "w").write("<!-- stats -->\n<!-- /stats -->\n")  # an empty block fills too
        self.publish.lists(self.out, repo=self.repo)
        self.assertIn("US job postings", open(os.path.join(self.repo, "README.md")).read())
        self.assertIn("**3 US job postings from 2 companies**", readme)
        self.assertIn("more text", readme)
        self.assertNotIn("\nold\n", readme)
        self.assertIn("Globex", readme)  # failed boards are named
        page = open(os.path.join(self.repo, "jobs", "internships-software.md")).read()
        self.assertIn("Software Engineer Intern, Summer 2027", page)
        self.assertIn("no visa sponsorship", page)
        self.assertIn("mechanical", open(os.path.join(self.repo, "jobs", "new-grad.md")).read().lower())

    def test_3_update_and_search(self):
        code, out, _ = self.run_cli("update")
        self.assertEqual(code, 0, out)
        self.assertIn("3 postings", out)
        code, out, _ = self.run_cli("search", "--title", "software", "--needs-sponsorship")
        self.assertEqual(code, 0)
        self.assertIn("acme:2", out)
        self.assertNotIn("acme:1", out)  # will not sponsor
        code, out, _ = self.run_cli("search", "--level", "intern,new-grad,entry", "--state", "TX", "--ids-only")
        self.assertEqual(out.split(), ["acme:1", "globex:9"])
        code, out, _ = self.run_cli("search", "--max-years", "2", "--ids-only", "--sort", "company")
        self.assertEqual(out.split(), ["acme:1", "globex:9"])
        code, out, _ = self.run_cli("search", "--state", "CA", "--or-remote", "--ids-only")
        self.assertEqual(out.split(), ["acme:2"])
        code, out, _ = self.run_cli("search", "--title", "engineer", "--count")
        self.assertIn("after --title: 3", out)
        code, out, _ = self.run_cli("--workspace", os.environ["JOBS_WORKSPACE"], "search", "--term", "summer", "--ids-only")
        self.assertEqual(out.split(), ["acme:1", "globex:9", "acme:2"])  # postings that state no term pass
        code, out, _ = self.run_cli("search", "--term", "fall 2027", "--strict-term", "--ids-only")
        self.assertEqual(out.split(), [])
        code, _, err = self.run_cli("search", "--level", "wizard")
        self.assertEqual(code, 1)
        self.assertIn("Unknown level", err)
        # every filter keeps its own value when several are combined (they used to share a closure variable)
        code, out, _ = self.run_cli("search", "--max-years", "2", "--min-pay", "1k", "--ids-only")
        self.assertEqual(out.split(), ["acme:1", "globex:9"])  # acme:2 asks 7+ years; postings without pay pass
        ids = os.path.join(self.tmp, "ids.txt")
        open(ids, "w").write("acme:1\nacme:2\n")
        code, out, _ = self.run_cli("search", "--term", "summer 2027", "--strict-term", "--ids", ids, "--ids-only")
        self.assertEqual(out.split(), ["acme:1"])
        code, out, _ = self.run_cli("search", "--since", "2026-09-01", "--posted-since", TODAY, "--ids-only", "--sort", "company")
        self.assertEqual(out.split(), ["acme:1", "globex:9"])
        code, out, _ = self.run_cli("search", "--level", "senior,intern", "--family", "software", "--count")
        self.assertIn("after --level: 2", out)
        self.assertIn("after --family: 2", out)

    def test_4_show_fetches_excerpts_by_range(self):
        self.run_cli("update")
        code, out, _ = self.run_cli("show", "globex:9", "acme:1")
        self.assertEqual(code, 0)
        self.assertIn("Must be a U.S. citizen.", out)
        self.assertIn("Pursuing a BS in Computer Science", out)
        self.assertIn("citizens/US-persons-only", out)

    def test_5_verdicts_tracking_board(self):
        self.run_cli("update")
        ws = os.environ["JOBS_WORKSPACE"]
        path = os.path.join(self.tmp, "v.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"id": "acme:1", "tier": "strong", "why": "Summer internship in their field."}) + "\n")
            f.write(json.dumps({"id": "acme:2", "tier": "no", "why": "Senior role."}) + "\n")
        code, out, err = self.run_cli("verdict", "--file", path)
        self.assertEqual(code, 0, err)
        code, out, _ = self.run_cli("search", "--unjudged", "--ids-only")
        self.assertEqual(out.split(), ["globex:9"])
        code, _, err = self.run_cli("verdict", "globex:9", "--tier", "maybe", "--why", "x")
        self.assertEqual(code, 1)
        self.assertEqual(self.run_cli("verdict", "globex:9", "--tier", "stretch", "--why", "Citizens only.", "--gaps", "Check status.")[0], 0)
        self.assertEqual(self.run_cli("track", "acme:1", "applied", "--note", "via site")[0], 0)
        code, out, _ = self.run_cli("board")
        self.assertEqual(code, 0)
        page = open(os.path.join(ws, "board.html")).read()
        self.assertIn("Software Engineer Intern, Summer 2027", page)
        self.assertNotIn("Senior Software Engineer", page)  # "no" verdicts stay off the board
        self.assertIn('data-status="applied"', page)
        md = open(os.path.join(ws, "matches.md")).read()
        self.assertIn("Gap: Check status.", md)

    def test_6_unknown_id(self):
        self.run_cli("update")
        code, _, err = self.run_cli("show", "nope:1")
        self.assertEqual(code, 1)
        self.assertIn("Not in the dataset", err)


if __name__ == "__main__":
    unittest.main()


class JevGrading(unittest.TestCase):
    """jobs.py jev against a fake TypeSafe API."""

    @classmethod
    def setUpClass(cls):
        Pipeline.setUpClass.__func__(cls)
        import jev
        cls.jev = jev
        cls.ws = os.path.join(cls.tmp, "jev-ws")
        os.makedirs(cls.ws)
        cls.resume = os.path.join(cls.tmp, "resume.md")
        with open(cls.resume, "w") as f:
            f.write("# Test Person\n\nB.S. Computer Science, May 2028. Software intern at Example Co, Python and C++.\n" * 3)
        cls.calls = []

        def fake_post(body, key, timeout=90):
            req = json.loads(body)
            cls.calls.append(req)
            if key == "bad-key-0000000000000":
                import urllib.error
                raise urllib.error.HTTPError("https://api.typesafe.ai", 401, "unauthorized", {}, io.BytesIO(b"{}"))
            title = req["state"]["job"]["title"]
            fit = 2.8 if "Intern" in title else 0.4
            return {"model": "jev-1.14.0", "usage": {"input_tokens": 2000, "output_tokens": 0},
                    "answers": {"eligible": {"noul": 0.9 if "Senior" not in title else 0.1},
                                "fit": {"score": fit, "confidence": 0.8}}}
        jev._post = fake_post

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("TYPESAFE_API_KEY", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    run_cli = Pipeline.run_cli

    def setUp(self):
        os.environ["TYPESAFE_API_KEY"] = "test-key-000000000000000"
        self.run_cli("update")

    def test_1_rubric_must_be_filled(self):
        code, out, _ = self.run_cli("jev", "rubric", "--workspace", self.ws)
        self.assertEqual(code, 0)
        code, _, err = self.run_cli("jev", "estimate", "--all", "--resume", self.resume, "--price-per-mtok", "0.042", "--workspace", self.ws)
        self.assertEqual(code, 1)
        self.assertIn("placeholders", err)
        text = re.sub(r"^- \[.*\]$\n?", "", open(os.path.join(self.ws, "rubric.md")).read(), flags=re.M)
        text = text.replace("[kinds of work they don't want, e.g. \"sales, customer support, retail, or any non-engineering role\"]", "sales")
        text = text.replace("[generic example]", "IT support").replace("[their 3 to 6 core areas, in their words]", "systems software")
        text = text.replace("[their core areas]", "systems software")
        open(os.path.join(self.ws, "rubric.md"), "w").write(text)
        rules, levels = self.jev.load_rubric(self.ws)
        self.assertEqual(len(levels), 4)
        self.assertTrue(rules)

    def test_2_estimate_and_grade(self):
        code, out, err = self.run_cli("jev", "estimate", "--all", "--resume", self.resume, "--price-per-mtok", "0.042", "--workspace", self.ws)
        self.assertEqual(code, 0, err)
        self.assertIn("3 postings to grade", out)
        self.assertEqual(self.calls, [])  # estimate sends nothing
        code, _, err = self.run_cli("jev", "grade", "--all", "--resume", self.resume, "--price-per-mtok", "0.042", "--workspace", self.ws)
        self.assertEqual(code, 1)
        self.assertIn("--max-cost", err)
        code, out, err = self.run_cli("jev", "grade", "--all", "--resume", self.resume, "--max-cost", "1", "--price-per-mtok", "0.042",
                                      "--workers", "2", "--workspace", self.ws)
        self.assertEqual(code, 0, err)
        self.assertIn("Graded 3 of 3", out)
        sent = self.calls[0]
        self.assertIn("Software intern at Example Co", sent["state"]["resume"])  # the resume goes verbatim
        self.assertTrue(sent["state"]["job"]["excerpt"])
        self.assertEqual(set(sent["questions"]), {"eligible", "fit"})
        # a second run grades nothing new and reuses the saved resume and selection
        n = len(self.calls)
        code, out, _ = self.run_cli("jev", "grade", "--max-cost", "1", "--price-per-mtok", "0.042", "--workspace", self.ws)
        self.assertIn("0 postings to grade", out)
        self.assertEqual(len(self.calls), n)
        code, out, _ = self.run_cli("search", "--graded", "--min-fit", "2", "--min-eligible", "0.5", "--sort", "rank", "--workspace", self.ws)
        self.assertIn("acme:1", out)
        self.assertNotIn("acme:2", out)
        self.assertIn("jev fit 2.8", out)
        code, out, _ = self.run_cli("board", "--workspace", self.ws)
        self.assertIn("1 Jev picks", out)
        self.assertIn("Jev's top picks", open(os.path.join(self.ws, "board.html")).read())
        spend = self.jev.spend(self.ws)
        self.assertAlmostEqual(spend[-1]["usd"], 3 * 2000 * 0.042 / 1e6, places=8)

    def test_3_cost_cap_and_bad_key(self):
        ws = os.path.join(self.tmp, "jev-ws2")
        os.makedirs(ws, exist_ok=True)
        shutil.copy(os.path.join(self.ws, "rubric.md"), ws)
        code, out, err = self.run_cli("jev", "grade", "--all", "--resume", self.resume, "--max-cost", "0.0000001",
                                      "--price-per-mtok", "0.042", "--workspace", ws)
        self.assertEqual(code, 0, err)
        self.assertIn("Graded 0 of 3", out)
        self.assertIn("cap", out)
        os.environ["TYPESAFE_API_KEY"] = "bad-key-0000000000000"
        code, _, err = self.run_cli("jev", "grade", "--all", "--resume", self.resume, "--max-cost", "1", "--price-per-mtok", "0.042", "--workspace", ws)
        self.assertEqual(code, 1)
        self.assertIn("key", err)

    def test_4_price_page_parsing(self):
        page = "| Price (per Btok / per Mtok) | \\$42 / \\$0.042 | \\$42 / \\$0.042 |"
        self.assertEqual(self.jev.parse_price(page), 0.042)
        self.assertIsNone(self.jev.parse_price("nothing here"))


class JevBudget(JevGrading):
    """--max-total caps the workspace's spend over all runs, and an interrupted run's checkpoint still counts."""

    def test_5_max_total_and_checkpoints(self):
        ws = os.path.join(self.tmp, "jev-ws3")
        os.makedirs(ws, exist_ok=True)
        shutil.copy(os.path.join(self.ws, "rubric.md"), ws)
        # a run killed after its last checkpoint: only the checkpoint line exists
        with open(os.path.join(ws, "jev-spend.jsonl"), "w") as f:
            f.write(json.dumps({"run": "r1", "at": "2026-11-01T10:00:00", "graded": 5, "failed": 0, "input_tokens": 1000,
                                "usd": 0.5, "final": False}) + "\n")
            f.write(json.dumps({"run": "r0", "at": "2026-11-01T09:00:00", "graded": 1, "failed": 0, "input_tokens": 10,
                                "usd": 0.1, "final": False}) + "\n")
            f.write(json.dumps({"run": "r0", "at": "2026-11-01T09:01:00", "graded": 2, "failed": 0, "input_tokens": 20,
                                "usd": 0.2, "final": True}) + "\n")
        self.assertAlmostEqual(self.jev.total_spent(ws), 0.7)  # last record per run
        code, out, _ = self.run_cli("jev", "spend", "--workspace", ws)
        self.assertIn("interrupted", out)
        code, _, err = self.run_cli("jev", "grade", "--all", "--resume", self.resume, "--max-total", "0.7",
                                    "--price-per-mtok", "0.042", "--workspace", ws)
        self.assertEqual(code, 1)
        self.assertIn("used up", err)
        code, out, err = self.run_cli("jev", "grade", "--all", "--resume", self.resume, "--max-total", "1",
                                      "--price-per-mtok", "0.042", "--workspace", ws)
        self.assertEqual(code, 0, err)
        self.assertIn("Graded 3 of 3", out)
        recs = [json.loads(l) for l in open(os.path.join(ws, "grades.jsonl"))]
        self.assertTrue(all(r["tok"] == 2000 for r in recs))
        code, out, _ = self.run_cli("jev", "grade", "--help", "--workspace", ws)
        self.assertIn("--max-total", out)


class LiveCheck(unittest.TestCase):
    """check: job-board APIs decide open/closed; other pages are read for a closed notice."""

    def test_live_status(self):
        sys.path.insert(0, os.path.join(ROOT, "skills", "find-jobs", "scripts"))
        import jobs
        calls = []

        def fake(url, headers=None, limit=None):
            calls.append(url)
            if "boards-api.greenhouse.io" in url:
                return (404, url, "") if url.endswith("/2") else (200, url, "{}")
            if "myworkdayjobs.com/wday/cxs/acme/External/job/" in url:
                return 200, url, json.dumps({"jobPostingInfo": {"canApply": False}})
            if "careers.example.com/closed" in url:
                return 200, url, "<html><h1>Sorry, this position has been filled.</h1></html>"
            return 200, url, "<html>Apply now</html>"
        old = jobs._status_code
        jobs._status_code = fake
        try:
            gh = lambda i: {"id": f"acme:{i}", "ats": "greenhouse", "company": "Acme", "url": f"https://job-boards.greenhouse.io/acme/jobs/{i}"}
            self.assertEqual(jobs.live_status(gh(1))[0], "open")
            self.assertEqual(jobs.live_status(gh(2))[0], "closed")
            wd = {"id": "acme:R1", "ats": "workday", "company": "Acme", "url": "https://acme.wd5.myworkdayjobs.com/en-US/External/job/Austin-TX/Engineer_R1"}
            self.assertEqual(jobs.live_status(wd)[0], "closed")
            self.assertIn("/wday/cxs/acme/External/job/Austin-TX/Engineer_R1", calls[-1])  # locale dropped
            page = lambda u: {"id": "x:1", "ats": "phenom", "company": "X", "url": u}
            self.assertEqual(jobs.live_status(page("https://careers.example.com/closed/1"))[0], "closed")
            self.assertEqual(jobs.live_status(page("https://careers.example.com/open/1"))[0], "open?")
        finally:
            jobs._status_code = old


class Filters(unittest.TestCase):
    def test_or_title_and_expired(self):
        sys.path.insert(0, os.path.join(ROOT, "skills", "find-jobs", "scripts"))
        import jobs
        rows = [{"id": "a:1", "title": "Instructional Designer", "family": "people", "deadline": "2020-01-01"},
                {"id": "a:2", "title": "Learning Experience Designer", "family": "design"},
                {"id": "a:3", "title": "Teacher", "family": "education"}]
        keep = lambda args: [r["id"] for r in rows if all(p(r) for _, p in jobs.build_filters(args, tempfile.mkdtemp()))]
        self.assertEqual(keep(["--family", "education", "--or-title", "designer"]), ["a:2", "a:3"])  # a:1's deadline passed
        self.assertEqual(keep(["--family", "education", "--or-title", "designer", "--include-expired"]), ["a:1", "a:2", "a:3"])
        self.assertEqual(jobs.prefilter(["--family", "education", "--or-title", "designer"]), [])  # titles need parsing


class JevScopes(JevGrading):
    def test_6_scopes_add_up(self):
        ws = os.path.join(self.tmp, "jev-ws4")
        os.makedirs(ws, exist_ok=True)
        shutil.copy(os.path.join(self.ws, "rubric.md"), ws)
        common = ["--resume", self.resume, "--max-cost", "1", "--price-per-mtok", "0.042", "--workspace", ws]
        code, out, err = self.run_cli("jev", "grade", "--title", "intern", *common)
        self.assertIn("Graded 1 of 1", out, err)
        code, out, err = self.run_cli("jev", "grade", "--title", "mechanical", *common)
        self.assertIn("Graded 1 of 1", out, err)
        cfg = json.load(open(os.path.join(ws, "jev.json")))
        self.assertEqual(len(cfg["selections"]), 2)
        n = len(self.calls)
        code, out, _ = self.run_cli("jev", "grade", "--max-cost", "1", "--price-per-mtok", "0.042", "--workspace", ws)
        self.assertIn("0 postings to grade (2 already graded", out)  # both scopes, nothing new
        self.assertEqual(len(self.calls), n)
        code, out, _ = self.run_cli("jev", "status", "--workspace", ws)
        self.assertEqual(out.count("Saved scope:"), 2)
