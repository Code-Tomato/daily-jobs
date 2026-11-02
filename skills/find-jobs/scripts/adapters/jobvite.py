"""Jobvite career sites (jobs.jobvite.com/<slug>). The bare list URL is Access Denied; the iframe variant
`/jobs?nl=1&fr=false` with a referer works. cfg: slug, referer (the company careers page).
Detail pages carry a JSON-LD JobPosting. Untested against a board with live postings (Quantlab was empty when built).
Feed mode, cfg: feed (a Jobvite-hosted careers site's XML job feed, e.g. https://careers.nutanix.com/en/jobs/xml/?rss=true): every job
with its full HTML description in one call. For sites whose job pages have no JSON-LD (Nutanix's gave 0 rows the other way)."""
import json, re, sys
import xml.etree.ElementTree as ET
import ats

HOST = "https://jobs.jobvite.com"

def _feed(cfg):
    """<source><job><title/><date/><requisitionid/><url/><city/><state/><country/><description/><category/><remotetype/>...</job></source>.
    The id is the Jobvite requisition id (same as the jobs.jobvite.com/<slug>/job/<id> links). Kept when the country is the US or blank."""
    xml = ats.get_text(cfg["feed"], headers={"Accept": "application/xml, text/xml"})
    out = []
    for j in ET.fromstring(xml.encode()).iter("job"):
        t = lambda k: (j.findtext(k) or "").strip()
        if t("country") not in ("", "United States", "United States of America", "US", "USA"):
            continue
        loc = ", ".join(filter(None, [t("city"), t("state"), t("country")]))
        if re.search(r"remote", t("remotetype"), re.I):
            loc = f"{loc} (Remote)" if loc else "Remote"
        out.append(ats.row(cfg, "jobvite", t("requisitionid") or t("apijobid"), t("title"), loc, " / ".join(filter(None, [t("category"), t("jobFamilySubgroup")])),
                           t("date"), t("url"), ats.strip(t("description"))))
    return out

def jobvite(cfg, known=()):
    if cfg.get("feed"):
        return _feed(cfg)
    hdr = {"Accept": "text/html", "Referer": cfg.get("referer", "https://www.jobvite.com/")}
    page = ats.get_text(f"{HOST}/{cfg['slug']}/jobs?nl=1&fr=false", headers=hdr)
    if "no open jobs" in page.lower():
        return []
    links = sorted(set(re.findall(rf'href="(/{re.escape(cfg["slug"])}/job/([A-Za-z0-9]+)[^"]*)"', page)))
    def one(pair):
        link, jid = pair
        h = ats.get_text(HOST + link, headers=hdr)
        ld = next((j for j in (json.loads(x) for x in re.findall(r'<script[^>]*ld\+json[^>]*>(.*?)</script>', h, re.S)) if isinstance(j, dict) and j.get("@type") == "JobPosting"), None)
        if not ld:
            print(f"jobvite: no JSON-LD on {link}", file=sys.stderr); return None
        loc = ld.get("jobLocation") or {}
        loc = loc[0] if isinstance(loc, list) and loc else loc
        addr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
        return ats.row(cfg, "jobvite", jid, ld.get("title"), ", ".join(filter(None, [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")])) or loc.get("name", ""),
                       ld.get("occupationalCategory", ""), ld.get("datePosted"), HOST + link, ats.strip(ld.get("description")))
    return ats.detail_map(cfg, known, links, lambda p: p[1], one, workers=3)

FETCHERS = {"jobvite": jobvite}
