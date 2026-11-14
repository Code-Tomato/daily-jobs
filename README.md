# daily-jobs

Every US job posting from more than 14,000 companies, scraped fresh every day, plus a Claude skill that reads your
resume and finds the ones you actually qualify for. The companies are the career sites of about 1,000 large employers
(Workday, Oracle, iCIMS, Phenom and others) plus every company we could find on the job-board systems with open APIs:
Greenhouse, Lever, Ashby, SmartRecruiters, Workable, BambooHR, Breezy, Rippling, Recruitee, Teamtailor, Pinpoint and Gem.

<!-- stats -->
**637,808 US job postings from 20,527 companies**, updated 2026-11-14 (10,477 first seen that day).

- [Internships and co-ops](jobs/internships.md): 17,485 open, 1,661 new this week
- [New grad and entry level](jobs/new-grad.md): 49,281 open, 5,861 new this week

<details><summary>Postings by field</summary>

| Field | Postings |
|---|---:|
| Business, consulting and operations | 131,821 |
| Healthcare | 96,422 |
| Skilled trades, service and retail | 70,139 |
| Sales, marketing and communications | 56,356 |
| Software engineering | 51,729 |
| Other | 47,483 |
| Finance, accounting and banking | 37,078 |
| Mechanical, aerospace and manufacturing | 26,967 |
| Data, ML and AI | 26,108 |
| Hardware, chips and embedded | 17,829 |
| Civil, construction and environmental | 16,662 |
| Product, program and project management | 14,658 |
| HR, legal and policy | 13,977 |
| Other engineering | 9,507 |
| Education | 8,687 |
| Science and research | 7,300 |
| Design and creative | 5,085 |

</details>

999 companies are a curated list; 19,528 more were found on the job-board systems with open APIs (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, BambooHR and others) and are checked daily (37 failed on their last check).

Curated boards that failed or looked wrong on their last check (their older postings are kept): AEP, AIG, AT&T, Abbott, Academy Sports + Outdoors, Adobe, Albemarle, Albertsons, Allstate, Ally Financial, Altera, American Express, American Family Insurance, Ameriprise Financial, Amgen, Analog Devices, Applied Materials, Argonne National Laboratory, Ascend Performance Materials, Austin Community College, Autodesk, BD, Baker Hughes, Bank of America, BlackRock, Blue Origin, Boom Supersonic, Boston Dynamics, Broadcom, Broadridge, Brookhaven National Laboratory, CME Group, CNA Insurance, Cadence, Calpine, Canva, Capital Group, CarMax, Cardinal Health, Caterpillar, Cboe, Centene, Chipotle, Ciena, Citi, ConocoPhillips, Cook Children's, Corebridge Financial, Corva, Cox Enterprises, CrowdStrike, Danaher, Deloitte, Dexcom, Dick's Sporting Goods, Disney, Dow, ERCOT, East Texas A&M University, Edwards Lifesciences, Elevance Health, Entegris, FICO, FIS, Fannie Mae, Fidelity Investments, Fifth Third Bank, Flowserve, Fluor, FormFactor, Fox Corporation, Fractal Analytics, GE Aerospace, GE HealthCare, GEICO, GM, Gap Inc., Gilead Sciences, Global Payments, GlobalFoundries, Grubhub, Guidehouse, HCSC, HP Inc, HPE, Harman, Home Depot, Huntsman, Huron, IQVIA, Illumina, Intel, Invesco, JetZero, Johnson & Johnson, KLA, KeyBank, Kimberly-Clark, Kyndryl, LPL Financial, Liberty Mutual, Lowe's, M&T Bank, MD Anderson, MKS Instruments, Marathon Petroleum, Marsh McLennan, Marvell, MassMutual, Mastercard, Medtronic, Methodist Health System, Micron, Mizuho Americas, Morgan Stanley, Motiva, Motorola Solutions, NVIDIA, NXP, Nasdaq, Nationwide, Navy Federal Credit Union, Netflix, New York Life, Nielsen, Nike, Noble Corporation, Northern Trust, Northwestern Mutual, ONEOK, Oaktree Capital Management, Old Mission, Onto Innovation, PIMCO, PNC, PTC, Palo Alto Networks, PayPal, Plains All American, Positron, Prairie View A&M University, Priceline, Protiviti, Prudential, Qorvo, Quantiphi, RSM US, Rackspace, Raymond James, RingCentral, Rippling, Rockwell Automation, S&P Global, SWBC, SailPoint, Semtech, Service Corporation International, ServiceTitan, Sharp HealthCare, SiFive, Sierra Space, Silicon Labs, Snap, Sony, Southwest Airlines, Stewart Information Services, Stryker, Synchrony, Sysco, T-Mobile, TIAA, Target, Tarleton State University, Texas A&M AgriLife Extension, Texas A&M AgriLife Research, Texas A&M Engineering Experiment Station (TEES), Texas A&M International University, Texas A&M Transportation Institute, Texas A&M University, Texas A&M University System Offices, Texas A&M University at Galveston, Texas A&M University-Corpus Christi, Texas A&M University-Kingsville, Texas A&M University-San Antonio, Texas A&M University-Texarkana, Texas Mutual Insurance, Thermo Fisher Scientific, Thomson Reuters, Thrivent, Transocean, Travelers, Trimble, TrueCar, U.S. Bank, UPS, USAA, United Airlines, Unity, University of Chicago, University of Texas at Austin, Unum, Valaris, Vanguard, Viavi Solutions, Visa, Waste Connections, Wells Fargo, West Texas A&M University, Westlake, Workday, Xcel Energy, Zendesk, Zillow, athenahealth, iHeartMedia.
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
