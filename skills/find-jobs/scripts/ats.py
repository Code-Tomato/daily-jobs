"""Fetchers for public job-board APIs. Every fetcher returns normalized rows:
{id, company, ats, title, location, category, posted, url, description, basic, preferred}
`basic`/`preferred` are "" when the board does not split qualifications out (then they live in description).
"""
import fcntl, glob, json, os, re, signal, socket, sys, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from html import unescape

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Content-Type": "application/json"}

def strip(html):
    """HTML (possibly entity-escaped) -> single-spaced text."""
    t = unescape(unescape(html or ""))
    t = re.sub(r"<(br|/p|/li|/h\d|/div)[^>]*>", "\n", t, flags=re.I)
    return re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", " ", t)).strip()

_US_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
_US_NAMES = ["alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
             "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
             "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio",
             "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
             "washington", "west virginia", "wisconsin", "wyoming"]
_US_CITIES = ["san francisco", "sunnyvale", "santa clara", "palo alto", "mountain view", "san jose", "cupertino", "menlo park", "seattle", "bellevue", "redmond",
              "austin", "new york", "nyc", "boston", "cambridge", "chicago", "denver", "boulder", "los angeles", "san diego", "portland", "atlanta", "pittsburgh",
              "houston", "dallas", "phoenix", "salt lake", "raleigh", "durham", "arlington", "reston", "miami", "minneapolis", "detroit", "ann arbor", "irvine",
              "oakland", "berkeley", "fremont", "foster city", "san mateo", "redwood city", "south san francisco", "emeryville", "waltham", "north reading",
              "hawthorne", "el segundo", "brownsville", "mclean", "tysons", "bay area", "silicon valley", "burlingame", "santa monica", "culver city", "bellevue",
              "kirkland", "boca raton", "tempe", "chandler", "hillsboro", "folsom", "columbus", "nashville", "philadelphia", "baltimore", "madison", "ithaca",
              # Texas towns that boards list bare (Texas Health Resources, Parkland, University Health)
              "fort worth", "plano", "san antonio", "el paso", "frisco", "irving", "the woodlands", "sugar land", "katy", "round rock",
              "college station", "corpus christi", "lubbock", "mckinney", "denton", "richardson", "pearland", "conroe", "galveston", "waco",
              "amarillo", "mcallen", "laredo", "killeen", "carrollton", "lewisville", "grapevine", "southlake", "baytown", "league city"]

_FOREIGN = re.compile(r"\b(ecuador|peru|uruguay|paraguay|bolivia|venezuela|guatemala|honduras|el salvador|nicaragua|panama|"
                      r"dominican republic|jamaica|trinidad|ukraine|lithuania|latvia|estonia|bulgaria|croatia|slovakia|slovenia|armenia|"
                      r"morocco|ghana|ethiopia|uganda|rwanda|tanzania|sri lanka|nepal|cambodia|bangladesh|turkiye|"
                      r"canada|mexico|brazil|argentina|chile|colombia|costa rica|latin america|south america|central america|caribbean|latam|united kingdom|uk|england|scotland|wales|ireland|germany|france|spain|portugal|italy|netherlands|belgium|poland|czech\w*|romania|hungary|serbia|greece|switzerland|austria|sweden|denmark|finland|norway|israel|uae|dubai|saudi|egypt|nigeria|kenya|south africa|india|pakistan|china|hong kong|japan|korea|taiwan|singapore|malaysia|thailand|vietnam|indonesia|philippines|australia|new zealand|emea|apac|europe|asia|ontario|british columbia|quebec|alberta|toronto|vancouver|montreal|ottawa|waterloo|calgary|london|berlin|munich|paris|amsterdam|dublin|zurich|tel aviv|haifa|bangalore|bengaluru|hyderabad|pune|chennai|noida|gurgaon|shanghai|beijing|shenzhen|tokyo|seoul|taipei|hsinchu|sydney|melbourne)\b", re.I)

