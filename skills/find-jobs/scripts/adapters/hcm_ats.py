"""Payroll/HCM-suite recruiting boards: Paylocity, UKG (UltiPro) and Dayforce. See adapters/__init__.py for the contract.
All three give a country per location, so each filters to the US at the source (a posting is kept when any location is US or it
has no location at all)."""
import http.cookiejar, json, re, sys, urllib.error, urllib.request
import ats
from adapters.jsonld import posting

CHROME = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"}
HTML = {**CHROME, "Accept": "text/html"}

def _js_object(html, marker):
    """The JSON literal right after `marker` in a page (window.pageData = {...}, CandidateOpportunityDetail({...}))."""
    m = re.search(marker, html)
    if not m:
        return None
    return json.JSONDecoder().raw_decode(html[m.end():])[0]

PAYLOCITY = "https://recruiting.paylocity.com/Recruiting/Jobs"

def paylocity(cfg, known=()):
    """cfg: guid (company id in recruiting.paylocity.com/Recruiting/Jobs/All/<guid>/<Name>, linked from the company's careers page).
    The list page inlines window.pageData.Jobs (title, location, date, truncated text); each Details/<id> page carries a JSON-LD
    JobPosting with the full description. The public feed endpoint (/recruiting/v2/api/feed/jobs/<guid>) is empty unless enabled."""
    d = _js_object(ats.get_text(f"{PAYLOCITY}/All/{cfg['guid']}", headers=HTML), r"window\.pageData\s*=\s*")
    if d is None:
        raise RuntimeError(f"{cfg['company']}: no window.pageData on the Paylocity list page (wrong guid?)")
    us = lambda j: (j.get("JobLocation") or {}).get("Country") in ("USA", "US", "United States", None, "")
    def one(j):
        try:
            ld = posting(ats.get_text(f"{PAYLOCITY}/Details/{j['JobId']}", headers=HTML))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            print(f"{cfg['company']}: removed posting {j['JobId']} (404)", file=sys.stderr); return None
        if not ld:  # closed jobs redirect to a JobNotFound page
            print(f"{cfg['company']}: no JSON-LD for Paylocity job {j['JobId']}", file=sys.stderr); return None
        l = j.get("JobLocation") or {}
        loc = ", ".join(filter(None, [l.get("City"), l.get("State")])) or j.get("LocationName") or ""
        if j.get("IsRemote"):
            loc = f"{loc} (Remote)" if loc else "Remote"
        return ats.row(cfg, "paylocity", j["JobId"], j.get("JobTitle"), loc, j.get("HiringDepartment"), j.get("PublishedDate"),
                       f"{PAYLOCITY}/Details/{j['JobId']}", ats.strip(ld.get("description")))
    return ats.detail_map(cfg, known, [j for j in d.get("Jobs") or [] if us(j) and not j.get("IsInternal")], lambda j: j["JobId"], one, workers=4)

def _ukg_loc(l):
    a = l.get("Address") or {}
    return ", ".join(filter(None, [a.get("City") or l.get("LocalizedName"), (a.get("State") or {}).get("Code"), (a.get("Country") or {}).get("Code")]))

def ukg(cfg, known=()):
    """cfg: board (https://recruiting<N>.ultipro.com/<TENANT>/JobBoard/<board guid>). LoadSearchResults pages 50 at a time; each
    OpportunityDetail page inlines the posting as CandidateOpportunityDetail({...}) with the full Description."""
    board = cfg["board"].rstrip("/")
    items, skip, total = [], 0, None
    while True:
        d = ats.get(f"{board}/JobBoardView/LoadSearchResults", {"opportunitySearch": {"Top": 50, "Skip": skip, "QueryString": "", "OrderBy": [
            {"Value": "postedDateDesc", "PropertyName": "PostedDate", "Ascending": False}], "Filters": []},
            "matchCriteria": {"PreferredJobs": [], "Educations": [], "LicenseAndCertifications": [], "Skills": [], "hasNoLicenses": False, "SkippedSkills": []}},
            headers=CHROME)
        total = d.get("totalCount", 0) if total is None else total
        items += d.get("opportunities") or []; skip += 50
        if skip >= total or not d.get("opportunities"):
            break
    us = lambda o: not o.get("Locations") or any(((l.get("Address") or {}).get("Country") or {}).get("Code") in ("USA", "US") for l in o["Locations"])
    def one(o):
        url = f"{board}/OpportunityDetail?opportunityId={o['Id']}"
        det = _js_object(ats.get_text(url, headers=HTML), r"CandidateOpportunityDetail\(")
        if not det or det.get("OpportunityIsClosed"):
            print(f"{cfg['company']}: UKG opportunity {o['Id']} closed or unreadable", file=sys.stderr); return None
        return ats.row(cfg, "ukg", o["Id"], det.get("Title") or o.get("Title"), "; ".join(_ukg_loc(l) for l in o.get("Locations") or []),
                       o.get("JobCategoryName"), o.get("PostedDate"), url, ats.strip(det.get("Description")))
    return ats.detail_map(cfg, known, [o for o in items if us(o)], lambda o: o["Id"], one, workers=3)

DAYFORCE = "https://jobs.dayforcehcm.com"

def dayforce(cfg, known=()):
    """cfg: namespace + board from jobs.dayforcehcm.com/<lang>/<namespace>/<board> (PROtect: protectllc / candidateportal), optional
    lang (en-US). The search API wants the anonymous next-auth CSRF token (GET /api/auth/csrf, cookie + X-CSRF-TOKEN header);
    it returns 25 postings per page with the full description inline, so there is no detail call."""
    ns, board, lang = cfg["namespace"], cfg["board"], cfg.get("lang", "en-US")
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    hdr = {**CHROME, "Origin": DAYFORCE, "Referer": f"{DAYFORCE}/{lang}/{ns}/{board}",
           "X-CSRF-TOKEN": ats.get(f"{DAYFORCE}/api/auth/csrf", headers=CHROME, opener=opener)["csrfToken"]}
    out, start = [], 0
    while True:
        d = ats.get(f"{DAYFORCE}/api/geo/{ns}/jobposting/search", {"clientNamespace": ns, "jobBoardCode": board, "cultureCode": lang,
                                                                   "distanceUnit": 0, "paginationStart": start}, headers=hdr, opener=opener)
        posts = d.get("jobPostings") or []
        for p in posts:
            locs = p.get("postingLocations") or []
            if locs and not any(l.get("isoCountryCode") == "US" for l in locs):
                continue
            loc = "; ".join(l.get("formattedAddress") or "" for l in locs) or ("Remote" if p.get("hasVirtualLocation") else "")
            out.append(ats.row(cfg, "dayforce", p["jobPostingId"], p.get("jobTitle"), loc, "", p.get("postingStartTimestampUTC"),
                               f"{DAYFORCE}/{lang}/{ns}/{board}/jobs/{p['jobPostingId']}", ats.strip(p.get("jobDescription"))))
        start += len(posts)
        if not posts or start >= d.get("maxCount", 0):
            return out

FETCHERS = {"paylocity": paylocity, "ukg": ukg, "dayforce": dayforce}
US_FILTERED = {"paylocity", "ukg", "dayforce"}
