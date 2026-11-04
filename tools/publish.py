"""Daily publisher: turn the scraper's store into the public dataset, job lists and a GitHub release.

Usage: python3 tools/publish.py <command> [options]
  export   --store DIR [--out DIR] [--workers N]   parse every posting into out/: jobs.jsonl.gz, excerpts.bin, excerpts.dict, meta.json
  lists    [--out DIR]                             write jobs/*.md and the README stats block from out/
  release  [--out DIR] [--keep N]                  upload out/ as release data-YYYY-MM-DD, mark it latest, delete all but N (default 7)
  daily    [--store DIR] [--src DIR] [--no-push]   all of it: wait for the scan, sync the scrapers, test, export, lists, push, release

The store is one JSON-lines file per company (job-fit-board's postings/ folder: rows from ats.py plus "seen", the date the
store first had the posting) and postings/_status.json. Parsed facts and excerpts are cached by posting id and a hash of its
text in ~/.local/state/daily-jobs/facts.sqlite3, so a day only parses what is new or changed.

excerpts.bin is one raw-deflate stream per posting, compressed against the shared dictionary excerpts.dict (zlib zdict);
each row of jobs.jsonl.gz has "x": [offset, length] into it, so a client fetches any one excerpt with an HTTP range request.
"""
import fcntl, gzip, hashlib, json, os, re, shutil, sqlite3, subprocess, sys, time, zlib
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "skills", "find-jobs", "scripts"))
import signals  # noqa: E402
import functools  # noqa: E402
import ats  # noqa: E402  (the synced scrapers: the same US rules the scrape applied)


@functools.lru_cache(maxsize=None)
def _us_place(location, filtered):
    """The scrapers' US rule, applied again at export so a rule fixed today also cleans rows stored before it: a board
    filtered to the US at the source loses only clearly foreign places; others must pass is_us."""
    return not ats.is_foreign(location) if filtered else ats.is_us(location)

STATE = os.environ.get("DAILY_JOBS_STATE") or os.path.expanduser("~/.local/state/daily-jobs")
DEFAULT_STORE = os.environ.get("JOBBOARD_STORE") or os.path.expanduser("~/projects/job-fit-board/postings")
DEFAULT_SRC = os.environ.get("JOBBOARD_SRC") or os.path.expanduser("~/projects/job-fit-board")
EXCLUDED_ATS = {"amazon", "neogov"}  # amazon.jobs terms forbid automated extraction; NEOGOV's robots.txt admits only search engines
SCHEMA = 1
FACTS_VERSION = "5"  # bump when signals.py changes in a way that should re-parse every posting


def arg(args, name, default):
    return type(default)(args[args.index(name) + 1]) if name in args else default


def log(*a):
    print(f"{datetime.now():%H:%M:%S}", *a, flush=True)


# --- export ----------------------------------------------------------------------------------------------------------

def text_hash(r):
    h = hashlib.sha1(FACTS_VERSION.encode())
    for k in ("title", "location", "category", "description", "basic", "preferred"):
        v = r.get(k)
        h.update(b"\0" + (v if isinstance(v, str) else json.dumps(v)).encode())
    return h.hexdigest()[:16]


def _parse(batch):
    """Worker: [(id, hash, row)] -> [(id, hash, facts json, excerpt)]."""
    out = []
    for jid, h, r in batch:
        try:
            f, ex = signals.facts(r), signals.excerpt(r)
        except Exception as e:  # one odd posting must not sink the export
            print(f"parse failed for {jid}: {e!r}", file=sys.stderr)
            f, ex = {}, ""
        out.append((jid, h, json.dumps(f), ex))
    return out


def _cache():
    os.makedirs(STATE, exist_ok=True)
    db = sqlite3.connect(os.path.join(STATE, "facts.sqlite3"))
    db.execute("CREATE TABLE IF NOT EXISTS facts (id TEXT PRIMARY KEY, hash TEXT, facts TEXT, excerpt TEXT)")
    return db


def _store_files(store):
    return sorted(os.path.join(store, n) for n in os.listdir(store) if n.endswith(".jsonl"))


