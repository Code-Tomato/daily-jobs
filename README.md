# daily-jobs

Every US job posting from about 1,000 company career sites, scraped fresh every day, plus a Claude skill that reads
your resume and finds the ones you actually qualify for.

<!-- stats -->
**262,198 US job postings from 1,000 companies**, updated 2026-11-02 (7,438 first seen that day).

- [Internships and co-ops](jobs/internships.md): 10,990 open, 1,110 new this week
- [New grad and entry level](jobs/new-grad.md): 21,623 open, 3,468 new this week

<details><summary>Postings by field</summary>

| Field | Postings |
|---|---:|
| Healthcare | 48,449 |
| Business, consulting and operations | 47,520 |
| Finance, accounting and banking | 25,936 |
| Skilled trades, service and retail | 25,746 |
| Software engineering | 25,064 |
| Sales, marketing and communications | 14,571 |
| Data, ML and AI | 13,000 |
| Other | 12,973 |
| Mechanical, aerospace and manufacturing | 12,935 |
| Hardware, chips and embedded | 10,026 |
| Product, program and project management | 6,779 |
| Other engineering | 4,913 |
| Civil, construction and environmental | 4,482 |
| HR, legal and policy | 4,007 |
| Science and research | 3,556 |
| Design and creative | 1,528 |
| Education | 713 |

</details>

Boards that failed or looked wrong on their last check (their older postings are kept): Autodesk, Dexterity, Houston Methodist, MD Anderson, Old Mission, Prosperity Bank, Service Corporation International, Tempus.
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
- `companies.json`: the 1,000+ boards scraped every day.
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
