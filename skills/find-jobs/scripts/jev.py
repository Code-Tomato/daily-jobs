"""Grade postings against a resume with Jev, TypeSafe's System One model (a fast decision model, not a chat LLM).

Called through jobs.py:  python3 jobs.py jev <status|key|rubric|estimate|grade|spend> ...

One request per posting: the state is {today, resume, job}, where resume is the person's resume file sent verbatim (the
agent never reads or rewrites it) and job is the posting's company, title, place and eligibility excerpt. Two questions:
`eligible` (a Noul: probability the person meets every hard requirement when the role starts) and `fit` (a Score on four
levels). Their rules and levels come from the workspace's rubric.md. Grades go to the workspace's grades.jsonl, keyed by
posting id and a hash of resume + rubric + model, so a run can stop and resume, and changing the resume or rubric marks
old grades stale.

Money: Jev bills input tokens only. `estimate` and `grade` read the current price from docs.typesafe.ai/models.md (or
--price-per-mtok), `grade` refuses to start without --max-cost and stops before a request could cross it, and every
run's spend (from the API's own usage counts) is appended to jev-spend.jsonl in the workspace.

The key: $TYPESAFE_API_KEY, else ~/.config/daily-jobs/typesafe_key (mode 600, written by `jev key`). Nothing here
prints it. Keys, usage and rate limits: https://console.typesafe.ai
"""
import getpass, hashlib, json, math, os, re, shutil, subprocess, sys, threading, time, urllib.error, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime

API = "https://api.typesafe.ai/v1/systemone"
PRICING_URL = "https://docs.typesafe.ai/models.md"
CONSOLE = "https://console.typesafe.ai"
KEY_FILE = os.path.join(os.path.expanduser("~"), ".config", "daily-jobs", "typesafe_key")
DEFAULT_MODEL = "jev-latest"
MAX_RESUME_CHARS = 40000
QUESTION_TOKENS = 450  # the two questions with a typical rubric, measured roughly; only used for estimates


class JevError(Exception):
    pass


# --- key -------------------------------------------------------------------------------------------------------------

def api_key():
    k = (os.environ.get("TYPESAFE_API_KEY") or "").strip()
    if k:
        return k
    try:
        with open(KEY_FILE) as f:
            return f.read().strip() or None
    except OSError:
        return None


def save_key():
    """Hidden prompt in the person's own terminal; stdin works too (`pbpaste | jobs.py jev key`). Never echoed."""
    if sys.stdin.isatty():
        k = getpass.getpass("Paste your TypeSafe API key (it won't show): ").strip()
    else:
        k = sys.stdin.readline().strip()
    if not k or len(k) < 16 or any(c.isspace() for c in k):
        raise JevError("That doesn't look like an API key; nothing was saved.")
    os.makedirs(os.path.dirname(KEY_FILE), mode=0o700, exist_ok=True)
    fd = os.open(KEY_FILE + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(k + "\n")
    os.replace(KEY_FILE + ".tmp", KEY_FILE)
    print(f"Saved to {KEY_FILE} (only you can read it). Check it with: python3 jobs.py jev status")


# --- resume and rubric ---------------------------------------------------------------------------------------------

def read_resume(path):
    """The resume's text, as the file has it. .md/.txt as is; .pdf through pdftotext when installed; .docx from its XML."""
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        raise JevError(f"No resume file at {path}")
    low = path.lower()
    if low.endswith(".pdf"):
        if not shutil.which("pdftotext"):
            raise JevError("This is a PDF and pdftotext isn't installed (poppler). Install it (macOS: brew install poppler; "
                           "Debian/Ubuntu: apt install poppler-utils), or save the resume as .txt / .md and pass that.")
        text = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, check=True).stdout
    elif low.endswith(".docx"):
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        xml = re.sub(r"</w:p>", "\n", xml)
        text = re.sub(r"<[^>]+>", "", xml)
        text = re.sub(r"&amp;", "&", re.sub(r"&lt;", "<", re.sub(r"&gt;", ">", text)))
    else:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    text = re.sub(r"[ \t]+\n", "\n", text).strip()
    if len(text) < 200:
        raise JevError(f"Only {len(text)} characters of text came out of {path}; is it a scanned image? Save it as text and retry.")
    return text[:MAX_RESUME_CHARS]