def _rows(path):
    with open(path) as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("id") and r.get("title") and r.get("ats") not in EXCLUDED_ATS \
                    and _us_place(r.get("location") or "", r.get("ats") in ats.US_FILTERED):
                yield r


def _build_dict(db, ids, size=32768):
    """A zlib preset dictionary from the excerpt lines most postings share (headings, standard requirement phrases,
    company boilerplate the excerpt kept). Most frequent last, where deflate reaches it most cheaply."""
    lines = Counter()
    for i, (ex,) in enumerate(db.execute("SELECT excerpt FROM facts")):
        if i % 7 == 0:  # a sample is enough
            lines.update(l for l in (ex or "").split("\n") if 20 <= len(l) <= 300)
    out = b""
    for line, n in lines.most_common(4000):
        if n < 4:
            break
        b = (line + "\n").encode()
        if len(out) + len(b) > size:
            continue
        out = b + out
    return out


def _two_years_back(posted, seen, today):
    """True when posted is about two years before the day it was first seen or before today: the fake date some iCIMS
    portals give every posting (the day they are fetched, minus two years)."""
    try:
        p = date.fromisoformat(posted[:10])
    except ValueError:
        return False
    for ref in (seen, today):
        try:
            if 725 <= (date.fromisoformat((ref or "")[:10]) - p).days <= 737:
                return True
        except ValueError:
            pass
    return False


def export(store, out, workers=4):
    """Parse the store into out/. Returns the meta dict."""
    os.makedirs(out, exist_ok=True)
    db = _cache()
    known = dict(db.execute("SELECT id, hash FROM facts"))
    files = _store_files(store)
    # pass 1: parse what is new or changed, in parallel
    todo, pending, done, seen_ids = [], [], 0, set()
    started = time.time()
    with ProcessPoolExecutor(workers) as ex:
        def drain(block):
            nonlocal done
            while pending and (block or pending[0].done()):
                res = pending.pop(0).result()
                db.executemany("INSERT OR REPLACE INTO facts VALUES (?, ?, ?, ?)", res)
                done += len(res)
                if done % 20000 < len(res):
                    db.commit()
                    log(f"parsed {done} postings ({time.time() - started:.0f}s)")
        for path in files:
            for r in _rows(path):
                if r["id"] in seen_ids:
                    continue
                seen_ids.add(r["id"])
                h = text_hash(r)
                if known.get(r["id"]) == h:
                    continue
                slim = {k: r.get(k) for k in ("title", "location", "category", "description", "basic", "preferred")}
                todo.append((r["id"], h, slim))
                if len(todo) >= 400:
                    pending.append(ex.submit(_parse, todo))
                    todo = []
                    while len(pending) > workers * 3:
                        drain(True)
            drain(False)
        if todo:
            pending.append(ex.submit(_parse, todo))
        drain(True)
    db.commit()
    log(f"parsed {done} new or changed postings; {len(seen_ids)} in the store")
    gone = set(known) - seen_ids
    if gone:
        db.executemany("DELETE FROM facts WHERE id = ?", ((i,) for i in gone))
        db.commit()
    # pass 2: write the index and the excerpts
    zdict = _build_dict(db, seen_ids)
    with open(os.path.join(out, "excerpts.dict.tmp"), "wb") as f:
        f.write(zdict)
    status = {}
    try:
        status = json.load(open(os.path.join(store, "_status.json")))
    except (OSError, ValueError):
        pass
    today = date.today().isoformat()
    counts, families, levels, new_today, boards = Counter(), Counter(), Counter(), 0, {}
    offset, written = 0, set()
    with gzip.open(os.path.join(out, "jobs.jsonl.gz.tmp"), "wt", compresslevel=9) as idx, \
            open(os.path.join(out, "excerpts.bin.tmp"), "wb") as exf:
        for path in files:
            for r in _rows(path):
                if r["id"] in written:
                    continue
                written.add(r["id"])
                got = db.execute("SELECT facts, excerpt FROM facts WHERE id = ?", (r["id"],)).fetchone()
                facts, excerpt = (json.loads(got[0]), got[1]) if got else ({}, "")
                if facts:  # cheap title/place facts are recomputed every day, so rule changes need no full re-parse
                    facts.update(family=signals.family(r), states=signals.states(r.get("location")), level=signals.level(r, facts.get("years")))
                co = zlib.compressobj(9, zlib.DEFLATED, -15, 9, zlib.Z_DEFAULT_STRATEGY, zdict)
                blob = co.compress(excerpt.encode()) + co.flush()
                exf.write(blob)
                cat = r.get("category")
                posted = r.get("posted") or ""
                if posted and _two_years_back(posted, r.get("seen"), today):
                    posted = ""  # an iCIMS portal stamps "fetched minus two years"; the adapter drops it, older rows still carry it
                row = {"id": r["id"], "company": r["company"], "title": r["title"], "location": r.get("location") or "",
                       "url": r.get("url") or "", "posted": posted, "seen": r.get("seen") or "", "ats": r.get("ats") or "",
                       "category": cat if isinstance(cat, str) else ", ".join(map(str, cat or [])),
                       **{k: v for k, v in facts.items() if v not in (None, False, "", [])},
                       "x": [offset, len(blob)]}
                offset += len(blob)
                idx.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                counts[r["company"]] += 1
                families[facts.get("family") or "other"] += 1
                levels[facts.get("level") or ""] += 1
                new_today += row["seen"] == today
    for co, n in counts.items():
        st = status.get(co, {})
        boards[co] = {"rows": n, "status": st.get("status") or "ok", "full_refresh": (st.get("full") or "")[:10] or None,
                      "checked": (st.get("at") or "")[:10] or None, **({"found": True} if st.get("by") == "wide" else {})}
    for name in ("jobs.jsonl.gz", "excerpts.bin", "excerpts.dict"):
        os.replace(os.path.join(out, name + ".tmp"), os.path.join(out, name))
    meta = {"schema": SCHEMA, "tag": f"data-{today}", "date": today, "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
            "postings": len(written), "companies": len(counts), "new_today": new_today,
            "excerpts": {"file": "excerpts.bin", "dict": "excerpts.dict", "format": "raw deflate per posting, zlib preset dictionary"},
            "levels": dict(levels.most_common()), "families": dict(families.most_common()), "boards": dict(sorted(boards.items()))}
    with open(os.path.join(out, "meta.json"), "w") as f:
        json.dump(meta, f, separators=(",", ":"))  # one entry per company: tens of thousands since the discovered boards
    log(f"exported {len(written)} postings from {len(counts)} companies ({new_today} new today); excerpts {offset / 1e6:.0f} MB")
    return meta


