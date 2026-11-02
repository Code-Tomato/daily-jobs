"""SAP SuccessFactors Recruiting Marketing (RMK / jobs2web) career sites: jobs.ornl.gov, careers.skyworksinc.com, seagatecareers.com.

cfg: host. https://<host>/sitemap.xml is one of two things, picked automatically:
- an RSS job feed (ORNL, Skyworks): every posting with its full description in one request. Rows come straight from it, filtered to
  the US by the g:location country code ("Oak Ridge, TN, US, 37830"). The feed has no posting date, so posted is "".
- a plain URL sitemap (Seagate): each /job/.../<id>/ page is fetched and read from schema.org microdata (older pages), JSON-LD, or
  the "Job Title: / Posting Start Date: / Job Description:" layout tokens (newer pages; location then comes from a "Location:"
  line in the description). Microdata pages without addressLocality/Region/Country (LyondellBasell, Woodside) are placed by their
  streetAddress / jobGeoLocation string. Optional prefilter_us: skip detail calls for job URLs whose slug names a foreign place.
Classic career<N>.successfactors.com/career?company=... portals (no RMK site) are not supported: their lists are built by JS.
"""
import re, sys, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime
from html import unescape
import ats
from adapters.jsonld import posting, location as ld_location, posted as ld_posted

G = "{http://base.google.com/ns/1.0}"
CHROME = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
          "Accept": "text/html,application/xhtml+xml,application/xml"}

def _feed_loc(loc):
    """"Oak Ridge, TN, US, 37830" -> ("Oak Ridge, TN, US", True); the 2-letter country code decides US. NRG puts "Virtual" in the
    country slot of its remote US roles ("Saginaw, MI, Virtual, 48602"); without a country code there, is_us decides."""
    parts = [p.strip() for p in (loc or "").split(",") if p.strip()]
    if parts and re.fullmatch(r"[\dA-Z -]{3,10}", parts[-1]) and re.search(r"\d", parts[-1]):
        parts = parts[:-1]  # postal code
    no_code = len(parts) >= 3 and not re.fullmatch(r"[A-Z]{2}", parts[2])
    return ", ".join(parts), "US" in parts[1:] or ((not parts[1:] or no_code) and ats.is_us(", ".join(parts)))

def parse_feed(cfg, xml):
    out = []
    for it in ET.fromstring(xml).iter("item"):
        loc, us = _feed_loc(it.findtext(G + "location"))
        if not us:
            continue
        jid = it.findtext(G + "id") or it.findtext("guid") or ""
        title = re.sub(r"\s*\([^()]*\)\s*$", "", (it.findtext("title") or "").strip())  # "Engineer (Oak Ridge, TN, US, 37830)"
        out.append(ats.row(cfg, "successfactors", jid.strip(), title, loc, it.findtext(G + "job_function"), "",
                           (it.findtext("link") or "").strip(), ats.strip(it.findtext("description"))))
    return out

