"""Infinite BrassRing (Kenexa) TalentGateway boards, sjobs.brassring.com/TGnewUI/Search/Home/Home?partnerid=<p>&siteid=<s>: Texas Tech,
TTUHSC, Edward Jones, Westat, Walgreens. See adapters/__init__.py for the contract.

cfg: partnerid; siteid, or siteids for several boards of one employer (Texas Tech's staff, faculty and student sites); optional facets
({"formtext23": ["Information Technology", ...]}: the board's own search facets, to cut a huge board such as Walgreens' 21,000 store
jobs down to the functions worth grading); optional loc_fields (question names joined into the location when a posting's page has no
schema.org place; the non-empty ones are joined, e.g. Edward Jones ["formtext61", "formtext5", "formtext42", "formtext34"]: branch city,
home-office "Missouri, St. Louis", state, country; a street address "4400 STATE ROAD 19,WINDSOR,WI 53598" becomes "Windsor, WI");
optional place (last-resort location); optional state ("TX": appended to a place that names no state, "Multiple Off-Campus Sites" ->
"..., TX"); optional category_field (the question, or a list of questions tried in order, holding department / job function).
Each board's home page carries the anonymous session its own search sends (the __RequestVerificationToken as the RFT header, plus the
CookieValue); MatchedJobs returns the first 50 postings and ProcessSortAndShowMoreJobs the next pages. One JobDetails call per posting
returns its labelled fields and, on most boards, a schema.org JobPosting with place and date. The board's captchas guard sign-in and
password reset only; this adapter never touches them. fetch.py applies is_us.
"""
import http.cookiejar, json, re, sys, time, urllib.request
from datetime import datetime
import ats

CHROME = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"}
HOST = "https://sjobs.brassring.com"
SKIP = re.compile(r"eeo|equal (?:employment )?opportunit|recruiter|military|air force|army|navy|marine|coast guard|required attachments|"
                  r"^pay statement$|accommodation|e-?verify|special instructions|safety information|^about the university$", re.I)
BASIC = re.compile(r"(?:required|minimum|basic) (?:qualif|education|experience|skills)|^(?:[\w/&-]+ )?(?:qualifications|requirements)$", re.I)
PREF = re.compile(r"prefer|desired (?:qualif|skills|experience)|nice to have", re.I)

def _date(s):
    """"10/19/2026", "20-Oct-2026" or ISO -> ISO date."""
    s = (s or "").strip()
    for fmt in ("%m/%d/%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return s[:10] if re.match(r"\d{4}-\d\d-\d\d", s) else ""

def _answers(questions, key="QuestionName", value="Value"):
    return {q.get(key): q.get(value) for q in questions or [] if q.get(key) and q.get(value)}

def address(v):
    """"4400 STATE ROAD 19,WINDSOR,WI 53598" / "400 US ROUTE 1,YORK,ME,03909" -> "Windsor, WI"; anything else unchanged."""
    m = re.match(r"\s*\d[^,]*,\s*([^,]+?)\s*,\s*([A-Z]{2})\b[\s,]*\d{5}", v or "")
    return f"{m[1].title()}, {m[2]}" if m else (v or "").strip()

def jsonld(sr):
    """The schema.org JobPosting BrassRing renders for Google (googlejobsMappingfielddataJson), or {}."""
    m = re.search(r"<script[^>]*>(.*)</script>", sr.get("googlejobsMappingfielddataJson") or "", re.S)
    try:
        return json.loads(m[1]) if m else {}
    except ValueError:
        return {}

def ld_place(ld):
    locs = ld.get("jobLocation") or []
    out = []
    for l in locs if isinstance(locs, list) else [locs]:
        a = (l or {}).get("address") or {}
        p = ", ".join(filter(None, (str(a.get(k) or "").strip() for k in ("addressLocality", "addressRegion", "addressCountry"))))
        if p and p not in out:
            out.append(p)
    return "; ".join(out)

class Session:
    """One board's anonymous search session: cookies, RFT token and the encrypted session value the page posts back."""
    def __init__(self, partner, site):
        self.partner, self.site = str(partner), str(site)
        self.home = f"{HOST}/TGnewUI/Search/Home/Home?partnerid={self.partner}&siteid={self.site}"
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        h = ats.get_text(self.home, headers={**CHROME, "Accept": "text/html"}, opener=self.opener)
        tok, ck = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', h), re.search(r'id="CookieValue"[^>]*value="([^"]*)"', h)
        if not tok or not ck:
            raise RuntimeError(f"no search session on {self.home}")
        self.token, self.cookie = tok[1], ck[1]

    def post(self, path, body):
        return ats.get(HOST + path, body, headers={**CHROME, "Accept": "application/json", "RFT": self.token, "Referer": self.home,
                                                   "Origin": HOST, "X-Requested-With": "XMLHttpRequest"}, opener=self.opener)

    def jobs(self, facets):
        """Every posting on the board (list records), paging 50 at a time."""
        ff = {"Facet": [{"Name": k, "Options": [{"OptionValue": v, "Selected": True} for v in vs]} for k, vs in (facets or {}).items()]}
        d = self.post("/TgNewUI/Search/Ajax/MatchedJobs", {"PartnerId": self.partner, "SiteId": self.site, "Keyword": "", "Location": "",
                      "KeywordCustomSolrFields": "", "LocationCustomSolrFields": "", "TurnOffHttps": False, "LinkID": "", "Latitude": 0,
                      "Longitude": 0, "EncryptedSessionValue": self.cookie, "FacetFilterFields": ff,
                      "PowerSearchOptions": {"PowerSearchOption": []}, "SortType": ""})
        total, jobs, page = int(d.get("JobsCount") or 0), list((d.get("Jobs") or {}).get("Job") or []), 1
        while len(jobs) < total:
            page += 1
            time.sleep(1)
            d = self.post("/TgNewUI/Search/Ajax/ProcessSortAndShowMoreJobs", {"partnerId": self.partner, "siteId": self.site, "keyword": "",
                          "location": "", "keywordCustomSolrFields": "", "locationCustomSolrFields": "", "linkId": "", "Latitude": 0, "Longitude": 0,
                          "facetfilterfields": ff, "powersearchoptions": {"PowerSearchOption": []}, "SortType": "LastUpdated",
                          "pageNumber": page, "encryptedSessionValue": self.cookie})
            more = (d.get("Jobs") or {}).get("Job") or []
            if not more:
                break
            jobs += more
        return jobs

    def details(self, reqid):
        return self.post("/TgNewUI/Search/Ajax/JobDetails", {"partnerId": self.partner, "siteId": self.site, "jobid": reqid, "configMode": "",
                                                            "jobSiteId": self.site, "turnOffHttps": False}).get("ServiceResponse") or {}