# "City, ST" / "City ST" ending a location or one part of it ("; ", " / ", " - Hybrid", " (Remote)", ", Remote", "(City, ST)"): a US town even when the city name is
# foreign ("London, KY", "Ontario, CA"). Skipped after a Canadian province ("Toronto, ON, CA") and for codes that double as
# country codes: "Tel Aviv, IL", "Berlin, DE", "Amsterdam, NH" are far more common in postings than "Paris, IL" or "Berlin, NH".
_PROV = r"\b(?i:ON|BC|AB|QC|NS|MB|SK|NB|NL|PE)"  # any case ("Toronto, On, CA"); state codes stay upper-case so "or", "in", "me" never match
_US_SUFFIX = re.compile(r"(?<!" + _PROV + r", )(?<!" + _PROV + r" )(?:(?<=, )|(?<=[A-Za-z.] ))(?:" + "|".join(sorted(_US_STATES - {"DE", "IN", "IL", "CO", "AR", "NH"}))
                        + r")(?i:,\s*(?:us|usa|remote|hybrid|on-?site))?\s*(?:[;|•/()–—-]|$)")  # not a bare ",": "Chennai, TN, in"
# A country or province code ending the location: lower-case after a region ("Bagneux, HAUTS-DE-SEINE, fr", whose DE is no Delaware),
# upper-case after a two-letter region that is no US state ("Vadodara, GJ, IN" is India, not Indiana), or a Canadian province ("CA - Woodbridge, ON").
_CC_TAIL = re.compile(r",\s*[^,]+,\s*(?!us\b)[a-z]{2}\s*$|,\s*(?!(?:" + "|".join(sorted(_US_STATES)) + r")\b)[A-Z]{2},\s*(?!US\b)[A-Z]{2}\s*$|,\s*" + _PROV + r"\s*$"
                      # a lower-case country code after a single comma ("MX Remote Work, mx"), but not a lower-case state ("Austin, tx")
                      r"|,\s*(?!(?:us|pr|" + "|".join(sorted(x.lower() for x in _US_STATES)) + r")\b)[a-z]{2}\s*$"
                      # an upper-case country code alone after the last comma ("San Jose, CR" is Costa Rica, not California)
                      r"|,\s*(?!(?:US|PR|GU|VI|AS|MP|DC|" + "|".join(sorted(_US_STATES)) + r")\b)[A-Z]{2}\s*$")

def is_foreign(location):
    """True only when the location names a foreign place and no US one ("MX Remote Work, mx", "Toronto, ON"). Unlike
    is_us, an unknown place ("Main Campus - Orange") is not foreign: for boards already filtered to the US at the source."""
    l = (location or "").lower().strip()
    if not l or re.search(r"\b(us|usa|u\.s\.|united states|north america)\b", l) \
            or _US_SUFFIX.search(re.sub(r"\s*,\s*", ", ", re.sub(r"\s+", " ", location.strip()))) or any(n in l for n in _US_NAMES):
        return False
    return bool(_COUNTRY.search(l) or re.search(r",\s*(?!(?:us|pr)\b)(?:mx|ca|in|gb|uk|br|cr|co|ar|ph|ie|de|fr|es|pl|nl|sg|jp|cn|kr|au|il|ro)\s*$", location or ""))


# Country names only (not cities or provinces, which collide with US places: Dublin OH, Ontario CA, Ottawa IL)
_COUNTRY = re.compile(r"\b(mexico|canada|india|united kingdom|england|scotland|ireland|germany|france|spain|italy|netherlands|belgium|"
                      r"switzerland|austria|sweden|norway|denmark|finland|poland|hungary|czech|romania|portugal|brazil|argentina|chile|"
                      r"colombia|peru|costa rica|philippines|singapore|japan|china|korea|taiwan|vietnam|thailand|malaysia|indonesia|"
                      r"australia|new zealand|israel|united arab emirates|saudi arabia|egypt|nigeria|kenya|south africa|"
                      r"ukraine|pakistan|bangladesh)\b")


