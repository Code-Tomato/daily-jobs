# The dataset

Published every day as a GitHub release of Code-Tomato/daily-jobs named `data-YYYY-MM-DD` (the last 7 are kept; the
newest is always `releases/latest`). `jobs.py update` downloads it; you can also use it directly.

| asset | what |
|---|---|
| `meta.json` | date, counts, levels and families, and every company's board status (`ok`, `failed`, `suspicious`) and last full refresh |
| `jobs.jsonl.gz` | one posting per line (fields below), ~25 MB |
| `excerpts.bin`, `excerpts.dict` | each posting's eligibility excerpt, compressed one by one; a row's `x: [offset, length]` locates it |

## Posting fields

Always present: `id`, `company`, `title`, `location`, `url`, `posted` (the board's date, may be empty), `seen` (the date
the scraper first saw it), `ats`, `category` (department, may be empty), `x`.

Present only when they say something (missing means unknown, false or empty):

| field | values | parsed from |
|---|---|---|
| `level` | intern, new-grad, entry, mid, senior, manager | title first ("Intern", "New Grad", "Engineer II", "Senior"), then the required years (≤1 entry, ≤4 mid, else senior) |
| `years` | integer | the largest "N+ years ... experience" among the required (not preferred) lines; with "HS + 8 or BS + 4 years", the bachelor's figure |
| `degree` | hs, associate, bs, ms, phd | the lowest degree the required lines name ("Bachelor's or Master's" is bs; "pursuing a PhD" is phd) |
| `term` | "Summer 2027" | internship and new-grad postings: the title, else the first term the text names |
| `pay` | [low, high, unit], unit hour/year/month/week | dollar ranges near pay words; bonuses, relocation and funding amounts are skipped |
| `remote` | remote, hybrid, onsite | the location and title, then clear sentences in the text |
| `states` | ["TX", "CA"] | state codes, state names and well-known cities in the location |
| `family` | software, data, hardware, mechanical, civil, science, healthcare, finance, product, business, sales, design, people, education, trades, engineering (other engineering) | the title (first matching family wins, then broader fallback words), else the category |
| `no_sponsor` | true | "will not sponsor", "without sponsorship now or in the future", "not eligible for visa sponsorship" |
| `citizen` | true | "must be a US citizen", "US persons" (ITAR/EAR), "citizens or permanent residents only"; equal-opportunity boilerplate ignored |
| `clearance` | true | a required security clearance (active, or the ability to obtain one) |
| `deadline` | YYYY-MM-DD | "apply by", "applications close", "deadline" followed by a date |
| `gpa` | "3.0" | a stated minimum GPA |

The parsers are in `scripts/signals.py`. They are heuristics over free text, right most of the time; the excerpt and
the posting are the authority.

## Without the script

```python
import gzip, json, urllib.request
base = "https://github.com/Code-Tomato/daily-jobs/releases/latest/download"
urllib.request.urlretrieve(f"{base}/jobs.jsonl.gz", "jobs.jsonl.gz")
rows = [json.loads(l) for l in gzip.open("jobs.jsonl.gz", "rt")]
interns = [r for r in rows if r.get("level") == "intern" and "TX" in r.get("states", [])]
```

pandas: `pd.read_json("jobs.jsonl.gz", lines=True)`.

One excerpt by HTTP range (use the release tag from `meta.json`, so offsets match):

```python
import zlib, urllib.request
zdict = urllib.request.urlopen(f"{base}/excerpts.dict").read()
off, n = row["x"]
req = urllib.request.Request(f"https://github.com/Code-Tomato/daily-jobs/releases/download/{tag}/excerpts.bin",
                             headers={"Range": f"bytes={off}-{off + n - 1}"})
text = zlib.decompressobj(-15, zdict=zdict).decompress(urllib.request.urlopen(req).read()).decode()
```

## Coverage and freshness

- US postings only (non-US rows are dropped by `ats.is_us`, a string match on the location).
- New postings are added every day. Closed ones drop out when their company gets a full refresh, at least weekly, so a
  posting can linger for a few days after it closes. `meta.json` has each board's last full refresh.
- A board that fails or suddenly returns far fewer postings keeps its previous rows and is marked `failed` or
  `suspicious` in `meta.json`.
- Not covered: Amazon (terms forbid automated extraction), sites behind bot walls (Meta, Tesla, Citadel, IBM...),
  defense contractors, and any company not in `scripts/companies.json`.