def parse_details(cfg, sr, listed):
    """(title, location, category, posted, description, basic, preferred) from one JobDetails response and the posting's list record."""
    jd = sr.get("Jobdetails") or {}
    qs = jd.get("JobDetailQuestions") or []
    zone = {**listed, **_answers(qs, "VerityZone", "AnswerValue")}
    ld = jsonld(sr)
    desc, basic, pref = [], [], []
    for q in qs:
        label, z, text = (q.get("QuestionName") or "").strip(), q.get("VerityZone"), ats.strip(q.get("AnswerValue"))
        if not text or SKIP.search(label) or (not label and z != "jobdescription"):
            continue
        block = f"{label}\n{text}" if label else text
        if PREF.search(label):
            pref.append(block)
        elif BASIC.search(label):
            basic.append(block)
        else:
            desc.append(f"{label}: {text}" if label and len(text) < 100 and "\n" not in text else block)
    parts = []
    for f in cfg.get("loc_fields") or []:
        p = address(ats.strip(zone.get(f)))
        if p and p not in parts:
            parts.append(p)
    place = ld_place(ld) or ", ".join(parts) or cfg.get("place", "")
    if place and cfg.get("state") and not (re.search(r",\s*(?:[A-Z]{2}|D\.C\.)\b", place) or any(n in place.lower() for n in ats._US_NAMES)):
        place = f"{place}, {cfg['state']}"
    cf = cfg.get("category_field") or []
    category = next((c for c in (ats.strip(zone.get(f)).strip() for f in ([cf] if isinstance(cf, str) else cf)) if c), "")
    return (ats.strip(zone.get("jobtitle") or jd.get("Title")).strip(), place, category or ld.get("occupationalCategory") or "",
            (ld.get("datePosted") or "")[:10] or _date(zone.get("lastupdated")), "\n\n".join(desc), "\n\n".join(basic), "\n\n".join(pref))

def brassring(cfg, known=()):
    sites = [str(s) for s in (cfg.get("siteids") or [cfg["siteid"]])]
    items = {}
    for site in sites:
        s = Session(cfg["partnerid"], site)
        for j in s.jobs(cfg.get("facets")):
            a = _answers(j.get("Questions"))
            if a.get("reqid"):
                items.setdefault(a["reqid"], (s, a, j.get("Link") or f"{HOST}/TGnewUI/Search/home/HomeWithPreLoad?partnerid={s.partner}"
                                              f"&siteid={site}&PageType=JobDetails&jobid={a['reqid']}"))
    def one(item):
        reqid, (s, listed, url) = item
        sr = s.details(reqid)
        if not (sr.get("Jobdetails") or {}).get("JobDetailQuestions"):
            print(f"{cfg['company']}: no details for posting {reqid}", file=sys.stderr); return None
        title, place, category, posted, desc, basic, pref = parse_details(cfg, sr, listed)
        if not (desc or basic):
            print(f"{cfg['company']}: posting {reqid} has no text", file=sys.stderr); return None
        return ats.row(cfg, "brassring", reqid, title, place, category, posted, url, desc, basic, pref)
    return ats.detail_map(cfg, known, sorted(items.items()), lambda i: i[0], one, workers=3)

FETCHERS = {"brassring": brassring}
