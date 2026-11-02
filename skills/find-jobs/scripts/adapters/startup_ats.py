"""Small-company ATSs with public JSON/RSS: Comeet, BambooHR, Recruitee, Teamtailor, Breezy, Pinpoint. See adapters/__init__.py for the contract."""
import re, sys, urllib.error
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import ats
from adapters.jsonld import posting, location as ld_location, posted as ld_posted

CHROME = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"}
HTML = {**CHROME, "Accept": "text/html"}
US_NAMES = {"US", "USA", "United States", "United States of America"}

def comeet(cfg, known=()):
    """cfg: slug + uid from the hosted board URL comeet.com/jobs/<slug>/<uid> (VAST Data: vastdata / 43.001), optional token.
    Without token it is read from the hosted page's COMPANY_DATA. One call (details=true) returns every position with its full text.
    The location record carries a country code; non-US positions are dropped here unless they are remote with no country."""
    token = cfg.get("token")
    if not token:
        h = ats.get_text(f"https://www.comeet.com/jobs/{cfg['slug']}/{cfg['uid']}", headers=HTML)
        m = re.search(r'COMPANY_DATA\s*=\s*\{.*?"token"\s*:\s*"([0-9A-Fa-f]+)"', h, re.S)
        if not m:
            raise RuntimeError(f"{cfg['company']}: no Comeet token on comeet.com/jobs/{cfg['slug']}/{cfg['uid']}")
        token = m[1]
    out = []
    for p in ats.get(f"https://www.comeet.co/careers-api/2.0/company/{cfg['uid']}/positions?token={token}&details=true", headers=CHROME):
        l = p.get("location") or {}
        if l.get("country") not in ("US", None, "") or (not l.get("country") and not ats.is_us(l.get("name"))):
            continue
        loc = l.get("name") or ", ".join(filter(None, [l.get("city"), l.get("state"), l.get("country")]))
        if l.get("is_remote") and "remote" not in loc.lower():
            loc += " (Remote)"
        desc = "\n".join(f"{d.get('name')}\n{ats.strip(d.get('value'))}" for d in p.get("details") or [] if d.get("value"))
        out.append(ats.row(cfg, "comeet", p["uid"], p.get("name"), loc, p.get("department"), p.get("time_updated"),
                           p.get("url_active_page") or p.get("url_comeet_hosted_page"), desc))
    return out

def bamboohr(cfg, known=()):
    """cfg: slug (<slug>.bamboohr.com; PRC-Saltillo is prentkeromich). List JSON has no text; one detail call per opening.
    Location is location {city, state} or, on newer boards, atsLocation {city, state, country}. US filtered on the list (country when
    given, else is_us on "city, state") so foreign openings cost no detail call, and so a "(Remote)" suffix never decides it."""
    base = f"https://{cfg['slug']}.bamboohr.com/careers"
    def us(j):
        a, b = j.get("location") or {}, j.get("atsLocation") or {}
        return b["country"] in US_NAMES if b.get("country") else ats.is_us(", ".join(filter(None, [a.get("city"), a.get("state")])))
    def one(j):
        try:
            d = ats.get(f"{base}/{j['id']}/detail", headers=CHROME)["result"]["jobOpening"]
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            print(f"{cfg['company']}: removed posting {j['id']} (404)", file=sys.stderr); return None
        a, b = d.get("location") or {}, d.get("atsLocation") or j.get("atsLocation") or {}
        loc = ", ".join(filter(None, [a.get("city"), a.get("state"), a.get("addressCountry")])) or ", ".join(filter(None, [b.get("city"), b.get("state") or b.get("province"), b.get("country")]))
        if d.get("locationType") == "1" or j.get("isRemote"):
            loc = f"{loc} (Remote)" if loc else "Remote"
        return ats.row(cfg, "bamboohr", j["id"], d.get("jobOpeningName") or j.get("jobOpeningName"), loc, d.get("departmentLabel"), d.get("datePosted"),
                       d.get("jobOpeningShareUrl") or f"{base}/{j['id']}", ats.strip(d.get("description")))
    items = [j for j in ats.get(f"{base}/list", headers=CHROME).get("result") or [] if us(j)]
    return ats.detail_map(cfg, known, items, lambda j: j["id"], one, workers=4)

def recruitee(cfg, known=()):
    """cfg: slug (<slug>.recruitee.com). Whole board with full text in one call; non-US offers dropped by country_code (remote kept)."""
    out = []
    for o in ats.get(f"https://{cfg['slug']}.recruitee.com/api/offers/", headers=CHROME).get("offers", []):
        locs = o.get("locations") or []
        codes = {o.get("country_code")} | {l.get("country_code") for l in locs}
        if "US" not in codes and not (o.get("remote") and not codes - {None, ""}):
            continue
        loc = "; ".join(filter(None, (", ".join(filter(None, [l.get("city"), l.get("state_code") or l.get("state"), l.get("country_code")])) for l in locs))) or o.get("location")
        out.append(ats.row(cfg, "recruitee", o["id"], o.get("title"), f"{loc} (Remote)" if o.get("remote") and "remote" not in (loc or "").lower() else loc, o.get("department"),
                           o.get("published_at") or o.get("created_at"), o.get("careers_url"), ats.strip(o.get("description")), ats.strip(o.get("requirements"))))
    return out

