"""Oracle HCM Cloud recruiting REST (oraclehcm) and Avature portal HTML (avature)."""
import re, sys, urllib.request
import ats
from adapters.jsonld import posting, posted as ld_posted

def oraclehcm(cfg, known=()):
    """cfg: host (API host), site (siteNumber), us_filter (finder fragment, e.g. "locationId=..." or "selectedLocationsFacet=..."; tenants
    differ), careers_host (public site for URLs), optional url_template with {id}, optional max_pages (probe only)."""
    base = f"https://{cfg['host']}/hcmRestApi/resources/latest"
    site, items, offset, total = cfg["site"], [], 0, None
    while True:
        d = ats.get(f"{base}/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations,flexFieldsFacet.values"
                    f"&finder=findReqs;siteNumber={site},limit=25,offset={offset},sortBy=POSTING_DATES_DESC,{cfg['us_filter']}")["items"][0]
        total = total if total is not None else d.get("TotalJobsCount", 0)
        if not total:
            raise RuntimeError(f"{cfg['company']}: TotalJobsCount 0 -- us_filter {cfg['us_filter']!r} is wrong for this tenant")
        items += d.get("requisitionList", []); offset += 25
        if offset >= total or not d.get("requisitionList") or offset >= 25 * cfg.get("max_pages", 1e9):
            break
    tmpl = cfg.get("url_template") or f"https://{cfg['careers_host']}/en/sites/{site}/job/{{id}}"
    def one(j):
        det = ats.get(f'{base}/recruitingCEJobRequisitionDetails?expand=all&onlyData=true&finder=ById;Id="{j["Id"]}",siteNumber={site}')["items"][0]
        return ats.row(cfg, "oraclehcm", j["Id"], j["Title"], j.get("PrimaryLocation"), j.get("JobFamily") or det.get("Category"), j.get("PostedDate"),
                       tmpl.format(id=j["Id"]), ats.strip((det.get("ExternalDescriptionStr") or "") + "\n" + (det.get("ExternalResponsibilitiesStr") or "")),
                       ats.strip(det.get("ExternalQualificationsStr")))
    return ats.detail_map(cfg, known, items, lambda j: j["Id"], one, workers=4)

_HTML = {"Accept": "text/html"}
# one field value: <div>s, or TotalEnergies' <dl><dt>label</dt><dd>value</dd></dl>
_VALUE = r'<(?:div|dd) class="article__content__view__field__value"[^>]*>(.*?)(?=<div class="article__content__view__field[ "]|</article>|</dd>)'
_FIELD = re.compile(r'article__content__view__field__label"[^>]*>\s*(.*?)\s*</(?:div|dt)>\s*' + _VALUE, re.S)
# /careers/JobDetail/<slug>/<id> (Two Sigma, Synopsys, EA, Bloomberg, Deloitte), /en_US/externaljobs/JobDetail/<id> (Siemens), /en_US/careers/JobDetail/<id>
# (Lenovo, slug optional), /en_US/careers/JobDetail?jobId=<id> (Macquarie), /Careers/FolderDetail/<place-title slug>/<id> (Epic's older skin)
_LINK = re.compile(r'href="(?:https?://[^/"]+)?((?:/[a-z]{2}_[A-Z]{2})?/\w+/(?:JobDetail|FolderDetail)(?:/(?:[^"\'?#]+/)?|\?jobId=)(\d+))(?=["\'?#&])')
# one search result: <article class="article article--result">, <article class="article--result"> (Deloitte), <li class="jobResultItem"> (Epic),
# <div class="article article--result"> up to the next one or the pager (TotalEnergies)
_ITEM = re.compile(r'<article class="(?:article )?article--result[" ].*?</article>|<li[^>]*class="jobResultItem[" ].*?</li>'
                   r'|<div class="article article--result[" ].*?(?=<div class="article article--result[" ]|<div class="list-controls)', re.S)
# location span, flat ("New York, ...") or wrapping city/state/country spans (Siemens)
_LOC = re.compile(r'<span class="list-item-location">((?:[^<]|<(?!/?span\b)|<span[^>]*>.*?</span>)*)</span>', re.S)
# Epic's skin: schema.org microdata, a "Position Summary" and a "Requirements" block, each under an <h3>
_MICRO = re.compile(r'<h3>(.*?)</h3>\s*<div itemprop="description"[^>]*>(.*?)(?=<h3>|<div class="tPad1|</article>)', re.S)