def _mdate(s):
    """RMK dates: "Thu Oct 01 00:00:00 UTC 2026", "9/22/26", "Oct 1, 2026", ISO."""
    s = (s or "").strip()
    for fmt in ("%a %b %d %H:%M:%S %Z %Y", "%m/%d/%y", "%m/%d/%Y", "%b %d, %Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return s[:10] if re.match(r"\d{4}-\d\d-\d\d", s) else ""

def parse_page(html):
    """(title, location, posted, description) from one RMK job page."""
    ld = posting(html)
    if ld:
        return ats.strip(ld.get("title")), ld_location(ld), ld_posted(ld), ats.strip(ld.get("description"))
    prop = lambda p: next(iter(re.findall(rf'itemprop="{p}"[^>]*content="([^"]*)"', html)), "")
    desc = re.search(r'itemprop="description"[^>]*>(.*?)(?=<div class="applylink|<div class="jobColumnTwo|<div class="job-location|<style|<script)', html, re.S)
    t = re.search(r"<title>(.*?)(?:\s+Job Details)?\s*(?:\|[^<]*)?</title>", html, re.S)
    if desc:
        title = re.search(r'itemprop="title"[^>]*>(.*?)<', html, re.S)  # CITGO's pages have none: their <title> then
        parts = [unescape(p) for p in [prop("addressLocality"), prop("addressRegion"), prop("addressCountry")] if p]
        # LyondellBasell, Woodside: one "Rotterdam, NL, 3013 AA" / "TX, US, 77056" / "AU" instead (city, state, country code, postal code)
        street = unescape(prop("streetAddress")) or ats.strip(next(iter(re.findall(r'class="jobGeoLocation">(.*?)<', html, re.S)), ""))
        loc = ", ".join(parts) or _feed_loc(street)[0]
        if prop("addressCountry") or not parts:  # the country code ends it; lower-cased unless US, is_us reads "Vadodara, GJ, in" as India
            loc = re.sub(r"\b(?!US$)[A-Z]{2}$", lambda m: m[0].lower(), loc)
        return ats.strip(title[1]) if title else ats.strip(t[1]) if t else "", loc, _mdate(prop("datePosted")), ats.strip(desc[1])
    fields, unlabelled = {}, []
    for chunk in html.split('<div class="joblayouttoken')[1:]:
        label = re.search(r'joblayouttoken-label[^>]*>(.*?)</span>(.*)', chunk, re.S)
        body = ats.strip(re.split(r'<div class="applylink|<div class="jobColumnTwo|<style|<script', label[2] if label else chunk.split(">", 1)[-1])[0])
        if label:
            fields.setdefault(ats.strip(label[1]).rstrip(": ").lower(), body)
        elif len(body) > 200:  # APA: the description token has no label
            unlabelled.append(body)
    desc = fields.get("job description") or "\n".join(unlabelled)
    loc = next((v for k, v in fields.items() if "location" in k), "")
    # Seagate: a "Location:" heading over a campus blurb, then a short "Location: Normandale, United States" line near the end
    m = [l.strip() for l in re.findall(r"\bLocation\s*:\s*([^\n]+)", desc) if len(l.strip()) <= 80]
    return (fields.get("job title") or (ats.strip(t[1]) if t else ""), loc or (m[-1] if m else ""),
            _mdate(fields.get("posting start date") or fields.get("date posted") or ""), desc)

def successfactors(cfg, known=()):
    base = f"https://{cfg['host']}"
    body = ats.get_text(base + "/sitemap.xml", headers=CHROME)
    if re.search(r"<rss\b", body[:500]):
        return parse_feed(cfg, body)
    if not re.search(r"<urlset\b", body[:1000]):
        raise RuntimeError(f"{cfg['company']}: {base}/sitemap.xml is neither an RMK job feed nor a sitemap")
    links = {}
    for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", body):
        m = re.search(r"/job/([^/]+)/(\d+)/?$", unescape(u))
        if m and not (cfg.get("prefilter_us") and ats._FOREIGN.search(m[1].replace("-", " "))):
            links[m[2]] = unescape(u)
    def one(jid):
        try:
            title, loc, posted, desc = parse_page(ats.get_text(links[jid], headers=CHROME))
        except urllib.error.HTTPError as e:
            if e.code not in (404, 410):
                raise
            print(f"{cfg['company']}: removed posting {jid} ({e.code})", file=sys.stderr); return None
        if not desc:
            print(f"{cfg['company']}: no description on {links[jid]}", file=sys.stderr); return None
        m = re.search(r"/job/([^/-]+)[^/]*-([A-Z]{2})-\d{5}/", links[jid])  # APA's pages name no place; its slugs end "-TX-79711"
        return ats.row(cfg, "successfactors", jid, title, loc or (f"{m[1]}, {m[2]}" if m else ""), "", posted, links[jid], desc)
    rows = ats.detail_map(cfg, known, sorted(links), lambda j: j, one, workers=4)
    return [r for r in rows if ats.is_us(r["location"])]  # same rule fetch.py uses; this ats is in US_FILTERED for the feed path

FETCHERS = {"successfactors": successfactors}
US_FILTERED = {"successfactors"}