RUBRIC_TEMPLATE = """# Jev rubric

<!-- Jev reads this with the resume for every posting. Keep the two headings; the Fit section needs exactly four
bullets (levels 0 to 3). Fill in the [brackets] from what the person told you; don't copy facts out of the resume,
Jev reads the resume itself. Editing this file makes existing grades stale. -->

## Eligibility rules

- Use the graduation date and degree shown in the resume. A required degree counts as met only if the role starts after that date or the posting allows finishing it by then. Do not assume an unstated start date.
- For internships and co-ops, check class-year, graduation-window and enrollment requirements against the resume. "Currently pursuing a degree" means enrolled during the internship. Do not assume graduate school unless the resume shows admission.
- Count internships and research as experience: they satisfy "1+ years of experience" or "internship experience", not "N+ years of full-time / professional experience" for N >= 2.
- A Master's or PhD requirement is met only if the resume shows that degree, completed or expected before the start date.
- [Work authorization, from the person: e.g. "The candidate is a US citizen; citizenship, US-person and clearance-eligibility requirements are met." or "The candidate will need visa sponsorship (F-1 OPT now, H-1B later). A posting that will not sponsor, or requires US citizenship, permanent residency or US-person status, is not met."]
- [Clearance: e.g. "The candidate has no clearance; an active clearance requirement is not met." Delete if not relevant.]
- [Anything else they told you that decides eligibility, e.g. "The candidate cannot relocate outside Texas; an onsite role elsewhere is not met." Delete if none.]

## Fit levels

- 0: Unrelated: [kinds of work they don't want, e.g. "sales, customer support, retail, or any non-engineering role"].
- 1: Adjacent: work they could do, but that uses little of their background or interests, e.g. [generic example].
- 2: Some direct overlap: the role touches at least one of their core areas: [their 3 to 6 core areas, in their words].
- 3: Strong match: the role is centered on [their core areas], the kind of work they want next.
"""


def load_rubric(ws):
    path = os.path.join(ws, "rubric.md")
    if not os.path.exists(path):
        raise JevError(f"No rubric yet. Run: python3 jobs.py jev rubric   (then fill in its [brackets] in {path})")
    text = re.sub(r"<!--.*?-->", "", open(path, encoding="utf-8").read(), flags=re.S)
    if re.search(r"\[[^\]]{3,}\]", text):
        raise JevError(f"{path} still has [bracketed] placeholders; fill them in or delete those lines.")
    sections, cur = {}, None
    for line in text.splitlines():
        if line.startswith("#"):
            low = line.lower()
            cur = "elig" if "eligib" in low else "fit" if "fit" in low else None
            continue
        m = re.match(r"\s*[-*]\s+(.*)", line)
        if m and cur:
            sections.setdefault(cur, []).append(re.sub(r"^[0-3]\s*:\s*", "", m.group(1)).strip())
    rules, levels = sections.get("elig") or [], sections.get("fit") or []
    if not rules:
        raise JevError(f"{path}: no bullets under an 'Eligibility' heading")
    if len(levels) != 4:
        raise JevError(f"{path}: the 'Fit' heading needs exactly four bullets (levels 0 to 3); it has {len(levels)}")
    return rules, levels


def questions(rules, levels):
    return {
        "eligible": {"type": "noul", "instructions": {
            "question": "Would the candidate in `resume` satisfy every hard requirement of `job` at the time this role would start? "
                        "The requirements are in `job.excerpt` (qualifications, degree, years, class standing, graduation window, "
                        "work authorization, location).",
            "rules": rules},
            "criteria": {"true": "Every hard requirement is met under `rules`, or the only unmet one is a soft 'or equivalent' clause.",
                         "false": "At least one hard requirement fails under `rules`: years of experience, degree, graduation window or "
                                  "enrollment, work authorization, clearance, location, or a required license or skill the resume lacks."}},
        "fit": {"type": "score",
                "instructions": "How closely does the day-to-day work in `job` match the candidate's demonstrated experience and stated "
                                "interests in `resume`, judged on the levels below?",
                "criteria": levels},
    }