TT = "{https://teamtailor.com/locations}"

def teamtailor(cfg, known=()):
    """cfg: feed (the board's jobs.rss URL: https://<slug>.teamtailor.com/jobs.rss, or the custom careers domain + /jobs.rss).
    Full HTML description per item. Kept when a location's country is the US or the item has no location (remoteStatus
    none / onsite / hybrid / fully); filtered here because is_us would keep "Tallinn, Estonia (Remote)"."""
    xml = ats.get_text(cfg["feed"], headers={**CHROME, "Accept": "application/rss+xml, application/xml"})
    if "<rss" not in xml[:500]:
        raise RuntimeError(f"{cfg['company']}: {cfg['feed']} is not an RSS feed")
    out = []
    for it in ET.fromstring(xml).iter("item"):
        places = [((l.findtext(TT + "city") or "").strip(), (l.findtext(TT + "country") or "").strip()) for l in it.iter(TT + "location")]
        if places and not any(c in US_NAMES for _, c in places):
            continue
        loc = "; ".join(filter(None, (", ".join(filter(None, p)) for p in places)))
        if not loc and it.findtext("remoteStatus") == "fully":
            loc = "Remote"
        pub, link = it.findtext("pubDate"), (it.findtext("link") or "").strip()
        jid = re.search(r"/jobs/(\d+)", link)  # numeric id in the link; the guid is a UUID
        out.append(ats.row(cfg, "teamtailor", jid[1] if jid else it.findtext("guid"), it.findtext("title"), loc, it.findtext(TT + "department"),
                           parsedate_to_datetime(pub).date().isoformat() if pub else "", link, ats.strip(it.findtext("description"))))
    return out

def breezy(cfg, known=()):
    """cfg: slug (<slug>.breezy.hr). /json lists postings without text; each /p/<id> page carries a JSON-LD JobPosting.
    Kept when any of its locations is in the US, or has no country (remote "within chosen location(s)" is country-scoped,
    so a remote Germany posting is dropped); filtered before the detail call."""
    def us(p):
        locs = [l for l in [p.get("location"), *(p.get("locations") or [])] if l]
        return not locs or any((l.get("country") or {}).get("id") in ("US", None) for l in locs)
    items = [p for p in ats.get(f"https://{cfg['slug']}.breezy.hr/json", headers=CHROME) if us(p)]
    def one(p):
        try:
            ld = posting(ats.get_text(p["url"], headers=HTML)) or {}
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            print(f"{cfg['company']}: removed posting {p['id']} (404)", file=sys.stderr); return None
        loc = (p.get("location") or {}).get("name") or ld_location(ld)
        return ats.row(cfg, "breezy", p["id"], p.get("name"), loc, p.get("department"), ld_posted(ld) or p.get("published_date"), p["url"],
                       ats.strip(ld.get("description")))
    return ats.detail_map(cfg, known, items, lambda p: p["id"], one, workers=4)

def pinpoint(cfg, known=()):
    """cfg: slug (<slug>.pinpointhq.com; Impulse Space is impulsespace). /postings.json returns every posting with its text in one call,
    split into sections with board-chosen headers ("Responsibilities", "Minimum Qualifications", "Preferred Skills and Experience" in the
    benefits slot). Basic/preferred are picked by header as for Lever. No posted date in the feed (the JSON-LD on each page has it; not
    worth a call per posting). Location has city/province but no country, so fetch.py's is_us decides."""
    out = []
    for j in ats.get(f"https://{cfg['slug']}.pinpointhq.com/postings.json", headers=CHROME).get("data", []):
        secs = [(j.get(f"{k}_header") or "", ats.strip(j.get(k))) for k in ("key_responsibilities", "skills_knowledge_expertise", "benefits") if j.get(k)]
        basic = "\n".join(t for h, t in secs if re.search(r"qualif|require|you have|looking for|skills", h, re.I) and not re.search(r"bonus|nice|preferred", h, re.I))
        pref = "\n".join(t for h, t in secs if re.search(r"bonus|nice|preferred", h, re.I))
        l = j.get("location") or {}
        loc = ", ".join(filter(None, [(l.get("city") or "").strip(), (l.get("province") or "").strip()])) or (l.get("name") or "").strip()
        if j.get("workplace_type") == "remote":
            loc = f"{loc} (Remote)" if loc else "Remote"
        out.append(ats.row(cfg, "pinpoint", j["id"], j.get("title"), loc, ((j.get("job") or {}).get("department") or {}).get("name"), "", j.get("url"),
                           "\n".join(filter(None, [ats.strip(j.get("description")), *(f"{h}\n{t}" for h, t in secs)])), basic, pref))
    return out

FETCHERS = {"comeet": comeet, "bamboohr": bamboohr, "recruitee": recruitee, "teamtailor": teamtailor, "breezy": breezy, "pinpoint": pinpoint}
US_FILTERED = {"comeet", "bamboohr", "recruitee", "teamtailor", "breezy"}
