"""ByteDance-family careers sites: TikTok (lifeattiktok.com/search) and ByteDance (joinbytedance.com/search). See adapters/__init__.py for the contract.

cfg: site ("tiktok" or "bytedance"). Both sites' own search pages call one public "supplier" JSON API with plain headers (Origin and
website-path; no signature, cookie or login). Each run reads the site's city filter list (config/job/filters) and searches with every
city whose country is the United States (country code CN_6), 100 postings a page. Every posting carries its full description and
requirements, so there is no detail call; requirements are split at "Preferred Qualifications" into basic and preferred. The API gives
no posting date. TikTok and ByteDance are separate boards (no shared ids), so each is its own config.
"""
import re, sys, time
import ats

CHROME = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"}
SITES = {  # api base, site origin, website-path header the site sends
    "tiktok": ("https://api.lifeattiktok.com/api/v1/public/supplier", "https://lifeattiktok.com", "tiktok"),
    "bytedance": ("https://jobs.bytedance.com/api/v1/public/supplier", "https://joinbytedance.com", "en"),
}
US = "CN_6"  # the API's location code for the United States of America
PAGE = 100

def _chain(c):
    """city_info / city_list entry -> [city, state, country] records, innermost first."""
    out = []
    while c:
        out.append(c)
        c = c.get("parent")
    return out

def _name(x):
    return (x or {}).get("en_name") or (x or {}).get("i18n_name") or (x or {}).get("name") or ""

def split_requirements(text):
    """"Minimum Qualifications: ... Preferred Qualifications: ..." -> (basic, preferred). Without a preferred heading it is all basic."""
    m = re.search(r"^\W*(?:preferred|nice[- ]to[- ]have|bonus)\b[^\n]*", text or "", re.I | re.M)
    if not m:
        return (text or "").strip(), ""
    return text[:m.start()].strip(), text[m.start():].strip()

def _check(d, what):
    if not isinstance(d, dict) or d.get("code") != 0 or not isinstance(d.get("data"), dict):
        raise RuntimeError(f"{what}: {str(d)[:200]}")
    return d["data"]

def bytedance(cfg, known=()):
    api, origin, path = SITES[cfg["site"]]
    hdr = {**CHROME, "Accept": "application/json", "Origin": origin, "Referer": origin + "/", "website-path": path, "accept-language": "en-US"}
    filters = _check(ats.get(f"{api}/config/job/filters", {}, headers=hdr), f"{cfg['company']}: job filters")
    cities = [c["code"] for c in filters.get("city_list") or [] if _chain(c)[-1].get("code") == US]
    if not cities:
        raise RuntimeError(f"{cfg['company']}: no United States cities in the {cfg['site']} filter list")
    out, seen, offset = [], set(), 0
    while True:
        d = _check(ats.get(f"{api}/search/job/posts", {"recruitment_id_list": [], "job_category_id_list": [], "subject_id_list": [],
                                                         "location_code_list": cities, "tag_id_list": [], "keyword": "", "limit": PAGE,
                                                         "offset": offset}, headers=hdr), f"{cfg['company']}: job search")
        posts = d.get("job_post_list") or []
        for p in posts:
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            place = _chain(p.get("city_info"))
            if place and place[-1].get("code") != US:  # the city filter already did this; a stray foreign posting is dropped, not trusted
                continue
            cat = p.get("job_category") or {}
            category = " / ".join(filter(None, [_name(cat.get("parent")), _name(cat), _name(p.get("recruit_type")), _name(p.get("job_subject"))]))
            basic, preferred = split_requirements(p.get("requirement"))
            out.append(ats.row(cfg, "bytedance", p["id"], (p.get("title") or "").strip(), ", ".join(filter(None, map(_name, place))), category, "",
                               f"{origin}/search/{p['id']}", (p.get("description") or "").strip(), basic, preferred))
        offset += len(posts)
        if not posts or offset >= d.get("count", 0):
            if len(seen) < d.get("count", 0):
                print(f"{cfg['company']}: listed {len(seen)} distinct of {d.get('count')}", file=sys.stderr)
            return out
        time.sleep(0.5)

FETCHERS = {"bytedance": bytedance}
US_FILTERED = {"bytedance"}