def is_us(location):
    """Cheap US check on a free-text location. An explicit US country/state wins; then a named foreign place loses ("Remote - Canada",
    "Toronto, ON, CA"); then empty, Remote, Hybrid and bare state codes count as US; unrecognized place names do not."""
    l = (location or "").lower().strip()
    if not l:
        return True
    if re.search(r"\b(us|usa|u\.s\.|united states|north america|new england|na|sf)\b", l) or _US_SUFFIX.search(re.sub(r"\s*,\s*", ", ", re.sub(r"\s+", " ", location.strip()))) or any(n in l for n in _US_NAMES):
        return True
    if _FOREIGN.search(l) or _CC_TAIL.search(location):
        return False
    if any(c in l for c in _US_CITIES):
        return True
    if re.search(r"\b(americas?|east coast|west coast|remote|hybrid|distributed|anywhere|global|worldwide)\b", l):
        return True
    return any(re.search(rf"\b{s}\b", location) for s in _US_STATES)  # ponytail: a US town not in the lists is the false-negative risk

def get_text(url, data=None, headers=None, opener=None):
    """GET (or POST `data`: dict -> JSON body, str/bytes -> raw) with retries; returns the body as str.
    `headers` are merged over UA; `opener` (urllib OpenerDirector) lets an adapter reuse cookies."""
    body = None if data is None else (json.dumps(data).encode() if isinstance(data, (dict, list)) else data if isinstance(data, bytes) else str(data).encode())
    req = urllib.request.Request(url, data=body, headers={**UA, **(headers or {})})
    open_ = opener.open if opener else urllib.request.urlopen
    for attempt in range(5):
        try:
            with open_(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == 4:
                raise
            wait = e.headers.get("Retry-After") if e.code == 429 and e.headers else None
            if wait and wait.isdigit() and int(wait) > 300:
                raise  # a block for hours (a spent daily quota): waiting here helps nothing
            time.sleep(10 * (attempt + 1) if e.code == 429 else 2 ** attempt)
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)

class BudgetExceeded(BaseException):
    """fetch.py's per-board SIGALRM deadline. BaseException, like KeyboardInterrupt, so no retry/outage `except Exception` swallows it."""

def online():
    """True if any well-known host resolves and accepts a TCP connection (5s each). By name, not IP: DNS down is offline too."""
    for host in ("www.google.com", "one.one.one.one"):
        try:
            socket.create_connection((host, 443), timeout=5).close()
            return True
        except OSError:
            pass
    return False

_net_lock = threading.Lock()  # grade.py's worker threads share one wait instead of each polling
def wait_online(every=300):
    """Block until the network is back, checking every `every` seconds. Never gives up: an outage pauses the run instead of failing it."""
    with _net_lock:
        left = signal.alarm(0)  # time offline does not count against fetch.py's per-board budget
        try:
            while not online():
                print(f"{datetime.now():%H:%M} offline; checking again in {every // 60} min", file=sys.stderr, flush=True)
                time.sleep(every)
        finally:
            if left:
                signal.alarm(left)

def get(url, data=None, headers=None, opener=None):
    """Same as get_text but parses JSON."""
    return json.loads(get_text(url, data, headers, opener))

def row(cfg, ats, jid, title, location, category, posted, url, description, basic="", preferred=""):
    return {"id": f"{cfg['company'].lower().replace(' ', '-')}:{jid}", "company": cfg["company"], "ats": ats,
            "title": title or "", "location": location or "", "category": category or "", "posted": (posted or "")[:10],
            "url": url or "", "description": description or "", "basic": basic or "", "preferred": preferred or ""}