def _date(s):
    """"14-Oct-2026" / "Wednesday, October 14, 2026" / "20 Oct 2026" / "20-10-2026" -> ISO date, else ""."""
    for fmt in ("%d-%b-%Y", "%A, %B %d, %Y", "%d %b %Y", "%d-%m-%Y"):
        try:
            return ats.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return ""

def _slug_loc(link, title):
    """FolderDetail slugs lead with the place: ("/Careers/FolderDetail/Verona-Wisconsin-United-States-Trainer/21716", "Trainer") ->
    "Verona Wisconsin United States"; "" when the slug does not end with the title."""
    slug, t = link.rsplit("/", 2)[-2], re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")
    return slug[:-len(t)].strip("-").replace("-", " ") if t and slug.lower().endswith(t.lower()) else ""

def _result(a):
    """One search result -> list item, or None without a JobDetail link. Markups: class="link" title + list-item-location span or
    paragraph_inner-span (Two Sigma) spans; Lenovo's plain <h3><a> title, <span class="paragraph"> area and bare subtitle spans, of which
    the place is the one with a comma, else the last that is not a "Req #:" / "Posted" label (Deloitte: "Deloitte US | <entity> | <place>");
    Macquarie's <p> values, each labelled by an icon's alt text ("Office Location:"); Epic's <li> items, whose only location is the start
    of the FolderDetail slug. "Multiple Locations" in the list (Siemens, Deloitte) is left blank so the job is not prefiltered out and the
    detail page fills it."""
    m = _LINK.search(a)
    if not m:
        return None
    title = re.search(r'<a class="link[" ][^>]*>(.*?)</a>', a, re.S) or re.search(r'<h3[^>]*>\s*<a [^>]*>(.*?)</a>', a, re.S)
    title = ats.strip(title.group(1)) if title else ""
    spans = [ats.strip(s) for s in re.findall(r'<span class="paragraph_inner-span">(.*?)</span>', a, re.S)]
    sub = re.search(r'__subtitle">\s*(<span>.*?)</div>', a, re.S)
    sub = [s for s in (ats.strip(s) for s in re.findall(r'<span>(.*?)</span>', sub[1], re.S)) if s and ":" not in s and not s.startswith("Posted")] if sub else []
    icon = {k: ats.strip(v) for k, v in re.findall(r'alt="([^":]+):?"[^>]*>\s*<p>(.*?)</p>', a, re.S)}
    loc = _LOC.search(a)
    cat = re.search(r'<span class="(?:paragraph|list-item-family)">(.*?)</span>', a, re.S)
    posted = re.search(r'Posted (\d\d-\w{3}-\d{4})|list-item-jobCreationDate">\s*([\d-]+)', a)  # TotalEnergies: "20-10-2026"
    loc = (re.sub(r" ,", ",", re.sub(r"\s+", " ", ats.strip(loc[1]))) if loc else next((s for s in sub if "," in s), sub[-1]) if sub
           else spans[0] if spans else icon.get("Office Location") or icon.get("Location") or "/FolderDetail/" in m[1] and _slug_loc(m[1], title) or "")
    return {"id": m.group(2), "link": m.group(1), "title": title, "loc": "" if loc.lower() == "multiple locations" else loc,
            "cat": ats.strip(cat[1]) if cat else " / ".join(spans[1:]) or icon.get("Job Category", ""),
            "posted": _date(posted[1] or posted[2]) if posted else _date(icon.get("Posted Date", ""))}