# --- lists -----------------------------------------------------------------------------------------------------------

LISTS = [  # (file, title, blurb, predicate)
    ("internships", "Internships and co-ops", "Every open internship, co-op and apprenticeship in the data, newest first.",
     lambda r: r.get("level") == "intern"),
    ("new-grad", "New grad and entry level", "New grad programs, rotational programs and entry-level roles (titled junior, associate, "
     "level I, or asking for at most one year of experience), newest first.",
     lambda r: r.get("level") == "new-grad" or (r.get("level") == "entry" and (r.get("years") or 0) <= 1)),
]
FAMILY_ORDER = list(dict.fromkeys([k for k, _, _ in signals.FAMILIES] + ["engineering", "other"]))
PER_FILE = 750  # rows per family page; GitHub stops rendering very long Markdown files
NEW_DAYS = 7


def _cell(s):
    return re.sub(r"\s+", " ", str(s or "")).replace("|", "/").strip()


def _md_row(r):
    flags = []
    if r.get("no_sponsor"):
        flags.append("no visa sponsorship")
    if r.get("citizen"):
        flags.append("US citizens/persons only")
    if r.get("clearance"):
        flags.append("clearance")
    title = _cell(r["title"])[:110]
    link = f"[{title}]({r['url']})" if r.get("url") else title
    if r.get("term"):
        link += f" · {r['term']}"
    loc = _cell(r.get("location"))[:70] + (f" ({r['remote']})" if r.get("remote") in ("remote", "hybrid") and r["remote"] not in (r.get("location") or "").lower() else "")
    return f"| {_cell(r['company'])} | {link} | {loc} | {signals.pay_text(r.get('pay'))} | {r.get('seen') or ''} | {', '.join(flags)} |"


