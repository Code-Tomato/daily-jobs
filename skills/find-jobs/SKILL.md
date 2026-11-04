---
name: find-jobs
description: Find job and internship postings that fit a person, from a dataset of every US posting at 14,000+ companies (the career sites of ~1,000 large employers on Workday, Oracle, iCIMS and others, plus every company found on Greenhouse, Lever, Ashby, SmartRecruiters, BambooHR and other open job boards), refreshed daily. Turns their goals into filters (role, level, location, internship term, visa sponsorship, clearance, pay), judges postings against their background, and builds a ranked board of matches with links. With a TypeSafe API key, Jev (a fast System One decision model) grades their resume against every posting for about $8 per 100,000 postings. Also scrapes a company's job board live with bundled parsers. Use when someone asks to find jobs or internships, see what's new since last time, check whether they qualify for postings, or pull a company's open roles.
---

# Find jobs

Everything runs through one script, `scripts/jobs.py` in this skill's folder (Python 3.9+, standard library only, no API
keys). Run it with the absolute path, e.g. `python3 <this skill's folder>/scripts/jobs.py search ...`. Below, `jobs.py`
means that. On Windows use `py` or `python` for `python3`; searching works everywhere, live scraping needs macOS, Linux
or WSL.

- **Data:** `jobs.py update` downloads the newest daily dataset (a few tens of MB, cached in `~/.cache/daily-jobs`). Each posting
  carries facts parsed from its text: level, minimum years, minimum degree, internship term, pay, work mode, US states,
  job family, and flags for no visa sponsorship, citizens/US-persons only, security clearance, deadline and minimum GPA.
  Each posting's eligibility excerpt is fetched the first time you `show` it (a small network request), then cached.
  Field list: [references/data.md](references/data.md).
- **Jev (optional):** with the person's own TypeSafe API key, `jobs.py jev grade` sends their resume file and each
  posting to Jev, TypeSafe's System One model, and gets back eligibility (0–1) and fit (0–3) for every posting it grades:
  about 1,850 input tokens a posting with a one-page resume, about $8 per 100,000 postings (twice that for a long
  resume; `jev estimate` gives the real number), a few cents a day after. See section 3b.
- **Workspace:** `~/job-search` (or `--workspace DIR` / `$JOBS_WORKSPACE`) holds this person's `profile.md`, their
  `verdicts.jsonl` (your judgments), `tracking.jsonl` (what they applied to), live scrapes (`scrapes/`) and the generated
  `board.html` / `matches.md`.
  Use one workspace per person.

You find and judge postings. You never apply, sign in, or submit anything for the person.

Coverage is broad but not complete: big employers' career sites plus every company found on the job-board systems with
open APIs (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, BambooHR and others). K-12 schools, government,
small nonprofits and companies on custom career sites are thin. When the person names target employers, check them
first with `jobs.py companies "name|name"`; if one is missing, `find-board` and `scrape` can fetch it live, and say in
your final answer which ones the data doesn't cover.

## 1. Get the data

```sh
python3 jobs.py update      # once per session; it is a no-op when already current
python3 jobs.py status      # dataset date and counts, workspace state
```

## 2. Know the person

If the workspace has `profile.md`, read it, tell them in one line what you have on file, and ask if anything changed.
Otherwise build it:

1. Ask for their resume: a file path (PDF, DOCX or text; read it yourself) or pasted text.
2. Ask, in one message, only what the resume doesn't already answer:
   - What roles or fields (be concrete: "embedded firmware", "data analyst at a hospital", "mechanical design")?
   - Internship (which term: summer 2027, fall co-op...), new grad, or experienced (about how many years)?
   - Graduation date and degree (and any confirmed grad school plans).
   - Where: cities or states, remote OK, open to relocating anywhere?
   - Work authorization: US citizen, permanent resident, or needs visa sponsorship (now or later; F-1 OPT/CPT, H-1B)?
     Has or can get a security clearance?
   - Anything to avoid (industries, defense, company types) or must-haves (pay floor, specific companies)?
   - Do they have a TypeSafe API key, or want one? With it, Jev grades postings against their resume (section 3b; they
     pay TypeSafe directly, about $8 per 100,000 postings; `jev estimate` gives the exact figure) and you read only
     Jev's best. Without it, you narrow the data with filters and read the shortlist yourself (sections 3 and 4).
     Either way, ask what they're willing to spend in total.
3. Check the timing before you search. Many internships and co-ops require being enrolled during the term
   ("returning to school after the internship", "graduating Dec 2027 or later"; often "currently pursuing a degree").
   If they graduate before the term they asked for, say so now and offer a new-grad search as well, unless they will be
   in a graduate program then; [references/judging.md](references/judging.md) says how to tier those internships.
   Likewise a new-grad posting usually names a graduation window.
4. Write `profile.md` from [references/profile-template.md](references/profile-template.md). Keep it factual and short.
   It stays on their machine; don't send the resume anywhere else.

