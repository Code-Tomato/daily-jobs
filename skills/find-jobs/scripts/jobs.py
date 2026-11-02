#!/usr/bin/env python3
"""Search the daily-jobs dataset: every US posting from ~1,000 company career sites, refreshed daily.

Usage: python3 jobs.py <command> [options]          (Python 3.9+, standard library only)

  update [--force]          download the newest dataset (~12 MB) when there is one
  status                    dataset date and counts, cache folder, workspace files
  search [filters]          postings that pass every filter, newest first (filters below; --count for the funnel)
  show ID [ID ...]          each posting's facts and its eligibility excerpt (~1,800 chars; fetched once over the network, then cached)
  verdict ID --tier T --why TEXT [--gaps TEXT] [--score 0-100]   record your judgment (tier: strong, good, stretch, no)
  verdict --file FILE       record many: one JSON object per line {"id", "tier", "why", "gaps", "score"}
  track ID STATUS [--note TEXT]   saved, applied, interviewing, offer, rejected, not-interested (or "clear")
  board [--open]            write the workspace's board.html and matches.md from the verdicts
  companies [REGEX]         companies in the data with posting counts and board status
  scrape COMPANY | --board JSON   fetch one company's board live with the bundled scrapers; its rows join your searches
  find-board COMPANY [--url CAREERS_URL] [--slug SLUG]   work out which job board a company uses (for scrape --board)

Search filters (all optional, combined with AND; REGEX is case-insensitive; repeat a flag to OR its values):
  --title REGEX  --not-title REGEX  --company REGEX  --not-company REGEX  --category REGEX
  --location REGEX  --state TX,CA  --remote  --or-remote (a remote posting passes the location filters)
  --level intern,new-grad,entry,mid,senior,manager,unknown     --family software,data,hardware,... (see `status`)
  --company/--title etc. take Python regexes; use \\b for word edges (--not-title "\\bsr\\b|\\blead\\b")
  --max-years N (stated minimum experience; postings that state none pass)   --degree hs|associate|bs|ms|phd (the person's
  highest; postings that require more are dropped)   --term "summer 2027" (season and/or year; postings that state
  no term pass unless --strict-term)
  --needs-sponsorship (drop no-sponsorship and citizens-only postings)   --no-citizen-only   --no-clearance
  --min-pay N (yearly; hourly x 2,080; --has-pay drops postings without pay)   --since DATE|Nd (first seen)   --posted-since DATE|Nd
  --unjudged (not in your verdicts)   --ids FILE (one id per line)
Output: --limit N (default 60) | --all, --sort seen|posted|company|pay, --json (full rows), --ids-only, --count (funnel and breakdowns)

Files: the dataset is cached in ~/.cache/daily-jobs ($DAILY_JOBS_CACHE). Your verdicts, statuses and board live in the
workspace, ~/job-search ($JOBS_WORKSPACE, or --workspace DIR before or after the command). Data: https://github.com/Code-Tomato/daily-jobs ($DAILY_JOBS_REPO).
"""
import gzip, html, json, os, re, shutil, sys, tempfile, time, urllib.error, urllib.request, webbrowser, zlib
from collections import Counter
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import signals  # noqa: E402

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


BOOL_FLAGS = {"--force", "--count", "--json", "--ids-only", "--all", "--remote", "--or-remote", "--strict-term", "--needs-sponsorship",
              "--no-citizen-only", "--no-clearance", "--has-pay", "--unjudged", "--open", "--keep-non-us"}


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
            if total and sys.stderr.isatty() and time.time() - last > 0.5:
                print(f"\r{label}: {got / 1e6:.0f} of {total / 1e6:.0f} MB", end="", file=sys.stderr, flush=True)
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
        if n.startswith("excerpts-") and n != f"excerpts-{latest['tag']}.jsonl":
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


def rows():
    need_data()
    local = {r["id"]: r for r in local_rows()}
    local_cos = {r["company"] for r in local.values()}
    with gzip.open(os.path.join(CACHE, "jobs.jsonl.gz"), "rt", encoding="utf-8") as f:
        for line in f:
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


