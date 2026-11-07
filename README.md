# daily-jobs

Every US job posting from more than 14,000 companies, scraped fresh every day, plus a Claude skill that reads your
resume and finds the ones you actually qualify for. The companies are the career sites of about 1,000 large employers
(Workday, Oracle, iCIMS, Phenom and others) plus every company we could find on the job-board systems with open APIs:
Greenhouse, Lever, Ashby, SmartRecruiters, Workable, BambooHR, Breezy, Rippling, Recruitee, Teamtailor, Pinpoint and Gem.

<!-- stats -->
**639,398 US job postings from 20,608 companies**, updated 2026-11-07 (28,658 first seen that day).

- [Internships and co-ops](jobs/internships.md): 17,640 open, 8,564 new this week
- [New grad and entry level](jobs/new-grad.md): 49,900 open, 34,638 new this week

<details><summary>Postings by field</summary>

| Field | Postings |
|---|---:|
| Business, consulting and operations | 131,293 |
| Healthcare | 97,162 |
| Skilled trades, service and retail | 69,356 |
| Sales, marketing and communications | 56,449 |
| Software engineering | 52,441 |
| Other | 47,578 |
| Finance, accounting and banking | 37,417 |
| Mechanical, aerospace and manufacturing | 27,015 |
| Data, ML and AI | 26,499 |
| Hardware, chips and embedded | 17,910 |
| Civil, construction and environmental | 16,767 |
| Product, program and project management | 14,899 |
| HR, legal and policy | 13,777 |
| Other engineering | 9,707 |
| Education | 8,573 |
| Science and research | 7,434 |
| Design and creative | 5,121 |

</details>

999 companies are a curated list; 19,609 more were found on the job-board systems with open APIs (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, BambooHR and others) and are checked daily (9 failed on their last check).

Curated boards that failed or looked wrong on their last check (their older postings are kept): Albertsons, American Express, Atmos Energy, Autodesk, Canva, Deloitte, Fluor, MD Anderson, Navy Federal Credit Union, Nielsen, Old Mission, Southwest Airlines, Synchrony, TIAA, UPS, United Airlines, Valaris.
<!-- /stats -->

## Three ways to use it

### 1. Ask Claude (the skill)

The `find-jobs` skill downloads the day's data, asks about what you want (roles, internship term or years, places,
visa needs), filters ~260k postings down to a shortlist, reads each one's requirements against your resume, and writes
you a board of strong, good and stretch matches with links. Next time it only shows what's new. No API keys, no
accounts; it runs on your machine with Python 3.9+.

**Claude Code:**

```
/plugin marketplace add Code-Tomato/daily-jobs
/plugin install daily-jobs@daily-jobs
```

Then ask: *"Find me summer 2027 software internships that fit my resume at ~/resume.pdf"*, or *"What's new on the job
board for me?"*

**Grade everything with Jev (optional).** With your own [TypeSafe](https://console.typesafe.ai/keys) API key, the skill
can have Jev, TypeSafe's System One model, read your resume against every posting in the database and rank them all by
eligibility and fit: about $8 per 100,000 postings (it tells you the exact cost first), a few cents a day after that,
with a hard spending cap you set. The script sends your resume file as is; you type the key into a hidden prompt, never into the chat. Details:
[references/jev.md](skills/find-jobs/references/jev.md).

**Other agents** (Codex, Cursor, Gemini CLI, ...): `npx skills add Code-Tomato/daily-jobs`, or copy
[`skills/find-jobs`](skills/find-jobs) into your agent's skills folder (`~/.claude/skills/`, `~/.codex/skills/`, ...).

**No agent:** the skill's script works by hand too.

```sh
git clone --depth 1 https://github.com/Code-Tomato/daily-jobs && cd daily-jobs/skills/find-jobs/scripts
python3 jobs.py update
python3 jobs.py search --level intern --term "summer 2027" --title "software|firmware" --state TX --or-remote
python3 jobs.py show <id>          # requirements excerpt for a posting
python3 jobs.py --help
```

### 2. Browse the lists

[Internships and co-ops](jobs/internships.md) and [new grad and entry-level roles](jobs/new-grad.md), split by field,
newest first, rebuilt every day. Each row links to the posting and flags "no visa sponsorship", "US citizens only" and
"clearance" when the posting says so.

### 3. Use the data

Each day's data is a [release](https://github.com/Code-Tomato/daily-jobs/releases/latest): `jobs.jsonl.gz` has one
posting per line with fields parsed from its text (level, minimum years, degree, internship term, pay, remote, states,
job family, sponsorship / citizenship / clearance flags, deadline, minimum GPA).

```python
import gzip, json, urllib.request
urllib.request.urlretrieve("https://github.com/Code-Tomato/daily-jobs/releases/latest/download/jobs.jsonl.gz", "jobs.jsonl.gz")
jobs = [json.loads(line) for line in gzip.open("jobs.jsonl.gz", "rt")]
```

Fields and formats: [skills/find-jobs/references/data.md](skills/find-jobs/references/data.md).

## The scrapers

[`skills/find-jobs/scripts`](skills/find-jobs/scripts) holds the parsers that build the data, and they ship inside the
skill so you can run them yourself:

- `ats.py` and `adapters/`: 44 job-board systems (Greenhouse, Lever, Ashby, Workday, Oracle, SuccessFactors, Taleo,
  iCIMS, Eightfold, Phenom, Avature, UKG, Dayforce, BrassRing, PeopleAdmin, Apple, Google, ByteDance, any site with
  JSON-LD job pages, and more). Each returns postings in one normalized shape.
- `companies.json`: the ~1,000 curated boards; `companies-found.json`: the boards found on the open-API systems
  (Common Crawl's URL index plus name guesses, each checked against the board's API). Both are scraped every day.
- `signals.py`: the text parsers that pull level, years, degree, pay, term, location and eligibility flags out of a posting.
- `jobs.py scrape "Company"` refetches one company live; `jobs.py find-board "Company" --url <careers page>` works out
  which system a company uses so you can scrape one that isn't listed.

How they work and how to add a company: [references/scraping.md](skills/find-jobs/references/scraping.md). To get a
company into the daily data, open an issue or a pull request with its config line.

## How it's made

A home server runs the scrapers every morning (Central time): new postings from every board, plus a full refresh of
each company at least weekly, which drops closed roles. Then [`tools/publish.py`](tools/publish.py) parses every
posting, rebuilds the lists above and publishes the release. The last 7 daily releases are kept.

## Caveats

- US postings only. Companies behind bot walls (Meta, Tesla, Citadel, IBM...) aren't covered, and Amazon is left out on
  purpose: its terms forbid automated extraction. Defense contractors are left out too.
- Closed postings can linger for a few days until their company's next full refresh.
- The parsed fields are heuristics over free text. They're right most of the time; the posting is the authority.
- Postings belong to their employers. This repo only collects public listings and links back to them.

## License

Code: MIT ([LICENSE](LICENSE)). The job postings are the employers' own public listings.
