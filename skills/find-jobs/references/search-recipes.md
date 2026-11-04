# Search recipes

`python3 jobs.py search [filters] --count` first, then the same filters with `--limit 200`. Every filter is optional;
repeating a flag ORs its values (`--title A --title B`), and different flags AND together.

## Level

| person | filters |
|---|---|
| internship / co-op | `--level intern --term "summer 2027"` (postings that don't name a term pass; `--strict-term` drops them) |
| new grad | `--level new-grad,entry,unknown --max-years 1` |
| 1–3 years | `--level entry,mid,unknown --max-years 3` |
| experienced | `--level mid,senior,unknown` plus a `--max-years` a bit above theirs |

`unknown` matters: many postings say nothing about level in the title, so `level` is set from the stated years, and is
empty when there are none. `--max-years` lets postings that state no minimum through.

Always add `--not-title "senior|\bsr\b|staff|principal|\blead\b|manager|director|head of|\bvp\b"` for students and new
grads; it catches titles the level parser missed. Use `\b` around short words so they don't match inside longer ones.

Degree: `--degree bs` drops postings whose required degree is above the person's (MS/PhD internships, "enrolled in a
graduate program"). Postings that name no degree pass.

## Fields (title regexes)

| field | `--title` | also |
|---|---|---|
| software | `software|\bsw\b|developer|\bswe\b|\bsde\b|full.?stack|back.?end|front.?end|platform|infrastructure|devops|\bsre\b|mobile|\bios\b|android|engineering intern` | `--family software` |
| systems / low level | `firmware|embedded|kernel|compiler|operating system|gpu|systems software|performance|hpc` | |
| ML / AI | `machine learning|\bml\b|\bai\b|deep learning|llm|nlp|computer vision|research (engineer|scientist)|applied scientist` | `--family data` |
| data | `data (scien|analy|engineer)|analytics|business intelligence|statistic|quantitative` | |
| hardware / chips | `hardware|asic|fpga|rtl|verification|silicon|analog|circuit|physical design|validation|electrical` | `--family hardware` |
| mechanical / aero | `mechanical|aerospace|propulsion|structures|thermal|manufacturing|robotics|controls|gnc` | `--family mechanical` |
| civil / construction | `civil|structural|construction|geotechnical|transportation|water resources|project engineer` | `--family civil` |
| chem / bio / lab | `chemi|biolog|biomedical|bioengineer|laboratory|research associate|process (engineer|development)` | `--family science` |
| finance | `investment banking|analyst|finance|financial|accounting|audit|tax|trading|quant|risk` | `--family finance` |
| consulting / business | `consult|strategy|business analyst|operations|rotational|leadership development` | `--family business` |
| product / program | `product manager|associate product|program manager|project manager` | `--family product` |
| design | `designer|ux|ui|user research|product design` | `--family design` |
| nursing / health | `nurse|rn\b|new grad rn|clinical|therapist|pharmac` | `--family healthcare` |
| learning / training / edtech | `instructional design|learning (experience|design|and development|& development)|\bl&d\b|curriculum|training (specialist|manager|developer)|enablement|customer education|e-?learning|implementation specialist|customer success` | `--family education,people,business,other`; these roles are filed under several fields, so prefer the title regex, or `--family education --or-title "..."` |
| career changer | the title regex for the new field, `--level entry,mid,unknown`, and no `--max-years` until you've seen the funnel | judge "N years as a <new title>" as a gap, not a pass |

`--family` is a coarse guess from the title (see `status` for the list); prefer `--title` regexes, and use `--family` to
narrow a big result or to browse. `--category REGEX` matches the board's own department label when it has one.

## Place

- A state or several: `--state TX,CA` (parsed from the location; multi-city postings list every state they name).
- Cities: `--location "austin|round rock|san marcos"`. Both together OR.
- Remote too: add `--or-remote`. Remote only: `--remote`.
- Anywhere in the US: no place filter (the dataset is US-only).

## Work authorization and clearance

- Needs sponsorship now or later (F-1 OPT, H-1B...): `--needs-sponsorship` drops "won't sponsor" and citizens/US-persons-only postings.
  Many postings say nothing either way; those stay in. The parser misses some wordings, so a posting without the flag
  can still refuse sponsorship: check the excerpt.
- Permanent resident: `--no-citizen-only` is too strict for ITAR "US person" roles (residents qualify); judge those by reading.
- No clearance and not a citizen: `--no-clearance`. Citizens who'd accept a clearance can skip it.

## Freshness and pay

- `--since 7d` first seen in the last week (the date the scraper first saw it; `--posted-since` uses the posting's own date, which some boards don't give).
- `--min-pay 70k` (yearly; hourly × 2,080). A range passes when its top reaches the floor ($60k–$130k passes 70k: say
  so when you recommend it). Postings without pay pass unless `--has-pay`.
- Postings whose parsed application deadline has passed are hidden; `--include-expired` shows them. Before you
  recommend a posting, `check` it: closed postings can stay in the data for a few days.
- `--text "REGEX"` filters on each posting's excerpt after the other filters: one template sentence ("12 months of
  recent RN experience", "new graduates welcome") sorts hundreds of near-identical postings at once.

## Shaping the funnel

- Too many (thousands): add the `--not-title` above, `--degree`, a `--since`, a place, `--family`, `--strict-term`;
  split into several searches.
- One company flooding the list (TikTok, ByteDance and big banks post dozens of near-identical roles): `--not-company`
  for a second pass, or judge one and copy the verdict to its siblings.
- Too few: loosen the title regex, add `unknown` to `--level`, drop `--strict-term` or the place filter, check `companies`
  for a company that should be there.
- Specific companies: `--company "nvidia|amd|apple"`. Exclude: `--not-company "staffing|recruit"`.

## Examples

```sh
# EE junior, summer 2027 hardware internship, Texas or remote, US citizen
jobs.py search --level intern --term "summer 2027" --title "hardware|electrical|asic|fpga|firmware|embedded|validation" \
  --state TX --or-remote --count

# CS new grad on F-1 OPT, backend or infra, anywhere
jobs.py search --level new-grad,entry,unknown --max-years 1 --title "software|backend|infrastructure|platform" \
  --not-title "senior|staff|principal|lead|manager" --needs-sponsorship --count

# Biology BS, lab research roles in Houston, posted in the last two weeks
jobs.py search --title "research (associate|assistant|technician)|lab(oratory)? (tech|assistant)" --location houston --since 14d
```
