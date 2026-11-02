"""Careers pages that inline their job list as a JS global, e.g. `window.__AYAR_CAREER_JOBS__ = [...]` (Ayar Labs, fed by Paycor).

cfg: page (URL), var (JS global name). Rows come straight from the array; keys seen: id, title, department, city, state, country,
summary (HTML), status, employmentType, url, applyUrl. Posted date is whatever key looks like a date, else "".
"""
import json, re
import ats

def inline_json(cfg, known=()):
    h = ats.get_text(cfg["page"], headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
    m = re.search(re.escape(cfg["var"]) + r"\s*=\s*", h)
    if not m:
        raise RuntimeError(f"{cfg['var']} not found on {cfg['page']}")
    jobs, _ = json.JSONDecoder().raw_decode(h[m.end():])
    out = []
    for j in jobs:
        if str(j.get("status", "Normal")).lower() not in ("normal", "open", "active", ""):
            continue
        loc = ", ".join(filter(None, [j.get("city"), j.get("state"), j.get("country")]))
        if not (re.search(r"united states|usa|\bus\b|remote", loc, re.I) or not j.get("country")):
            continue
        posted = next((str(v)[:10] for k, v in j.items() if re.search(r"date|created|posted|updated", k, re.I) and v), "")
        out.append(ats.row(cfg, "inline_json", j["id"], j.get("title"), loc, j.get("department"), posted,
                           j.get("url") or j.get("applyUrl"), ats.strip(j.get("summary") or j.get("description"))))
    return out

FETCHERS = {"inline_json": inline_json}
US_FILTERED = {"inline_json"}
