---
name: find-jobs
description: Find job and internship postings that fit a person, from a dataset of every US posting on ~1,000 company career sites (Greenhouse, Lever, Ashby, Workday, iCIMS, Oracle, Eightfold, Google, Apple and more) refreshed daily. Reads their resume, turns their goals into filters (role, level, location, internship term, visa sponsorship, clearance, pay), judges each shortlisted posting against their background, and builds a ranked board of matches with links. Also scrapes a company's job board live with bundled parsers. Use when someone asks to find jobs or internships, see what's new since last time, check whether they qualify for postings, or pull a company's open roles.
---

# Find jobs

Everything runs through one script, `scripts/jobs.py` in this skill's folder (Python 3.9+, standard library only, no API
keys). Run it with the absolute path, e.g. `python3 <this skill's folder>/scripts/jobs.py search ...`. Below, `jobs.py`
means that. On Windows use `py` or `python` for `python3`; searching works everywhere, live scraping needs macOS, Linux
or WSL.

- **Data:** `jobs.py update` downloads the newest daily dataset (~12 MB, cached in `~/.cache/daily-jobs`). Each posting
  carries facts parsed from its text: level, minimum years, minimum degree, internship term, pay, work mode, US states,
  job family, and flags for no visa sponsorship, citizens/US-persons only, security clearance, deadline and minimum GPA.
  Each posting's eligibility excerpt is fetched the first time you `show` it (a small network request), then cached.
  Field list: [references/data.md](references/data.md).
- **Workspace:** `~/job-search` (or `--workspace DIR` / `$JOBS_WORKSPACE`) holds this person's `profile.md`, their
  `verdicts.jsonl` (your judgments), `tracking.jsonl` (what they applied to) and the generated `board.html` / `matches.md`.
  Use one workspace per person.

You find and judge postings. You never apply, sign in, or submit anything for the person.

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
3. Check the timing before you search. Internships and co-ops almost always require being enrolled during the term
   ("currently pursuing a degree", "returning to school after the internship", "graduating Dec 2027 or later"). If they
   graduate before the term they asked for, say so now and offer a new-grad search instead, unless they will be in a
   graduate program then. Likewise a new-grad posting usually names a graduation window.
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

## 4. Judge

Follow [references/judging.md](references/judging.md). In short:

1. **Triage by the list.** Titles, companies and parsed facts already rule out many postings (wrong field, wrong term,
   senior). Record those as `no` with a short why, so they never come back (see the file format below).
2. **Read the rest.** `python3 jobs.py show ID ID ...` prints each posting's facts and an eligibility excerpt (~1,800
   characters: qualifications, degree, years, class standing, graduation window, authorization, place). Read 10–25 at a
   time. Open the posting URL only when the excerpt leaves a hard requirement unclear.
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

More than ~80 postings to read? If you can start subagents, split the ids into batches of 25–40 and give each subagent
this skill's folder path, the profile path, its ids, `references/judging.md`, and its own output file; then load every
file with `verdict --file`. Otherwise work through them in batches yourself and tell the person how far you got.

## 5. Show the results

```sh
python3 jobs.py board        # writes board.html (filterable, by tier) and matches.md in the workspace; add --open to open it
```

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

- Never claim someone qualifies without checking the excerpt (or posting) for degree, graduation timing, years,
  authorization, clearance and location. Say "the posting doesn't say" when it doesn't.
- Treat citizenship, sponsorship and clearance flags as hard filters only when the person told you their status.
- Don't apply, create accounts, or fill forms for them. Give them links.
- If `update` fails (no network), say so and work from the cached data, noting its date. `show` needs the network
  for excerpts it hasn't cached yet; without it, judge from the list and the posting links.