def input_hash(resume, rules, levels, model):
    return hashlib.sha256(json.dumps([resume, rules, levels, model], ensure_ascii=False).encode()).hexdigest()[:16]


# --- price -----------------------------------------------------------------------------------------------------------

def price_per_mtok(model, override=None):
    """USD per million input tokens for `model`, read from TypeSafe's public models page (the highest per-Mtok price on
    the page when the column can't be pinned down, so estimates err high)."""
    if override is not None:
        return float(override)
    try:
        with urllib.request.urlopen(urllib.request.Request(PRICING_URL, headers={"User-Agent": "daily-jobs-skill"}), timeout=30) as r:
            text = r.read(500_000).decode("utf-8", "replace").replace("\\$", "$")
    except Exception as e:
        raise JevError(f"Couldn't read the price list at {PRICING_URL} ({e}). Check it yourself and pass --price-per-mtok N.")
    p = parse_price(text)
    if p is None:
        raise JevError(f"Couldn't find the per-Mtok price on {PRICING_URL}; check it and pass --price-per-mtok N.")
    return p


def parse_price(text):
    """The highest per-Mtok price in the models table's price row ("| Price (per Btok / per Mtok) | $42 / $0.042 | ..."), or None."""
    row = next((l for l in text.replace("\\$", "$").splitlines() if re.search(r"price", l, re.I) and "Mtok" in l), "")
    prices = [float(p) for p in re.findall(r"/\s*\$\s*([\d.]+)", row)]
    return max(prices) if prices else None


def tokens_of(text):
    return len(text.encode("utf-8")) / 3.6  # rough; the API's usage count is what's billed and recorded


# --- the call --------------------------------------------------------------------------------------------------------

