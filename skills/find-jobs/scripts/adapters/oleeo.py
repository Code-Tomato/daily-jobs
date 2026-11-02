"""Oleeo (tal.net) candidate job boards: Morgan Stanley campus programs (morganstanley.tal.net). See adapters/__init__.py for the contract.

cfg: board (the vacancy board URL, e.g. https://morganstanley.tal.net/vx/lang-en-GB/mobile-0/brand-2/candidate/jobboard/vacancy/1/adv/),
optional country (a value of the board's Location facet, "United States of America"; when given, the list is filtered by that facet at
the source and the country is added to each row's city).
The board is server-rendered HTML: 50 opportunities a page (?start=50) as table rows with id, title and city, and a facet sidebar of
checkboxes (f_Item_Opportunity_<field>_lk=<value>) labelled with counts. Each opportunity page is an eForm of labelled fields (City,
Business Unit, Program, Education Level, Job description...). tal.net's robots.txt asks for a 10 s crawl delay, so every request
waits for it and detail calls run one at a time. Some Oleeo tenants (Jefferies) answer with an "oleeoProtect" proof-of-work bot check;
that is never attempted: the run raises.
"""
import re, sys, threading, time, urllib.error, urllib.parse
from html import unescape
import ats

CHROME = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
          "Accept": "text/html"}
DELAY = 10  # robots.txt Crawl-delay on *.tal.net
_ROW = re.compile(r'<tr class="[^"]*\bsearch_res\b[^"]*"[^>]*data-oppid="(\d+)"[^>]*data-title="([^"]*)"[^>]*>(.*?)</tr>', re.S)
_FACET = re.compile(r"name=\"(f_Item_Opportunity_\d+_lk)\" value='(\d+)'[^>]*>.{0,300}?<span class=\"facet_label\">(.*?)</span>", re.S)
_FIELD = re.compile(r'<span class="hform_lbl_text"[^>]*>(.*?)</span>.*?class="form-control-static"[^>]*>(.*?)(?=<style|<!-- template=eform2/field\.tt -->|$)', re.S)
_lock, _last = threading.Lock(), [0.0]

def _get(url):
    with _lock:  # one request at a time, DELAY apart, across the list and detail threads
        wait = _last[0] + DELAY - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            h = ats.get_text(url, headers=CHROME)
        finally:
            _last[0] = time.monotonic()
    if "oleeoProtect" in h or "Quick Check Needed" in h:
        raise RuntimeError(f"{urllib.parse.urlparse(url).netloc} answered with Oleeo's bot check; not attempted")
    return h

def facet(html, label):
    """Query parameter (name, value) of the board's facet checkbox labelled `label`, or None."""
    for name, value, lab in _FACET.findall(html):
        if " ".join(ats.strip(lab).replace("\xa0", " ").split()).lower() == label.lower():
            return name, value
    return None

def rows(html):
    """[(opp id, title, url, city)] from one board page."""
    out = []
    for oid, title, body in _ROW.findall(html):
        link = re.search(r'href="([^"]*/opp/' + oid + r'[^"]*)"', body)
        cells = re.findall(r'<td class="comm_list_tbody">(.*?)</td>', body, re.S)
        url = re.sub(r"/xf-[0-9a-f]+/", "/", unescape(link[1])) if link else ""  # filtered pages put a session segment in the link
        out.append((oid, " ".join(unescape(title).split()), url, ats.strip(cells[1]) if len(cells) > 1 else ""))
    return out

def fields(html):
    """[(label, text)] of one opportunity page's eForm, empty values dropped."""
    out = []
    for label, value in _FIELD.findall(html):
        label, text = ats.strip(label).replace("\xa0", " ").strip(), ats.strip(value)
        if label and text:
            out.append((label, text))
    return out

def oleeo(cfg, known=()):
    board = cfg["board"]
    first = _get(board)
    query = ""
    if cfg.get("country"):
        f = facet(first, cfg["country"])
        if not f:
            raise RuntimeError(f"{cfg['company']}: no '{cfg['country']}' facet on {board}")
        query = urllib.parse.urlencode([f])
        first = _get(f"{board}?{query}")
    total = int((re.search(r"(\d+) results? match", first) or [0, 0])[1])
    items, page, start = {}, first, 0
    while True:
        got = rows(page)
        for oid, title, url, city in got:
            items.setdefault(oid, (title, url, city))
        start += 50
        if not got or start >= total:
            break
        page = _get(f"{board}?{query + '&' if query else ''}start={start}")
    if total and len(items) < total:
        print(f"{cfg['company']}: listed {len(items)} of {total} opportunities", file=sys.stderr)
    def one(item):
        oid, (title, url, city) = item
        try:
            fs = fields(_get(url))
        except urllib.error.HTTPError as e:
            if e.code not in (404, 410):
                raise
            print(f"{cfg['company']}: removed opportunity {oid} ({e.code})", file=sys.stderr); return None
        d = dict(fs)
        body = next((t for l, t in fs if re.search(r"description", l, re.I)), "")
        if not body:
            print(f"{cfg['company']}: no job description on {url}", file=sys.stderr); return None
        city = d.get("City") or city
        meta = "\n".join(f"{l}: {t}" for l, t in fs if t != body and l != "City")
        return ats.row(cfg, "oleeo", oid, title, ", ".join(filter(None, [city, cfg.get("country")])),
                       " / ".join(filter(None, [d.get("Business Unit"), d.get("Program")])), "", url, "\n\n".join(filter(None, [body, meta])))
    return ats.detail_map(cfg, known, sorted(items.items()), lambda i: i[0], one, workers=1)

FETCHERS = {"oleeo": oleeo}
US_FILTERED = set()  # a country facet narrows the list, but fetch.py's is_us still checks "City, United States of America"