def detail_map(cfg, known, items, key, fn, workers=8):
    """Fetch per-job detail in parallel, skipping ids already in `known` (daily runs). One posting that closed between the
    list and its detail call (404/410) or whose detail is malformed is skipped, not fatal to the board; if more than half
    fail that way the board fails, so a broken adapter still shows up."""
    todo = [i for i in items if f"{cfg['company'].lower().replace(' ', '-')}:{key(i)}" not in known]
    bad = []

    def one(i):
        try:
            return fn(i)
        except urllib.error.HTTPError as e:
            if e.code not in (404, 410):
                raise
            bad.append(f"{key(i)}: HTTP {e.code}")
        except (KeyError, ValueError, TypeError, IndexError, AttributeError) as e:
            bad.append(f"{key(i)}: {type(e).__name__} {e}")
        return None
    ex = ThreadPoolExecutor(workers)
    try:
        out = [r for r in ex.map(one, todo) if r]
    finally:
        ex.shutdown(wait=False, cancel_futures=True)  # a budget timeout must not wait on thousands of queued detail calls
    if bad:
        print(f"{cfg['company']}: skipped {len(bad)} posting(s): {'; '.join(bad[:3])}", file=sys.stderr)
        if len(bad) > 5 and len(bad) > len(todo) / 2:
            raise RuntimeError(f"{len(bad)} of {len(todo)} detail calls failed, e.g. {bad[0]}")
    return out

# --- adapters -------------------------------------------------------------

def greenhouse(cfg, known=()):
    d = get(f"https://boards-api.greenhouse.io/v1/boards/{cfg['slug']}/jobs?content=true")
    return [row(cfg, "greenhouse", j["id"], j["title"], j["location"]["name"], ", ".join(x["name"] for x in j.get("departments") or []),
                j.get("first_published") or j.get("updated_at"), j["absolute_url"], strip(j["content"])) for j in d["jobs"]]

def lever(cfg, known=()):
    """cfg: slug, optional region ("eu": api.eu.lever.co, the jobs.eu.lever.co boards such as Mobileye)."""
    out, api = [], "https://api.eu.lever.co" if cfg.get("region") == "eu" else "https://api.lever.co"
    for j in get(f"{api}/v0/postings/{cfg['slug']}?mode=json"):
        c = j.get("categories", {})
        lists = j.get("lists", [])
        quals = "\n".join(strip(l["content"]) for l in lists if re.search(r"qualif|require|you have|looking for", l["text"], re.I) and not re.search(r"bonus|nice|preferred", l["text"], re.I))
        pref = "\n".join(strip(l["content"]) for l in lists if re.search(r"bonus|nice|preferred", l["text"], re.I))
        desc = "\n".join(filter(None, [j.get("descriptionPlain"), *(f"{l['text']}\n{strip(l['content'])}" for l in lists), j.get("additionalPlain")]))
        out.append(row(cfg, "lever", j["id"], j["text"], c.get("location"), " / ".join(filter(None, [c.get("department"), c.get("team")])),
                       datetime.fromtimestamp(j["createdAt"] / 1000, timezone.utc).isoformat(), j["hostedUrl"], desc, quals, pref))
    return out

def ashby(cfg, known=()):
    d = get(f"https://api.ashbyhq.com/posting-api/job-board/{cfg['slug']}")
    return [row(cfg, "ashby", j["id"], j["title"], j.get("location"), " / ".join(filter(None, [j.get("department"), j.get("team")])),
                j.get("publishedAt"), j["jobUrl"], j.get("descriptionPlain") or strip(j.get("descriptionHtml"))) for j in d["jobs"] if j.get("isListed", True)]

def smartrecruiters(cfg, known=()):
    """cfg: slug, optional country (e.g. "us": the API filters before the per-posting detail calls; Bosch lists 5,000 worldwide)."""
    base = f"https://api.smartrecruiters.com/v1/companies/{cfg['slug']}/postings"
    country = f"&country={cfg['country']}" if cfg.get("country") else ""
    items, offset = [], 0
    while True:
        d = get(f"{base}?limit=100&offset={offset}{country}")
        items += d["content"]; offset += 100
        if offset >= d["totalFound"] or not d["content"]:
            break
    def one(p):
        det = get(f"{base}/{p['id']}"); s = det.get("jobAd", {}).get("sections", {})
        txt = lambda k: strip(s.get(k, {}).get("text"))
        loc = p.get("location", {})
        return row(cfg, "smartrecruiters", p["id"], p["name"], ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")])),
                   (p.get("department") or {}).get("label"), p.get("releasedDate"), det.get("postingUrl"),
                   "\n".join(filter(None, [txt("jobDescription"), txt("additionalInformation")])), txt("qualifications"))
    return detail_map(cfg, known, items, lambda p: p["id"], one)