def avature(cfg, known=()):
    """cfg: host (careers.twosigma.com / synopsys.avature.net / jobs.siemens.com / jobs.lenovo.com), list_path (/careers/OpenRoles/,
    /careers/SearchJobs/, /en_US/externaljobs/SearchJobs/, /en_US/careers/SearchJobs/), optional list_params: extra query string for the
    search page, e.g. a country filter "42386%5B%5D=812209&listFilterMode=1" (Siemens, US). The option id comes from the portal's
    <list portal path>/_portalDatasetSingleColumnOptionsSearchApi, as the Country picker on the search page does; worldwide boards
    otherwise page through every country (the is_us prefilter below still skips their foreign detail pages). Optional paging: "folder"
    for portals whose pager links use folderOffset/folderRecordsPerPage (Siemens, Epic; Siemens ignores jobOffset and serves page 1
    again). Optional join_fields: true for portals that split one description over many field blocks (Macquarie): every block without
    a label is joined; by default the longest block is the description. Detail pages without those blocks are read from their JSON-LD JobPosting (Deloitte) or
    schema.org microdata (Epic). TotalEnergies (jobs.totalenergies.com, /en_US/careers/SearchJobs/, US: "3834%5B%5D=41696&listFilterMode=1") lists
    <div> results and writes its fields as <dl>s; Siemens Energy (/en_US/jobs/SearchJobsUS/) has no place in its list."""
    items, seen, offset = [], set(), 0
    extra = f"&{cfg['list_params']}" if cfg.get("list_params") else ""
    pg = cfg.get("paging", "job")
    while True:
        h = ats.get_text(f"https://{cfg['host']}{cfg['list_path']}?{pg}RecordsPerPage=10&{pg}Offset={offset}{extra}", headers=_HTML)
        new, page = [], _ITEM.findall(h)
        for a in page:
            j = _result(a)
            if j and j["id"] not in seen:
                seen.add(j["id"]); new.append(j)
        items += new
        if not new:
            break
        offset += len(page)  # Synopsys and Siemens cap the page at 6 despite asking for 10
    def one(j):
        try:
            d = ats.get_text(f"https://{cfg['host']}{j['link']}", headers=_HTML)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            print(f"{cfg['company']}: removed posting {j['id']} (404)", file=sys.stderr)
            return None
        f = {ats.strip(k).rstrip(":"): v for k, v in _FIELD.findall(d)}  # Lenovo labels end in ":"
        vals = re.findall(_VALUE, d, re.S)
        desc = "\n".join(v for v in vals if v not in f.values()) if cfg.get("join_fields") else max(vals, key=len, default="")
        ld = {} if desc else posting(d) or {}
        if not desc:
            desc = "\n".join(f"{h}\n{b}" for h, b in _MICRO.findall(d)) or ld.get("description") or ""
        multi = re.search(r'article__header--locations.*?</div>', d, re.S)  # Deloitte: "Same job available in N locations", one <p> each
        # Siemens Energy: unlabelled "posting-location" values (country, state, city), then a Country/State/City list per further place
        here = [ats.strip(v) for v in re.findall(r'field posting-location">\s*<div class="article__content__view__field__value"[^>]*>(.*?)</div>', d, re.S)]
        places = [here] + [[ats.strip(v) for v in re.findall(r'MultipleDataSetFieldValue">(.*?)</span>', u, re.S)]
                           for u in re.findall(r'<ul class="MultipleDataSetFields">(.*?)</ul>', d, re.S)] if here else []
        title = j["title"] or ats.strip(f.get("Job Title"))
        loc = (j["loc"] or ", ".join(filter(None, [ats.strip(f.get("City")), ats.strip(f.get("Country"))])) or ats.strip(f.get("Location"))
               or "; ".join(l.strip() for l in ats.strip(f.get("Location(s)")).splitlines() if l.strip())  # Siemens: one <li> per site
               or "; ".join(", ".join(reversed(p)) for p in places if p)
               or (multi and "; ".join(ats.strip(p) for p in re.findall(r'<p class="paragraph">(.*?)</p>', multi[0], re.S))) or "")
        cat = j["cat"] or " / ".join(filter(None, [ats.strip(f.get("Job Category")), ats.strip(f.get("Job Subcategory"))]))
        posted = _date(ats.strip(f.get("Date Posted") or f.get("Posted since") or f.get("Date"))) or j["posted"] or ld_posted(ld)
        return ats.row(cfg, "avature", j["id"], title, loc, cat, posted, f"https://{cfg['host']}{j['link']}", ats.strip(desc))
    # These boards are US-filtered by fetch.py anyway; avoid fetching clearly foreign details.
    return ats.detail_map(cfg, known, [j for j in items if ats.is_us(j["loc"])], lambda j: j["id"], one, workers=3)

FETCHERS = {"oraclehcm": oraclehcm, "avature": avature}
US_FILTERED = {"oraclehcm"}