def read_index(out):
    with gzip.open(os.path.join(out, "jobs.jsonl.gz"), "rt") as f:
        for line in f:
            yield json.loads(line)


def lists(out, repo=REPO):
    meta = json.load(open(os.path.join(out, "meta.json")))
    since = (date.fromisoformat(meta["date"]) - timedelta(days=NEW_DAYS - 1)).isoformat()
    groups = {name: {} for name, *_ in LISTS}
    for r in read_index(out):
        for name, _, _, pred in LISTS:
            if pred(r):
                groups[name].setdefault(r.get("family") or "other", []).append(r)
    jobs_dir = os.path.join(repo, "jobs")
    os.makedirs(jobs_dir, exist_ok=True)
    keep = {"README.md"}
    summary = []
    for name, title, blurb, _ in LISTS:
        fams = groups[name]
        total = sum(map(len, fams.values()))
        fresh = sum(1 for rs in fams.values() for r in rs if (r.get("seen") or "") >= since)
        lines = [f"# {title}", "", f"{blurb} Updated {meta['date']}: **{total:,}** open, **{fresh:,}** first seen in the last {NEW_DAYS} days.",
                 "", "| Field | Open | New this week |", "|---|---:|---:|"]
        for fam in FAMILY_ORDER:
            rs = fams.get(fam)
            if not rs:
                continue
            rs.sort(key=lambda r: (r.get("seen") or "", r.get("posted") or ""), reverse=True)
            page = f"{name}-{fam}.md"
            keep.add(page)
            n_new = sum(1 for r in rs if (r.get("seen") or "") >= since)
            lines.append(f"| [{signals.FAMILY_LABELS[fam]}]({page}) | {len(rs):,} | {n_new:,} |")
            body = [f"# {title}: {signals.FAMILY_LABELS[fam]}", "",
                    f"{len(rs):,} open, newest first (by the date the scraper first saw them), updated {meta['date']}."
                    + (f" Showing the newest {PER_FILE}; the rest are in the dataset (see the [README](../README.md))." if len(rs) > PER_FILE else ""),
                    "", "Flags come from the posting text and can be wrong. Check the posting before you apply.", "",
                    "| Company | Role | Location | Pay | First seen | Flags |", "|---|---|---|---|---|---|"]
            body += [_md_row(r) for r in rs[:PER_FILE]]
            with open(os.path.join(jobs_dir, page), "w") as f:
                f.write("\n".join(body) + "\n")
        lines += ["", "Back to the [README](../README.md)."]
        with open(os.path.join(jobs_dir, f"{name}.md"), "w") as f:
            f.write("\n".join(lines) + "\n")
        keep.add(f"{name}.md")
        summary.append((name, title, total, fresh))
    for n in os.listdir(jobs_dir):
        if n.endswith(".md") and n not in keep:
            os.remove(os.path.join(jobs_dir, n))
    # README stats block
    fam_rows = "\n".join(f"| {signals.FAMILY_LABELS.get(k, k)} | {v:,} |" for k, v in meta["families"].items())
    lists_md = "\n".join(f"- [{t}](jobs/{n}.md): {total:,} open, {fresh:,} new this week" for n, t, total, fresh in summary)
    failed = sorted(co for co, b in meta["boards"].items() if b["status"] != "ok" and not b.get("found"))
    found = [b for b in meta["boards"].values() if b.get("found")]
    found_failed = sum(b["status"] != "ok" for b in found)
    block = (f"**{meta['postings']:,} US job postings from {meta['companies']:,} companies**, updated {meta['date']} "
             f"({meta['new_today']:,} first seen that day).\n\n{lists_md}\n\n<details><summary>Postings by field</summary>\n\n"
             f"| Field | Postings |\n|---|---:|\n{fam_rows}\n\n</details>"
             + (f"\n\n{len(meta['boards']) - len(found):,} companies are a curated list; {len(found):,} more were found on the job-board systems "
                f"with open APIs (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, BambooHR and others) and are checked daily"
                + (f" ({found_failed:,} failed on their last check)" if found_failed else "") + "." if found else "")
             + (f"\n\nCurated boards that failed or looked wrong on their last check (their older postings are kept): {', '.join(failed)}." if failed else ""))
    readme = os.path.join(repo, "README.md")
    text = open(readme).read()
    new = re.sub(r"(<!-- stats -->).*?(<!-- /stats -->)", lambda m: m.group(1) + "\n" + block + "\n" + m.group(2), text, flags=re.S)
    if new == text and "<!-- stats -->" not in text:
        log("README has no <!-- stats --> block; stats not written")
    with open(readme, "w") as f:
        f.write(new)
    log(f"lists: " + ", ".join(f"{n} {total}" for n, _, total, _ in summary))