def workable(cfg, known=()):
    # ponytail: widget API, untested against a live board with postings (test slugs returned empty)
    d = get(f"https://apply.workable.com/api/v1/widget/accounts/{cfg['slug']}?details=true")
    return [row(cfg, "workable", j["shortcode"], j["title"], ", ".join(filter(None, [j.get("city"), j.get("state"), j.get("country")])) or j.get("location"),
                j.get("department"), j.get("published_on"), j["url"], strip(j.get("description")), strip(j.get("requirements")), strip(j.get("benefits")) and "")
            for j in d.get("jobs", [])]

def rippling(cfg, known=()):
    base = f"https://api.rippling.com/platform/api/ats/v1/board/{cfg['slug']}/jobs"
    def one(j):
        det = get(f"{base}/{j['uuid']}"); desc = det.get("description") or {}
        desc = desc if isinstance(desc, str) else "\n".join(strip(v) for v in desc.values() if isinstance(v, str))
        return row(cfg, "rippling", j["uuid"], j["name"], (j.get("workLocation") or {}).get("label"), (j.get("department") or {}).get("label"),
                   det.get("createdOn"), j["url"], strip(desc))
    return detail_map(cfg, known, get(base), lambda j: j["uuid"], one)

def workday(cfg, known=()):
    """cfg: host (e.g. nvidia.wd5.myworkdayjobs.com), tenant, site, optional facets {} and searchText.
    Optional prefilter_us: drop list entries whose locationsText is clearly non-US before the per-job detail call. For worldwide
    boards with no country facet (HPE: 1440 postings -> 669 detail calls on 2026-10-05, after a 403 on the full run). "N Locations" is
    kept; fetch.py's client_us filter still drops non-US rows by the detail location."""
    base = f"https://{cfg['host']}/wday/cxs/{cfg['tenant']}/{cfg['site']}"
    items, offset, total = [], 0, None
    while True:
        d = get(f"{base}/jobs", {"appliedFacets": cfg.get("facets", {}), "limit": 20, "offset": offset, "searchText": cfg.get("searchText", "")})
        items += [p for p in d.get("jobPostings", []) if p.get("externalPath")]; offset += 20
        total = total or d.get("total", 0)  # only the first page carries total
        if offset >= total or not d.get("jobPostings"):
            break
    if cfg.get("prefilter_us"):
        items = [p for p in items if re.fullmatch(r"\d+ Locations", p.get("locationsText") or "") or is_us(p.get("locationsText"))]
    jid = lambda p: p["externalPath"].rsplit("_", 1)[-1]
    def posted(p):  # "Posted Today" / "Posted Yesterday" / "Posted 3 Days Ago" / "Posted 30+ Days Ago"
        m = re.search(r"(\d+)", p.get("postedOn", "")); t = p.get("postedOn", "").lower()
        days = 0 if "today" in t else 1 if "yesterday" in t else int(m.group(1)) if m else 0
        return (date.today() - timedelta(days=days)).isoformat()
    def one(p):
        try:
            info = get(base + p["externalPath"]).get("jobPostingInfo", {})
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            print(f"{cfg['company']}: removed posting {jid(p)} (404)", file=sys.stderr)
            return None
        time.sleep(0.5)
        if not info.get("jobDescription"):  # one blank posting must not fail the whole board
            print(f"{cfg['company']}: skipped {jid(p)} (no job description)", file=sys.stderr)
            return None
        return row(cfg, "workday", jid(p), info.get("title") or p["title"], info.get("location") or p.get("locationsText"), "",
                   posted(p), info.get("externalUrl") or f"https://{cfg['host']}/{cfg['site']}{p['externalPath']}", strip(info.get("jobDescription")))
    return detail_map(cfg, known, items, jid, one, workers=2)  # ponytail: Workday 429s above ~4 req/s