def _post(body, key, timeout=90):
    req = urllib.request.Request(API, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "daily-jobs-skill"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def ask(body, key, stop):
    """One request with retries for 429/529/5xx and network errors. Returns the response dict. Raises JevError on a
    problem every request would hit (bad key, malformed request), ValueError for this posting only."""
    for attempt in range(6):
        if stop.is_set():
            raise JevError("stopped")
        try:
            return _post(body, key)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read(300).decode("utf-8", "replace")
            except Exception:
                pass
            if e.code in (401, 403):
                raise JevError(f"TypeSafe answered {e.code}: the key is missing, wrong or revoked. Check it at {CONSOLE}/keys.")
            if e.code in (400, 413, 422):
                if "max_tokens" in detail or e.code == 413:
                    raise ValueError("request too long for the model's context")
                raise JevError(f"TypeSafe rejected the request ({e.code}): {detail[:200]}")
            if e.code in (402,):
                raise JevError(f"TypeSafe answered 402 (payment required): add credit at {CONSOLE}.")
            wait = float(e.headers.get("retry-after") or 0) if e.headers else 0
            time.sleep(max(wait, min(60, 2 ** attempt)))
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            time.sleep(min(60, 2 ** attempt))
    raise ValueError("no answer after 6 attempts")


def check_key():
    """A tiny real request (about 100 tokens, a fraction of a cent) proving the key works. Returns the model id."""
    key = api_key()
    if not key:
        raise JevError("No key. The person runs `python3 jobs.py jev key` in their own terminal, or sets TYPESAFE_API_KEY.")
    body = json.dumps({"model": DEFAULT_MODEL, "state": "The sky is blue.",
                       "questions": {"ok": {"type": "noul", "instructions": "The `state` mentions a color."}}}).encode()
    resp = ask(body, key, threading.Event())
    return resp.get("model") or DEFAULT_MODEL


# --- grading ---------------------------------------------------------------------------------------------------------

def job_state(r, excerpt):
    job = {"company": r["company"], "title": r["title"], "location": r.get("location") or "", "posted": r.get("posted") or "",
           "excerpt": excerpt or ""}
    if r.get("category"):
        job["team"] = r["category"]
    return job


def run(rows, excerpt_for, resume, rules, levels, model, ws, max_cost, price, workers=4, progress=print):
    """Grade rows (index rows) in parallel; excerpt_for(row) -> text. Appends to grades.jsonl as answers arrive and stops
    before spend could pass max_cost. Returns a summary dict."""
    key = api_key()
    if not key:
        raise JevError("No TypeSafe key. The person runs `python3 jobs.py jev key` in their own terminal, or sets TYPESAFE_API_KEY.")
    h = input_hash(resume, rules, levels, model)
    qs = questions(rules, levels)
    today = date.today().isoformat()
    lock, stop = threading.Lock(), threading.Event()
    spent = {"tokens": 0, "usd": 0.0, "done": 0, "failed": 0, "reserved": 0.0}
    out_path = os.path.join(ws, "grades.jsonl")
    started = time.time()
    last = [started]
    fatal = []

    def one(r):
        if stop.is_set():
            return
        state = {"today": today, "resume": resume, "job": job_state(r, excerpt_for(r))}
        body = json.dumps({"state": state, "model": model, "questions": qs}, ensure_ascii=False).encode()
        worst = tokens_of(body.decode()) * 1.5 * price / 1e6
        with lock:
            if spent["usd"] + spent["reserved"] + worst > max_cost:
                stop.set()
                return
            spent["reserved"] += worst
        try:
            resp = ask(body, key, stop)
            a = resp["answers"]
            el, fit = a["eligible"]["noul"], a["fit"]["score"]
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (el, fit)):
                raise ValueError("non-numeric answer")
            toks = (resp.get("usage") or {}).get("input_tokens")
            toks = toks if isinstance(toks, int) and toks >= 0 else int(tokens_of(body.decode()))
            rec = {"id": r["id"], "eligible": round(float(el), 4), "fit": round(float(fit), 3),
                   "conf": a["fit"].get("confidence"), "model": resp.get("model"), "h": h, "at": datetime.now().isoformat(timespec="seconds")}
            with lock:
                spent["reserved"] -= worst
                spent["tokens"] += toks
                spent["usd"] += toks * price / 1e6
                spent["done"] += 1
                with open(out_path, "a") as f:
                    f.write(json.dumps(rec) + "\n")
                if time.time() - last[0] > 20:
                    last[0] = time.time()
                    rate = spent["done"] / max(1, time.time() - started)
                    left = (len(rows) - spent["done"] - spent["failed"]) / max(rate, 0.01)
                    progress(f"graded {spent['done']:,}/{len(rows):,}, ${spent['usd']:.3f} spent, about {left / 60:.0f} min left")
        except JevError as e:
            with lock:
                spent["reserved"] -= worst
                if str(e) != "stopped":
                    fatal.append(str(e))
            stop.set()
        except (ValueError, KeyError, TypeError) as e:
            with lock:
                spent["reserved"] -= worst
                spent["failed"] += 1

    with ThreadPoolExecutor(max(1, workers)) as ex:
        futs = []
        for r in rows:
            if stop.is_set():
                break
            futs.append(ex.submit(one, r))
            if len(futs) >= workers * 50:  # keep memory flat on a 260k run
                for f in futs:
                    f.result()
                futs = []
        for f in futs:
            f.result()
    summary = {"at": datetime.now().isoformat(timespec="seconds"), "model": model, "graded": spent["done"], "failed": spent["failed"],
               "input_tokens": spent["tokens"], "usd": round(spent["usd"], 6), "price_per_mtok": price, "selected": len(rows),
               "minutes": round((time.time() - started) / 60, 1), "stopped": "cost cap" if stop.is_set() and not fatal else (fatal[0] if fatal else None)}
    with open(os.path.join(ws, "jev-spend.jsonl"), "a") as f:
        f.write(json.dumps(summary) + "\n")
    if fatal:
        raise JevError(fatal[0] + f" ({spent['done']:,} graded before it stopped; rerun to continue.)")
    return summary


def grades(ws, h=None):
    """Latest grade per id; with h, only grades made under that resume/rubric/model hash."""
    out = {}
    path = os.path.join(ws, "grades.jsonl")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    g = json.loads(line)
                except ValueError:
                    continue
                if h is None or g.get("h") == h:
                    out[g["id"]] = g
    return out


def spend(ws):
    rows = []
    path = os.path.join(ws, "jev-spend.jsonl")
    if os.path.exists(path):
        with open(path) as f:
            rows = [json.loads(l) for l in f if l.strip()]
    return rows
