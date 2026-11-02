"""Career sites whose job search runs on Coveo (SLB: careers.slb.com/job-listing). See adapters/__init__.py for the contract.

cfg: page (the site's job search page; its hidden organizationId and accessToken inputs carry the Coveo org and the public search token
the page itself searches with, read fresh on every run), aq (Coveo advanced query, e.g. '@country==("United States","USA")' for SLB,
which tags US postings both ways), optional search_hub / pipeline (default: the page's searchHub input and the pipeline attribute of
its atomic-search-interface), optional fields (field names when they differ from SLB's: title, country, city, category, posted,
description). The search API returns 100 postings a page with the full description, so there is no detail call.
fetch.py applies is_us to "City, Country".
"""
import re, sys, urllib.parse
from datetime import datetime, timezone
import ats

CHROME = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"}
FIELDS = {"title": "title", "country": "country", "city": "city", "category": "category", "posted": "jobposteddate", "description": "description"}

def _text(v):
    """Coveo field value (str, list or None) -> str."""
    return ", ".join(map(str, v)) if isinstance(v, list) else str(v or "")

def coveo(cfg, known=()):
    page = ats.get_text(cfg["page"], headers={**CHROME, "Accept": "text/html"})
    hidden = lambda name: (re.search(rf'id="{name}"\s+value="([^"]*)"', page) or [None, ""])[1]
    org, token = cfg.get("org") or hidden("organizationId"), hidden("accessToken")
    if not (org and token):
        raise RuntimeError(f"{cfg['company']}: no Coveo organizationId/accessToken on {cfg['page']}")
    pipeline = cfg.get("pipeline") or (re.search(r'<atomic-search-interface[^>]*\bpipeline="([^"]*)"', page) or [None, ""])[1]
    f = {**FIELDS, **cfg.get("fields", {})}
    hdr = {**CHROME, "Authorization": f"Bearer {token}", "Accept": "application/json"}
    out, seen, first = [], set(), 0
    while True:
        d = ats.get(f"https://{org}.org.coveo.com/rest/search/v2?organizationId={org}",
                    {"q": "", "aq": cfg.get("aq", ""), "searchHub": cfg.get("search_hub") or hidden("searchHub"), "pipeline": pipeline,
                     "numberOfResults": 100, "firstResult": first, "sortCriteria": "date descending", "fieldsToInclude": list(f.values())}, headers=hdr)
        res = d.get("results") or []
        for r in res:
            raw, url = r.get("raw") or {}, (r.get("clickUri") or "").replace(" ", "%20")  # SLB: "...?id=EF20238-en_US 1"
            jid = (urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("id") or [raw.get("permanentid") or ""])[0].split(" ")[0]
            desc = ats.strip(re.sub(r"<!\[CDATA\[|\]\]>", "", _text(raw.get(f["description"]))))
            if not jid or jid in seen:
                continue
            seen.add(jid)
            if not desc:  # SLB's evergreen "Early Careers" pool postings carry no text
                print(f"{cfg['company']}: skipped {jid} (no description)", file=sys.stderr); continue
            ts = raw.get(f["posted"]) or raw.get("date")
            posted = datetime.fromtimestamp(int(ts) / 1000, timezone.utc).date().isoformat() if str(ts or "").isdigit() else ""
            loc = ", ".join(filter(None, [_text(raw.get(f["city"])), _text(raw.get(f["country"]))]))
            out.append(ats.row(cfg, "coveo", jid, _text(raw.get(f["title"])) or r.get("title"), loc, _text(raw.get(f["category"])), posted, url, desc))
        first += len(res)
        if not res or first >= d.get("totalCount", 0):
            if len(seen) < d.get("totalCount", 0):  # SLB stamps every result with one index date, so this sort is not a strict order
                print(f"{cfg['company']}: Coveo listed {len(seen)} distinct of {d.get('totalCount')}", file=sys.stderr)
            return out

FETCHERS = {"coveo": coveo}
