# Judging a posting

You decide two things for each posting: does the person meet its hard requirements at the time the job starts, and is the
work what they want. Then you pick a tier and write one or two plain sentences.

## Tiers

| tier | meaning |
|---|---|
| `strong` | Meets every hard requirement, and the day-to-day work is squarely what they want (their core field or interests). Apply now. |
| `good` | Meets every hard requirement and the work is reasonably close to what they want, or squarely theirs with one soft doubt. Worth applying. |
| `stretch` | One gap they could plausibly bridge: a year short on experience, a "required" skill they have only from coursework, a degree field that is adjacent. Name the gap. |
| `no` | Fails a hard requirement, or the work isn't what they're looking for. |

Unclear is not the same as met: if the posting states a hard requirement you can't check against the profile (a
graduation window cut off in the excerpt, a license they may or may not have), the best tier is `good`, and `gaps` says
what to confirm. Silence is different. Most postings say nothing about visas; for someone who needs sponsorship, silence
is not a failed requirement (large employers routinely hire interns on CPT and new grads on OPT), so it can still be
`strong`, with "The posting doesn't say whether it sponsors visas" in `gaps`.

Give each verdict a `score` from 0 to 100 too: your overall sense of the match, used only to order postings within a
tier (two `good` postings are rarely equally good).

## Hard requirements, in the order to check them

1. **Level and timing.** Internship or co-op: does the term match what they want (summer 2027, fall co-op)? Does the
   posting restrict class standing ("rising seniors", "sophomores and juniors", "graduating between Dec 2026 and
   Jun 2027", "must return to school after the internship")? Check against their graduation date. For someone who
   graduates before the internship starts (May 2027 grad, summer 2027 internship) and has no confirmed grad school:
   - `no` when the posting requires returning to school after it, enrollment during it, or a graduation date after it.
   - `stretch` when it only says "currently pursuing a degree" or "students": many such programs mean enrolled during
     the internship, some only at application. Gap: "may require enrollment during the internship; you graduate first".
   Don't assume grad school unless the profile says it's confirmed. New grad: does their graduation date fall in the
   window?
2. **Degree.** A required degree they don't have by the start date fails ("Master's required" for a BS student; a
   bachelor's required for a role starting before they graduate, unless the posting allows finishing by then). A
   degree field that is listed with "or related field" usually passes for adjacent majors.
3. **Experience.** Count internships, co-ops and research as experience, but only so far: about two years of internships
   and research satisfy "1+ years of experience" or "internship experience", not "3+ years" and not "N years of
   non-internship / full-time / professional experience" for N ≥ 2. A posting that asks for 2–3 years is at most a
   `stretch` for a new grad with strong internships.
4. **Work authorization.** If they need sponsorship (now or later), "will not sponsor", "must be authorized without
   sponsorship now or in the future", "US citizens only", ITAR/EAR "US person" (citizens and permanent residents) all
   fail. If they are a US citizen, none of these matter. Don't guess their status; use the profile.
5. **Clearance.** A required active clearance fails unless they have one. "Ability to obtain" passes for citizens who
   are fine with it, and fails for non-citizens.
6. **Location.** Onsite in a place they won't move to fails. Remote-in-the-US passes for anyone in the US.
7. **Other gates.** Minimum GPA, licenses or certifications (RN, CPA, PE, CDL), required languages, travel, physical
   requirements, shift work. Check only what the posting states.

Also note, without changing the tier on its own: a `posted` date many months old (evergreen or stale listing; say
"posted in May 2025, may be an evergreen req"), and a deadline that is past or within days.

## Fit

How close is the day-to-day work to what they've done and what they said they want? Read the responsibilities and the
required skills, not just the title: "Software Engineer" at a chip company may be RTL verification; "Analyst" may be
SQL dashboards or investment banking. A role they could do but that uses none of their background is `good` at best.

## Writing `why` and `gaps`

- `why`: one or two factual sentences naming the role and the reason it fits: "Summer 2027 firmware internship for EE
  juniors; their STM32 motor-control project is the core of the work." For `no`, the reason it fails: "Requires an
  active TS/SCI clearance." or "Senior role asking for 6+ years."
- `gaps`: what may hold them back, or null. "Asks for 2 years of professional experience; they have internships."
- Plain sentences, no dashes as punctuation, no hype, no exclamation marks. Never invent facts the posting doesn't state.

## Verdict file format

One JSON object per line, then `python3 jobs.py verdict --file FILE`:

```json
{"id": "acme:123", "tier": "strong", "score": 92, "why": "…", "gaps": null}
{"id": "acme:456", "tier": "stretch", "score": 55, "why": "…", "gaps": "Asks for 2+ years of experience."}
{"id": "acme:789", "tier": "no", "why": "Requires a master's degree."}
```

Recording `no` verdicts matters: `search --unjudged` hides every judged posting, so next time only new ones come back.

Near-duplicates: when a company posts the same role many times (one per team or city), read one or two, then give the
rest the same verdict with the same why. Don't let one company fill the strong tier with copies; say "and N similar
postings" in your summary instead.

## Nursing and other licensed health roles

- **License timing.** A new nurse takes the NCLEX after graduating. "RN license required at start" is met if the start
  date leaves time for it (residency cohorts usually do); "active RN license required" at application is not met yet.
  Same pattern for pharmacists, therapists and other licensed roles.
- **Residencies and cohorts.** New-grad RN jobs are mostly residency programs with cohorts (Spring, Summer, Fall) and
  graduation windows ("graduating between Dec 2026 and May 2027"). Match the cohort to their graduation and NCLEX date;
  a closed application window is `no` even if the posting is still listed.
- **Experience templates.** Health systems post hundreds of near-identical roles. Find the template sentence once
  ("12 months of recent RN experience required", "new graduates welcome", "not for new graduates") and use
  `search ... --text "<that sentence>"` to tier every sibling at once; spot-check a few.
- **Technician experience.** PCT, CNA or student-nurse work counts as health care experience, not as RN experience: a
  posting that asks for "1 year of RN experience" is not met by it, while "experience preferred" is a gap, not a no.
