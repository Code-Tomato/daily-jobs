# The scrapers

`scripts/ats.py` and `scripts/adapters/*.py` are the parsers that build the dataset every day. They read each company's
public job-board API or careers pages and return every posting in one normalized shape. You can use them on their own.

## Row shape

Every scraper returns a list of dicts built by `ats.row(...)`:

```
id           "<company-lowercase>:<the board's own posting id>"
company      as configured
ats          scraper name (greenhouse, workday, ...)
title, location, category (department when the board has one), posted (YYYY-MM-DD when the board gives it), url
description  plain text of the posting
basic, preferred   qualifications, when the board splits them out (otherwise "", and they are inside description)
```

`signals.facts(row)` adds the parsed facts (level, years, degree, pay, flags...) and `signals.excerpt(row)` the
eligibility excerpt; `jobs.py scrape` does both and saves the rows where searches find them.

## Using a scraper from Python

```python
import sys; sys.path.insert(0, "<skill folder>/scripts")
import os; os.chdir("<skill folder>/scripts")       # ats.py loads adapters/ and companies.json from here
import ats, signals
rows = ats.FETCHERS["greenhouse"]({"company": "Anthropic", "ats": "greenhouse", "slug": "anthropic"})
us = [r for r in rows if ats.is_us(r["location"])]   # boards not in ats.US_FILTERED return every country
print(len(us), us[0]["title"], signals.facts(us[0]))
```

`ats.FETCHERS[name](cfg, known=set())`: ids in `known` skip their per-posting detail call (that is how the daily run
stays fast). Network goes through `ats.get` / `ats.get_text` (retries 429s and 5xx with backoff).

## Supported job boards

`companies.json` lists every board the dataset scrapes (one JSON object per line). The config fields each scraper needs
are in its docstring (`python3 -c "import ats; help(ats.FETCHERS['workday'])"` from `scripts/`).

| scraper | what it reads | config |
|---|---|---|
| greenhouse | boards-api.greenhouse.io | `slug` (job-boards.greenhouse.io/<slug>) |
| lever | api.lever.co | `slug`, optional `region: "eu"` |
| ashby | api.ashbyhq.com posting API | `slug` (jobs.ashbyhq.com/<slug>) |
| smartrecruiters | api.smartrecruiters.com | `slug`, optional `country: "us"` |
| workable, rippling | public widget / board APIs | `slug` |
| workday | <tenant>.wd<N>.myworkdayjobs.com/wday/cxs | `host`, `tenant`, `site`, optional `facets` (US filter), `prefilter_us` |
| oraclehcm | Oracle Recruiting Cloud REST | `host`, `site`, `us_filter` |
| avature | Avature career portals | `host`, `list_path`, ... |
| successfactors | SAP SuccessFactors RMK sitemaps and job pages | `host`, ... |
| taleo | Taleo career sections | `host`, `section`, ... |
| icims, jibe, radancy | iCIMS portals, Jibe and Radancy career sites | `host`, `country` / `facet` |
| eightfold, eightfold_pcsx, phenom, gem | Eightfold (old and PCSX APIs), Phenom, Gem | `host`, `domain`, `country`, `slug` |
| apple, google, atlassian, bytedance, goldman, optiver, swri | those companies' own sites | mostly none |
| ukg, dayforce, paylocity, paycor, adp | HR-suite job boards | `board`, `namespace`, `guid`, ... |
| jobvite, comeet, bamboohr, recruitee, teamtailor, breezy, pinpoint | small-company ATSs | `slug` / `feed` |
| brassring, peopleadmin, oleeo, coveo | university and campus systems | see docstrings |
| jsonld | catch-all: any site whose job pages carry JSON-LD `JobPosting` | `list_url` or sitemap + `link_regex` |
| inline_json | pages that embed the job list as a JavaScript variable | see docstring |

`neogov` exists but is not used for the dataset: governmentjobs.com's robots.txt admits only named search engines.
Amazon is not in the dataset because amazon.jobs' terms forbid automated extraction.

## Adding a company

1. `python3 jobs.py companies "<name>"`: maybe it's already there.
2. Find its board. Open its careers page, click any job, read the address: `job-boards.greenhouse.io/<slug>`,
   `jobs.lever.co/<slug>`, `jobs.ashbyhq.com/<slug>`, `<tenant>.wd5.myworkdayjobs.com/<site>`, `*.icims.com`,
   `*.oraclecloud.com`, `*.eightfold.ai`... Or run `python3 jobs.py find-board "<name>" --url <careers page>`, which
   tries the common APIs and scans the page for job-board links (an iframe or a JavaScript-loaded list can hide them).
3. `python3 jobs.py scrape --board '<config JSON>'` to fetch it now.
4. To get it into the shared daily dataset, open an issue or pull request on the repo with the config line.

## Good manners

The scrapers identify as a normal browser, pace the systems known to rate-limit (Workday, Eightfold), and only read
public job listings. Scrape single companies on request, not the whole list in a loop: the daily dataset already does
that once a day for everyone.
