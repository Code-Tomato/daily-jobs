"""Optiver public paginated jobs API plus detail pages.
Filters configured US offices and departments after collecting the complete listing.
"""
import json, re, sys, urllib.error
import ats

HOST = "https://www.optiver.com"

def optiver(cfg, known=()):
    links, seen, offset = {}, set(), 0
    while True:
        d = ats.get(f"{HOST}/en/api/v1/jobs?from={offset}&size=16")
        items, total = d["items"], d["totalCount"]
        fresh = {j["href"] for j in items} - seen
        if not fresh and offset < total:
            raise RuntimeError(f"optiver pagination stalled at {offset} of {total}; kept cache")
        seen.update(fresh)
        for j in items:
            info = j.get("jobClickTracking") or {}
            loc, dep = info.get("vacancyOffice"), info.get("vacancyDomain")
            if loc in cfg["locations"] and dep in cfg["departments"]:
                links[j["href"]] = (loc, dep)
        offset += len(items)
        if offset >= total:
            break
    def one(link):
        try:
            h = ats.get_text(HOST + link, headers={"Accept": "text/html"})
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            print(f"optiver: removed posting {link} (404)", file=sys.stderr)
            return None
        ld = next((j for j in (json.loads(x) for x in re.findall(r'<script[^>]*ld\+json[^>]*>(.*?)</script>', h, re.S)) if isinstance(j, dict) and j.get("@type") == "JobPosting"), {})
        text = ats.strip(h[h.find("<main"):h.rfind("</main>")] if "<main" in h else h)
        i = text.find("Apply", text.find("Apply") + 1)  # body starts after the second "Apply" button
        desc = re.sub(r"\s*Apply\s*$", "", text[i + 5:] if i > 0 else text).strip()
        loc, dep = links[link]
        return ats.row(cfg, "optiver", link.rstrip("/").rsplit("/", 1)[-1] + "-" + loc, ld.get("title") or re.sub(r"-", " ", link.rstrip("/").rsplit("/", 1)[-1]).title(),
                       (ld.get("jobLocation") or {}).get("name") or loc.replace("-", " ").title(), dep.replace("-", " "), ld.get("datePosted"), HOST + link, desc)
    return ats.detail_map(cfg, known, sorted(links), lambda l: l.rstrip("/").rsplit("/", 1)[-1] + "-" + links[l][0], one, workers=3)

FETCHERS = {"optiver": optiver}
US_FILTERED = {"optiver"}