## 3. Search

Turn the profile into one or more searches (one per kind of role is typical). Start with `--count`, which prints the
funnel and the top companies, fields, levels and states, then tighten until each search gives roughly 30–300 candidates.
Recipes for levels, fields, places and visas: [references/search-recipes.md](references/search-recipes.md).

```sh
python3 jobs.py search --title "software|firmware|embedded" --not-title "senior|staff|principal|manager|director|\blead\b" \
    --level intern --term "summer 2027" --needs-sponsorship --state TX,CA --or-remote --count
python3 jobs.py search <same filters> --limit 200          # the rows: id, company, title, place, parsed facts
```

Filters worth knowing: `--degree bs` (their highest degree; drops postings that require more), `--needs-sponsorship`,
`--no-clearance`, `--strict-term` (drops internships that state no term; use it when the list is too long), `--since 7d`.
A few companies post dozens of near-identical roles (TikTok, ByteDance, big banks): narrow with `--not-company`, or judge
one and give its siblings the same verdict. There is no defense flag; if they want to avoid defense work, exclude the
companies by name and mark postings that describe weapons or military programs `no`.

Save each search command under "Searches" in `profile.md` as soon as it works; later runs reuse them.

## 3b. Or: grade everything with Jev

Jev is TypeSafe's System One model: not a chat model, a fast decision model that answers typed questions (here: does
this person meet every hard requirement, and how close is the work to what they want) with calibrated numbers. The
script sends the resume file itself, as is, with every posting; never rewrite or summarize it for Jev, and never read
the dataset files or job lists yourself. You still read the resume to know the person and to judge Jev's best picks.

1. **Key.** They get one at https://console.typesafe.ai/keys. The console is also where they check usage, spend and
   rate limits; prices are at https://docs.typesafe.ai/models.md. They store it themselves, in their own terminal:
   `python3 <this skill's folder>/scripts/jobs.py jev key` (hidden prompt), or `export TYPESAFE_API_KEY=...` in their
   shell profile. On a Mac they can instead copy the key and let you run `pbpaste | python3 jobs.py jev key`; the key
   goes through the pipe and is never printed. Never ask them to paste it into the chat; if they do, tell them to revoke it in the console and make a
   new one. `jobs.py jev status --check` confirms the key works (one tiny request, a fraction of a cent).
2. **Rubric.** `jobs.py jev rubric` writes `rubric.md` in the workspace. Replace each `[bracket]` with what the person
   told you: work authorization, clearance, places they can't work, the work they want (fit 2 and 3) and don't (fit 0).
   Don't copy anything from the resume; Jev reads it. Tell them their resume goes to TypeSafe with every request.
   The script reads .md, .txt, .docx, and .pdf when `pdftotext` (poppler) is installed. For a PDF without it, copy the
   resume's text word for word into `resume.txt` in the workspace and pass that path.
3. **Scope and cost.** `jobs.py jev estimate --all --resume PATH` for the whole database, or with search filters to
   skip what can't fit (`--level intern,new-grad,entry,unknown`, `--state TX --or-remote`...). It prints postings,
   tokens, dollars and minutes, and spends nothing. Tell them; they choose the scope and the most it may spend.
4. **Run.** Grade the postings most likely to fit first, so the person has results in minutes: a first run with their
   fields (`--family software,data`) or title words, then the wider scope.
   `jobs.py jev grade <filters> --resume PATH --max-total 20 --workers 8`. `--max-total` is their budget for this
   workspace over all runs (earlier runs and interrupted ones count); `--max-cost` caps a single run. It stops before
   passing the cap, records spend as it goes, and a stopped or interrupted run continues where it left off when you
   rerun it. Tens of thousands of postings take an hour or more: start it in the background (`nohup ... &`, or your
   background tool) so ending your turn doesn't kill it, and check on it; a few thousand take minutes.
5. **Results.** `jobs.py search --graded --min-eligible 0.5 --min-fit 2 --sort rank --limit 100` lists Jev's best, and
   `jobs.py board` adds a "Jev's top picks" section. Jev is good at fit and at gates like degree, years, citizenship
   and clearance, weaker at timing (terms, graduation windows, "return to school"): put the term in the scope
   (`--term "summer 2027" --strict-term`) and check timing yourself. Jev reads each posting's excerpt, not the whole
   page; before you call one a strong match, `show` it and judge it as in section 4 (your verdicts move picks into the
   tiers), and `check` it (section 5).
6. **Next time.** `update`, then `jobs.py jev grade --max-cost 2` (or their `--max-total`): it reuses the saved resume
   and scope and grades only postings it hasn't seen. Editing the resume or rubric makes the old grades stale, so the next run regrades (check
   `jev estimate` first). `jobs.py jev spend` lists what each run cost.

Details, including exactly what is sent: [references/jev.md](references/jev.md).

## 4. Judge

