"""Apple (jobs.apple.com) and Google (google.com/about/careers) adapters, both restricted to the US at the source; Atlassian (its own careers JSON)."""
import json, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
import ats

CHROME = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
APPLE_EMPTY_RETRIES = 5  # per search page; 6 empty answers in a row is a real outage, not the random blank page

def apple(cfg, known=()):
    """cfg: optional title_filter (case-insensitive regex applied to list titles before the detail call)."""
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    def token():  # also sets the jssid cookie in `op`
        with op.open(urllib.request.Request("https://jobs.apple.com/api/v1/csrfToken", headers=CHROME), timeout=60) as r:
            return r.headers["x-apple-csrf-token"]
    tok, items, page, total = token(), [], 1, None
    while True:
        body = {"query": "", "filters": {"locations": ["postLocation-USA"]}, "page": page, "locale": "en-us", "sort": "newest",
                "format": {"longDate": "MMMM D, YYYY", "mediumDate": "MMM D, YYYY"}}
        res = ats.get("https://jobs.apple.com/api/v1/search", body, {**CHROME, "X-Apple-CSRF-Token": tok}, op)["res"]
        hits = res.get("searchResults") or []
        # Apple answers ~1 in 8 search pages with {"searchResults": [], "totalRecords": 0} at random (seen 2026-10-05); the same page
        # succeeds when asked again. Over ~225 pages a single retry still fails most runs, so back off a few times before giving up.
        for attempt in range(APPLE_EMPTY_RETRIES):
            if hits or not (page == 1 or total and (page - 1) * 20 < total):
                break
            time.sleep(2 * (attempt + 1))
            if attempt % 2:
                tok = token()
            res = ats.get("https://jobs.apple.com/api/v1/search", body, {**CHROME, "X-Apple-CSRF-Token": tok}, op)["res"]
            hits = res.get("searchResults") or []
        if not hits and (page == 1 or total and (page - 1) * 20 < total):
            raise RuntimeError(f"apple search incomplete on page {page} (totalRecords={res.get('totalRecords')}); kept cache")
        items += hits; total = total or res.get("totalRecords", 0); page += 1
        if not hits or (page - 1) * 20 >= total:
            break
    tf = cfg.get("title_filter")
    items = [j for j in {j["id"]: j for j in items}.values() if not tf or re.search(tf, j.get("postingTitle") or "", re.I)]  # newest-first paging can repeat an id
    def one(j):
        for attempt in range(4):  # ats.get retries only 429; Apple's detail host also throws transient 502s
            try:
                d = ats.get(f"https://jobs.apple.com/api/v1/jobDetails/{j['id']}?languageCd=en-us", headers=CHROME, opener=op)["res"]; break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    print(f"apple: skip {j['id']} (404, listing removed)", file=sys.stderr); return None
                if e.code < 500 or attempt == 3:
                    raise
                time.sleep(5 * (attempt + 1))
        desc = "\n".join(filter(None, [ats.strip(d.get("jobSummary") or j.get("jobSummary")), ats.strip(d.get("description"))]))
        return ats.row(cfg, "apple", j["id"], j["postingTitle"], (j.get("locations") or [{}])[0].get("name"), (j.get("team") or {}).get("teamName"),
                       j.get("postDateInGMT"), f"https://jobs.apple.com/en-us/details/{j['id']}/{j.get('transformedPostingTitle', '')}",
                       desc, ats.strip(d.get("minimumQualifications")), ats.strip(d.get("preferredQualifications")))
    return ats.detail_map(cfg, known, items, lambda j: j["id"], one, workers=4)

def google(cfg, known=()):
    """cfg: optional query (search text). List page embeds all fields; no detail call."""
    base = "https://www.google.com/about/careers/applications/jobs/results/"
    q = urllib.parse.urlencode({"location": "United States", **({"q": cfg["query"]} if cfg.get("query") else {})})
    out, page, total = [], 1, None
    while True:
        html = ats.get_text(f"{base}?{q}&page={page}")
        i = html.find("AF_initDataCallback({key: 'ds:1'")
        i = html.find("data:", i) + 5 if i >= 0 else -1
        if i < 5:
            raise RuntimeError(f"google page {page}: ds:1 payload not found")
        data = json.JSONDecoder().raw_decode(html[i:].lstrip())[0]
        jobs = data[0] or []; total = total or data[2] or 0
        for j in jobs:
            try:
                sub = lambda k: (j[k] or [None, ""])[1] or "" if len(j) > k and isinstance(j[k], list) else ""
                quals = sub(4); m = re.search(r"<h\d[^>]*>\s*Preferred", quals, re.I)
                basic, pref = (quals[:m.start()], quals[m.start():]) if m else (quals, "")
                locs = [l[0] for l in (j[9] or []) if l and l[0]]
                ts = next((x for x in (j[12], j[13], j[14]) if x and x[0]), None)
                posted = datetime.fromtimestamp(ts[0], timezone.utc).isoformat() if ts else ""
                out.append(ats.row(cfg, "google", j[0], j[1], " | ".join(locs[:3]), "", posted, f"{base}{j[0]}",
                                   ats.strip(sub(10) + "\n" + sub(3)), ats.strip(basic), ats.strip(pref)))
            except Exception as e:
                print(f"google: skip job {j[0] if j else '?'}: {e!r}", file=sys.stderr)
        page += 1
        if not jobs or (page - 1) * (data[3] or 20) >= total:
            break
    return out

def atlassian(cfg, known=()):
    """cfg: none beyond company. atlassian.com/endpoint/careers/listings returns every posting (worldwide, ~350) with overview,
    responsibilities and qualifications HTML in one call; some appear twice (same id), kept once. Locations read "Austin - United
    States - Austin, Texas 78702 United States", "Remote - UK - Remote", "Remote - Remote"; fetch.py's is_us decides on the joined list."""
    out, seen = [], set()
    for j in ats.get("https://www.atlassian.com/endpoint/careers/listings", headers=CHROME):
        if j["id"] in seen:
            continue
        seen.add(j["id"])
        upd = (j.get("portalJobPost") or {}).get("updatedDate") or ""  # "2026-09-24 03:33 PM"
        out.append(ats.row(cfg, "atlassian", j["id"], j.get("title"), "; ".join(re.sub(r"\s+", " ", l).strip() for l in j.get("locations") or []),
                           j.get("category"), upd[:10], f"https://www.atlassian.com/company/careers/details/{j['id']}",
                           "\n".join(filter(None, [ats.strip(j.get("overview")), ats.strip(j.get("responsibilities"))])), ats.strip(j.get("qualifications"))))
    return out

FETCHERS = {"apple": apple, "google": google, "atlassian": atlassian}
US_FILTERED = {"apple", "google"}