def excerpts(rs):
    """{id: excerpt} for rows, from the local cache, local scrapes, or byte ranges of the release's excerpts.bin."""
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
    if todo:
        zdict = open(os.path.join(CACHE, "excerpts.dict"), "rb").read()
        url = f"https://github.com/{REPO}/releases/download/{m['tag']}/excerpts.bin"
        todo.sort(key=lambda r: r["x"][0])
        groups, cur = [], []
        for r in todo:  # neighbors share one request when the gap between them is small
            if cur and (r["x"][0] - (cur[-1]["x"][0] + cur[-1]["x"][1]) > 65536 or r["x"][0] + r["x"][1] - cur[0]["x"][0] > 4 << 20):
                groups.append(cur)
                cur = []
            cur.append(r)
        groups.append(cur)
        new = {}
        for g in groups:
            start, end = g[0]["x"][0], g[-1]["x"][0] + g[-1]["x"][1] - 1
            try:
                with _get(url, {"Range": f"bytes={start}-{end}"}) as resp:
                    blob = resp.read()
                    if resp.status != 206:  # a server that ignores Range sends the whole file
                        blob = blob[start:end + 1]
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raise Fail("Your copy of the dataset is older than the oldest release kept online. Run: python3 jobs.py update")
                raise
            for r in g:
                a = r["x"][0] - start
                d = zlib.decompressobj(-15, zdict=zdict)
                new[r["id"]] = (d.decompress(blob[a:a + r["x"][1]]) + d.flush()).decode("utf-8", "replace")
        with open(cache_path, "a") as f:
            for i, t in new.items():
                f.write(json.dumps({"id": i, "text": t}) + "\n")
        out.update(new)
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
    """[(name, predicate)] in funnel order."""
    f = []
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
        f.append(("family", lambda r: (r.get("family") or "other") in fams))
    if opt(args, "--max-years") is not None:
        n = float(opt(args, "--max-years"))
        f.append(("max-years", lambda r: r.get("years") is None or r["years"] <= n))
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
            n = float(raw[:-1]) * 1000 if raw.endswith("k") else float(raw)
        except ValueError:
            raise Fail("--min-pay takes a yearly amount like 80000 or 80k")
        f.append(("min-pay", lambda r: (signals.yearly(r.get("pay")) or 0) >= n if r.get("pay") else not has))
    elif flag(args, "--has-pay"):
        f.append(("has-pay", lambda r: bool(r.get("pay"))))
    if opt(args, "--since"):
        s = _days(opt(args, "--since"))
        f.append(("since", lambda r: (r.get("seen") or "") >= s))
    if opt(args, "--posted-since"):
        s = _days(opt(args, "--posted-since"))
        f.append(("posted-since", lambda r: (r.get("posted") or r.get("seen") or "") >= s))
    if flag(args, "--unjudged"):
        judged = set(verdicts(ws))
        f.append(("unjudged", lambda r: r["id"] not in judged))
    if opt(args, "--ids"):
        want = {l.strip() for l in open(opt(args, "--ids")) if l.strip()}
        f.append(("ids", lambda r: r["id"] in want))
    return f


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
        out.append(f"deadline {r['deadline']}")
    return out


def line(r, v=None, s=None):
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
    tail = f" | seen {r.get('seen') or '?'}" + (f" | YOU: {v['tier']}" if v else "") + (f" [{s['status']}]" if s else "") + (" | local" if r.get("local") else "")
    cut = lambda t, n: t if len(t) <= n else t[:n - 1] + "…"
    return f"{r['id']}  {r['company']} | {cut(r['title'], 90)} | {cut(r.get('location') or '?', 45)} | {', '.join(bits)}{tail}"


def search(args):
    ws = workspace(args)
    filters = build_filters(args, ws)
    funnel, out = Counter(), []
    total = 0
    for r in rows():
        total += 1
        ok = True
        for name, pred in filters:
            if not pred(r):
                ok = False
                break
            funnel[name] += 1
        if ok:
            out.append(r)
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
            "company": lambda r: (r["company"].lower(), r["title"].lower()), "pay": lambda r: signals.yearly(r.get("pay")) or 0}
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
            print(line(r, vs.get(r["id"]), ss.get(r["id"])))
        more = f" (showing {len(shown)}; --limit N or --all for more)" if len(out) > len(shown) else ""
        print(f"\n{len(out):,} match{'' if len(out) == 1 else 'es'}{more}", file=sys.stderr)


def show(args):
    ids = positional(args)
    if not ids:
        raise Fail("show takes posting ids (from search)")
    rs = get_rows(ids)
    ex = excerpts(rs)
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
        print(f"=== {r['id']}\n{r['company']}: {r['title']}\n{r.get('location') or '?'} | posted {r.get('posted') or '?'} | first seen {r.get('seen') or '?'}\n"
              f"{r.get('url')}\nParsed: {'; '.join(facts)}\n--- excerpt\n{ex.get(r['id'], '(no text)')}\n")


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
    with open(os.path.join(ws, "matches.md"), "w") as f:
        f.write("\n".join(md))
    print(f"Wrote {path} and matches.md ({len(jobs)} matches)")
    if flag(args, "--open"):
        webbrowser.open("file://" + path)


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
    vs, ss = verdicts(ws), statuses(ws)
    tiers = ", ".join(f"{n} {t}" for t, n in Counter(v["tier"] for v in vs.values()).items())
    print(f"Workspace: {ws}: {len(vs)} postings judged" + (f" ({tiers})" if tiers else "") + f", {len(ss)} tracked, "
          + ("profile.md present" if os.path.exists(os.path.join(ws, "profile.md")) else "no profile.md yet"))


# --- live scraping ---------------------------------------------------------------------------------------------------

def _boards_for(name):
    cfgs = json.load(open(os.path.join(HERE, "companies.json")))
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


COMMANDS = {"update": update, "status": status, "search": search, "show": show, "verdict": verdict, "track": track, "board": board,
            "companies": companies, "scrape": scrape, "find-board": find_board}


def main(argv):
    argv = list(argv)
    cmd = next((i for i, a in enumerate(argv) if a in COMMANDS and (i == 0 or argv[i - 1] != "--workspace")), None)
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