Follow [references/judging.md](references/judging.md). In short:

1. **Triage by the list.** Titles, companies and parsed facts already rule out many postings (wrong field, wrong term,
   senior). Record those as `no` with a short why, so they never come back (see the file format below).
2. **Read the rest.** `python3 jobs.py show ID ID ...` prints each posting's facts and an eligibility excerpt (~1,800
   characters: qualifications, degree, years, class standing, graduation window, authorization, place). Read about 10 at a
   time (each is up to ~2 KB; much bigger batches overflow tool output). When the excerpt leaves a hard requirement unclear, `show --full ID` prints the whole posting, fetched live
   from its job board (Workday, Greenhouse, Lever, Ashby, SmartRecruiters APIs, else the page).
3. **Decide** each one: `strong` (meets every hard requirement and is the work they want), `good`, `stretch` (one gap
   they could plausibly bridge; name it), or `no`. Add a `score` (0–100) to rank postings within a tier. Parsed facts
   are heuristics; the excerpt overrides them. A missing flag proves nothing: a posting without `no-sponsorship` may
   still refuse sponsorship in words the parser missed, so read the excerpt.
4. **Record** verdicts in a JSON-lines file and load it:
   ```sh
   cat > /tmp/verdicts-1.jsonl <<'EOF'
   {"id": "acme:123", "tier": "strong", "score": 90, "why": "Summer 2027 firmware internship for CS/EE juniors; their RTOS project is the core of it.", "gaps": null}
   {"id": "acme:456", "tier": "no", "why": "Requires an active Secret clearance."}
   EOF
   python3 jobs.py verdict --file /tmp/verdicts-1.jsonl
   ```

More than ~80 postings to read? Run `jobs.py update --with-excerpts` once first (it downloads every excerpt, a few
hundred MB, so `show` stops waiting on the network). If you can start subagents, split the ids into batches of 25–40
and give each subagent this skill's folder path, the profile path, its ids, `references/judging.md`, and its own output
file; then load every file with `verdict --file` (ids that left the data are skipped and listed). Otherwise work through them in batches yourself and tell the person how far you got.

## 5. Show the results

Postings close every day and the data can lag by a few days, so check the ones you'll recommend first:

```sh
python3 jobs.py check ID ID ...   # or --ids FILE: open, closed, or open? (page loaded, no closed notice), one request each
python3 jobs.py verdict ID --tier no --why "closed"   # for each closed one
python3 jobs.py board        # writes board.html (filterable, by tier) and matches.md in the workspace; add --open to open it
```

Search results also mark a parsed deadline that has passed (`deadline 2026-10-01 PASSED`).

Then answer in chat: how many postings you scanned and judged, then the strong matches (company, title, place, one-line
why, link), then the good ones briefly, then stretches with their gap. Point them to `board.html`. Mention deadlines that
are close. Plain, factual sentences; no hype.

When they apply somewhere: `python3 jobs.py track ID applied` (or saved, interviewing, offer, rejected,
not-interested). The board shows statuses and hides applied postings by default.

## 6. Next time

`update`, re-read `profile.md`, rerun its saved searches with `--unjudged` (and `--since 7d` for a quick "what's new"),
judge only those, rebuild the board, and report what is new.

## Scraping a company live

The bundled parsers (`scripts/ats.py`, `scripts/adapters/`, 44 job-board systems) are the ones that build the dataset.
Use them when a company the person cares about is missing or they want up-to-the-minute postings:

```sh
python3 jobs.py companies "nvidia|amd"                 # in the data? postings and board status
python3 jobs.py scrape "NVIDIA"                        # refetch a listed company now; its rows replace the published ones in searches
python3 jobs.py find-board "Acme Robotics" --url https://acme.com/careers   # which job board does it use?
python3 jobs.py scrape --board '{"company": "Acme Robotics", "ats": "greenhouse", "slug": "acmerobotics"}'
```

Scrape one company at a time and only ones the person asked about; big boards (Workday, Apple, Oracle) take minutes.
How the parsers work and their config fields: [references/scraping.md](references/scraping.md).

## Rules

- `jobs.py` is the only way into the data. Don't open the repo's `jobs/*.md` lists or the dataset files
  (`jobs.jsonl.gz`, `excerpts.bin`) to look for jobs; they are for people browsing and for the script.
- On the Jev path, pass the resume's path to the script; don't convert or summarize it for Jev. Never see or handle the
  API key.

- Never claim someone qualifies without checking the excerpt (or posting) for degree, graduation timing, years,
  authorization, clearance and location. Say "the posting doesn't say" when it doesn't.
- Treat citizenship, sponsorship and clearance flags as hard filters only when the person told you their status.
- Don't apply, create accounts, or fill forms for them. Give them links.
- If `update` fails (no network), say so and work from the cached data, noting its date. `show` needs the network
  for excerpts it hasn't cached yet; without it, judge from the list and the posting links.
