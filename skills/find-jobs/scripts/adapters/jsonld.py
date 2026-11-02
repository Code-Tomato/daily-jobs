"""Generic catch-all for custom career sites whose job pages carry a schema.org JobPosting in <script type="application/ld+json">.
Also exports the JSON-LD helpers (posting, location, posted) other adapters reuse.

cfg: list_url (str or list: an HTML listing page, an XML sitemap or a sitemap index; "{page}" in it pages 1, 2, ... until a page adds
no new links), link_regex (re.search against every absolute link/<loc>; group 1 is the job id when present), optional id_regex
(job id from the URL; default group 1 of link_regex, else the last run of digits, else the last path segment), optional sitemap_regex
(which child sitemaps of an index to follow; default all), optional location_regex (re.findall against the job page when its posting
has no jobLocation or an empty one; the group-1 matches, joined by "; ", are the location), optional location (used when neither gives
one), optional workers (parallel detail calls, default 4) and delay (seconds each worker waits before a detail call) for hosts that
rate-limit, optional max_jobs (probe only). fetch.py applies is_us; a page without a JobPosting is skipped and logged, not fatal.
Example: Garmin {"list_url": "https://careers.garmin.com/sitemap.xml", "link_regex": "/jobs/(\\d+)\\?lang=en-us$"}.
D. E. Shaw's JSON-LD address is blank; its Next.js page data has the office: "location_regex": "\"name\":\"([^\"]+)\",\"abbreviation\"".
"""
import json, re, sys, time, urllib.error, urllib.parse
from html import unescape
import ats

CHROME = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
          "Accept": "text/html,application/xhtml+xml,application/xml"}

def _walk(x):
    """Every dict in a JSON-LD tree (handles top-level lists and "@graph")."""
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from _walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v)

def posting(html):
    """First schema.org JobPosting in an HTML page, or None. Tolerates broken blocks and @type lists."""
    for b in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            # raw_decode: the first complete object wins, trailing junk is ignored (EOG closes its JobPosting with one "}" too many)
            d = json.JSONDecoder(strict=False).raw_decode(b.strip().removeprefix("<!--").removesuffix("-->").strip())[0]
        except ValueError:
            continue
        for x in _walk(d):
            t = x.get("@type")
            if t == "JobPosting" or isinstance(t, list) and "JobPosting" in t:
                return x
    return None

def location(ld):
    """"City, Region, Country" per jobLocation, joined by "; "; "Remote" added for TELECOMMUTE postings."""
    locs = ld.get("jobLocation") or []
    out = []
    for l in locs if isinstance(locs, list) else [locs]:
        a = l.get("address") if isinstance(l, dict) else l
        if isinstance(a, dict):
            c = a.get("addressCountry")
            c = c.get("name") if isinstance(c, dict) else c
            s = ", ".join(str(p) for p in [a.get("addressLocality"), a.get("addressRegion"), c] if p)
        else:
            s = str(a or (l.get("name") if isinstance(l, dict) else "") or "")
        if s and s not in out:
            out.append(s)
    if "TELECOMMUTE" in str(ld.get("jobLocationType") or "").upper():
        out.append("Remote")
    return "; ".join(out)

def posted(ld):
    """datePosted as YYYY-MM-DD (also "2026-6-2" and full timestamps), else ""."""
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(ld.get("datePosted") or ""))
    return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}" if m else ""

def _links(url, body, cfg, seen_maps):
    """Job-link candidates from one list page / sitemap; recurses into sitemap indexes."""
    if re.search(r"<sitemapindex\b", body[:2000]):
        out = []
        for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", body):
            loc = unescape(loc)
            if loc not in seen_maps and re.search(cfg.get("sitemap_regex", ""), loc):
                seen_maps.add(loc)
                out += _links(loc, ats.get_text(loc, headers=CHROME), cfg, seen_maps)
        return out
    raw = re.findall(r"<loc>\s*(.*?)\s*</loc>", body) if re.search(r"<urlset\b", body[:2000]) else re.findall(r'href\s*=\s*["\']([^"\'#]+)', body)
    return [urllib.parse.urljoin(url, unescape(u)) for u in raw]

def _jid(cfg, url):
    m = re.search(cfg["id_regex"], url) if cfg.get("id_regex") else re.search(cfg["link_regex"], url)
    if m and m.groups() and m.group(1):
        return m.group(1)
    m = re.findall(r"\d{3,}", url)
    return m[-1] if m else urllib.parse.urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]

def jsonld(cfg, known=()):
    links, seen_maps = {}, set()
    for base in cfg["list_url"] if isinstance(cfg["list_url"], list) else [cfg["list_url"]]:
        for page in range(1, 200) if "{page}" in base else [None]:
            url = base.format(page=page) if page else base
            new = {u for u in _links(url, ats.get_text(url, headers=CHROME), cfg, seen_maps) if re.search(cfg["link_regex"], u)} - set(links.values())
            links.update({_jid(cfg, u): u for u in sorted(new)})
            if not new:
                break
    if not links:
        raise RuntimeError(f"{cfg['company']}: no job links matching {cfg['link_regex']!r} on {cfg['list_url']}")
    items = sorted(links.items())[:cfg.get("max_jobs")]
    def one(item):
        jid, url = item
        time.sleep(cfg.get("delay", 0))
        try:
            html = ats.get_text(url, headers=CHROME)
        except urllib.error.HTTPError as e:
            if e.code not in (404, 410):
                raise
            print(f"{cfg['company']}: removed posting {jid} ({e.code})", file=sys.stderr); return None
        ld = posting(html)
        if not ld:
            print(f"{cfg['company']}: no JSON-LD JobPosting on {url}", file=sys.stderr); return None
        cat = ld.get("occupationalCategory") or ld.get("industry") or ""
        cat = ", ".join(cat) if isinstance(cat, list) else str(cat)
        loc = location(ld) or cfg.get("location_regex") and "; ".join(dict.fromkeys(ats.strip(m) for m in re.findall(cfg["location_regex"], html)))
        return ats.row(cfg, "jsonld", jid, ats.strip(ld.get("title")), loc or cfg.get("location", ""), "" if cat.upper() == "UNAVAILABLE" else cat,
                       posted(ld), ld.get("url") if str(ld.get("url", "")).startswith("http") else url, ats.strip(ld.get("description")))
    return ats.detail_map(cfg, known, items, lambda i: i[0], one, workers=cfg.get("workers", 4))

FETCHERS = {"jsonld": jsonld}
