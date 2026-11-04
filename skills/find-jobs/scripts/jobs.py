#!/usr/bin/env python3
"""Search the daily-jobs dataset: every US posting from ~1,000 company career sites, refreshed daily.

Usage: python3 jobs.py <command> [options]          (Python 3.9+, standard library only)

  update [--force]          download the newest dataset (~12 MB) when there is one
  status                    dataset date and counts, cache folder, workspace files
  search [filters]          postings that pass every filter, newest first (filters below; --count for the funnel)
  show ID [ID ...]          each posting's facts and its eligibility excerpt (~1,800 chars; fetched once over the network, then cached)
  check ID [ID ...] | --ids FILE   is each posting still open? (asks its job board's API, or loads its page)
  verdict ID --tier T --why TEXT [--gaps TEXT] [--score 0-100]   record your judgment (tier: strong, good, stretch, no)
  verdict --file FILE       record many: one JSON object per line {"id", "tier", "why", "gaps", "score"}
  track ID STATUS [--note TEXT]   saved, applied, interviewing, offer, rejected, not-interested (or "clear")
  board [--open]            write the workspace's board.html and matches.md from the verdicts
  companies [REGEX]         companies in the data with posting counts and board status
  scrape COMPANY | --board JSON   fetch one company's board live with the bundled scrapers; its rows join your searches
  find-board COMPANY [--url CAREERS_URL] [--slug SLUG]   work out which job board a company uses (for scrape --board)
  jev ...                   grade postings against the resume with Jev, TypeSafe's System One model (`jobs.py jev` for help)

Search filters (all optional, combined with AND; REGEX is case-insensitive; repeat a flag to OR its values):
  --title REGEX  --not-title REGEX  --company REGEX  --not-company REGEX  --category REGEX
  --location REGEX  --state TX,CA  --remote  --or-remote (a remote posting passes the location filters)
  --level intern,new-grad,entry,mid,senior,manager,unknown     --family software,data,hardware,... (see `status`)
  --or-title REGEX (with --family: a title match also passes, for roles filed under another field)
  --include-expired (postings whose parsed application deadline has passed are hidden unless you pass this)
  --company/--title etc. take Python regexes; use \\b for word edges (--not-title "\\bsr\\b|\\blead\\b")
  --max-years N (stated minimum experience; postings that state none pass)   --degree hs|associate|bs|ms|phd (the person's
  highest; postings that require more are dropped)   --term "summer 2027" (season and/or year; postings that state
  no term pass unless --strict-term)
  --needs-sponsorship (drop no-sponsorship and citizens-only postings)   --no-citizen-only   --no-clearance
  --min-pay N (yearly; hourly x 2,080; a range passes when its top reaches N; postings without pay pass unless --has-pay)   --since DATE|Nd (first seen)   --posted-since DATE|Nd
  --unjudged (not in your verdicts)   --ids FILE (one id per line)
  --graded / --ungraded, --min-fit F (0-3), --min-eligible E (0-1): Jev grades from `jobs.py jev grade`
Output: --limit N (default 60) | --all, --sort seen|posted|company|pay|rank (Jev fit x eligible), --json (full rows), --ids-only, --count (funnel and breakdowns)

Files: the dataset is cached in ~/.cache/daily-jobs ($DAILY_JOBS_CACHE). Your verdicts, statuses and board live in the
workspace, ~/job-search ($JOBS_WORKSPACE, or --workspace DIR before or after the command). Data: https://github.com/Code-Tomato/daily-jobs ($DAILY_JOBS_REPO).
"""
import gzip, html, http.client, json, os, re, shutil, sys, tempfile, time, urllib.error, urllib.parse, urllib.request, webbrowser, zlib
from collections import Counter
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import signals  # noqa: E402
import jev  # noqa: E402

REPO = os.environ.get("DAILY_JOBS_REPO", "Code-Tomato/daily-jobs")
CACHE = os.environ.get("DAILY_JOBS_CACHE") or os.path.join(os.path.expanduser("~"), ".cache", "daily-jobs")
UA = {"User-Agent": "daily-jobs-skill/1.0"}
TIERS = ("strong", "good", "stretch", "no")
STATUSES = ("saved", "applied", "interviewing", "offer", "rejected", "not-interested")
LEVELS = ("intern", "new-grad", "entry", "mid", "senior", "manager", "unknown")


class Fail(Exception):
    pass


def opt(args, name, default=None):
    """Value after `name` (the last one if repeated), else default."""
    vals = opts(args, name)
    return vals[-1] if vals else default


def opts(args, name):
    return [args[i + 1] for i, a in enumerate(args[:-1]) if a == name]


def flag(args, name):
    return name in args


BOOL_FLAGS = {"--help", "-h", "--include-expired", "--force", "--count", "--json", "--ids-only", "--all", "--remote", "--or-remote", "--strict-term", "--needs-sponsorship",
              "--no-citizen-only", "--no-clearance", "--has-pay", "--unjudged", "--open", "--keep-non-us", "--graded", "--ungraded",
              "--check", "--yes"}


def positional(args):
    """Arguments that are neither flags nor a flag's value."""
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a.startswith("--"):
            skip = a not in BOOL_FLAGS
        else:
            out.append(a)
    return out


def workspace(args):
    ws = opt(args, "--workspace") or os.environ.get("JOBS_WORKSPACE") or os.path.join(os.path.expanduser("~"), "job-search")
    os.makedirs(ws, exist_ok=True)
    return ws


# --- dataset ---------------------------------------------------------------------------------------------------------

def _get(url, headers=None, timeout=120):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    for attempt in range(4):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in (404, 410, 416) or attempt == 3:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 3:
                raise
        time.sleep(2 * (attempt + 1))


def _download(url, dest, label):
    with _get(url) as r, tempfile.NamedTemporaryFile("wb", dir=os.path.dirname(dest), delete=False) as tmp:
        total, got, last = int(r.headers.get("Content-Length") or 0), 0, 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            tmp.write(chunk)
            got += len(chunk)
            tty = sys.stderr.isatty()
            if total and time.time() - last > (0.5 if tty else 15):  # an agent's shell is no terminal: a line every 15 s
                print(f"{chr(13) if tty else ''}{label}: {got / 1e6:.0f} of {total / 1e6:.0f} MB", end="" if tty else "\n",
                      file=sys.stderr, flush=True)
                last = time.time()
    if total and sys.stderr.isatty():
        print(file=sys.stderr)
    os.replace(tmp.name, dest)


