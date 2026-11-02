"""Oracle Taleo Enterprise career sections (<company>.taleo.net/careersection/<section>/jobsearch.ftl).

cfg: host (weyerhaeuser.taleo.net), section (10000, swd_external), optional portal (the portalNo of a newer "swd" faceted-search
section; then the list comes from the JSON /careersection/rest/jobboard/searchjobs), optional lang (default en).
Without portal the list is the classic one, paged through jobsearch.ajax (session cookie from jobsearch.ftl).
Both lists only give job numbers; every posting is read from jobdetail.ftl, whose "initialHistory" field holds the values and whose
_hlid array names them (reqlistitem.title / description / qualification / primarylocation / postingdate ...).
fetch.py applies is_us. Many Taleo hosts no longer resolve (Oracle is retiring the product); a dead section returns
"Career Section Unavailable" and raises here.
"""
import http.cookiejar, re, sys, urllib.parse, urllib.request
from datetime import datetime
import ats

FORM = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "text/html,*/*"}
_JOBNO = re.compile(r"Job Number(?:%5C|\\)?(?:%3A|:)\s*(?:%20|\+)*([A-Za-z0-9_-]+)\)")  # "(Job Number\: 01024875)" in the list data

def _history(html):
    m = re.search(r'name="initialHistory"[^>]*value="([^"]*)"', html) or re.search(r'id="initialHistory"[^>]*value="([^"]*)"', html)
    return m[1] if m else ""

def _unq(s):
    return urllib.parse.unquote(s).replace("\\:", ":").replace("\\|", "|").removeprefix("!*!")

def parse_detail(html):
    """{reqlistitem key: value} from a jobdetail.ftl page. Values follow "descRequisition"; _hlid[i] labels value i."""
    parts = _history(html).split("!|!")
    keys = re.search(r"_hlid\s*:\s*\[([^\]]*)\]", html)
    if "descRequisition" not in parts or not keys:
        return {}
    i = parts.index("descRequisition") + 1
    vals = [parts[i].split("!$!")[-1]] + parts[i + 1:]
    out = {}
    for k, v in zip(re.findall(r"'reqlistitem\.(\w+)'", keys[1]), vals):
        if v and k not in out:
            out[k] = _unq(v)
    return out

def _date(s):
    m = re.match(r"([A-Z][a-z]{2} \d{1,2}, \d{4})", (s or "").strip())
    return datetime.strptime(m[1], "%b %d, %Y").date().isoformat() if m else ""

def _rest_jobs(cfg, base, lang):
    """Job numbers from a swd section's JSON search, newest first."""
    out, page = [], 1
    hdr = {"tz": "GMT-05:00", "Referer": f"{base}/{cfg['section']}/jobsearch.ftl?lang={lang}&portal={cfg['portal']}"}
    while True:
        d = ats.get(f"{base}/rest/jobboard/searchjobs?lang={lang}&portal={cfg['portal']}", {
            "multilineEnabled": False, "sortingSelection": {"sortBySelectionParam": "3", "ascendingSortingOrder": "false"},
            "fieldData": {"fields": {"KEYWORD": "", "LOCATION": ""}, "valid": True}, "filterSelectionParam": {"searchFilterSelections": []},
            "advancedSearchFiltersSelectionParam": {"searchFilterSelections": []}, "pageNo": page}, headers=hdr)
        if d.get("careerSectionUnAvailable"):
            raise RuntimeError(f"{cfg['company']}: Taleo section {cfg['section']} (portal {cfg['portal']}) is unavailable")
        new = [r["contestNo"] for r in d.get("requisitionList") or [] if r.get("contestNo") and r["contestNo"] not in out]
        out += new
        paging = d.get("pagingData") or {}
        # pages past the end repeat the last one, and totalCount can count a posting no page shows (El Sewedy: 55 vs 54)
        if not new or page * paging.get("pageSize", 25) >= paging.get("totalCount", 0):
            return out
        page += 1

def _classic_jobs(cfg, base, lang, opener):
    """Job numbers from a classic section: jobsearch.ftl opens the session, then the jobsearch.ajax pager at 100 per page (dropListSize)
    until a page adds nothing. At the default 25 per page the order shifts between requests and pages overlap (Weyerhaeuser: 156 of 179)."""
    html = ats.get_text(f"{base}/{cfg['section']}/jobsearch.ftl?lang={lang}", headers={"Accept": "text/html"}, opener=opener)
    if "Career Section Unavailable" in html[:3000]:
        raise RuntimeError(f"{cfg['company']}: Taleo section {cfg['section']} is unavailable")
    out, page = [], 1
    while True:
        body = urllib.parse.urlencode({"ftlpageid": "reqListBasicPage", "ftlinterfaceid": "requisitionListInterface", "ftlcompid": "rlPager",
                                       "jsfCmdId": "rlPager", "ftlcompclass": "PagerComponent", "ftlcallback": "ftlPager_processResponse",
                                       "ftlajaxid": "ftlx1", "rlPager.currentPage": page, "dropListSize": 100, "lang": lang})
        new = [n for n in dict.fromkeys(_JOBNO.findall(ats.get_text(f"{base}/{cfg['section']}/jobsearch.ajax", body, headers=FORM, opener=opener)))
               if n not in out]
        if not new:
            return out
        out += new; page += 1

def taleo(cfg, known=()):
    base, lang = f"https://{cfg['host']}/careersection", cfg.get("lang", "en")
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    jobs = _rest_jobs(cfg, base, lang) if cfg.get("portal") else _classic_jobs(cfg, base, lang, opener)
    def one(no):
        url = f"{base}/{cfg['section']}/jobdetail.ftl?job={urllib.parse.quote(no)}&lang={lang}"
        f = parse_detail(ats.get_text(url, headers={"Accept": "text/html"}))
        if not f.get("title"):
            print(f"{cfg['company']}: no Taleo detail fields for {no}", file=sys.stderr); return None
        loc = "; ".join(filter(None, [f.get("primarylocation"), f.get("otherlocations")]))
        return ats.row(cfg, "taleo", no, f["title"], loc, f.get("jobfield") or f.get("jobfamily"), _date(f.get("postingdate")), url,
                       ats.strip(f.get("description")), ats.strip(f.get("qualification")))
    return ats.detail_map(cfg, known, jobs, lambda n: n, one, workers=3)

FETCHERS = {"taleo": taleo}