def lock():
    """One pipeline run at a time: overlapping daily/fetch/grade runs overwrite each other's jobs.jsonl and graded.jsonl.
    Waits for the other run to finish. Scripts launched by a locked run inherit the lock through the environment."""
    global _lock
    if os.environ.get("JOBBOARD_LOCKED"):
        return
    _lock = open(".lock", "w")
    try:
        fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another job-board run is going; waiting for it", file=sys.stderr, flush=True)
        fcntl.flock(_lock, fcntl.LOCK_EX)
    os.environ["JOBBOARD_LOCKED"] = "1"

def write_atomic(path, text):
    """Write via a temp file + rename, so a run killed mid-write leaves the old file, never a truncated one."""
    with open(path + ".tmp", "w") as f:
        f.write(text)
    os.replace(path + ".tmp", path)

def read_jsonl(path):
    """Rows of a .jsonl file, skipping lines a run killed mid-append left torn (cut short, or glued to the next record)."""
    rows = []
    for l in open(path):
        try:
            rows.append(json.loads(l))
        except ValueError:
            pass
    return rows

def load_cfgs():
    """Board list: companies.json plus every companies.d/*.json fragment (same shape)."""
    cfgs = []
    for path in ["companies.json"] + sorted(glob.glob("companies.d/*.json")):
        with open(path) as f:
            cfgs += json.load(f)
    return cfgs

INTERN = re.compile(r"\b(?:intern(?:ship)?s?|co[- ]?op)\b", re.I)
# required security clearance only; ITAR / export-control "US person" is not a clearance and the candidate (US citizen) satisfies it
CLEARANCE = re.compile(r"(active|current|existing|must (have|hold|possess|obtain|be able to obtain)|ability to obtain|eligib\w+ (to obtain|for)|required to (obtain|hold)|hold an?|obtain and maintain)[^.]{0,60}\b(security clearance|clearance|TS/SCI|top secret|secret clearance)"
                       r"|\b(security clearance|TS/SCI|top secret|secret clearance)\b[^.]{0,80}\b(required|must|necessary)", re.I)

def verdict(g, j):
    """Board verdict for graded row g and its job row j (None once the posting is gone). Code, not model; shared by report.py and daily.py."""
    if g["eligible"] < .3:
        return "Ineligible"
    if j and CLEARANCE.search((j["basic"] or "") + " " + j["description"]):
        return "Clearance"
    if j and INTERN.search(j["title"]):
        return "Check"
    if g["fit"] >= 2 and g["eligible"] >= .5:
        return "Apply"
    return "Maybe" if g["fit"] >= 1.5 else "Skip"

def amazon_normalize(cfg, j):
    posted = datetime.strptime(" ".join(j["posted_date"].split()), "%B %d, %Y").date().isoformat() if j.get("posted_date") else ""
    team = j.get("team"); team = team.get("label", "") if isinstance(team, dict) else (team or "")
    return row(cfg, "amazon", j["id_icims"], j["title"], j["location"], j.get("job_category"), posted, "https://www.amazon.jobs" + j["job_path"],
               strip(j.get("description")), strip(j.get("basic_qualifications")), strip(j.get("preferred_qualifications"))) | {"team": team}

FETCHERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "smartrecruiters": smartrecruiters,
            "workable": workable, "rippling": rippling, "workday": workday}
US_FILTERED = {"amazon", "workday"}  # ATSs whose adapter already restricts to the US; fetch.py skips is_us for them

# plug-ins: every adapters/<name>.py contributes FETCHERS (and optionally US_FILTERED); see adapters/__init__.py for the contract
import importlib, pkgutil
import adapters as _adapters
for _m in pkgutil.iter_modules(_adapters.__path__):
    try:
        _mod = importlib.import_module(f"adapters.{_m.name}")
    except Exception as _e:  # one broken plug-in must not take the others down
        print(f"adapters/{_m.name}.py failed to import: {_e!r}", file=sys.stderr); continue
    FETCHERS.update(getattr(_mod, "FETCHERS", {}))
    US_FILTERED.update(getattr(_mod, "US_FILTERED", ()))
