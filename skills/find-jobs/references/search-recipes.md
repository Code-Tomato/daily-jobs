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

Always add `--not-title "senior|sr\.?|staff|principal|lead|manager|director|head of|vp"` for students and new grads; it
catches titles the level parser missed.

## Fields (title regexes)

| field | `--title` | also |
|---|---|---|
| software | `software|developer|swe|sde|full.?stack|back.?end|front.?end|platform|infrastructure|devops|sre|mobile|ios|android` | `--family software` |
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

`--family` is a coarse guess from the title (see `status` for the list); prefer `--title` regexes, and use `--family` to
narrow a big result or to browse. `--category REGEX` matches the board's own department label when it has one.

## Place

- A state or several: `--state TX,CA` (parsed from the location; multi-city postings list every state they name).
- Cities: `--location "austin|round rock|san marcos"`. Both together OR.
- Remote too: add `--or-remote`. Remote only: `--remote`.
- Anywhere in the US: no place filter (the dataset is US-only).

## Work authorization and clearance

- Needs sponsorship now or later (F-1 OPT, H-1B...): `--needs-sponsorship` drops "won't sponsor" and citizens/US-persons-only postings.
  Many postings say nothing either way; those stay in, so check the excerpt.
- Permanent resident: `--no-citizen-only` is too strict for ITAR "US person" roles (residents qualify); judge those by reading.
- No clearance and not a citizen: `--no-clearance`. Citizens who'd accept a clearance can skip it.

## Freshness and pay

- `--since 7d` first seen in the last week (the date the scraper first saw it; `--posted-since` uses the posting's own date, which some boards don't give).
- `--min-pay 70k` (yearly; hourly × 2,080). Postings without pay pass unless `--has-pay`.

## Shaping the funnel

- Too many (thousands): add the `--not-title` above, a `--since`, a place, `--family`; split into several searches.
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