# --- release ---------------------------------------------------------------------------------------------------------

def gh(*args, check=True):
    return subprocess.run(["gh", *args], cwd=REPO, check=check, capture_output=True, text=True)


def release(out, keep=7):
    meta = json.load(open(os.path.join(out, "meta.json")))
    tag = meta["tag"]
    assets = [os.path.join(out, n) for n in ("meta.json", "jobs.jsonl.gz", "excerpts.dict", "excerpts.bin")]
    notes = (f"{meta['postings']:,} US postings from {meta['companies']:,} companies, {meta['new_today']:,} first seen on {meta['date']}.\n\n"
             "Assets: `jobs.jsonl.gz` (one posting per line with parsed facts), `excerpts.bin` + `excerpts.dict` (eligibility excerpts, "
             "fetched per posting by byte range), `meta.json` (counts and board status). Field list: skills/find-jobs/references/data.md.")
    existing = gh("release", "view", tag, "--json", "isDraft", check=False)
    if existing.returncode == 0:
        if json.loads(existing.stdout or "{}").get("isDraft"):  # a failed earlier run's draft: nobody could use it
            gh("release", "delete", tag, "--yes", "--cleanup-tag")
            time.sleep(3)
        else:
            # A rerun on the same day gets a tag of its own: whoever updated from the earlier release keeps an index whose
            # excerpt offsets still match that release's excerpts.bin.
            n = 2
            while gh("release", "view", f"{tag}-{n}", check=False).returncode == 0:
                n += 1
            tag = f"{tag}-{n}"
            meta["tag"] = tag
            with open(os.path.join(out, "meta.json"), "w") as f:
                json.dump(meta, f, separators=(",", ":"))
    gh("release", "create", tag, "--title", f"Jobs {meta['date']}", "--notes", notes, "--draft", "--target", "main")
    for a in assets:
        for attempt in range(6):
            r = gh("release", "upload", tag, a, "--clobber", check=False)
            if r.returncode == 0:
                break
            log(f"upload of {os.path.basename(a)} failed ({r.stderr.strip()[:200]}); retrying")
            time.sleep(30 * (attempt + 1))
        else:
            raise RuntimeError(f"could not upload {a}")
    gh("release", "edit", tag, "--draft=false", "--latest")
    log(f"released {tag}")
    tags = json.loads(gh("release", "list", "--limit", "100", "--json", "tagName,createdAt,isDraft").stdout)
    data = sorted((t for t in tags if t["tagName"].startswith("data-")), key=lambda t: t["tagName"], reverse=True)
    for t in data[keep:]:
        gh("release", "delete", t["tagName"], "--yes", "--cleanup-tag", check=False)
        log(f"deleted old release {t['tagName']}")


# --- daily -----------------------------------------------------------------------------------------------------------

def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=REPO, check=check, capture_output=True, text=True)


def wait_for_scan(src, hours=5, lock=".lock", what="the daily scan"):
    """Block while job-fit-board's daily run holds its pipeline lock (or wide.py its own), so the export never reads a
    half-updated day."""
    path = os.path.join(src, lock)
    if not os.path.exists(path):
        return
    with open(path) as f:
        deadline = time.time() + hours * 3600
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
                return
            except BlockingIOError:
                if time.time() > deadline:
                    log(f"{what} is still running; publishing what the store has")
                    return
                time.sleep(60)


