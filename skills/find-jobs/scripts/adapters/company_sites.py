"""Companies with their own careers front-end: Goldman Sachs (higher.gs.com) and Southwest Research Institute (resapp.swri.org).
See adapters/__init__.py for the contract."""
import json, re, sys, urllib.error
from html import unescape
import ats

CHROME = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"}
HTML = {**CHROME, "Accept": "text/html"}

GS_API = "https://api-higher.gs.com/gateway/api/v1/graphql"
GS_ROLES = "https://higher.gs.com/roles/"
_GS_SEARCH = ("query GetRoles($searchQueryInput: RoleSearchQueryInput!) { roleSearch(searchQueryInput: $searchQueryInput) { totalCount items {"
              " roleId jobTitle jobFunction division locations { primary state country city } externalSource { sourceId } } } }")

def _gs_loc(locs):
    return "; ".join(", ".join(filter(None, [l.get("city"), l.get("state"), l.get("country")])) for l in locs or [])

def goldman(cfg, known=()):
    """cfg: optional experiences (default [["CAMPUS"], ["EARLY_CAREER", "PROFESSIONAL"]]: the campus programs such as Possibilities
    and Summer Analyst, then lateral roles; each group is searched separately, as higher.gs.com's /campus and /results pages do).
    The list comes from the site's own roleSearch GraphQL (250 per page, no text); a role is kept when any location is in the United
    States. Each kept role's text is read from its higher.gs.com/roles/<id> page (the only path its robots.txt opens to crawlers),
    whose __NEXT_DATA__ carries the role with descriptionHtml. Roles are keyed by the Oracle requisition id (externalSource.sourceId),
    which is also the page id."""
    hdr = {**CHROME, "Accept": "application/json", "Origin": "https://higher.gs.com", "Referer": "https://higher.gs.com/results"}
    items = {}
    for exps in cfg.get("experiences") or [["CAMPUS"], ["EARLY_CAREER", "PROFESSIONAL"]]:
        page, total = 0, None
        while True:
            q = {"page": {"pageSize": 250, "pageNumber": page}, "sort": {"sortStrategy": "POSTED_DATE", "sortOrder": "DESC"},
                 "filters": [], "experiences": exps, "searchTerm": ""}
            d = ats.get(GS_API, {"operationName": "GetRoles", "variables": {"searchQueryInput": q}, "query": _GS_SEARCH}, headers=hdr)
            if not d.get("data"):
                raise RuntimeError(f"{cfg['company']}: roleSearch failed: {str(d.get('errors'))[:200]}")
            rs = d["data"]["roleSearch"]
            total = rs.get("totalCount", 0) if total is None else total
            for r in rs.get("items") or []:
                sid = (r.get("externalSource") or {}).get("sourceId") or r["roleId"].split("_", 1)[0]
                if any(l.get("country") == "United States" for l in r.get("locations") or []):
                    items.setdefault(sid, r)
            page += 1
            if not rs.get("items") or page * 250 >= total:
                break
    def one(item):
        sid, r = item
        try:
            h = ats.get_text(GS_ROLES + sid, headers=HTML)
        except urllib.error.HTTPError as e:
            if e.code not in (404, 410):
                raise
            print(f"{cfg['company']}: removed role {sid} ({e.code})", file=sys.stderr); return None
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
        role = (json.loads(m[1]).get("props", {}).get("pageProps", {}).get("role") if m else None) or {}
        if not role.get("descriptionHtml"):  # closed since the search, or a page without the role
            print(f"{cfg['company']}: no role text for {sid}", file=sys.stderr); return None
        return ats.row(cfg, "goldman", sid, role.get("jobTitle") or r.get("jobTitle"), _gs_loc(role.get("locations") or r.get("locations")),
                       role.get("jobFunction") or r.get("jobFunction") or role.get("division") or r.get("division"), "", GS_ROLES + sid,
                       ats.strip(role["descriptionHtml"]))
    return ats.detail_map(cfg, known, sorted(items.items()), lambda i: i[0], one, workers=3)

SWRI = "https://resapp.swri.org/ResApp"
# each result link carries the posting's fields as attributes: JOB_CD="03-01579" JOB_TITLE="..." WORK_LOCATION="San Antonio, Texas" DIV_TITLE="..."
_SWRI_LINK = re.compile(r'<a href="[^"]*Job_Details\.aspx\?JOB_CD=([\w-]+)[^"]*"((?:\s+\w+="[^"]*")*)\s*>')

def swri(cfg, known=()):
    """cfg: none beyond company. SwRI's own job search: one results page per tab (Salaried, Hourly, Student = internships), every
    location and category. Each Job_Details page has the text in its divJobDescription2 block (requirements in
    divSkillsAndQualifications, ITAR/clearance notes in jMISC); its JSON-LD is malformed (missing commas), so only datePosted is read
    from it. Every SwRI site is in the US; fetch.py's is_us still applies."""
    items = {}
    for tab in ("Salaried", "Hourly", "Student"):
        h = ats.get_text(f"{SWRI}/Job_Search_Results.aspx?EMPLOYMENT_STATUS={tab}&WORK_LOCATION=All+Locations&JOB_CATEGORY=All+Categories", headers=HTML)
        for code, attrs in _SWRI_LINK.findall(h):
            items.setdefault(code, {k: unescape(v) for k, v in re.findall(r'(\w+)="([^"]*)"', attrs)})
    if not items:
        raise RuntimeError(f"{cfg['company']}: no Job_Details links on the SwRI results pages")
    def one(item):
        code, a = item
        url = f"{SWRI}/Job_Details.aspx?JOB_CD={code}"
        d = ats.get_text(url, headers=HTML)
        body = re.search(r'id="divJobDescription2"[^>]*>(.*?)(?=<h5 id="CONSIDERATIONS"|<h5 id="jLOC"|<input type="submit")', d, re.S)
        if not body:  # closed postings come back as the search page
            print(f"{cfg['company']}: no description for {code}", file=sys.stderr); return None
        quals, misc = re.search(r'<ul id="divSkillsAndQualifications">(.*?)</ul>', d, re.S), re.search(r'<p id="jMISC">(.*?)</p>', d, re.S)
        posted = re.search(r'"datePosted"\s*:\s*"(\d{4}-\d\d-\d\d)', d)
        return ats.row(cfg, "swri", code, re.sub(r"\s+", " ", ats.strip(a.get("JOB_TITLE"))), a.get("WORK_LOCATION"), ats.strip(a.get("DIV_TITLE")),
                       posted[1] if posted else "", url, "\n".join(filter(None, [ats.strip(body[1]), ats.strip(misc[1]) if misc else ""])),
                       ats.strip(quals[1]) if quals else "")
    return ats.detail_map(cfg, known, sorted(items.items()), lambda i: i[0], one, workers=3)

FETCHERS = {"goldman": goldman, "swri": swri}
US_FILTERED = {"goldman"}
