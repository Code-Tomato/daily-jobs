# Grading with Jev

`jobs.py jev` grades postings against a person's resume with Jev, TypeSafe's System One model, through
`POST https://api.typesafe.ai/v1/systemone`. The code is `scripts/jev.py`; nothing outside it talks to TypeSafe.

## What is sent

One request per posting:

```json
{
  "model": "jev-latest",
  "state": {
    "today": "2026-11-03",
    "resume": "<the resume file's text, unchanged>",
    "job": {"company": "...", "title": "...", "location": "...", "posted": "...", "team": "...", "excerpt": "<~1,800 characters>"}
  },
  "questions": {
    "eligible": {"type": "noul", "instructions": {"question": "Does the candidate in `resume` pass the hard gates `job` sets ...", "rules": ["<rubric.md's eligibility bullets>"]}, "criteria": {"true": "...", "false": "..."}},
    "fit": {"type": "score", "instructions": "How closely does the day-to-day work in `job` match ...", "criteria": ["<rubric.md's four fit levels>"]}
  }
}
```

- The resume is read from the file the person names: `.md` and `.txt` as they are, `.docx` from its text, `.pdf`
  through `pdftotext` (poppler) when it's installed. Up to 40,000 characters, sent as is: the agent reads the resume to
  know the person, but never rewrites or summarizes it for Jev.
- The excerpt is the same one `jobs.py show` prints: the lines of the posting about qualifications, degree, years,
  class standing, graduation window, authorization and place.
- The answers kept per posting: `eligible` (0–1, the probability every hard requirement is met), `fit` (0–3 on the
  rubric's levels), the fit confidence, and the model version that answered.

## Cost and speed

Jev bills input tokens only (output is free). On 2026-11-04 it was $0.042 per million tokens; `estimate` and `grade`
read the current price from https://docs.typesafe.ai/models.md every run (pass `--price-per-mtok` if that page can't be
read). Every request carries the whole resume, so its length sets the price: a request measured about 1,850 tokens
with a one-page resume ($0.00008 a posting, about $8 per 100,000 postings) and about 3,950 with a detailed two-page one
(about $17 per 100,000). A day's new postings cost cents. Run `estimate` for the real figure.

Jev answers in about 0.4 s. Throughput is set by `--workers`: in the November 2026 tests 8 workers graded about 260
postings a minute and 32 about 1,500, with no rate limiting (429). Use 16 to 32 for runs of tens of thousands; a 429 or
529 (rate limit, overload) is retried with backoff, and each organization's limits are on https://console.typesafe.ai
(rate limits page). Grade the likeliest postings first (`grade` orders titles that match the rubric's top fit levels
first), then widen: results arrive while the long run continues.

## Safety rails

- `--max-cost` (this run) or `--max-total` (the workspace, all runs together) is required; the run reserves a
  pessimistic cost before each request and stops before it could pass the cap. Actual spend comes from the API's own
  `usage.input_tokens`: each grade in `grades.jsonl` carries its tokens, and `jev-spend.jsonl` gets a checkpoint every
  20 seconds and at the end, so a killed run still counts. The console shows TypeSafe's own record.
- A 401/403 (bad or revoked key) or 402 stops the run at once. A posting that fails after retries is skipped and retried
  on the next run.
- Grades are appended to `grades.jsonl` as they arrive, keyed by posting id and a hash of resume + rubric + model. An
  interrupted run loses nothing; rerunning skips what's graded. Changing the resume, rubric or model makes old grades
  stale (`search --graded` ignores them) and the next run regrades.
- The key lives in `$TYPESAFE_API_KEY` or `~/.config/daily-jobs/typesafe_key` (mode 600). The script never prints it.

## Reading the grades

- `search --graded --min-eligible 0.5 --min-fit 2 --sort rank`: rank is fit × eligible.
- `search --ungraded`: what Jev hasn't seen (new postings, or ones outside the graded scope).
- `show ID`: the excerpt plus Jev's numbers.
- `board`: verdict tiers plus "Jev's top picks, not reviewed yet" (eligible ≥ 0.5, fit ≥ 2, best 150).

Jev's eligibility is only as good as the rubric and the excerpt. For the top picks, read the excerpt and record a
verdict; that is what puts a posting in the strong / good / stretch tiers.
