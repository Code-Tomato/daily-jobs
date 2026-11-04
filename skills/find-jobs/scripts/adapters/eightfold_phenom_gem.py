"""Eightfold (Netflix; PCSX: Microsoft, Qualcomm, Lam...), Phenom (Cisco), Gem (Retool, Groq) adapters. See adapters/__init__.py for the contract."""
import sys, threading, time, urllib.error, urllib.parse
from datetime import datetime, timezone
from ats import get, strip, row, detail_map

CHROME = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"}
_iso = lambda ts: datetime.fromtimestamp(ts, timezone.utc).date().isoformat() if ts else ""

def eightfold(cfg, known=()):
    """cfg: host (explore.jobs.netflix.net), domain (netflix.com). US filtered at the source (location=United States).
    Microsoft/Lam/Deere/Qualcomm/Infineon/Ericsson 403 on this API ("Not authorized for PCSX"); use eightfold_pcsx for them."""
    base = f"https://{cfg['host']}/api/apply/v2/jobs"
    items, start = [], 0
    while True:
        d = get(f"{base}?domain={cfg['domain']}&start={start}&num=10&location=United%20States&locationRadius=100", headers=CHROME)  # num hard-capped at 10
        items += d.get("positions", []); start += 10
        if start >= d.get("count", 0) or not d.get("positions"):
            break
    def one(p):
        det = get(f"{base}/{p['id']}?domain={cfg['domain']}", headers=CHROME)
        return row(cfg, "eightfold", p["id"], p["name"], (p.get("location") or "").replace(",", ", "), p.get("department"),
                   _iso(p.get("t_create")), p.get("canonicalPositionUrl") or f"https://{cfg['host']}/careers/job/{p['id']}", strip(det.get("job_description")))
    return detail_map(cfg, known, items, lambda p: p["id"], one, workers=4)

def eightfold_pcsx(cfg, known=()):
    """Eightfold's newer career-site API (/api/pcsx), for tenants that 403 the old one. cfg: host (careers.qualcomm.com), domain (qualcomm.com),
    optional location (default "United States"; a hard filter at the source), optional queries (list of search strings, each paged
    separately and merged by position id, to bound a huge board such as Microsoft's; default: one empty query = the whole board),
    optional interval (seconds between any two requests, all workers together; default 1). 10 positions per search page; the text
    comes from one position_details call per new position, so a first fetch of 800 positions takes ~15 min (Microsoft with 6 queries
    ~17 min) and daily runs only the new ones. Every tenant sits behind one CloudFront edge that answers 403 to the whole IP for ~5 min
    once it sees too many requests (2 workers at ~2.5 req/s tripped it on 2026-10-15; 1 req/s ran 876 requests clean); such a 403
    (CloudFront's error page) waits blocked_wait seconds (default 330) and retries, up to blocked_retries times (default 2).
    Search also answers 429 when hammered (Microsoft, Qualcomm), which ats.get_text backs off from."""
    base, h = f"https://{cfg['host']}/api/pcsx", {**CHROME, "Accept": "application/json"}
    loc, items = urllib.parse.quote(cfg.get("location", "United States")), {}
    lock, last, retries = threading.Lock(), [0.0], cfg.get("blocked_retries", 2)
    def fetch(url):
        for attempt in range(retries + 1):
            with lock:  # pace every request, whichever worker sends it
                time.sleep(max(0, last[0] + cfg.get("interval", 1) - time.monotonic()))
                last[0] = time.monotonic()
            try:
                return get(url, headers=h)
            except urllib.error.HTTPError as e:
                if e.code != 403 or attempt == retries or "cloudfront" not in (e.headers.get("Server") or "").lower():
                    raise
                print(f"{cfg['company']}: Eightfold edge 403, waiting {cfg.get('blocked_wait', 330)}s", file=sys.stderr, flush=True)
                time.sleep(cfg.get("blocked_wait", 330))
    for q in cfg.get("queries") or [""]:
        start, ids = 0, set()
        while True:  # newest first: a posting added mid-run shifts the rest down a page (a repeat), it cannot hide one (a miss)
            d = fetch(f"{base}/search?domain={cfg['domain']}&query={urllib.parse.quote(q)}&location={loc}&start={start}&sort_by=timestamp")["data"]
            page = d.get("positions") or []
            for p in page:
                items.setdefault(p["id"], p); ids.add(p["id"])
            start += len(page)
            if not page or start >= d.get("count", 0):
                break
        if len(ids) < d.get("count", 0):  # the default distance sort once paged 571 Lam positions into 529 distinct ones
            print(f"{cfg['company']}: search {q!r} listed {len(ids)} distinct of {d.get('count')}", file=sys.stderr)
    def one(p):
        try:
            det = fetch(f"{base}/position_details?position_id={p['id']}&domain={cfg['domain']}").get("data")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            det = None
        if not det or not det.get("jobDescription"):  # closed between the search and the detail call
            print(f"{cfg['company']}: skipped {p['id']} (no position details)", file=sys.stderr); return None
        locs = dict.fromkeys(p.get("standardizedLocations") or p.get("locations") or [])  # Deere repeats each location
        return row(cfg, "eightfold_pcsx", p["id"], det.get("name") or p["name"], "; ".join(locs),
                   det.get("department") or p.get("department"), _iso(p.get("postedTs") or p.get("creationTs")),
                   det.get("publicUrl") or f"https://{cfg['host']}/careers/job/{p['id']}", strip(det.get("jobDescription")))
    return detail_map(cfg, known, list(items.values()), lambda p: p["id"], one, workers=2)

