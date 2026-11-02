"""Paycor Recruiting (formerly Newton) public Atom feed: recruitingbypaycor.com/career/CareerAtomFeed.action?clientId=...

cfg: client_id (32-hex Paycor client id; a public JobIntroduction.action?id=<job id> link redirects to a URL carrying it).
Used for Ayar Labs, whose own careers page (which inlines the same list) sits behind a SiteGround captcha since 2026-10.
Job ids and links are the same ones the careers page used, so cached rows carry over.
"""
import re
import xml.etree.ElementTree as ET
import ats

A, N = "{http://www.w3.org/2005/Atom}", "{http://www.newtonsoftware.com}"

def parse(cfg, xml):
    out = []
    for e in ET.fromstring(xml).findall(A + "entry"):
        f = lambda k: (e.findtext(N + k) or "").strip()
        loc = ", ".join(filter(None, [f("location"), f("state"), f("country")]))
        if not (re.search(r"united states|usa|\bus\b|remote", loc, re.I) or not f("country")):
            continue
        link = e.find(A + "link")
        cat = e.find(A + "category")
        out.append(ats.row(cfg, "paycor", e.findtext(A + "id"), e.findtext(A + "title"), loc,
                           f("department") or (cat.get("term") if cat is not None else ""), e.findtext(A + "published"),
                           link.get("href") if link is not None else "", ats.strip(e.findtext(A + "summary"))))
    return out

def paycor(cfg, known=()):
    url = f"https://recruitingbypaycor.com/career/CareerAtomFeed.action?clientId={cfg['client_id']}"
    xml = ats.get_text(url, headers={"Accept": "application/atom+xml, application/xml"})
    if "<feed" not in xml[:500]:
        raise RuntimeError(f"paycor feed for {cfg['company']} is not an Atom feed")
    return parse(cfg, xml)

FETCHERS = {"paycor": paycor}
US_FILTERED = {"paycor"}