def meta():
    try:
        with open(os.path.join(CACHE, "meta.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def update(args):
    os.makedirs(CACHE, exist_ok=True)
    try:
        with _get(f"https://github.com/{REPO}/releases/latest/download/meta.json", timeout=60) as r:
            latest = json.loads(r.read())
    except Exception as e:
        raise Fail(f"could not reach the dataset at github.com/{REPO} ({e}). Check the connection and try again.")
    have = meta()
    files = ("jobs.jsonl.gz", "excerpts.dict")
    if have and have.get("tag") == latest["tag"] and all(os.path.exists(os.path.join(CACHE, f)) for f in files) and not flag(args, "--force"):
        print(f"Up to date: {latest['postings']:,} postings from {latest['companies']:,} companies, {latest['date']}.")
        return
    base = f"https://github.com/{REPO}/releases/download/{latest['tag']}"
    for name in files:
        _download(f"{base}/{name}", os.path.join(CACHE, name), name)
    with open(os.path.join(CACHE, "meta.json.tmp"), "w") as f:
        json.dump(latest, f)
    os.replace(os.path.join(CACHE, "meta.json.tmp"), os.path.join(CACHE, "meta.json"))
    for n in os.listdir(CACHE):  # excerpts fetched for an older release no longer match its offsets
        if n.startswith("excerpts-") and latest["tag"] not in n:
            os.remove(os.path.join(CACHE, n))
    new = f", {latest['new_today']:,} first seen that day" if latest.get("new_today") else ""
    print(f"Updated to {latest['date']}: {latest['postings']:,} postings from {latest['companies']:,} companies{new}.")


def need_data():
    m = meta()
    if not m or not os.path.exists(os.path.join(CACHE, "jobs.jsonl.gz")):
        raise Fail("No dataset yet. Run: python3 jobs.py update")
    return m


def local_rows():
    """Rows scraped on this machine (scrape command); they override the dataset's rows with the same id."""
    d = os.path.join(CACHE, "local")
    if not os.path.isdir(d):
        return
    for n in sorted(os.listdir(d)):
        if n.endswith(".jsonl"):
            with open(os.path.join(d, n)) as f:
                for line in f:
                    try:
                        yield {**json.loads(line), "local": True}
                    except ValueError:
                        pass


def rows(pre=(), seen=None, funnel=None):
    """Every posting: the dataset's rows, then this machine's scraped ones. pre: [(name, check(raw JSON line))] skips most
    rows before they are parsed (search's level and field filters; several times faster on a narrow search); seen[0]
    counts every dataset line and funnel[name] the lines passing each check."""
    need_data()
    local = {r["id"]: r for r in local_rows()}
    local_cos = {r["company"] for r in local.values()}
    with gzip.open(os.path.join(CACHE, "jobs.jsonl.gz"), "rt", encoding="utf-8") as f:
        for line in f:
            if seen is not None:
                seen[0] += 1
            ok = True
            for name, check in pre:
                if not check(line):
                    ok = False
                    break
                if funnel is not None:
                    funnel[name] += 1
            if not ok:
                continue
            r = json.loads(line)
            if r["company"] in local_cos:  # a fresh local scrape replaces the company's published rows
                continue
            yield r
    yield from local.values()


def get_rows(ids):
    want = set(ids)
    found = {r["id"]: r for r in rows() if r["id"] in want}
    missing = [i for i in ids if i not in found]
    if missing:
        raise Fail("Not in the dataset (closed, or a typo?): " + ", ".join(missing[:10]))
    return [found[i] for i in ids]


def _resolve(url):
    """GitHub answers a release download with a redirect to a signed storage URL; resolving it once saves a round trip
    per range request. Falls back to the original URL."""
    try:
        with _get(url, {"Range": "bytes=0-0"}, timeout=60) as resp:
            return resp.geturl()
    except Exception:
        return url


def _range(url, start, end, tries=5):
    """Bytes start..end of url, retried through dropped connections, TLS errors and short reads."""
    for attempt in range(tries):
        try:
            with _get(url, {"Range": f"bytes={start}-{end}"}, timeout=60) as resp:
                blob = resp.read()
                if resp.status != 206:  # a server that ignores Range sends the whole file
                    blob = blob[start:end + 1]
            if len(blob) == end - start + 1:
                return blob
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise Fail("Your copy of the dataset is older than the oldest release kept online. Run: python3 jobs.py update")
            if e.code != 403 or attempt == tries - 1:  # 403: the signed URL expired
                raise
            raise _Expired()
        except (OSError, http.client.HTTPException, ValueError):
            if attempt == tries - 1:
                raise
        time.sleep(2 * (attempt + 1))
    raise Fail(f"Could not read the excerpts file (short reads). Try again, or run: python3 jobs.py update")


class _Expired(Exception):
    pass


def _inflate(blob, zdict):
    d = zlib.decompressobj(-15, zdict=zdict)
    return (d.decompress(blob) + d.flush()).decode("utf-8", "replace")


def excerpts(rs, progress=None):
    """{id: excerpt} for rows: from the local cache, local scrapes, the whole excerpts file when it was downloaded (a big
    Jev run does that), or byte ranges of the release's excerpts.bin, fetched in parallel and cached as they arrive."""
    m = need_data()
    cache_path = os.path.join(CACHE, f"excerpts-{m['tag']}.jsonl")
    have = {}
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            for line in f:
                try:
                    d = json.loads(line)
                    have[d["id"]] = d["text"]
                except ValueError:
                    pass
    out = {r["id"]: r["excerpt"] for r in rs if r.get("local")}
    todo = [r for r in rs if r["id"] not in out and r["id"] not in have and r.get("x")]
    out.update({r["id"]: have[r["id"]] for r in rs if r["id"] in have})
    if not todo:
        return out
    zdict = open(os.path.join(CACHE, "excerpts.dict"), "rb").read()
    whole = os.path.join(CACHE, f"excerpts-{m['tag']}.bin")
    if os.path.exists(whole):
        with open(whole, "rb") as fh:
            for r in todo:
                fh.seek(r["x"][0])
                out[r["id"]] = _inflate(fh.read(r["x"][1]), zdict)
        return out
    url = f"https://github.com/{REPO}/releases/download/{m['tag']}/excerpts.bin"
    todo.sort(key=lambda r: r["x"][0])
    groups, cur = [], []
    for r in todo:  # neighbors share one request when the gap between them is small
        if cur and (r["x"][0] - (cur[-1]["x"][0] + cur[-1]["x"][1]) > 65536 or r["x"][0] + r["x"][1] - cur[0]["x"][0] > 4 << 20):
            groups.append(cur)
            cur = []
        cur.append(r)
    groups.append(cur)
    import threading
    from concurrent.futures import ThreadPoolExecutor
    lock, signed, done, last = threading.Lock(), [_resolve(url)], [0], [time.time()]

    def one(g):
        start, end = g[0]["x"][0], g[-1]["x"][0] + g[-1]["x"][1] - 1
        try:
            blob = _range(signed[0], start, end)
        except _Expired:
            with lock:
                signed[0] = _resolve(url)
            blob = _range(signed[0], start, end)
        got = {r["id"]: _inflate(blob[r["x"][0] - start:r["x"][0] - start + r["x"][1]], zdict) for r in g}
        with lock:
            with open(cache_path, "a") as f:
                f.writelines(json.dumps({"id": i, "text": t}) + "\n" for i, t in got.items())
            out.update(got)
            done[0] += 1
            if progress and time.time() - last[0] > 10:
                last[0] = time.time()
                progress(f"fetching excerpts: {done[0]:,} of {len(groups):,} requests")

    with ThreadPoolExecutor(min(8, len(groups))) as ex:
        list(ex.map(one, groups))
    return out


# --- workspace -------------------------------------------------------------------------------------------------------

def read_jsonl(path):
    out = []
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def verdicts(ws):
    """Latest verdict per id."""
    return {v["id"]: v for v in read_jsonl(os.path.join(ws, "verdicts.jsonl"))}


def statuses(ws):
    out = {}
    for t in read_jsonl(os.path.join(ws, "tracking.jsonl")):
        if t.get("status") == "clear":
            out.pop(t["id"], None)
        else:
            out[t["id"]] = t
    return out


def jev_config(ws):
    try:
        with open(os.path.join(ws, "jev.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_jev_config(ws, cfg):
    with open(os.path.join(ws, "jev.json"), "w") as f:
        json.dump(cfg, f, indent=1)


def current_grades(ws):
    """Jev grades made under the resume and rubric of the last `jev grade` run."""
    h = jev_config(ws).get("h")
    return jev.grades(ws, h) if h else {}


def rank(g):
    return (g.get("fit") or 0) * (g.get("eligible") or 0)


# --- search ----------------------------------------------------------------------------------------------------------

def _days(s):
    """'2026-10-01' or '7d' -> ISO date."""
    if re.fullmatch(r"\d+d", s or ""):
        return (date.today() - timedelta(days=int(s[:-1]))).isoformat()
    try:
        return date.fromisoformat(s).isoformat()
    except (TypeError, ValueError):
        raise Fail(f"Not a date or a number of days: {s!r} (use 2026-10-01 or 14d)")


def _rx(vals, what):
    if not vals:
        return None
    try:
        return re.compile("|".join(f"(?:{v})" for v in vals), re.I)
    except re.error as e:
        raise Fail(f"Bad {what} regex {vals}: {e}")


def _season_year(text):
    m = re.search(r"(summer|fall|autumn|spring|winter)", text or "", re.I)
    y = re.search(r"(20\d\d)", text or "")
    return (m.group(1).lower().replace("autumn", "fall") if m else None, y.group(1) if y else None)


def _term_ok(want, have):
    """Seasons must agree when both are known, and years too: "Fall" passes "fall 2027"; "Summer 2028" does not."""
    return all(w is None or h is None or w == h for w, h in zip(want, have))


def _csv(vals):
    return {x.strip().lower() for v in vals for x in v.split(",") if x.strip()}


def build_filters(args, ws):
    """[(name, predicate)] in funnel order. Level and field come first: prefilter() turns them into a raw-line check."""
    f = []
    levels = _csv(opts(args, "--level"))
    if levels:
        bad = levels - set(LEVELS)
        if bad:
            raise Fail(f"Unknown level {', '.join(bad)}; use {', '.join(LEVELS)}")
        f.append(("level", lambda r: (r.get("level") or "unknown") in levels))
    fams = _csv(opts(args, "--family"))
    if fams:
        bad = fams - set(signals.FAMILY_LABELS)
        if bad:
            raise Fail(f"Unknown family {', '.join(bad)}; use {', '.join(signals.FAMILY_LABELS)}")
        or_title = _rx(opts(args, "--or-title"), "--or-title")
        f.append(("family", lambda r: (r.get("family") or "other") in fams or bool(or_title and or_title.search(r["title"]))))
    title, not_title = _rx(opts(args, "--title"), "--title"), _rx(opts(args, "--not-title"), "--not-title")
    company, not_company = _rx(opts(args, "--company"), "--company"), _rx(opts(args, "--not-company"), "--not-company")
    category, location = _rx(opts(args, "--category"), "--category"), _rx(opts(args, "--location"), "--location")
    st, or_remote = {s.upper() for s in _csv(opts(args, "--state"))}, flag(args, "--or-remote")
    if title:
        f.append(("title", lambda r: title.search(r["title"])))
    if not_title:
        f.append(("not-title", lambda r: not not_title.search(r["title"])))
    if company:
        f.append(("company", lambda r: company.search(r["company"])))
    if not_company:
        f.append(("not-company", lambda r: not not_company.search(r["company"])))
    if category:
        f.append(("category", lambda r: category.search(r.get("category") or "")))
    if flag(args, "--remote"):
        f.append(("remote", lambda r: r.get("remote") == "remote"))
    if location or st:
        def place(r):
            if or_remote and r.get("remote") == "remote":
                return True
            if location and location.search(r.get("location") or ""):
                return True
            return bool(st and st & set(r.get("states") or ()))
        f.append(("location", place))
    if opt(args, "--max-years") is not None:
        max_years = float(opt(args, "--max-years"))
        f.append(("max-years", lambda r: r.get("years") is None or r["years"] <= max_years))
    if opt(args, "--degree"):
        order = ["hs", "associate", "bs", "ms", "phd"]
        d = opt(args, "--degree").lower()
        if d not in order:
            raise Fail(f"--degree takes one of {', '.join(order)}")
        f.append(("degree", lambda r: not r.get("degree") or order.index(r["degree"]) <= order.index(d)))
    if opt(args, "--term"):
        want, strict = _season_year(opt(args, "--term")), flag(args, "--strict-term")
        if want == (None, None):
            raise Fail("--term takes a season and/or year, like \"summer 2027\" or \"fall\"")
        f.append(("term", lambda r: _term_ok(want, _season_year(r["term"])) if r.get("term") else not strict))
    if flag(args, "--needs-sponsorship"):
        f.append(("sponsorship", lambda r: not r.get("no_sponsor") and not r.get("citizen")))
    elif flag(args, "--no-citizen-only"):
        f.append(("citizen-only", lambda r: not r.get("citizen")))
    if flag(args, "--no-clearance"):
        f.append(("clearance", lambda r: not r.get("clearance")))
    if opt(args, "--min-pay"):
        raw, has = opt(args, "--min-pay").replace(",", "").replace("$", "").lower(), flag(args, "--has-pay")
        try:
            min_pay = float(raw[:-1]) * 1000 if raw.endswith("k") else float(raw)
        except ValueError:
            raise Fail("--min-pay takes a yearly amount like 80000 or 80k")
        f.append(("min-pay", lambda r: (signals.yearly(r.get("pay")) or 0) >= min_pay if r.get("pay") else not has))
    elif flag(args, "--has-pay"):
        f.append(("has-pay", lambda r: bool(r.get("pay"))))
    if not flag(args, "--include-expired"):
        today = time.strftime("%Y-%m-%d")
        f.append(("open", lambda r: not r.get("deadline") or r["deadline"] >= today))
    if opt(args, "--since"):
        since = _days(opt(args, "--since"))
        f.append(("since", lambda r: (r.get("seen") or "") >= since))
    if opt(args, "--posted-since"):
        posted_since = _days(opt(args, "--posted-since"))
        f.append(("posted-since", lambda r: (r.get("posted") or r.get("seen") or "") >= posted_since))
    if flag(args, "--unjudged"):
        judged = set(verdicts(ws))
        f.append(("unjudged", lambda r: r["id"] not in judged))
    if opt(args, "--ids"):
        id_set = {l.strip() for l in open(opt(args, "--ids")) if l.strip()}
        f.append(("ids", lambda r: r["id"] in id_set))
    if any(flag(args, x) or opt(args, x) for x in ("--graded", "--ungraded", "--min-fit", "--min-eligible")):
        gs = current_grades(ws)
        if flag(args, "--ungraded"):
            f.append(("ungraded", lambda r: r["id"] not in gs))
        elif not gs:
            raise Fail("No Jev grades yet (see `jobs.py jev --help`).")
        else:
            lo_fit, lo_el = float(opt(args, "--min-fit", 0)), float(opt(args, "--min-eligible", 0))
            f.append(("graded", lambda r: r["id"] in gs and gs[r["id"]]["fit"] >= lo_fit and gs[r["id"]]["eligible"] >= lo_el))
    return f


def prefilter(args):
    """[(filter name, raw-line check)] equivalent to the --level and --family filters, in funnel order. Index lines are compact JSON, and a quote
    inside a string value is escaped, so '"level":"intern"' appears in a line only as that field."""
    checks = []
    for key, names, missing in (("level", _csv(opts(args, "--level")), "unknown"), ("family", _csv(opts(args, "--family")), "other")):
        if not names or (key == "family" and opts(args, "--or-title")):  # a title can let a row through: parse it
            continue
        marks = tuple(f'"{key}":"{n}"' for n in names if n != missing)
        tag = f'"{key}":'
        if missing in names:
            checks.append((key, lambda l, m=marks, t=tag, miss=f'"{key}":"{missing}"': any(x in l for x in m) or t not in l or miss in l))
        else:
            checks.append((key, lambda l, m=marks: any(x in l for x in m)))
    return checks


def flags_of(r):
    out = []
    if r.get("no_sponsor"):
        out.append("no-sponsorship")
    if r.get("citizen"):
        out.append("citizens/US-persons-only")
    if r.get("clearance"):
        out.append("clearance")
    if r.get("gpa"):
        out.append(f"gpa {r['gpa']}+")
    if r.get("deadline"):
        out.append(f"deadline {r['deadline']}" + (" PASSED" if r["deadline"] < time.strftime("%Y-%m-%d") else ""))
    return out


def line(r, v=None, s=None, g=None):
    bits = [r.get("level") or "level ?"]
    if r.get("years") is not None:
        bits.append(f"{r['years']}+ yrs")
    if r.get("degree"):
        bits.append(r["degree"].upper() if len(r["degree"]) <= 3 else r["degree"])
    if r.get("term"):
        bits.append(r["term"])
    if r.get("pay"):
        bits.append(signals.pay_text(r["pay"]))
    if r.get("remote"):
        bits.append(r["remote"])
    bits += flags_of(r)
    tail = (f" | seen {r.get('seen') or '?'}" + (f" | jev fit {g['fit']:.1f} elig {g['eligible']:.2f}" if g else "")
            + (f" | YOU: {v['tier']}" if v else "")) + (f" [{s['status']}]" if s else "") + (" | local" if r.get("local") else "")
    cut = lambda t, n: t if len(t) <= n else t[:n - 1] + "…"
    return f"{r['id']}  {r['company']} | {cut(r['title'], 90)} | {cut(r.get('location') or '?', 45)} | {', '.join(bits)}{tail}"


def search(args):
    ws = workspace(args)
    filters = build_filters(args, ws)
    funnel, out, seen = Counter(), [], [0]
    pre = prefilter(args)
    done = {name for name, _ in pre}
    for r in rows(pre, seen, funnel):
        ok = True
        for name, pred in filters:
            if name in done and not r.get("local"):
                continue  # already checked on the raw line, and counted there
            if not pred(r):
                ok = False
                break
            funnel[name] += 1
        if ok:
            out.append(r)
    total = seen[0] + sum(1 for _ in local_rows())
    if flag(args, "--count"):
        print(f"{total:,} postings")
        for name, _ in filters:
            print(f"  after --{name}: {funnel[name]:,}")
        for key, label in (("company", "companies"), ("family", "fields"), ("level", "levels"), ("states", "states")):
            c = Counter()
            for r in out:
                if key == "states":
                    vals = r.get("states") or ["?"]
                else:
                    vals = [r.get(key) or ("unknown" if key == "level" else "other")]
                c.update(vals)
            print(f"top {label}: " + ", ".join(f"{k} {n}" for k, n in c.most_common(15)))
        return
    sort = opt(args, "--sort", "seen")
    keys = {"seen": lambda r: (r.get("seen") or "", r.get("posted") or ""), "posted": lambda r: (r.get("posted") or "", r.get("seen") or ""),
            "company": lambda r: (r["company"].lower(), r["title"].lower()), "pay": lambda r: signals.yearly(r.get("pay")) or 0,
            "rank": lambda r: rank(gs.get(r["id"], {}))}
    gs = current_grades(ws) if sort == "rank" or not flag(args, "--json") else {}
    if sort not in keys:
        raise Fail(f"--sort takes {', '.join(keys)}")
    out.sort(key=keys[sort], reverse=sort != "company")
    limit = None if flag(args, "--all") else int(opt(args, "--limit", 60))
    shown = out[:limit]
    if flag(args, "--json"):
        for r in shown:
            print(json.dumps({k: v for k, v in r.items() if k != "x"}, ensure_ascii=False))
    elif flag(args, "--ids-only"):
        print("\n".join(r["id"] for r in shown))
    else:
        vs, ss = verdicts(ws), statuses(ws)
        for r in shown:
            print(line(r, vs.get(r["id"]), ss.get(r["id"]), gs.get(r["id"])))
        more = f" (showing {len(shown)}; --limit N or --all for more)" if len(out) > len(shown) else ""
        print(f"\n{len(out):,} match{'' if len(out) == 1 else 'es'}{more}", file=sys.stderr)


def show(args):
    ids = positional(args)
    if not ids:
        raise Fail("show takes posting ids (from search)")
    rs = get_rows(ids)
    ex = excerpts(rs)
    gs = current_grades(workspace(args))
    if flag(args, "--json"):
        for r in rs:
            print(json.dumps({**{k: v for k, v in r.items() if k != "x"}, "excerpt": ex.get(r["id"], "")}, ensure_ascii=False))
        return
    for r in rs:
        facts = [f"level {r.get('level') or '?'}", f"min years {r['years'] if r.get('years') is not None else 'not stated'}",
                 f"degree {r.get('degree') or 'not stated'}"]
        for k, label in (("term", "term"), ("remote", "work mode"), ("deadline", "deadline"), ("gpa", "min GPA")):
            if r.get(k):
                facts.append(f"{label} {r[k]}")
        if r.get("pay"):
            facts.append("pay " + signals.pay_text(r["pay"]))
        facts += [f for f in flags_of(r) if not f.startswith(("gpa", "deadline"))]
        g = gs.get(r["id"])
        if g:
            facts.append(f"Jev: fit {g['fit']:.2f} of 3, eligible {g['eligible']:.2f}")
        print(f"=== {r['id']}\n{r['company']}: {r['title']}\n{r.get('location') or '?'} | posted {r.get('posted') or '?'} | first seen {r.get('seen') or '?'}\n"
              f"{r.get('url')}\nParsed: {'; '.join(facts)}\n--- excerpt\n{ex.get(r['id'], '(no text)')}\n")


# --- live check ------------------------------------------------------------------------------------------------------

BROWSER = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 "
           "Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
CLOSED_TEXT = re.compile(r"no longer (?:available|accepting|open|active|posted|exists)|(?:position|job|role|posting|requisition|opening) "
                         r"(?:has been |is |was )?(?:filled|closed|expired|removed|no longer)|job (?:not found|does not exist)|"
                         r"(?:page|job) (?:you(?:'re| are) looking for|cannot be found|could not be found)|not currently accepting|"
                         r"this (?:job|position|posting) (?:has )?(?:expired|closed)|applications? (?:are|is) (?:now )?closed", re.I)


def _status_code(url, headers=None, limit=None):
    """(HTTP status, final URL, body text) of a GET; status 0 when the network failed. limit caps the bytes read."""
    req = urllib.request.Request(url, headers={**BROWSER, **(headers or {})})
    for attempt in range(2):  # one retry through a dropped connection or DNS hiccup
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.geturl(), (r.read(limit) if limit else r.read()).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, url, ""
        except (OSError, http.client.HTTPException, ValueError):
            time.sleep(1)
    return 0, url, ""


def live_status(r, cache=None):
    """("open" | "closed" | "unknown" | "open?", how) for one posting, from its job board's API when there is one, else its page."""
    url, a = r.get("url") or "", r.get("ats")
    u = urllib.parse.urlsplit(url)
    parts = [p for p in u.path.split("/") if p]
    host = (u.hostname or "").lower()
    jid = r["id"].split(":", 1)[1]
    J = {"Accept": "application/json"}
    try:
        if a == "workday" and host.endswith("myworkdayjobs.com") and "job" in parts:
            if re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
                parts = parts[1:]
            code, _, body = _status_code(f"https://{host}/wday/cxs/{host.split('.')[0]}/{'/'.join(parts)}", {**J, "Content-Type": "application/json"})
            if code == 200:
                info = json.loads(body).get("jobPostingInfo") or {}
                return ("open", "Workday API") if info.get("canApply", True) else ("closed", "Workday: not accepting applications")
            return ("closed", f"Workday API {code}") if code in (404, 410) else ("unknown", f"Workday API {code or 'unreachable'}")
        if a == "greenhouse":
            slug = parts[0] if host in ("boards.greenhouse.io", "job-boards.greenhouse.io") and parts else None
            slug = slug or next((c.get("slug") for c in _all_cfgs() if c["company"] == r["company"] and c["ats"] == "greenhouse"), None)
            if slug:
                code, _, _ = _status_code(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{jid}", J)
                if code in (200, 404):
                    return ("open" if code == 200 else "closed", "Greenhouse API")
        if a == "lever" and host.endswith("lever.co") and len(parts) >= 2:
            api = "https://api.eu.lever.co" if ".eu." in host else "https://api.lever.co"
            code, _, _ = _status_code(f"{api}/v0/postings/{parts[0]}/{parts[1]}", J)
            if code in (200, 404):
                return ("open" if code == 200 else "closed", "Lever API")
        if a == "ashby" and host == "jobs.ashbyhq.com" and len(parts) >= 2:
            q = ("query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) { jobPosting("
                 "organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) { id } }")
            body = json.dumps({"operationName": "ApiJobPosting", "query": q,
                               "variables": {"organizationHostedJobsPageName": parts[0], "jobPostingId": parts[1]}}).encode()
            req = urllib.request.Request("https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting", data=body,
                                         headers={**BROWSER, "Content-Type": "application/json"})
            for attempt in range(2):
                try:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        d = json.loads(resp.read())
                    return ("open" if (d.get("data") or {}).get("jobPosting") else "closed", "Ashby API")
                except (OSError, http.client.HTTPException):
                    time.sleep(1)
        if a == "smartrecruiters" and len(parts) >= 1:
            slug = parts[0] if host.endswith("smartrecruiters.com") else None
            if slug:
                code, _, _ = _status_code(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{jid}", J)
                if code in (200, 404):
                    return ("open" if code == 200 else "closed", "SmartRecruiters API")
        if a == "rippling" and host == "ats.rippling.com" and len(parts) >= 3:
            code, _, _ = _status_code(f"https://api.rippling.com/platform/api/ats/v1/board/{parts[0]}/jobs/{parts[-1]}", J)
            if code in (200, 404):
                return ("open" if code == 200 else "closed", "Rippling API")
    except (ValueError, KeyError, TypeError):
        pass
    if not url:
        return "unknown", "no link"
    code, final, body = _status_code(url, limit=400_000)
    if code in (404, 410):
        return "closed", f"page {code}"
    if code != 200:
        return "unknown", f"page {code or 'unreachable'}"
    m = CLOSED_TEXT.search(re.sub(r"<[^>]+>", " ", body))
    if m or re.search(r"[?&]error=true", final):
        return "closed", f"page says \"{m[0] if m else 'error=true'}\""
    return "open?", "page loads with no closed notice (pages built by scripts can't always tell)"


def _all_cfgs():
    global _CFGS
    try:
        return _CFGS
    except NameError:
        _CFGS = []
        for n in ("companies.json", "companies-found.json"):
            try:
                _CFGS += json.load(open(os.path.join(HERE, n)))
            except (OSError, ValueError):
                pass
        return _CFGS


def check(args):
    """Is each posting still open? One request per posting, to its job board's API or its page."""
    ids = positional(args)
    if opt(args, "--ids"):
        ids += [l.strip() for l in open(opt(args, "--ids")) if l.strip()]
    if not ids:
        raise Fail("check takes posting ids (or --ids FILE)")
    rs = get_rows(ids)
    from concurrent.futures import ThreadPoolExecutor
    cache = {}

    def one(r):
        return r, live_status(r, cache)

    counts = Counter()
    with ThreadPoolExecutor(6) as ex:
        for r, (st, how) in ex.map(one, rs):
            counts[st] += 1
            if flag(args, "--json"):
                print(json.dumps({"id": r["id"], "status": st, "how": how}))
            else:
                print(f"{st:8} {r['id']}  {r['company']} | {r['title'][:70]}  ({how})")
    print(", ".join(f"{n} {k}" for k, n in counts.most_common()) + ". Mark closed ones: verdict ID --tier no --why \"closed\"",
          file=sys.stderr)


# --- verdicts, tracking, board ---------------------------------------------------------------------------------------

def _posting_fields(r):
    return {k: r.get(k) for k in ("company", "title", "location", "url", "posted", "seen", "level", "pay", "term", "deadline", "remote")}


def verdict(args):
    ws = workspace(args)
    items = []
    if opt(args, "--file"):
        items = read_jsonl(opt(args, "--file"))
        if not items:
            raise Fail(f"No JSON lines in {opt(args, '--file')}")
    else:
        if not positional(args):
            raise Fail("verdict ID --tier strong|good|stretch|no --why TEXT [--gaps TEXT], or verdict --file FILE")
        items = [{"id": positional(args)[0], "tier": opt(args, "--tier"), "why": opt(args, "--why"), "gaps": opt(args, "--gaps"),
                  "score": opt(args, "--score")}]
    for v in items:
        if v.get("tier") not in TIERS:
            raise Fail(f"{v.get('id')}: tier must be one of {', '.join(TIERS)}")
        if not v.get("why"):
            raise Fail(f"{v.get('id')}: give a one-sentence why")
        if v.get("score") is not None:
            try:
                v["score"] = max(0, min(100, int(float(v["score"]))))
            except (TypeError, ValueError):
                raise Fail(f"{v.get('id')}: score must be a number from 0 to 100")
    try:
        found = {r["id"]: r for r in get_rows([v["id"] for v in items])}
    except Fail as e:
        raise Fail(f"{e}. Nothing was recorded.")
    now = datetime.now().isoformat(timespec="seconds")
    with open(os.path.join(ws, "verdicts.jsonl"), "a") as f:
        for v in items:
            f.write(json.dumps({"id": v["id"], "tier": v["tier"], "why": v["why"], "gaps": v.get("gaps") or None, "score": v.get("score"), "at": now,
                                **_posting_fields(found[v["id"]])}, ensure_ascii=False) + "\n")
    c = Counter(v["tier"] for v in items)
    print(f"Recorded {len(items)} verdict{'s' * (len(items) != 1)} ({', '.join(f'{n} {t}' for t, n in c.items())}) in {ws}/verdicts.jsonl")


def track(args):
    ws = workspace(args)
    pos = positional(args)
    if len(pos) != 2 or pos[1] not in STATUSES + ("clear",):
        raise Fail(f"track ID STATUS, STATUS one of {', '.join(STATUSES)} or clear")
    jid, status = pos
    known = verdicts(ws).get(jid)
    if not known:
        known = _posting_fields(get_rows([jid])[0])
    with open(os.path.join(ws, "tracking.jsonl"), "a") as f:
        f.write(json.dumps({"id": jid, "status": status, "note": opt(args, "--note"), "at": datetime.now().isoformat(timespec="seconds"),
                            **{k: known.get(k) for k in ("company", "title", "url")}}, ensure_ascii=False) + "\n")
    print(f"{jid}: status cleared" if status == "clear" else f"{jid}: {status}")


BOARD_CSS = """
:root{--bg:#fbfaf8;--fg:#1d1d1f;--muted:#6b6b70;--line:#e4e2dd;--card:#fff;--strong:#1f7a4d;--good:#2d5fa8;--stretch:#9a6b00;--chip:#f0eee9}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--fg:#ececef;--muted:#9a9aa2;--line:#2b2b30;--card:#1c1c20;--strong:#5ccf95;--good:#7fa8ff;--stretch:#e0b14a;--chip:#26262b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:22px;margin:0 0 4px}p.sub{color:var(--muted);margin:0 0 18px}
.bar{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 18px}.bar input,.bar select{font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}
.bar input[type=search]{flex:1;min-width:200px}h2{font-size:16px;margin:26px 0 8px;display:flex;gap:8px;align-items:baseline}h2 small{color:var(--muted);font-weight:400}
.job{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:0 0 8px}
.job .top{display:flex;gap:10px;justify-content:space-between;flex-wrap:wrap}.job a{color:var(--fg);font-weight:600;text-decoration:none}.job a:hover{text-decoration:underline}
.co{color:var(--muted)}.why{margin:6px 0 0}.gaps{margin:4px 0 0;color:var(--stretch)}.meta{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.chip{background:var(--chip);border-radius:999px;padding:1px 9px;font-size:13px;color:var(--muted)}.st{font-weight:600;color:var(--fg)}
.tier-strong h2{color:var(--strong)}.tier-good h2{color:var(--good)}.tier-stretch h2{color:var(--stretch)}.hide{display:none}
"""
BOARD_JS = """
const q=document.getElementById('q'),st=document.getElementById('st');
function run(){const t=q.value.toLowerCase(),s=st.value;document.querySelectorAll('.job').forEach(j=>{
const okT=!t||j.dataset.text.includes(t);const js=j.dataset.status;
const okS=s==='all'||(s==='open'&&!['applied','interviewing','offer','rejected','not-interested'].includes(js))||js===s;
j.classList.toggle('hide',!(okT&&okS))});document.querySelectorAll('section').forEach(sec=>{
const n=sec.querySelectorAll('.job:not(.hide)').length;sec.querySelector('.n').textContent=n;sec.classList.toggle('hide',n===0)})}
q.addEventListener('input',run);st.addEventListener('change',run);run();
"""


def board(args):
    ws = workspace(args)
    vs, ss = verdicts(ws), statuses(ws)
    current = {}
    try:
        live, have_data = {r["id"]: r for r in rows() if r["id"] in vs}, True
    except Fail:
        live, have_data = {}, False
    for i, v in vs.items():
        if v["tier"] == "no":
            continue
        r = live.get(i)
        current[i] = {**v, **(_posting_fields(r) if r else {}), "gone": r is None and have_data}
    order = {t: n for n, t in enumerate(TIERS)}
    jobs = sorted(current.values(), key=lambda v: (order[v["tier"]], -(v.get("score") if v.get("score") is not None else 50),
                                                    -(int((v.get("seen") or "0000-00-00").replace("-", "")))))
    m = meta() or {}
    e = html.escape
    sections = []
    labels = {"strong": "Strong matches", "good": "Good matches", "stretch": "Stretches"}
    for tier in TIERS[:3]:
        cards = []
        for v in (j for j in jobs if j["tier"] == tier):
            s = ss.get(v["id"], {}).get("status", "")
            chips = [x for x in (v.get("location"), signals.pay_text(v.get("pay")), v.get("term"), v.get("remote"),
                                 f"deadline {v['deadline']}" if v.get("deadline") else None, f"first seen {v['seen']}" if v.get("seen") else None,
                                 "posting gone" if v.get("gone") else None) if x]
            text = " ".join(str(x) for x in (v.get("company"), v.get("title"), v.get("location"), v.get("why"), v.get("gaps"))).lower()
            cards.append(
                f'<div class="job" data-status="{e(s)}" data-text="{e(text)}"><div class="top"><div><a href="{e(v.get("url") or "#")}" target="_blank" rel="noopener">'
                f'{e(v.get("title") or "")}</a> <span class="co">· {e(v.get("company") or "")}</span></div>'
                + (f'<span class="chip st">{e(s)}</span>' if s else "") + "</div>"
                f'<p class="why">{e(v.get("why") or "")}</p>' + (f'<p class="gaps">Gap: {e(v["gaps"])}</p>' if v.get("gaps") else "")
                + '<div class="meta">' + "".join(f'<span class="chip">{e(str(c))}</span>' for c in chips) + "</div></div>")
        sections.append(f'<section class="tier-{tier}"><h2>{labels[tier]} <small><span class="n">{len(cards)}</span></small></h2>{"".join(cards)}</section>')
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>Job matches</title><style>{BOARD_CSS}</style></head><body><main><h1>Job matches</h1>"
            f'<p class="sub">{len(jobs)} postings judged worth a look, from the daily-jobs data of {e(m.get("date", "?"))}. '
            f"Built {datetime.now():%Y-%m-%d %H:%M}.</p>"
            '<div class="bar"><input id="q" type="search" placeholder="Filter by company, title, place, reason"><select id="st">'
            '<option value="open">Not applied yet</option><option value="all">Everything</option>'
            + "".join(f'<option value="{s}">{s}</option>' for s in STATUSES) + "</select></div>"
            + "".join(sections) + f"<script>{BOARD_JS}</script></main></body></html>")
    picks = jev_picks(ws, vs)
    if picks:
        rows_html = "".join(
            f'<div class="job" data-status="{e(ss.get(r["id"], {}).get("status", ""))}" data-text="{e((r["company"] + " " + r["title"] + " " + (r.get("location") or "")).lower())}">'
            f'<div class="top"><div><a href="{e(r.get("url") or "#")}" target="_blank" rel="noopener">{e(r["title"])}</a> <span class="co">· {e(r["company"])}</span></div>'
            f'<span class="chip">fit {g["fit"]:.1f} · eligible {g["eligible"]:.0%}</span></div><div class="meta">'
            + "".join(f'<span class="chip">{e(str(c))}</span>' for c in (r.get("location"), signals.pay_text(r.get("pay")), r.get("term"),
                                                                         f"first seen {r['seen']}" if r.get("seen") else None) if c)
            + "</div></div>" for r, g in picks)
        page = page.replace(f"<script>{BOARD_JS}</script>",
                            f'<section class="tier-good"><h2>Jev\'s top picks, not reviewed yet <small><span class="n">{len(picks)}</span></small></h2>'
                            f'<p class="sub">Ranked by fit × eligibility from Jev\'s pass over the data. Read the posting before applying.</p>{rows_html}</section>'
                            f"<script>{BOARD_JS}</script>")
    path = os.path.join(ws, "board.html")
    with open(path, "w") as f:
        f.write(page)
    md = [f"# Job matches ({m.get('date', '?')})", ""]
    for tier in TIERS[:3]:
        group = [j for j in jobs if j["tier"] == tier]
        if group:
            md += [f"## {labels[tier]} ({len(group)})", ""]
            for v in group:
                s = ss.get(v["id"], {}).get("status")
                md.append(f"- [{v.get('company')}: {v.get('title')}]({v.get('url')}) · {v.get('location') or '?'}"
                          + (f" · {signals.pay_text(v.get('pay'))}" if v.get("pay") else "") + (f" · **{s}**" if s else "")
                          + (" · posting gone" if v.get("gone") else "") + f"\n  {v.get('why')}" + (f" Gap: {v['gaps']}" if v.get("gaps") else ""))
            md.append("")
    if picks:
        md += [f"## Jev's top picks, not reviewed yet ({len(picks)})", ""]
        md += [f"- [{r['company']}: {r['title']}]({r.get('url')}) · {r.get('location') or '?'} · fit {g['fit']:.1f}, eligible {g['eligible']:.0%}"
               for r, g in picks]
    with open(os.path.join(ws, "matches.md"), "w") as f:
        f.write("\n".join(md))
    print(f"Wrote {path} and matches.md ({len(jobs)} judged matches" + (f", {len(picks)} Jev picks" if picks else "") + ")")
    if flag(args, "--open"):
        webbrowser.open("file://" + path)


def jev_picks(ws, vs, limit=150):
    """Graded postings Jev rates eligible (>= 0.5) and related (fit >= 2), best first, minus ones already judged."""
    gs = current_grades(ws)
    if not gs:
        return []
    good = {i for i, g in gs.items() if g["eligible"] >= 0.5 and g["fit"] >= 2 and i not in vs}
    try:
        live = [r for r in rows() if r["id"] in good]
    except Fail:
        return []
    live.sort(key=lambda r: -rank(gs[r["id"]]))
    return [(r, gs[r["id"]]) for r in live[:limit]]


def companies(args):
    m = need_data()
    rx = _rx(positional(args), "company")
    for co, b in m.get("boards", {}).items():
        if not rx or rx.search(co):
            print(f"{co}: {b['rows']:,} postings, {b['status']}" + (f", full refresh {b['full_refresh']}" if b.get("full_refresh") else ""))


def status(args):
    ws = workspace(args)
    m = meta()
    if m:
        age = (date.today() - date.fromisoformat(m["date"])).days
        print(f"Dataset {m['tag']}: {m['postings']:,} postings, {m['companies']:,} companies, {m.get('new_today', 0):,} new that day"
              + (f" ({age} days old; run update)" if age > 1 else ""))
        print("Levels: " + ", ".join(f"{k or 'unknown'} {v:,}" for k, v in m.get("levels", {}).items()))
        print("Families: " + ", ".join(f"{k} {v:,}" for k, v in m.get("families", {}).items()))
    else:
        print("No dataset yet; run update.")
    print(f"Cache: {CACHE}")
    local = Counter(r["company"] for r in local_rows())
    if local:
        print("Local scrapes: " + ", ".join(f"{c} {n}" for c, n in local.items()))
    gs, cfg = current_grades(ws), jev_config(ws)
    if cfg or jev.api_key():
        total = sum(x.get("usd") or 0 for x in jev.spend(ws))
        print(f"Jev: key {'set' if jev.api_key() else 'missing'}, {len(gs):,} current grades, ${total:.2f} spent in this workspace"
              + ("" if os.path.exists(os.path.join(ws, "rubric.md")) else ", no rubric.md yet"))
    vs, ss = verdicts(ws), statuses(ws)
    tiers = ", ".join(f"{n} {t}" for t, n in Counter(v["tier"] for v in vs.values()).items())
    print(f"Workspace: {ws}: {len(vs)} postings judged" + (f" ({tiers})" if tiers else "") + f", {len(ss)} tracked, "
          + ("profile.md present" if os.path.exists(os.path.join(ws, "profile.md")) else "no profile.md yet"))


# --- live scraping ---------------------------------------------------------------------------------------------------

def _boards_for(name):
    cfgs = _all_cfgs()
    exact = [c for c in cfgs if c["company"].lower() == name.lower()]
    if exact:
        return exact
    loose = sorted({c["company"] for c in cfgs if name.lower() in c["company"].lower()})
    if len(loose) == 1:
        return [c for c in cfgs if c["company"] == loose[0]]
    if loose:
        raise Fail(f"{name!r} matches several companies: {', '.join(loose[:12])}")
    raise Fail(f"{name!r} is not in the board list. Use find-board to locate its job board, then scrape --board '<json>'.")


def scrape(args):
    os.chdir(HERE)  # ats.py finds its adapters and companies.json relative to here
    import ats
    pos = positional(args)
    if opt(args, "--board"):
        try:
            cfgs = [json.loads(opt(args, "--board"))]
        except ValueError as e:
            raise Fail(f"--board takes a JSON object like {{\"company\": \"Acme\", \"ats\": \"greenhouse\", \"slug\": \"acme\"}} ({e})")
    elif pos:
        cfgs = _boards_for(pos[0])
    else:
        raise Fail("scrape COMPANY or scrape --board JSON")
    for c in cfgs:
        if c.get("ats") not in ats.FETCHERS:
            raise Fail(f"No scraper for ats {c.get('ats')!r}; known: {', '.join(sorted(ats.FETCHERS))}")
    got = []
    for c in cfgs:
        print(f"Fetching {c['company']} ({c['ats']}); big boards can take several minutes...", file=sys.stderr, flush=True)
        t = time.time()
        batch = ats.FETCHERS[c["ats"]](c, set())
        if c["ats"] not in ats.US_FILTERED and not flag(args, "--keep-non-us"):
            n = len(batch)
            batch = [r for r in batch if ats.is_us(r["location"])]
            if n - len(batch):
                print(f"  dropped {n - len(batch)} non-US postings (--keep-non-us keeps them)", file=sys.stderr)
        print(f"  {len(batch)} postings in {time.time() - t:.0f}s", file=sys.stderr)
        got += batch
    today = date.today().isoformat()
    published = {}
    try:
        published = {r["id"]: r.get("seen") for r in rows() if r["company"] in {c["company"] for c in cfgs}}
    except Fail:
        pass
    out = []
    for r in {r["id"]: r for r in got}.values():
        facts = signals.facts(r)
        out.append({k: r[k] for k in ("id", "company", "title", "location", "url", "posted", "ats", "category")}
                   | {"seen": published.get(r["id"]) or today} | {k: v for k, v in facts.items() if v not in (None, False, "", [])}
                   | {"excerpt": signals.excerpt(r)})
    os.makedirs(os.path.join(CACHE, "local"), exist_ok=True)
    name = re.sub(r"[^a-z0-9]+", "-", cfgs[0]["company"].lower()).strip("-") or "company"
    path = os.path.join(CACHE, "local", name + ".jsonl")
    with open(path, "w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    new = sum(1 for r in out if r["id"] not in published)
    print(f"Saved {len(out)} {cfgs[0]['company']} postings ({new} not in the published data) to {path}; searches include them now. "
          f"Delete the file to go back to the published rows.")


def find_board(args):
    os.chdir(HERE)
    import ats, probe
    pos = positional(args)
    if not pos:
        raise Fail("find-board COMPANY [--url CAREERS_PAGE] [--slug SLUG]")
    company = pos[0]
    base = re.sub(r"[^a-z0-9]", "", company.lower())
    guesses = [s for s in dict.fromkeys([opt(args, "--slug"), base, re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-"),
                                         base.removesuffix("inc").removesuffix("ai") or base, company.split()[0].lower()]) if s]
    found = []
    if opt(args, "--url"):
        import detect_ats
        try:
            page = ats.get_text(opt(args, "--url"), headers={"Accept": "text/html"})
        except Exception as e:
            print(f"Could not open {opt(args, '--url')}: {e}", file=sys.stderr)
            page = ""
        marks = sorted(set(m.group(0) for m in detect_ats.PAT.finditer(page)))
        if marks:
            print("Job-board links on that page: " + ", ".join(marks[:15]))
            for mk in marks:
                for rx, name in ((r"greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)", "greenhouse"), (r"lever\.co/(?:v0/postings/)?([a-z0-9_-]+)", "lever"),
                                 (r"ashbyhq\.com/(?:posting-api/job-board/)?([a-z0-9_.-]+)", "ashby"), (r"smartrecruiters\.com/([A-Za-z0-9_-]+)", "smartrecruiters"),
                                 (r"workable\.com/([a-z0-9-]+)", "workable"), (r"rippling\.com/([a-z0-9-]+)", "rippling")):
                    m = re.search(rx, mk, re.I)
                    if m and m.group(1).lower() not in ("jobs", "v1", "boards", "embed", "api"):
                        guesses.insert(0, m.group(1))
                m = re.search(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)", mk)
                if m:
                    r = probe.workday(m.group(1), m.group(3))
                    if r and "error" not in r:
                        found.append({"company": company, "ats": "workday", **{k: v for k, v in r.items() if k not in ("total", "us_total")}})
        else:
            print("No known job-board links on that page (it may load them with JavaScript, or embed an iframe).", file=sys.stderr)
    for name in ("greenhouse", "lever", "ashby", "smartrecruiters", "workable", "rippling"):
        for slug in dict.fromkeys(guesses):
            n = probe.count(name, slug)
            if n is not None:
                found.append({"company": company, "ats": name, "slug": slug, "_postings": n})
                break
    if any(c.get("_postings") for c in found):  # an empty board with the same slug is usually someone else's
        found = [c for c in found if c.get("_postings") is None or c["_postings"] > 0]
    if not found:
        print("Nothing found. Open the company's careers page, click a job, and look at the address: e.g. job-boards.greenhouse.io/<slug>, "
              "jobs.lever.co/<slug>, jobs.ashbyhq.com/<slug>, <tenant>.wd5.myworkdayjobs.com/<site>. Then rerun with --slug or --url.")
        return
    for c in found:
        n = c.pop("_postings", None)
        print(json.dumps(c) + (f"   ({n} postings worldwide)" if n is not None else ""))
    print("\nUse one with: python3 jobs.py scrape --board '<the JSON above>'", file=sys.stderr)


# --- Jev (TypeSafe System One) ------------------------------------------------------------------------------------

JEV_HELP = """Grade postings against the person's resume with Jev (TypeSafe's System One model), one request per posting.
  jev status [--check]       key set? (--check sends one tiny request, a fraction of a cent, to prove it works)
  jev key                    the PERSON runs this in their own terminal: a hidden prompt saves the key (never paste it in chat)
  jev rubric                 create the workspace's rubric.md from the template; then fill in its [brackets]
  jev estimate [filters | --all] [--resume PATH]          how many postings, tokens, dollars and minutes; spends nothing
  jev grade [filters | --all] --resume PATH (--max-cost USD | --max-total USD) [--workers N] [--model jev-latest] [--limit N]
                             grade every selected posting not graded yet under this resume + rubric. --max-cost caps this
                             run; --max-total caps the workspace's spend over all runs (use it for the person's budget).
                             Spend is recorded as it goes, so an interrupted run still counts. Rerunning continues where
                             it stopped. Later runs reuse the saved resume and selection: `jev grade --max-cost 2`
  jev spend                  what each run cost, and the total
Filters are the search filters (--title, --level, --state...). --all selects the whole dataset. Results: search
--sort rank, --min-fit 2, --min-eligible 0.5, --graded/--ungraded; show and board include Jev's grades.
Key, usage and rate limits: https://console.typesafe.ai  ·  prices: https://docs.typesafe.ai/models.md"""


def _jev_selection(args, ws, cfg):
    """(rows to grade, hash, resume, rules, levels, model, filter args) for estimate/grade."""
    resume_path = opt(args, "--resume") or cfg.get("resume")
    if not resume_path:
        raise Fail("Pass --resume PATH (the person's resume file; the script reads it, you don't need to).")
    resume_path = os.path.abspath(os.path.expanduser(resume_path))
    try:
        resume = jev.read_resume(resume_path)
        rules, levels = jev.load_rubric(ws)
    except jev.JevError as e:
        raise Fail(str(e))
    model = opt(args, "--model") or cfg.get("model") or jev.DEFAULT_MODEL
    sel = [a for a in args if a not in ("--yes", "--check")]
    for name in ("--resume", "--max-cost", "--max-total", "--workers", "--model", "--limit", "--price-per-mtok", "--workspace"):
        while name in sel:
            i = sel.index(name)
            del sel[i:i + 2]
    if not sel:
        sel = cfg.get("selection") or []
        if not sel:
            raise Fail("Say what to grade: search filters (e.g. --level intern --family software), or --all for every posting.")
    filters = [] if sel == ["--all"] else build_filters(sel, ws)
    h = jev.input_hash(resume, rules, levels, model)
    done = jev.grades(ws, h)
    todo = [r for r in rows(prefilter(args)) if r["id"] not in done and all(p(r) for _, p in filters)]
    todo.sort(key=lambda r: (r.get("seen") or "", r.get("posted") or ""), reverse=True)  # newest first, so a capped run covers them
    if opt(args, "--limit"):
        todo = todo[:int(opt(args, "--limit"))]
    return todo, len(done), h, resume, rules, levels, model, sel, resume_path


def _jev_estimate(todo, resume, rules, levels, price, workers):
    fixed = jev.tokens_of(resume) + jev.tokens_of(json.dumps(jev.questions(rules, levels))) + 60
    excerpt_tokens = sum(jev.tokens_of(r["title"] + r["company"] + (r.get("location") or "")) + (r.get("x") or [0, 1500 / 3])[1] * 3 / 3.6
                         for r in todo)
    tokens = len(todo) * fixed + excerpt_tokens
    return tokens, tokens * price / 1e6, len(todo) * 0.45 / max(1, workers) / 60


def _excerpt_source(todo):
    """excerpt_for(row) for a grading run: byte ranges for a few hundred postings, the whole excerpts file for more."""
    m = need_data()
    path = os.path.join(CACHE, f"excerpts-{m['tag']}.bin")
    if len(todo) <= 1500 and not os.path.exists(path):
        print(f"Fetching {len(todo):,} excerpts...", file=sys.stderr, flush=True)
        got = excerpts(todo, progress=lambda msg: print(msg, file=sys.stderr, flush=True))
        return lambda r: got.get(r["id"], "")
    if not os.path.exists(path):
        _download(f"https://github.com/{REPO}/releases/download/{m['tag']}/excerpts.bin", path, "excerpts.bin (once per dataset)")
    zdict = open(os.path.join(CACHE, "excerpts.dict"), "rb").read()
    import threading
    lock, fh = threading.Lock(), open(path, "rb")
    local = {r["id"]: r.get("excerpt", "") for r in todo if r.get("local")}

    def read(r):
        if r["id"] in local:
            return local[r["id"]]
        if not r.get("x"):
            return ""
        with lock:
            fh.seek(r["x"][0])
            blob = fh.read(r["x"][1])
        d = zlib.decompressobj(-15, zdict=zdict)
        return (d.decompress(blob) + d.flush()).decode("utf-8", "replace")
    return read


def jev_cmd(args):
    ws = workspace(args)
    sub = positional(args)[:1]
    if not sub or sub[0] not in ("status", "key", "rubric", "estimate", "grade", "spend") or flag(args, "--help") or "-h" in args:
        print(JEV_HELP)
        return
    sub, rest = sub[0], args[args.index(sub[0]) + 1:] + ([a for a in args[:args.index(sub[0])]])
    cfg = jev_config(ws)
    if sub == "key":
        try:
            jev.save_key()
        except jev.JevError as e:
            raise Fail(str(e))
    elif sub == "status":
        k = jev.api_key()
        src = "TYPESAFE_API_KEY" if os.environ.get("TYPESAFE_API_KEY") else jev.KEY_FILE
        print(f"Key: {'set, from ' + src if k else 'not set'}" + ("" if k else f" (get one at {jev.CONSOLE}/keys; the person runs `jobs.py jev key`)"))
        if k and flag(rest, "--check"):
            try:
                print(f"Key works (answered by {jev.check_key()}).")
            except jev.JevError as e:
                raise Fail(str(e))
        print(f"Rubric: {'present' if os.path.exists(os.path.join(ws, 'rubric.md')) else 'missing (jobs.py jev rubric)'}"
              f"; resume: {cfg.get('resume') or 'not chosen yet (--resume PATH)'}")
        if cfg.get("selection"):
            print("Saved selection: " + " ".join(cfg["selection"]))
        gs = current_grades(ws)
        print(f"Grades: {len(gs):,} current; spent ${jev.total_spent(ws):.3f} in this workspace. Usage and limits: {jev.CONSOLE}")
        runs = jev.spend(ws)
        if runs and not runs[-1].get("final", True):
            age = time.time() - time.mktime(time.strptime(runs[-1]["at"], "%Y-%m-%dT%H:%M:%S"))
            print(f"Last run: {'running' if age < 90 else 'stopped without finishing (rerun grade to continue)'}: "
                  f"{runs[-1]['graded']:,} of {runs[-1]['selected']:,} graded, last checkpoint {runs[-1]['at']}.")
    elif sub == "rubric":
        path = os.path.join(ws, "rubric.md")
        if os.path.exists(path):
            print(f"{path} already exists; edit it there.")
        else:
            with open(path, "w") as f:
                f.write(jev.RUBRIC_TEMPLATE)
            print(f"Wrote {path}. Fill in the [brackets] from what the person told you (not from the resume; Jev reads that itself).")
    elif sub == "spend":
        runs = jev.spend(ws)
        for x in runs:
            print(f"{x['at']}: {x['graded']:,} graded, {x['input_tokens']:,} tokens, ${x['usd']:.4f}" + (f", stopped: {x['stopped']}" if x.get("stopped") else "")
                  + ("" if x.get("final", True) else " (interrupted; spend up to its last checkpoint)"))
        print(f"Total: ${sum(x.get('usd') or 0 for x in runs):.4f} over {len(runs)} runs. TypeSafe's own record: {jev.CONSOLE}")
    else:
        todo, n_done, h, resume, rules, levels, model, sel, resume_path = _jev_selection(rest, ws, cfg)
        workers = int(opt(rest, "--workers", 4))
        try:
            price = jev.price_per_mtok(model, opt(rest, "--price-per-mtok"))
        except jev.JevError as e:
            raise Fail(str(e))
        tokens, usd, minutes = _jev_estimate(todo, resume, rules, levels, price, workers)
        print(f"{len(todo):,} postings to grade ({n_done:,} already graded under this resume and rubric). "
              + (f"About {tokens / 1e6:.1f}M input tokens" if tokens >= 1e6 else f"About {tokens / 1e3:.0f}k input tokens"))
        print(f"  = about ${usd:.2f}" if usd >= 0.1 else f"  = about ${usd:.4f}", f"at ${price}/M input tokens, about {max(1, round(minutes))} min with {workers} workers.")
        if sub == "estimate":
            return
        if not todo:
            print("Nothing to grade.")
            save_jev_config(ws, {**cfg, "resume": resume_path, "selection": sel, "model": model, "h": h})
            return
        if not opt(rest, "--max-cost") and not opt(rest, "--max-total"):
            raise Fail("Pass --max-cost USD (the most this run may spend) or --max-total USD (the most this workspace may have "
                       "spent in all, earlier runs included); the person decides it. Nothing was sent.")
        caps = []
        if opt(rest, "--max-cost"):
            caps.append(float(opt(rest, "--max-cost")))
        if opt(rest, "--max-total"):
            already = jev.total_spent(ws)
            caps.append(float(opt(rest, "--max-total")) - already)
            print(f"Spent so far in this workspace: ${already:.4f}; this run may spend up to ${max(0, caps[-1]):.4f}.")
        cap = min(caps)
        if cap <= 0:
            raise Fail("The --max-total budget is used up. Nothing was sent.")
        if not jev.api_key():
            raise Fail(f"No TypeSafe key. The person runs `python3 {os.path.abspath(__file__)} jev key` in their own terminal "
                       f"(or sets TYPESAFE_API_KEY). Keys: {jev.CONSOLE}/keys")
        save_jev_config(ws, {**cfg, "resume": resume_path, "selection": sel, "model": model, "h": h})
        excerpt_for = _excerpt_source(todo)
        try:
            out = jev.run(todo, excerpt_for, resume, rules, levels, model, ws, cap, price, workers,
                          progress=lambda m: print(m, flush=True))
        except jev.JevError as e:
            raise Fail(str(e))
        note = f"; stopped at the ${cap:.2f} cap, rerun to continue" if out["stopped"] == "cost cap" else ""
        print(f"Graded {out['graded']:,} of {out['selected']:,} in {out['minutes']} min for ${out['usd']:.4f}"
              + (f" ({out['failed']} failed; rerun retries them)" if out["failed"] else "") + note + ".")
        print("Next: python3 jobs.py search --graded --min-eligible 0.5 --min-fit 2 --sort rank")


COMMANDS = {"update": update, "status": status, "search": search, "show": show, "check": check, "verdict": verdict, "track": track, "board": board,
            "companies": companies, "scrape": scrape, "find-board": find_board, "jev": jev_cmd}


def main(argv):
    argv = list(argv)
    cmd = next((i for i, a in enumerate(argv) if a in COMMANDS and (i == 0 or argv[i - 1] != "--workspace")), None)
    if cmd is not None and argv[cmd] == "jev" and ("-h" in argv or "--help" in argv):
        print(JEV_HELP)
        return 0
    if cmd is None or "-h" in argv or "--help" in argv or "help" in argv[:1]:
        print(__doc__)
        return 0 if cmd is not None or any(a in ("-h", "--help", "help") for a in argv) else 2
    try:
        COMMANDS[argv[cmd]](argv[cmd + 1:] + argv[:cmd])  # options given before the command still count
    except Fail as e:
        print(e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
