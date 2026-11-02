"""ADP Workforce Now recruiting career centers (workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=<cid>):
Intuitive Machines, Prosperity Bank, W&T Offshore. See adapters/__init__.py for the contract.

cfg: cid (the career center's client id, the UUID in the company's careers link), optional ccId (default 19000101_000001), optional
lang (default en_US).
The career center page reads the public JSON at careercenter/public/events/staffing/v1/job-requisitions: 20 requisitions a page
($top/$skip) with title, post date and locations but no text; one detail call per requisition adds requisitionDescription.
Internal-only postings are skipped. Rows are keyed by the ExternalJobID the page's own share links use (jobId=<it>), falling back to
the requisition's itemID. fetch.py applies is_us to the locations ("Houston, TX, US").
"""
import sys, time, urllib.error, urllib.parse
import ats

CHROME = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
          "Accept": "application/json"}
ADP = "https://workforcenow.adp.com/mascsr/default"
PAGE = 20

def _custom(j, group, code):
    for f in (j.get("customFieldGroup") or {}).get(group) or []:
        if (f.get("nameCode") or {}).get("codeValue") == code:
            return f
    return {}

def external_id(j):
    return (_custom(j, "stringFields", "ExternalJobID").get("stringValue") or "").strip() or j["itemID"]

def locations(j):
    """"Houston, TX, US; Glen Burnie, MD, US": the career center's own location label, else city and state from the address."""
    out = []
    for l in j.get("requisitionLocations") or []:
        a = l.get("address") or {}
        name = ((l.get("nameCode") or {}).get("shortName") or "").strip().strip(",").strip()
        name = name or ", ".join(filter(None, [(a.get("cityName") or "").strip(), ((a.get("countrySubdivisionLevel1") or {}).get("codeValue") or "").strip()]))
        if name and name not in out:
            out.append(name)
    return "; ".join(out)

def adp(cfg, known=()):
    cid, ccid, lang = cfg["cid"], cfg.get("ccId", "19000101_000001"), cfg.get("lang", "en_US")
    base = f"{ADP}/careercenter/public/events/staffing/v1/job-requisitions"
    q = f"cid={cid}&ccId={ccid}&lang={lang}&locale={lang}"
    items, skip = [], 0
    while True:
        d = ats.get(f"{base}?{q}&$top={PAGE}&$skip={skip}", headers=CHROME)
        reqs = d.get("jobRequisitions") or []
        items += [j for j in reqs if not _custom(j, "indicatorFields", "InternalPostingFlag").get("indicatorValue")]
        skip += PAGE
        if not reqs or skip >= (d.get("meta") or {}).get("totalNumber", 0):
            break
        time.sleep(0.5)
    def one(j):
        try:
            det = ats.get(f"{base}/{urllib.parse.quote(j['itemID'])}?{q}", headers=CHROME)
        except urllib.error.HTTPError as e:
            if e.code not in (404, 410):
                raise
            print(f"{cfg['company']}: removed requisition {j['itemID']} ({e.code})", file=sys.stderr); return None
        det = (det.get("jobRequisitions") or [det])[0]
        desc = ats.strip(det.get("requisitionDescription"))
        if not desc:
            print(f"{cfg['company']}: no description for requisition {j['itemID']}", file=sys.stderr); return None
        ext = external_id(j)
        units = " / ".join(filter(None, ((u.get("nameCode") or {}).get("shortName") or (u.get("nameCode") or {}).get("longName") for u in det.get("organizationalUnits") or [])))
        return ats.row(cfg, "adp", ext, (det.get("requisitionTitle") or j.get("requisitionTitle") or "").strip(), locations(det) or locations(j),
                       units or (_custom(det, "stringFields", "HomeDepartment").get("stringValue") or "").strip(), j.get("postDate"),
                       f"{ADP}/mdf/recruitment/recruitment.html?cid={cid}&ccId={ccid}&jobId={urllib.parse.quote(ext)}&lang={lang}", desc)
    return ats.detail_map(cfg, known, items, external_id, one, workers=2)

FETCHERS = {"adp": adp}