def phenom(cfg, known=()):
    """cfg: host (careers.cisco.com), country (exact facet value, e.g. "United States of America"), optional site_path (default global/en),
    optional keywords (the board's own search, e.g. "registered nurse": a 10,000-posting health system in minutes, not an hour)."""
    url, site = f"https://{cfg['host']}/widgets", cfg.get("site_path", "global/en")
    h = {**CHROME, "Origin": f"https://{cfg['host']}", "Referer": f"https://{cfg['host']}/{site}/search-results"}
    common = {"lang": "en_us", "deviceType": "desktop", "country": "us", "siteType": "external"}
    items, frm = [], 0
    while True:
        d = get(url, {**common, "pageName": "search-results", "ddoKey": "refineSearch", "sortBy": "", "subsearch": "", "from": frm, "jobs": True, "counts": True,
                      "all_fields": ["category", "country", "state", "city"], "size": 1000, "clearAll": False, "jdsource": "facets", "isSliderEnable": False,
                      "pageId": "page12", "keywords": cfg.get("keywords", ""), "global": True, "selected_fields": {"country": [cfg["country"]]}, "locationData": {}}, headers=h)["refineSearch"]
        jobs = d.get("data", {}).get("jobs", [])
        items += jobs; frm += len(jobs)
        if frm >= d.get("totalHits", 0) or not jobs:
            break
    def one(j):
        det = get(url, {**common, "ddoKey": "jobDetail", "jobId": j["jobId"], "jobSeqNo": j["jobSeqNo"], "pageName": "job-details"}, headers=h)
        loc = j.get("cityStateCountry") or ", ".join(filter(None, [j.get("city"), j.get("state"), j.get("country")]))
        return row(cfg, "phenom", j["jobId"], j["title"], loc, j.get("category"), j.get("postedDate"), f"https://{cfg['host']}/{site}/job/{j['jobId']}",
                   strip(det["jobDetail"]["data"]["job"].get("description")))
    return detail_map(cfg, known, items, lambda j: j["jobId"], one, workers=4)

_GEM = "https://jobs.gem.com/api/public/graphql"
def _us_posting(locs):
    """US if any location is USA, or it is remote and no location names another country (a UK-remote posting is not US)."""
    countries = {l.get("isoCountry") for l in locs if l.get("isoCountry")}
    return "USA" in countries or (any(l.get("isRemote") for l in locs) and not (countries - {"USA"}))

_GEM_LIST = "query JobBoardList($boardId: String!) { oatsExternalJobPostings(boardId: $boardId) { jobPostings { id extId title locations { name city isoCountry isRemote } job { department { name } locationType employmentType } } } }"
_GEM_ONE = "query D($boardId:String!,$extId:String!){ oatsExternalJobPosting(boardId:$boardId, extId:$extId){ id extId title descriptionHtml firstPublishedTsSec locations{name city isoCountry isRemote} job{ requisitionId teamDisplayName employmentType locationType department{name} } jobPostSectionHtml{introHtml outroHtml} } }"

def gem(cfg, known=()):
    """cfg: slug (retool, groq). Whole board in one call; kept when any location is USA or remote."""
    h = {**CHROME, "Origin": "https://jobs.gem.com", "Referer": f"https://jobs.gem.com/{cfg['slug']}"}
    d = get(_GEM, {"operationName": "JobBoardList", "variables": {"boardId": cfg["slug"]}, "query": _GEM_LIST}, headers=h)
    items = [p for p in (d.get("data", {}).get("oatsExternalJobPostings") or {}).get("jobPostings", [])
             if _us_posting(p.get("locations") or [])]
    def one(p):
        det = get(_GEM, {"operationName": "D", "variables": {"boardId": cfg["slug"], "extId": p["extId"]}, "query": _GEM_ONE}, headers=h)["data"]["oatsExternalJobPosting"]
        sec = det.get("jobPostSectionHtml") or {}
        return row(cfg, "gem", p["extId"], det.get("title") or p["title"], ", ".join(l.get("name") or "" for l in det.get("locations") or p.get("locations") or []),
                   ((det.get("job") or {}).get("department") or {}).get("name"), _iso(det.get("firstPublishedTsSec")), f"https://jobs.gem.com/{cfg['slug']}/{p['extId']}",
                   strip((sec.get("introHtml") or "") + (det.get("descriptionHtml") or "") + (sec.get("outroHtml") or "")))
    return detail_map(cfg, known, items, lambda p: p["extId"], one, workers=4)

FETCHERS = {"eightfold": eightfold, "eightfold_pcsx": eightfold_pcsx, "phenom": phenom, "gem": gem}
US_FILTERED = {"eightfold", "phenom", "gem"}
