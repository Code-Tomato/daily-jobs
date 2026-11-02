"""PeopleAdmin 7 university job boards (<host>/postings/search): UT Dallas, Texas State, UTRGV, Texas Southern. See adapters/__init__.py.

cfg: host (jobs.utdallas.edu), location (the campus, used when a posting's page names no place: "Richardson, TX"), optional state
("TX": appended to a bare town in a posting's Location field, "Richardson" -> "Richardson, TX").
The list is the board's public Atom feed (/postings/all_jobs.atom, linked from its search page): every open posting with title,
publish date and a summary. Each /postings/<id> page is a th/td table of labelled fields whose labels differ per school ("Minimum
Qualifications", "Required Qualifications", "Education", "Job Location", "Location"...). The row text is every field except
boilerplate (EEO, legal notices, how to apply); required/minimum qualification fields go to basic and preferred ones to preferred.
A posting whose page cannot be read keeps the feed summary. fetch.py applies is_us.
"""
import re, sys, urllib.error
import xml.etree.ElementTree as ET
import ats

CHROME = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"}
A = "{http://www.w3.org/2005/Atom}"
_FIELD = re.compile(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", re.S)
SKIP = re.compile(r"eeo|equal (?:employment )?opportunit|legal notice|accommodation|record checks?|eligibility for employment|why work|quick link|"
                  r"special instructions|important message|please note|applicant documents|supplemental questions|^posting number$|"
                  r"job posting number|^position title$|^working title$|^functional title$", re.I)
PLACE = re.compile(r"^(?:job |work |primary |campus )?(?:location|campus)s?$|^city$", re.I)
DEPT = re.compile(r"^(?:department(?:/school)?|college/division|division/organization|division|college|organization|hiring department)$", re.I)
BASIC = re.compile(r"minimum|required|qualif|^education|experience|knowledge|requirements", re.I)
PREF = re.compile(r"prefer|desirable", re.I)

def fields(html):
    """[(label, text)] from one /postings/<id> page, in page order, empty values dropped."""
    out = []
    for th, td in _FIELD.findall(html):
        label, text = ats.strip(th).rstrip(": ").strip(), ats.strip(td)
        if label and text:
            out.append((label, text))
    return out

def names_state(place):
    """True when a place already says its state: "Edinburg, Texas", "Richardson, TX", "Washington, D.C."."""
    return bool(re.search(r",\s*(?:[A-Z]{2}|D\.C\.)\b", place)) or any(n in place.lower() for n in ats._US_NAMES)

def parse_page(cfg, html):
    """(location, category, description, basic, preferred) from one posting page; None when it has no field table."""
    fs = fields(html)
    if not fs:
        return None
    place = next((t for l, t in fs if PLACE.search(l)), "")
    if re.fullmatch(r"n/?a|none|tbd|-+", place.strip(), re.I):
        place = ""
    if place and cfg.get("state") and not names_state(place) and not re.search(r"international|abroad|overseas", place, re.I):
        place = f"{place}, {cfg['state']}"
    dept = next((t for l, t in fs if DEPT.search(l)), "")
    desc, basic, pref = [], [], []
    for label, text in fs:
        if SKIP.search(label) or PLACE.search(label):
            continue
        if PREF.search(label):
            pref.append(f"{label}\n{text}")
        elif BASIC.search(label) and not label.endswith("?"):
            basic.append(f"{label}\n{text}")
        else:
            desc.append(f"{label}: {text}" if len(text) < 100 and "\n" not in text else f"{label}\n{text}")
    return place or cfg.get("location", ""), dept, "\n\n".join(desc), "\n\n".join(basic), "\n\n".join(pref)

def peopleadmin(cfg, known=()):
    base = f"https://{cfg['host']}"
    xml = ats.get_text(f"{base}/postings/all_jobs.atom", headers={**CHROME, "Accept": "application/atom+xml, application/xml"})
    if "<feed" not in xml[:1000]:
        raise RuntimeError(f"{cfg['company']}: {base}/postings/all_jobs.atom is not an Atom feed")
    items = []
    for e in ET.fromstring(xml.encode()).iter(A + "entry"):
        link = next((l.get("href") for l in e.iter(A + "link") if l.get("rel", "alternate") == "alternate"), None) or e.findtext(A + "id") or ""
        m = re.search(r"/postings/(\d+)", link)
        if m:
            items.append({"id": m[1], "url": f"{base}/postings/{m[1]}", "title": (e.findtext(A + "title") or "").strip(),
                          "posted": e.findtext(A + "published") or e.findtext(A + "updated") or "", "summary": ats.strip(e.findtext(A + "content"))})
    def one(it):
        try:
            got = parse_page(cfg, ats.get_text(it["url"], headers={**CHROME, "Accept": "text/html"}))
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                print(f"{cfg['company']}: removed posting {it['id']} ({e.code})", file=sys.stderr); return None
            raise
        if not got:
            print(f"{cfg['company']}: no field table on {it['url']}; keeping the feed summary", file=sys.stderr)
            got = (cfg.get("location", ""), "", it["summary"], "", "")
        place, dept, desc, basic, pref = got
        return ats.row(cfg, "peopleadmin", it["id"], it["title"], place, dept, it["posted"], it["url"], desc or it["summary"], basic, pref)
    return ats.detail_map(cfg, known, items, lambda it: it["id"], one, workers=3)

FETCHERS = {"peopleadmin": peopleadmin}
