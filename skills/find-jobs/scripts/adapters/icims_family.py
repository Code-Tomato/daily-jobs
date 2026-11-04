"""iCIMS-backed boards: Jibe front-ends (careers.amd.com/api/jobs), Radancy front-ends (careers.arm.com) and classic iCIMS portals."""
import json, re, sys, urllib.parse
from datetime import date, datetime
from ats import get, get_text, strip, row, detail_map

CHROME = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
          "Accept": "text/html,application/xhtml+xml"}

def _ld(html):
    """First JSON-LD JobPosting block in an HTML page, or None."""
    for b in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try:
            d = json.loads(b)
        except ValueError:
            continue
        for x in d if isinstance(d, list) else [d]:
            if isinstance(x, dict) and x.get("@type") == "JobPosting":
                return x
    return None

def _ld_loc(ld):
    locs = ld.get("jobLocation") or {}
    a = ((locs[0] if locs else {}) if isinstance(locs, list) else locs).get("address") or {}
    return ", ".join(filter(None, [a.get("addressLocality"), a.get("addressRegion")])) or a.get("addressCountry") or ""

def _iso(d):  # Radancy emits "2026-6-22"
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", d or "")
    return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}" if m else ""

def jibe(cfg, known=()):
    """cfg: host (careers.amd.com), country ("United States"). Everything is inline; no detail call."""
    out, page = [], 1
    while True:
        d = get(f"https://{cfg['host']}/api/jobs?page={page}&limit=100&country={urllib.parse.quote(cfg['country'])}")  # limit > 100 -> 422
        jobs = [j["data"] for j in d.get("jobs", [])]
        for j in jobs:
            loc = f"{j['city']}, {j['state']}" if j.get("city") and j.get("state") else j.get("full_location") or j.get("location_name")
            out.append(row(cfg, "jibe", j["req_id"], j["title"], loc, ", ".join(c["name"] for c in j.get("categories") or []), j.get("posted_date"),
                           f"https://{cfg['host']}/careers-home/jobs/{j['req_id']}",  # public posting page; apply_url is the iCIMS login
                           strip((j.get("description") or "") + "\n" + (j.get("responsibilities") or "")), strip(j.get("qualifications"))))
        page += 1
        if len(jobs) < 100 or len(out) >= d.get("totalCount", 0):
            return out

def radancy(cfg, known=()):
    """cfg: host (careers.arm.com), facet {"ID", "FacetType", "Display"} = the board's country facet (Arm US: 6252001 / 2 / United States)."""
    f, hdr = cfg["facet"], {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
    base = (f"https://{cfg['host']}/search-jobs/results?ActiveFacetID=0&Distance=50&RadiusUnitType=0&Keywords=&Location=&ShowRadius=False&IsPagination=False&FacetType=0"
            f"&FacetFilters%5B0%5D.ID={f['ID']}&FacetFilters%5B0%5D.FacetType={f['FacetType']}&FacetFilters%5B0%5D.Count=1&FacetFilters%5B0%5D.Display={urllib.parse.quote(f['Display'])}"
            "&FacetFilters%5B0%5D.IsApplied=true&FacetFilters%5B0%5D.FieldName=&SearchResultsModuleName=Search+Results&SearchFiltersModuleName=Search+Filters"
            "&SortCriteria=0&SortDirection=0&SearchType=5&PostalCode=&ResultsType=0&fc=&fl=&fcf=&afc=&afl=&afcf=")
    links_of = lambda n, per: set(re.findall(r'href="(/job/[^"]+)"', get(f"{base}&CurrentPage={n}&RecordsPerPage={per}", headers=hdr)["results"]))
    links, n, per = set(), 1, 100
    while True:
        new = links_of(n, per) - links
        if n == 1 and per == 100 and len(new) <= 15:  # host ignored RecordsPerPage=100: page at its default of 15
            per = 15; new = links_of(1, per) - links
        if not new:
            break
        links |= new; n += 1
    jid = lambda l: l.rstrip("/").rsplit("/", 1)[-1]
    def one(link):
        url = f"https://{cfg['host']}{link}"; ld = _ld(get_text(url, headers=CHROME))
        if not ld:
            print(f"radancy: no JSON-LD JobPosting on {url}", file=sys.stderr); return None
        return row(cfg, "radancy", jid(link), ld.get("title"), _ld_loc(ld), "", _iso(ld.get("datePosted")), url, strip(ld.get("description")))
    return detail_map(cfg, known, sorted(links), jid, one, workers=4)

def _real_date(posted):
    """Some iCIMS portals stamp every posting's JSON-LD datePosted as the day it is fetched minus two years (Celanese,
    Joby, MaxLinear: 2024-11-04 on 2026-11-04). That date says nothing; keep it only when it isn't one of those."""
    try:
        d = datetime.fromisoformat(str(posted)[:10]).date()
    except ValueError:
        return posted
    today = date.today()
    fake = today.replace(year=today.year - 2) if not (today.month == 2 and today.day == 29) else today.replace(year=today.year - 2, day=28)
    return "" if abs((d - fake).days) <= 3 else posted


def icims(cfg, known=()):
    """cfg: host (careers-<co>.icims.com). Classic iCIMS portal HTML; list pages pr= are 0-based. fetch.py applies is_us."""
    h, paths, n = cfg["host"], {}, 0
    while True:
        html = get_text(f"https://{h}/jobs/search?ss=1&in_iframe=1&pr={n}", headers=CHROME)
        new = {i: p for i, p in re.findall(r'/jobs/(\d+)/([^"\'?]+/job)\b', html) if i not in paths}
        if not new:
            if not paths and "window.top.location.href" in html and "icims_stripIFrameParameter" not in html:
                raise RuntimeError(f"{h}: portal only serves a redirect stub (window.top.location) — use the company's Jibe/Radancy front-end instead")
            break
        paths.update(new); n += 1
    def one(jid):
        url = f"https://{h}/jobs/{jid}/{paths[jid]}"; html = get_text(url + "?in_iframe=1", headers=CHROME); ld = _ld(html)
        if ld:
            return row(cfg, "icims", jid, ld.get("title"), _ld_loc(ld), ld.get("occupationalCategory"), _real_date(ld.get("datePosted")), url, strip(ld.get("description")))
        title = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S); loc = re.search(r"Job Locations</span>\s*<span[^>]*>\s*([^<]+)", html)
        posted = re.search(r"Posted Date</dt>\s*<dd[^>]*>\s*<span[^>]*>\s*([^<]+)", html); body = re.search(r'<div class="iCIMS_MainWrapper[^"]*">(.*)', html, re.S)
        return row(cfg, "icims", jid, strip(title[1]) if title else "", loc[1].strip() if loc else "", "", posted[1].strip() if posted else "", url,
                   strip(body[1] if body else html))
    return detail_map(cfg, known, sorted(paths), lambda i: i, one, workers=4)

FETCHERS = {"jibe": jibe, "radancy": radancy, "icims": icims}
US_FILTERED = {"jibe", "radancy"}
