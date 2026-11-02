"""Adapter plug-ins. Each adapters/<group>.py is auto-loaded by ats.py and must expose:

    FETCHERS = {"<ats_name>": fn, ...}
    US_FILTERED = {"<ats_name>", ...}   # optional: ATS names whose fn already restricts to US postings

Contract for every fn:

    def <ats_name>(cfg: dict, known: set = ()) -> list[dict]

- cfg is one entry from companies.json / companies.d/*.json. It always has "company" and "ats"; any other keys the
  adapter needs (host, slug, facet ids, filters) are documented in the function docstring.
- Return rows built ONLY with ats.row(cfg, ats_name, job_id, title, location, category, posted_iso, url,
  description_text, basic_text="", preferred_text=""). job_id must be the board's stable requisition/posting id.
- Filter to the US at the source when the API allows it and list the ats_name in US_FILTERED; otherwise return
  everything and fetch.py applies ats.is_us(location).
- If a per-job detail call is needed, go through ats.detail_map(cfg, known, items, key_fn, one_fn, workers=N) so
  ids already in `known` are skipped on daily runs. Keep workers low (2-4) for rate-limited hosts.
- Network via ats.get (JSON) / ats.get_text (str); both take data (POST), headers, opener (cookie reuse) and retry.
  HTML -> text via ats.strip.
- Raise on hard failure (fetch.py records it in fetch_status.json and keeps the board's cached rows). Log only to
  sys.stderr. Never write files. Never import or edit fetch.py / grade.py / report.py / daily.py.
"""