def sync_and_test(src):
    """Copy the latest scrapers in; keep them only if the tests pass. Returns a short status line."""
    r = subprocess.run([sys.executable, os.path.join(HERE, "sync_code.py"), "--from", src], cwd=REPO, capture_output=True, text=True)
    if r.returncode:
        git("checkout", "--", "skills/find-jobs/scripts")
        return f"scraper sync skipped: {(r.stderr or r.stdout).strip()[:300]}"
    if "already up to date" in r.stdout:
        return "scrapers unchanged"
    t = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=REPO, capture_output=True, text=True)
    if t.returncode:
        git("checkout", "--", "skills/find-jobs/scripts")
        subprocess.run(["git", "clean", "-fdq", "skills/find-jobs/scripts"], cwd=REPO)
        return f"scraper sync reverted, tests failed: {t.stderr.strip()[-300:]}"
    return "scrapers synced: " + ", ".join(l.split(" ", 1)[1] for l in r.stdout.splitlines() if l.startswith(("updated", "removed")))


def daily(args):
    store, src = arg(args, "--store", DEFAULT_STORE), arg(args, "--src", DEFAULT_SRC)
    out = os.path.join(STATE, "build")
    lock = open(os.path.join(STATE, ".publish.lock"), "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    wait_for_scan(src)
    wait_for_scan(src, hours=3, lock=os.path.join("wide", ".lock"), what="the scrape of discovered boards (wide.py)")
    if "--no-push" not in args and git("pull", "--ff-only", "--quiet", check=False).returncode:
        log("git pull failed; continuing with the local main")
    sync_note = sync_and_test(src)
    log(sync_note)
    if sync_note.startswith("scrapers synced"):
        bump_version()
    meta = export(store, out, workers=arg(args, "--workers", 3))
    lists(out)
    git("add", "-A", "jobs", "README.md", "skills", ".claude-plugin")
    if git("diff", "--cached", "--quiet", check=False).returncode:
        msg = f"Jobs for {meta['date']}: {meta['postings']:,} postings, {meta['new_today']:,} new"
        if sync_note.startswith("scrapers synced"):
            msg += "\n\n" + sync_note
        git("commit", "-q", "-m", msg)
    if "--no-push" in args:
        log("--no-push: not pushing or releasing")
        return
    push()
    release(out, keep=arg(args, "--keep", 7))
    if not sync_note.startswith(("scrapers synced", "scrapers unchanged")):
        leave_note("daily-jobs: scraper sync held back", sync_note, "info")


def bump_version():
    """Raise the plugin's patch version, so Claude Code installs pick up changed scrapers."""
    path = os.path.join(REPO, ".claude-plugin", "plugin.json")
    with open(path) as f:
        p = json.load(f)
    major, minor, patch = (p.get("version") or "1.0.0").split(".")
    p["version"] = f"{major}.{minor}.{int(patch) + 1}"
    with open(path, "w") as f:
        f.write(json.dumps(p, indent=2) + "\n")


def push():
    """Push main over HTTPS (gh's credential helper), else over SSH."""
    for attempt in range(3):
        if git("push", "-q", "origin", "main", check=False).returncode == 0:
            return
        if git("push", "-q", "git@github.com:Code-Tomato/daily-jobs.git", "main", check=False).returncode == 0:
            git("fetch", "-q", "origin", check=False)
            return
        time.sleep(60)
    raise RuntimeError("git push failed over HTTPS and SSH")


def leave_note(title, text, kind="info"):
    """Tell the maintainer, through the `note` command when the machine has one."""
    if shutil.which("note"):
        subprocess.run(["note", title, "-m", text[-1500:], "--kind", kind, "--from", "daily-jobs"], capture_output=True, timeout=60)


def main():
    args = sys.argv[1:]
    if not args or args[0] not in ("export", "lists", "release", "daily"):
        sys.exit(__doc__)
    cmd, out = args[0], arg(args, "--out", os.path.join(STATE, "build"))
    os.makedirs(STATE, exist_ok=True)
    if cmd == "export":
        export(arg(args, "--store", DEFAULT_STORE), out, workers=arg(args, "--workers", 3))
    elif cmd == "lists":
        lists(out)
    elif cmd == "release":
        release(out, keep=arg(args, "--keep", 7))
    else:
        try:
            daily(args)
        except Exception:
            import traceback
            leave_note("daily-jobs publish failed", traceback.format_exc() + "\nLogs: journalctl --user -u daily-jobs-publish", "todo")
            raise


if __name__ == "__main__":
    main()
