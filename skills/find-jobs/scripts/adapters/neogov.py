"""NEOGOV agency job boards on governmentjobs.com (City of Houston: governmentjobs.com/careers/houston; Harris County: .../harriscountytx).
See adapters/__init__.py for the contract.

cfg: agency (the slug in governmentjobs.com/careers/<agency>), place (the agency's city, "Houston, TX": used when a posting's location
is a street address, "Various" or empty), optional state ("TX": appended to a bare town such as "Tomball"), optional sections (which
row field each feed section fills; default {"examplesofduties": "basic", "qualifications": "preferred"}: Houston and Harris County both
put minimum education/experience in the feed's examplesofduties and preferences in its qualifications).
NEOGOV publishes one RSS job feed per agency (agency.governmentjobs.com/jobfeed.cfm?agency=<agency>, redirecting to
www.governmentjobs.com/SearchEngine/JobsFeed): every open public posting with its full text, department, job type and advertise dates.
That one request per run is all this adapter makes. It never fetches the site's pages or listing API: www.governmentjobs.com's
robots.txt admits only named search engines and job boards. fetch.py applies is_us.
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
import ats

CHROME = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"}
NS = "{http://www.neogov.com/namespaces/JobListing}"
HEADINGS = {"examplesofduties": "Minimum Qualifications", "qualifications": "Preferred Qualifications", "supplementalinformation": "Supplemental Information"}
DEFAULT_SECTIONS = {"examplesofduties": "basic", "qualifications": "preferred", "supplementalinformation": "description"}

def _date(s):
    """"Fri, 09 Oct 2026 00:00:00:0" (advertiseFromDate) or an RFC 822 pubDate -> ISO date."""
    m = re.search(r"(\d{1,2}) (\w{3}) (\d{4})", s or "")
    if m:
        try:
            return datetime.strptime(" ".join(m.groups()), "%d %b %Y").date().isoformat()
        except ValueError:
            pass
    try:
        return parsedate_to_datetime(s).date().isoformat() if s else ""
    except (TypeError, ValueError):
        return ""

def _place(cfg, loc):
    loc = re.sub(r"\s+", " ", loc or "").strip()
    if not loc or re.search(r"\d|\bvarious\b|\bmultiple\b", loc, re.I):
        return cfg.get("place", "")
    names_state = re.search(r",\s*(?:[A-Z]{2}|D\.C\.)\b", loc) or any(n in loc.lower() for n in ats._US_NAMES)
    return f"{loc}, {cfg['state']}" if cfg.get("state") and not names_state else loc

def _salary(f):
    """"35.94 - 41.09 USD per Hour"; a non-numeric bound ("Depends on Qualifications") is shown once, alone."""
    lo, hi = f("minimumSalary").strip(), f("maximumSalary").strip()
    if not re.match(r"[\d.,]+$", lo):
        return lo
    rng = lo if not hi or hi == lo else f"{lo} - {hi}"
    return " ".join(filter(None, [rng, f("salaryCurrency").strip(), f"per {f('salaryInterval').strip()}" if f("salaryInterval").strip() else ""]))

def parse_feed(cfg, xml):
    sections = {**DEFAULT_SECTIONS, **cfg.get("sections", {})}
    out = []
    for it in ET.fromstring(xml.lstrip("﻿").encode()).iter("item"):
        f = lambda k: it.findtext(NS + k) or ""
        link = (it.findtext("link") or "").strip()
        jid = f("jobId").strip() or (re.search(r"/jobs/(\d+)", link) or [None, ""])[1]
        if not jid:
            continue
        text = {"description": [ats.strip(it.findtext("description"))], "basic": [], "preferred": []}
        for key, slot in sections.items():
            body = ats.strip(f(key))
            if body:
                text[slot].append(body if slot != "description" else f"{HEADINGS.get(key, key)}\n{body}")
        meta = "\n".join(f"{label}: {v}" for label, v in (("Job type", f("jobType").strip()), ("Salary", _salary(f))) if v)
        out.append(ats.row(cfg, "neogov", jid, (it.findtext("title") or "").strip(), _place(cfg, f("location")),
                           " / ".join(filter(None, [f("department").strip(), f("division").strip()])), _date(f("advertiseFromDate") or it.findtext("pubDate")),
                           link, "\n\n".join(filter(None, [*text["description"], meta])), "\n\n".join(text["basic"]), "\n\n".join(text["preferred"])))
    return out

def neogov(cfg, known=()):
    xml = ats.get_text(f"https://agency.governmentjobs.com/jobfeed.cfm?agency={cfg['agency']}",
                       headers={**CHROME, "Accept": "application/rss+xml, application/xml"})
    if "<rss" not in xml[:1000]:
        raise RuntimeError(f"{cfg['company']}: the NEOGOV job feed for {cfg['agency']} is not RSS")
    return parse_feed(cfg, xml)

FETCHERS = {"neogov": neogov}
