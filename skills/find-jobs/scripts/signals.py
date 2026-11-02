"""Parsing algorithms that turn a job posting's text into facts you can filter on.

Every function takes plain text (or a posting row) and returns a small value; nothing here touches the network. The daily
export runs `facts(row)` on every posting, so the published data already carries these fields (see references/data.md):

    level      intern | new-grad | entry | mid | senior | manager | "" (title and years say nothing)
    years      minimum years of experience the posting requires, or None
    degree     lowest degree the posting requires: hs | associate | bs | ms | phd, or None
    clearance  True when a security clearance is required
    citizen    True when the role is limited to US citizens / US persons / permanent residents
    no_sponsor True when the posting says it will not sponsor a work visa
    pay        [low, high, unit] with unit hour | year | month | week, or None
    term       internship term such as "Summer 2027", or None
    remote     remote | hybrid | onsite | ""
    states     US state codes found in the location, e.g. ["TX", "CA"]
    family     job function guessed from the title: software, data, hardware, mechanical, ... (see FAMILIES)
    deadline   application deadline as YYYY-MM-DD, or None
    gpa        minimum GPA as a string ("3.0"), or None

`excerpt(row)` picks the lines of a long posting that matter for eligibility and fit (qualifications, degree, years, class
standing, graduation window, authorization, place), so an agent can judge a posting from ~1,800 characters instead of 6,000.

All of these are heuristics over free text. They are right most of the time and meant for narrowing a search, not for
the final call: read the posting (or its excerpt) before telling someone they qualify.
"""
import re
from datetime import date

# --- text helpers -----------------------------------------------------------------------------------------------------

def _pieces(text):
    """Text split into short lines: on newlines and bullets, long lines further into sentences."""
    out = []
    for line in re.split(r"\n|•|\s\*\s|\s·\s", (text or "").replace("\xa0", " ")):
        line = " ".join(line.split())
        for s in (re.split(r"(?<=[.!?;])\s+(?=[A-Z(])", line) if len(line) > 300 else [line]):
            if len(s) > 2:
                out.append(s if len(s) <= 350 else s[:349] + "…")
    return out


_PREFERRED = re.compile(r"\b(prefer\w*|desir\w*|nice[- ]to[- ]have|bonus|a plus|is a plus|ideal(ly)?|advantage\w*|strongly considered|"
                        r"would be great|helpful|pluses|good to have)\b", re.I)
_PREF_HEAD = re.compile(r"^\W*(preferred|desired|bonus|nice[- ]to[- ]haves?|additional|plus(es)?|ideal\w*)\b.{0,40}$|"
                        r"^\W*(?:what would make you stand out|it would be great if|we'?d love|extra credit)", re.I)
_REQ_HEAD = re.compile(r"^\W*(?:basic |minimum |required |key |must[- ]have |mandatory )?(?:qualifications?|requirements?|"
                       r"what you(?:'ll| will)? (?:need|bring|have)|who you are|about you|you (?:have|bring|are)|must[- ]haves?)\b", re.I)


def requirement_lines(row):
    """(required, preferred) lists of lines. Uses the board's own split when it has one (basic/preferred fields);
    otherwise walks the description, tracking whether the current section is a preferred one."""
    if row.get("basic"):
        basic = _pieces(row["basic"])
        return [p for p in basic if not _PREFERRED.search(p)], _pieces(row.get("preferred")) + [p for p in basic if _PREFERRED.search(p)]
    req, pref, in_pref = [], [], False
    for p in _pieces(row.get("description")):
        if _PREF_HEAD.search(p) and len(p) < 120:
            in_pref = True
            continue
        if _REQ_HEAD.search(p) and len(p) < 120:
            in_pref = False
            continue
        (pref if in_pref or _PREFERRED.search(p) else req).append(p)
    return req, pref


# --- level and years -------------------------------------------------------------------------------------------------

INTERN = re.compile(r"\b(?:intern(?:ship)?s?|co[- ]?ops?|summer (?:analyst|associate|student|scholar|undergraduate|program)|"
                    r"apprentice(?:ship)?s?|externs?(?:hip)?|student (?:worker|assistant|researcher|trainee|employee|technician|engineer)|"
                    r"undergraduate research|research (?:intern|student)|working student|placement student|industrial placement)\b", re.I)
NEW_GRAD = re.compile(r"\b(?:new[- ]?grad(?:uate)?s?|new college grad\w*|recent (?:college )?grad\w*|university grad\w*|college grad\w*|"
                      r"graduate (?:program|scheme|engineer|trainee|rotation\w*|development)|early[- ]?(?:career|talent|in[- ]career)|"
                      r"campus (?:hire|hiring)|class of 20\d\d|20\d\d (?:start|grad\w*)|(?:leadership |professional )?development program|"
                      r"rotational|rotation program|residency program|fellowship program|associate program|analyst program|"
                      r"entry[- ]level program|university (?:hire|recruit\w*)|grad(?:uate)? hire|\bNCG\b|\bRCG\b)\b", re.I)
_MANAGER = re.compile(r"\b(?:director|head of|vp|svp|evp|avp|vice president|chief|cxo|cto|cfo|ceo|coo|president|supervisor|superintendent|"
                      r"general manager|(?:engineering|software|hardware|people|team|program management|development|store|branch|"
                      r"department|area|regional|district|plant|site|office|operations|practice|delivery|unit|nurse) manager|"
                      r"manager,|manager of|managing director|partner)\b", re.I)
_SENIOR = re.compile(r"\b(?:senior|sr\.?|staff|principal|distinguished|fellow|lead|leader|expert|master|architect|specialist (?:iii|iv|v)|"
                     r"(?:engineer|developer|scientist|analyst|designer|specialist|consultant|technician|administrator|accountant|associate)"
                     r"\s+(?:iii|iv|v|vi|3|4|5|6)|level\s*[3-9]|l[5-9]|ic[4-6]|e[5-8])\b", re.I)
_ENTRY = re.compile(r"\b(?:junior|jr\.?|entry[- ]?level|entry|graduate|trainee|apprentice|beginner|"
                    r"(?:engineer|developer|scientist|analyst|designer|specialist|consultant|technician|administrator|accountant|programmer)"
                    r"\s+(?:i|1)|level\s*1|associate (?:\w+ )?(?:engineer|developer|scientist|analyst|programmer|consultant|designer|"
                    r"product manager|technologist|researcher|accountant|software))\b", re.I)
_MID = re.compile(r"\b(?:(?:engineer|developer|scientist|analyst|designer|specialist|consultant|technician|administrator|accountant|programmer)"
                  r"\s+(?:ii|2)|level\s*2|intermediate|mid[- ]level)\b", re.I)

_NUMWORD = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "twelve": 12, "fifteen": 15}
_N = r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen)"
_YEARS = re.compile(r"(?:(?:at least|minimum(?: of)?|min\.?|over|more than)\s+)?" + _N +
                    r"(?:\s*(?:\+|plus))?(?:\s*(?:-|–|—|to|or)\s*" + _N + r")?(?:\s*\(\d+\))?\s*(?:\+\s*)?(?:or more\s+)?"
                    r"(?:full[- ]time\s+|professional\s+|relevant\s+|related\s+|industry\s+|post[- ]graduate\s+|progressive(?:ly)?\s+|"
                    r"hands[- ]on\s+|practical\s+|work(?:ing)?\s+|technical\s+|direct\s+|prior\s+|total\s+|combined\s+)*"
                    r"(?:years?|yrs?)\b(?:\s*['’]\s*)?(?!\s*(?:old|of age|ago|or older|or over|and older|and over|in business|in operation|of history|of (?:service|serving)))"
                    r"(?=[^.;\n]{0,80}\b(?:experience|exp\b|background|track record|working|work(?:ing)? (?:in|with|on)|developing|"
                    r"designing|building|programming|coding|in (?:a|an|the)\b|of\b|with\b|as\b|post\b|after\b|beyond\b))", re.I)
_YEARS_NOT = re.compile(r"\b(?:we have|we'?ve|our|company|founded|history|since|for over|serving|served|in business|legacy|anniversary|"
                        r"within|commit\w* to (?:stay|remain)|remain in|stay in|contract|duration|term of|program (?:lasts|is)|"
                        r"\d+[- ]year (?:program|rotation|degree)|graduat\w* (?:in|within)|degree program|"
                        r"age|old|retire|vesting|warranty|guarantee|lease)\b", re.I)


_BACHELOR = re.compile(r"bachelor|baccalaur|\bB\.?S\.?\b|\bB\.?A\.?\b|\bBSc\b|undergraduate degree|4[- ]year degree", re.I)


def _num(s):
    return int(s) if s.isdigit() else _NUMWORD[s.lower()]


def years(row):
    """Minimum years of experience the posting requires (the largest 'N+ years ... experience' among its required lines,
    which for 'BS + 4 years or MS + 2 years' is the bachelor's bar), or None when it states none."""
    req, _ = requirement_lines(row)
    found = []  # (years, line names a bachelor's)
    for line in req:
        low = line.lower()
        if "year" not in low and "yr" not in low:
            continue
        for m in _YEARS.finditer(line):
            before = line[max(0, m.start() - 50):m.start()]
            if _YEARS_NOT.search(before):
                continue
            lo = _num(m.group(1))
            if lo <= 15:
                found.append((lo, bool(_BACHELOR.search(line))))
    if not found:
        return None
    with_bs = [y for y, bs in found if bs]  # "HS + 8 years, or BS + 4 years, or MS + 2": the bachelor's bar
    return max(with_bs or [y for y, _ in found])


def level(row, yrs=None):
    """intern / new-grad / entry / mid / senior / manager from the title first, then the required years; "" when neither
    says anything. The title wins: a "Senior" role is senior even when it asks for 2 years."""
    title = row.get("title") or ""
    if INTERN.search(title) and not re.search(r"\b(?:intern(?:ship)? (?:program )?(?:manager|coordinator|director|recruiter|lead))\b", title, re.I):
        return "intern"
    if NEW_GRAD.search(title) and not re.search(r"program (?:manager|management|coordinator|director|lead|specialist)|recruit|"
                                                 r"university relations|campus (?:relations|partnerships)", title, re.I):
        return "new-grad"
    if _MANAGER.search(title):
        return "manager"
    if _SENIOR.search(title):
        return "senior"
    if _ENTRY.search(title):
        return "entry"
    if _MID.search(title):
        return "mid"
    if yrs is None:
        return ""
    return "entry" if yrs <= 1 else "mid" if yrs <= 4 else "senior"


# --- degree, authorization, clearance --------------------------------------------------------------------------------

_DEGREES = [  # word forms ignore case; abbreviations (BS, MS, PhD...) must be written in capitals, so "be" or "ms" in prose never count
    ("hs", re.compile(r"\b(?:high school|secondary school|h\.s\. diploma)|(?-i:\bGED\b|\bHSD\b)", re.I)),
    ("associate", re.compile(r"\bassociate'?s?(?: degree| of (?:science|arts|applied))|associate[’']s degree|(?-i:\bA\.?A\.?S\.?\b)", re.I)),
    ("bs", re.compile(r"\b(?:bachelor|baccalaureate|undergraduate degree|(?:4|four)[- ]year (?:college |university )?degree)|bachelor[’']s|"
                      r"(?-i:\b(?:BS|B\.S\.|BA|B\.A\.|BSc|B\.Sc\.|BSEE|BSME|BSCS|BSE|BEng|B\.Eng\.?|B\.E\.|B\.Tech|BTech)(?![\w]))", re.I)),
    ("ms", re.compile(r"\b(?:master'?s?|master[’']s|graduate degree|advanced degree)\b|"
                      r"(?-i:\b(?:MS|M\.S\.|MSc|M\.Sc\.|MEng|M\.Eng\.?|MBA|M\.B\.A\.|MSEE|MSCS|MPH|MPA)(?![\w]))", re.I)),
    ("phd", re.compile(r"\b(?:ph\.\s?d\.?|phd|doctorate|doctoral degree|doctoral)\b|(?-i:\bD\.Phil\b)", re.I)),
]
_DEGREE_CTX = re.compile(r"degree|diploma|graduat|pursu|enroll|equivalent|major|field of study|related field|discipline|required|"
                         r"minimum|or higher|or above|candidate|student|program|(?-i:\bin [A-Z])", re.I)
_ORDER = ["hs", "associate", "bs", "ms", "phd"]
_DEGREE_HINT = re.compile(r"bachelor|baccalaur|master|ph\.?\s?d|doctor|degree|diploma|high school|secondary school|graduate|"
                          r"(?-i:\b(?:GED|BS|BA|BSc|BSE|BEng|MS|MSc|MEng|MBA|MPH|PhD|AAS)\b|\b[BM]\.[SAE])", re.I)


def degree(row):
    """Lowest degree named in the posting's required lines: "Bachelor's or Master's" is bs, "PhD in ..." is phd. None when no
    degree is named. Pursuing counts: an internship for "students pursuing a PhD" is phd."""
    req, _ = requirement_lines(row)
    found = set()
    for line in req:
        if not _DEGREE_HINT.search(line) or not _DEGREE_CTX.search(line):
            continue
        for name, rx in _DEGREES:
            if rx.search(line):
                found.add(name)
    if not found:
        return None
    return min(found, key=_ORDER.index)


# A required security clearance; ITAR / export-control "US person" rules are not a clearance (see `citizen`).
CLEARANCE = re.compile(r"(active|current|existing|must (have|hold|possess|obtain|be able to obtain)|ability to obtain|eligib\w+ (to obtain|for)|required to (obtain|hold)|hold an?|obtain and maintain)[^.]{0,60}\b(security clearance|clearance|TS/SCI|top secret|secret clearance)"
                       r"|\b(security clearance|TS/SCI|top secret|secret clearance)\b[^.]{0,80}\b(required|must|necessary)", re.I)
_CITIZEN = re.compile(
    r"(?:must|shall|required to|need to|requires?|requirement|only|open to|limited to|restricted to|eligible|candidates? (?:must|should))"
    r"[^.;\n]{0,60}?\b(?:u\.?\s?s\.?\s?citizen(?:s|ship)?|united states citizen(?:s|ship)?|american citizen\w*|citizens? of the united states|"
    r"u\.?\s?s\.? persons?|us persons?|lawful permanent residen\w*|permanent residen\w*|green card)"
    r"|\b(?:u\.?\s?s\.?\s?citizen(?:ship)?|united states citizen(?:ship)?|u\.?\s?s\.? person)\b[^.;\n]{0,40}?\b(?:is |are )?(?:required|only|"
    r"a (?:requirement|must)|mandatory|needed)"
    r"|\bitar\b[^.;\n]{0,80}\b(?:requires?|required|must|eligib|u\.?s\.? person|citizen)", re.I)
_CITIZEN_NOT = re.compile(r"regard(?:less)? (?:to|of)|without regard|protected|discriminat|equal opportunity|national origin|"
                          r"e-?verify|i-9|form i|employment eligibility verification|not required|is not a requirement", re.I)
_NO_SPONSOR = re.compile(
    r"(?:will not|won'?t|unable to|not able to|cannot|can ?not|can'?t|does not|do not|doesn'?t|don'?t|is not able to|are not able to|"
    r"no longer|not (?:currently )?(?:in a position to|offering|providing|available to))\s+(?:be\s+)?(?:able to\s+)?"
    r"(?:provide |offer |support |consider |pursue |sponsor )?(?:any )?(?:immigration |visa |employment |work )?"
    r"(?:sponsor\w*|visa\w*|h-?1b)"
    r"|without (?:the )?(?:need (?:for|of)|requiring|requirement (?:for|of)|necessity of)?\s*(?:current or future |now or in the future |future )?"
    r"(?:employer[- ])?(?:immigration |visa |employment |work )?(?:sponsorship|sponsor)"
    r"|(?:visa |immigration |employment |work )?sponsorship (?:is |will )?(?:not|n'?t) (?:be )?(?:available|provided|offered|supported|possible|considered)"
    r"|\bno (?:visa |immigration |employment )?sponsorship\b|not eligible for (?:visa |immigration )?sponsorship|"
    r"(?:not|n'?t) (?:require|need) (?:visa |immigration |employment )?sponsorship (?:now|currently|at any time)", re.I)


def _flag(rx, text, not_rx=None):
    for m in rx.finditer(text or ""):
        around = text[max(0, m.start() - 80):m.end() + 40]
        if not_rx and not_rx.search(around):
            continue
        return True
    return False


def clearance(text):
    low = (text or "").lower()
    return ("clearance" in low or "secret" in low) and bool(CLEARANCE.search(text))


def citizen(text):
    """Limited to US citizens, US persons (ITAR/EAR) or permanent residents; equal-opportunity boilerplate is ignored."""
    low = (text or "").lower()
    if not any(w in low for w in ("citizen", "person", "permanent resid", "green card", "itar")):
        return False
    return _flag(_CITIZEN, text, _CITIZEN_NOT)


def no_sponsor(text):
    """The posting says it will not sponsor a work visa now or later."""
    low = (text or "").lower()
    if "sponsor" not in low and "visa" not in low and "h1b" not in low and "h-1b" not in low:
        return False
    return _flag(_NO_SPONSOR, text, re.compile(r"\bwill sponsor|sponsorship (?:is )?available|able to sponsor|can sponsor", re.I))


# --- pay, deadline, gpa, term, remote ------------------------------------------------------------------------------

_NUM = r"(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s?([kK])?(?![\d,])"
_PAY = re.compile(r"(?:\$|\bUSD\s?|\bUS\$\s?)\s?" + _NUM + r"(?:\s*(?:-|–|—|to|and)\s*(?:\$|USD\s?)?\s?" + _NUM + r")?"
                  r"(?:\s*(?:USD|US dollars|dollars))?(?:\s*(?:/|per|an|a)\s*(hour|hr|year|yr|annum|month|mo|week|wk)\b|\s+(hourly|annually|yearly|annual|monthly|weekly)\b)?",
                  re.I)
_PAY_CONTEXT = re.compile(r"salary|\bpay\b|compensation|wage|\bbase\b|\brate\b|range|stipend|earn|hourly|annual|\bote\b|\bcomp\b", re.I)
_NOT_PAY = re.compile(r"bonus|sign[- ]?on|signing|relocat|housing|tuition|reimburs|allowance|referral|401|match|equity|stock|raised|funding|"
                      r"revenue|valuation|assets|donat|insurance|wellness|gym|commut|meal|lunch|budget|credit|discount|\bfee|cost|price|spend|grant", re.I)
_UNIT = {"hour": "hour", "hr": "hour", "hourly": "hour", "year": "year", "yr": "year", "annum": "year", "annually": "year", "yearly": "year",
         "annual": "year", "month": "month", "mo": "month", "monthly": "month", "week": "week", "wk": "week", "weekly": "week"}
_SANE = {"hour": (7, 500), "year": (15000, 2000000), "month": (500, 30000), "week": (200, 10000)}


def _amount(whole, frac, k):
    return (float(whole.replace(",", "") + (frac or ""))) * (1000 if k else 1)


def pay(text):
    """Pay as posted: [low, high, unit] (unit hour/year/month/week), or None. Several ranges in one unit (pay zones) give
    the overall min and max. Bonuses, relocation, funding rounds and other dollar amounts are skipped."""
    found = []
    for m in _PAY.finditer(text or ""):
        before, after = text[max(0, m.start() - 120):m.start()], text[m.end():m.end() + 20]
        if re.match(r"\s*(?:million|billion|trillion|m\b|mm\b|bn?\b|\+)", after, re.I) or _NOT_PAY.search(before[-60:]):
            continue
        lo = _amount(*m.group(1, 2, 3))
        hi = _amount(*m.group(4, 5, 6)) if m.group(4) else lo
        if m.group(4) and m.group(3) and not m.group(6) and hi < 1000:
            hi *= 1000  # "$120k-150"
        unit = _UNIT.get((m.group(7) or m.group(8) or "").lower())
        if not unit:
            if not _PAY_CONTEXT.search(before):
                continue
            unit = "hour" if hi < 300 else "year" if lo >= 15000 else None
            if not unit:
                continue
        lo_ok, hi_ok = _SANE[unit]
        if not (lo_ok <= lo <= hi <= hi_ok):
            continue
        found.append((unit, lo, hi))
    if not found:
        return None
    unit = found[0][0]
    lo, hi = min(f[1] for f in found if f[0] == unit), max(f[2] for f in found if f[0] == unit)
    num = lambda x: int(x) if x == int(x) else round(x, 2)
    return [num(lo), num(hi), unit]


def pay_text(p):
    """[62000, 78000, "year"] -> "$62,000 to $78,000"; [45, 45, "hour"] -> "$45/hour"."""
    if not p:
        return ""
    lo, hi, unit = p
    money = lambda x: f"${x:,.2f}" if x != int(x) else f"${int(x):,}"
    span = money(lo) if lo == hi else f"{money(lo)} to {money(hi)}"
    return span if unit == "year" else f"{span}/{unit}"


def yearly(p):
    """Rough yearly equivalent of a pay triple, for --min-pay (2,080 hours a year)."""
    if not p:
        return None
    return p[1] * {"hour": 2080, "week": 52, "month": 12, "year": 1}[p[2]]


_MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
_MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_DATE = rf"({_MON})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d\d)|(\d{{1,2}})/(\d{{1,2}})/(20\d\d)|(20\d\d)-(\d\d)-(\d\d)|(\d{{1,2}})\s+({_MON}),?\s+(20\d\d)"
_DEADLINE = re.compile(r"(?:deadline|apply (?:by|before|no later than)|applications? (?:are |is |will be )?(?:due|close[sd]?|closing|"
                       r"must be (?:received|submitted)|accepted (?:until|through)|open (?:until|through))|closing date|close date|"
                       r"posting (?:end|close)s?(?: date)?|end date for applications|accepting applications (?:until|through)|"
                       r"submit (?:your |an )?applications? by|no later than)[^.]{0,40}?(?:" + _DATE + ")", re.I)


def deadline(text):
    """The application deadline the text states, as YYYY-MM-DD, or None."""
    low = (text or "").lower()
    if not any(w in low for w in ("deadline", "apply", "application", "clos", "no later", "end date", "submit")):
        return None
    m = _DEADLINE.search(text)
    if not m:
        return None
    g = m.groups()
    try:
        if g[0]:
            d = date(int(g[2]), _MONTHS[g[0][:3].lower()], int(g[1]))
        elif g[3]:
            d = date(int(g[5]), int(g[3]), int(g[4]))
        elif g[6]:
            d = date(int(g[6]), int(g[7]), int(g[8]))
        else:
            d = date(int(g[11]), _MONTHS[g[10][:3].lower()], int(g[9]))
    except ValueError:
        return None
    return d.isoformat()


_GPA = re.compile(r"(?:\bgpa\b|grade point average)[^.;\n]{0,40}?\b([1-3]\.\d{1,2}|4\.0)\b|\b([1-3]\.\d{1,2})\s*(?:/\s*4\.0\s*)?(?:or (?:higher|above|better)\s*)?"
                  r"(?:cumulative |overall |minimum )?(?:\bgpa\b|grade point)", re.I)


def gpa(text):
    """A minimum GPA the text states ("3.0"), or None."""
    low = (text or "").lower()
    if "gpa" not in low and "grade point" not in low:
        return None
    m = _GPA.search(text)
    return (m.group(1) or m.group(2)) if m else None


_TERM = re.compile(r"\b(summer|fall|autumn|spring|winter)\s*(?:semester |term |quarter |session )?['’]?(20\d\d|\d\d)\b", re.I)


def term(row):
    """The internship or co-op term, "Summer 2027", from the title, else the first one the description names."""
    for text in (row.get("title"), row.get("description")):
        m = _TERM.search(text or "")
        if m:
            season = m.group(1).lower().replace("autumn", "fall").title()
            yr = m.group(2)
            return f"{season} {yr if len(yr) == 4 else '20' + yr}"
    return None


_REMOTE = re.compile(r"\b(?:remote|work from home|wfh|telecommut\w*|virtual|anywhere in the (?:us|united states))\b", re.I)
_HYBRID = re.compile(r"\bhybrid\b", re.I)
_REMOTE_DESC = re.compile(r"\b(?:this (?:is a |role is |position is )(?:fully |100% )?remote|(?:fully|100%) remote (?:role|position|opportunity)|"
                          r"remote[- ]first|can be (?:performed|done|worked) remotely|open to remote|remote (?:within|in) the (?:us|united states))\b", re.I)
_HYBRID_DESC = re.compile(r"\b(?:this (?:is a |role is |position is )hybrid|hybrid (?:role|position|schedule|work model|work arrangement)|"
                          r"\d days? (?:a|per) week (?:in|at) (?:the|our) (?:office|site))\b", re.I)
_ONSITE_DESC = re.compile(r"\b(?:this (?:is an? |role is |position is )(?:fully )?(?:on-?site|in[- ](?:office|person))|"
                          r"(?:fully|100%) (?:on-?site|in[- ]office|in[- ]person)|on-?site (?:role|position)|must (?:work|be) on-?site)\b", re.I)


def remote(row):
    """remote / hybrid / onsite from the location and title, then from clear sentences in the description; "" when unsaid."""
    head = f"{row.get('location') or ''} {row.get('title') or ''}"
    if _HYBRID.search(head):
        return "hybrid"
    if _REMOTE.search(head):
        return "remote"
    desc = row.get("description") or ""
    if _REMOTE_DESC.search(desc):
        return "remote"
    if _HYBRID_DESC.search(desc):
        return "hybrid"
    if _ONSITE_DESC.search(desc):
        return "onsite"
    return ""


# --- places ----------------------------------------------------------------------------------------------------------

STATES = {"AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california", "CO": "colorado", "CT": "connecticut",
          "DE": "delaware", "FL": "florida", "GA": "georgia", "HI": "hawaii", "ID": "idaho", "IL": "illinois", "IN": "indiana", "IA": "iowa",
          "KS": "kansas", "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland", "MA": "massachusetts", "MI": "michigan",
          "MN": "minnesota", "MS": "mississippi", "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada", "NH": "new hampshire",
          "NJ": "new jersey", "NM": "new mexico", "NY": "new york", "NC": "north carolina", "ND": "north dakota", "OH": "ohio", "OK": "oklahoma",
          "OR": "oregon", "PA": "pennsylvania", "RI": "rhode island", "SC": "south carolina", "SD": "south dakota", "TN": "tennessee",
          "TX": "texas", "UT": "utah", "VT": "vermont", "VA": "virginia", "WA": "washington", "WV": "west virginia", "WI": "wisconsin",
          "WY": "wyoming", "DC": "district of columbia", "PR": "puerto rico"}
# Cities boards often list without a state. Ambiguous names (Portland, Cambridge, Arlington, Columbus) map to the larger one.
CITIES = {
    "CA": "san francisco|sunnyvale|santa clara|palo alto|mountain view|san jose|cupertino|menlo park|los angeles|san diego|irvine|oakland|"
          "berkeley|fremont|foster city|san mateo|redwood city|south san francisco|emeryville|hawthorne|el segundo|burlingame|santa monica|"
          "culver city|folsom|sacramento|pasadena|long beach|anaheim|santa ana|costa mesa|newport beach|torrance|carlsbad|milpitas|"
          "pleasanton|san ramon|livermore|walnut creek|san bruno|brisbane|santa barbara|goleta|riverside|ontario, ca|bay area|silicon valley|"
          "playa vista|venice, ca|thousand oaks|westlake village|camarillo|chatsworth|burbank|glendale, ca|van nuys|fullerton|orange, ca|"
          "lake forest|aliso viejo|mission viejo|san clemente|fresno|bakersfield|stockton|modesto|redlands|temecula|chula vista",
    "WA": "seattle|bellevue|redmond|kirkland|bothell|everett|tacoma|spokane|issaquah|renton|vancouver, wa|woodinville|tukwila",
    "NY": "new york|nyc|manhattan|brooklyn|queens|bronx|albany|rochester, ny|buffalo|ithaca|syracuse|white plains|yonkers|long island|"
          "armonk|yorktown heights|poughkeepsie|east fishkill|tarrytown",
    "MA": "boston|cambridge, ma|waltham|burlington, ma|lexington, ma|somerville|north reading|framingham|marlborough|andover|wilmington, ma|"
          "bedford, ma|woburn|quincy|newton|chelmsford|lowell|worcester|natick|needham|cambridge",
    "IL": "chicago|evanston|naperville|schaumburg|oak brook|deerfield|northbrook|lake forest, il|peoria|champaign|urbana|mossville|moline",
    "CO": "denver|boulder|colorado springs|aurora, co|fort collins|broomfield|louisville, co|englewood, co|golden|littleton|lakewood, co|centennial",
    "GA": "atlanta|alpharetta|marietta|savannah|duluth, ga|norcross|sandy springs",
    "PA": "pittsburgh|philadelphia|king of prussia|harrisburg|allentown|malvern|conshohocken|wayne, pa|state college",
    "NC": "raleigh|durham|charlotte|cary|research triangle|chapel hill|morrisville|greensboro|winston-salem",
    "AZ": "phoenix|tempe|chandler|scottsdale|mesa|tucson|gilbert|glendale, az",
    "UT": "salt lake|lehi|provo|draper|ogden|sandy, ut|south jordan|orem",
    "VA": "reston|mclean|tysons|arlington, va|herndon|chantilly|richmond|alexandria|fairfax|sterling|vienna, va|norfolk|virginia beach|"
          "charlottesville|dulles|ashburn|leesburg|falls church",
    "FL": "miami|boca raton|orlando|tampa|jacksonville|fort lauderdale|st. petersburg|melbourne, fl|cape canaveral|tallahassee|gainesville|"
          "west palm beach|sarasota|kennedy space center",
    "MN": "minneapolis|st. paul|saint paul|rochester, mn|eden prairie|bloomington, mn|plymouth, mn|eagan",
    "MI": "detroit|ann arbor|dearborn|grand rapids|troy, mi|warren, mi|lansing|novi|southfield|auburn hills",
    "OH": "columbus|cleveland|cincinnati|dayton|akron|toledo|dublin, oh|mason, oh",
    "OR": "portland|hillsboro|beaverton|eugene|salem, or|bend",
    "TN": "nashville|memphis|knoxville|chattanooga|franklin, tn|oak ridge",
    "MD": "baltimore|bethesda|rockville|columbia, md|annapolis|gaithersburg|silver spring|laurel, md|greenbelt|college park",
    "WI": "madison|milwaukee|green bay|waukesha",
    "MO": "st. louis|saint louis|kansas city|springfield, mo",
    "NV": "las vegas|reno|henderson",
    "NJ": "newark|jersey city|princeton|hoboken|edison|parsippany|morristown|holmdel",
    "DC": "washington, dc|washington dc|washington, d.c.",
    "IN": "indianapolis|carmel, in|fort wayne|west lafayette|bloomington, in",
    "CT": "hartford|stamford|new haven|greenwich|norwalk",
    "LA": "new orleans|baton rouge|lafayette, la|shreveport",
    "AL": "huntsville|birmingham|montgomery|mobile, al",
    "KY": "louisville|lexington, ky",
    "OK": "oklahoma city|tulsa",
    "NM": "albuquerque|santa fe|los alamos|las cruces",
    "SC": "charleston, sc|greenville, sc|columbia, sc",
    "NE": "omaha|lincoln, ne",
    "KS": "wichita|overland park|lawrence, ks",
    "IA": "des moines|cedar rapids|iowa city",
    "ID": "boise|idaho falls",
    "HI": "honolulu",
    "AK": "anchorage",
    "RI": "providence",
    "NH": "nashua|manchester, nh",
    "DE": "wilmington, de",
    "AR": "little rock|bentonville|fayetteville, ar",
    "MS": "jackson, ms",
    "WV": "charleston, wv|morgantown",
}
CITIES["TX"] = ("austin|houston|dallas|san antonio|fort worth|el paso|plano|irving|frisco|the woodlands|sugar land|katy|round rock|"
                "college station|corpus christi|lubbock|mckinney|denton|richardson|pearland|conroe|galveston|waco|amarillo|mcallen|laredo|"
                "killeen|carrollton|lewisville|grapevine|southlake|baytown|league city|arlington, tx|allen, tx|addison|tomball|humble|"
                "brownsville|cedar park|georgetown, tx|san marcos|pflugerville|temple, tx|tyler|longview|midland|odessa|beaumont|abilene|"
                "spring, tx|cypress, tx|pasadena, tx|stafford, tx|webster, tx|clear lake|bastrop|kyle|leander|mansfield, tx|garland|mesquite|"
                "coppell|flower mound|westlake, tx|fort hood|lackland|deer park|la porte|freeport|texas city|nacogdoches|san angelo|wichita falls|harlingen|edinburg")
_CITY_RX = {st: re.compile(r"\b(?:" + "|".join(re.escape(c).replace(r"\ ", " ") for c in cities.split("|")) + r")\b", re.I)
            for st, cities in CITIES.items()}
_NAME_RX = re.compile(r"\b(" + "|".join(sorted((n for n in STATES.values()), key=len, reverse=True)) + r")\b", re.I)
_BY_NAME = {v: k for k, v in STATES.items()}
_CODE_RX = re.compile(r"(?:^|[,(/|;•\-–]\s*|\b(?:US|USA|United States)[\s,\-]+)(" + "|".join(STATES) + r")(?=\s*(?:$|[,)/|;•\-–]|\d{5}|\s+\d|\s+(?:US|USA|United States)\b))")


def states(location):
    """US state codes a free-text location names: "Austin, TX" -> ["TX"]; "US, CA, Cupertino; Seattle" -> ["CA", "WA"].
    Uses codes after a comma or dash, full state names, and a list of well-known cities (Washington the state vs DC handled)."""
    loc = location or ""
    found = []
    def add(code):
        if code not in found:
            found.append(code)
    for m in _CODE_RX.finditer(loc):
        add(m.group(1))
    low = loc.lower()
    for m in _NAME_RX.finditer(low):
        name = m.group(1).lower()
        if name == "washington" and re.search(r"washington,?\s*(?:d\.?c\.?|district)", low):
            continue
        if name == "new york" and "NY" in found:
            continue
        add(_BY_NAME[name])
    for st, rx in _CITY_RX.items():
        if st not in found and rx.search(loc):
            add(st)
    return found


# --- job families ----------------------------------------------------------------------------------------------------

FAMILIES = [  # (key, label, title regex); the first match wins, so the order matters
    ("software", "Software engineering", r"software|\bswe\b|\bsde\b|developer|programmer|full[- ]?stack|front[- ]?end|back[- ]?end|web (?:engineer|dev)|"
                 r"mobile (?:engineer|dev)|\bios\b|android|devops|dev ops|\bsre\b|site reliability|platform engineer|infrastructure engineer|"
                 r"cloud engineer|systems engineer.*(?:software|linux|cloud)|distributed systems|compiler|kernel|security engineer|"
                 r"application security|cyber ?security|penetration|\bqa\b|test automation|automation engineer|quality assurance|"
                 r"forward deployed|solutions? engineer|member of technical staff|\bmts\b|engineer, (?:backend|frontend|infrastructure|product)|"
                 r"product engineer|game (?:engineer|programmer)|graphics engineer|database (?:engineer|administrator)|network engineer|"
                 r"it (?:engineer|specialist|support|analyst)|systems administrator|sysadmin"),
    ("data", "Data, ML and AI", r"data scien|data engineer|data analy|machine learning|\bml\b|\bai\b|artificial intelligence|deep learning|"
             r"research scientist|applied scientist|research engineer|analytics|business intelligence|\bbi\b|statistic|quantitative|\bquant\b|"
             r"\bnlp\b|computer vision|perception|data (?:architect|platform|infrastructure)|modeling|econometric|bioinformatic|"
             r"computational"),
    ("hardware", "Hardware, chips and embedded", r"hardware|electrical|electronic|\basic\b|\bfpga\b|\brtl\b|verification|silicon|\bsoc\b|chip|"
                 r"analog|digital design|circuit|layout|semiconductor|firmware|embedded|\bpcb\b|\brf\b|signal integrity|power (?:electronics|engineer)|"
                 r"photonic|optical|\bdft\b|physical design|mixed[- ]signal|validation engineer|test engineer|product engineer|process engineer|"
                 r"yield|lithograph|wafer|packaging engineer|device engineer|antenna|microwave|dsp\b|controls? engineer|instrumentation"),
    ("mechanical", "Mechanical, aerospace and manufacturing", r"mechanical|aerospace|aeronautic|propulsion|structures?|thermal|fluids|\bcfd\b|"
                   r"\bgnc\b|guidance|avionics|flight|spacecraft|launch|manufacturing|industrial engineer|robotics|mechatronic|automotive|"
                   r"vehicle|materials|metallurg|welding|composites|quality engineer|reliability engineer|design engineer|\bcad\b|tooling|"
                   r"production engineer|systems engineer|integration engineer|hvac|energy engineer|nuclear|petroleum|reservoir|drilling|"
                   r"mining|pipeline|facilities engineer|plant engineer"),
    ("civil", "Civil, construction and environmental", r"civil|structural|construction|geotechnical|transportation engineer|traffic|"
              r"environmental (?:engineer|scientist|specialist)|water resources|surveyor|estimator|project engineer|field engineer|"
              r"architect(?!ure)|urban planner|land development"),
    ("science", "Science and research", r"chemist|chemical engineer|biolog|biochem|biomedical|bioengineer|biotech|molecular|genetic|genomic|"
                r"laborator|\blab\b|scientist|research (?:associate|assistant|technician|fellow)|postdoc|physicist|geolog|geophysic|"
                r"microbiolog|immunolog|pharmacolog|toxicolog|formulation|assay|clinical research"),
    ("healthcare", "Healthcare", r"nurse|nursing|\brn\b|\blpn\b|\bcna\b|physician|doctor|\bmd\b|surgeon|therap|pharmac|medical|clinical|clinic|"
                   r"patient|health|dental|dentist|hygienist|radiolog|sonograph|phlebotom|paramedic|\bemt\b|respiratory|anesthe|"
                   r"psychiatr|psycholog|counselor|social worker|dietitian|nutrition|optomet|veterinar|caregiver|behavior technician|"
                   r"medical assistant|care (?:coordinator|manager)|technologist"),
    ("finance", "Finance, accounting and banking", r"financ|accountant|accounting|audit|\btax\b|treasury|controller|investment|banking|banker|"
                r"\btrader\b|trading|portfolio|actuar|underwrit|credit|lending|loan|mortgage|wealth|asset management|equity research|"
                r"capital markets|valuation|fp&a|payroll|billing|bookkeep|insurance|claims"),
    ("product", "Product, program and project management", r"product manager|product owner|program manager|project manager|\btpm\b|"
                r"product management|program management|project management|scrum|agile coach|product lead|product operations"),
    ("business", "Business, consulting and operations", r"consult|strategy|business analyst|business (?:operations|development)|operations|"
                 r"supply chain|procurement|purchasing|buyer|sourcing|logistics|planner|planning|analyst|associate|management trainee|"
                 r"rotational|leadership development|administrat|coordinator|assistant|office|executive"),
    ("sales", "Sales, marketing and communications", r"sales|account (?:executive|manager|representative)|business development|\bsdr\b|\bbdr\b|"
              r"marketing|brand|communications|public relations|\bpr\b|content|social media|\bseo\b|growth|copywrit|writer|editor|"
              r"customer success|customer (?:service|support|experience)|support specialist|client|partnerships|merchandis|advertising"),
    ("design", "Design and creative", r"designer|\bux\b|\bui\b|user experience|user research|graphic|creative|art director|animator|"
               r"illustrat|video|photograph|motion|visual|industrial design|game design|producer"),
    ("people", "HR, legal and policy", r"recruit|talent|human resources|\bhr\b|people (?:partner|operations|team)|benefits|compensation analyst|"
               r"legal|counsel|attorney|paralegal|lawyer|compliance|policy|regulatory|government affairs|privacy|trust (?:and|&) safety"),
    ("education", "Education", r"teacher|teaching|instructor|tutor|professor|faculty|lecturer|educat|curriculum|academic|school|"
                  r"admissions|student (?:success|affairs|services)|librar"),
    ("trades", "Skilled trades, service and retail", r"technician|mechanic|electrician|plumb|welder|machinist|operator|driver|warehouse|"
               r"fulfillment|forklift|material handler|package handler|loader|retail|store|cashier|barista|cook|chef|food|server|"
               r"custodian|janitor|housekeep|security (?:officer|guard)|maintenance|installer|crew|laborer|production (?:worker|associate)|"
               r"assembl|delivery|courier|attendant|sales associate|team member"),
]
# Second pass for titles no family claimed: broader words, in this order ("Technology Intern", "Engineering Co-op").
FALLBACK = [
    ("data", r"\bdata\b|analytic|algorithm|quantum|\bresearch\b"),
    ("software", r"technolog|\bit\b|information|digital|cloud|computing|cyber|\bcdn\b|systems"),
    ("hardware", r"dram|nand|memory|\bcmp\b|etch|equipment|optic|device|module|silicon|semiconductor|packaging"),
    ("engineering", r"engineer|r&d|sustaining|simulation"),
    ("sales", r"writing|media|news"),
    ("business", r"mba|leader|business|management|manager|corporate|operations|program|events|engagement|strategy|"
                 r"risk|regulation|supervision|affairs|analyst|associate"),
    ("trades", r"apprentice|lineman|line ?worker|hourly"),
]
_FAMILY_RX = [(k, re.compile(rx, re.I)) for k, _, rx in FAMILIES]
_FALLBACK_RX = [(k, re.compile(rx, re.I)) for k, rx in FALLBACK]
FAMILY_LABELS = {k: label for k, label, _ in FAMILIES} | {"engineering": "Other engineering", "other": "Other"}


def family(row):
    """The job function the title points to (key from FAMILIES), else "other". Category is a fallback for vague titles."""
    texts = [" ".join(map(str, t)) if isinstance(t, list) else str(t or "") for t in (row.get("title"), row.get("category"))]
    for table in (_FAMILY_RX, _FALLBACK_RX):
        for text in texts:
            for key, rx in table:
                if text and rx.search(text):
                    return key
    return "other"


# --- excerpt ---------------------------------------------------------------------------------------------------------

_HEAD = re.compile(r"^\W*(?:basic |minimum |preferred |required |key |desired |additional )?(?:qualifications?|requirements?|eligibility|"
                   r"what you(?:'ll| will)? (?:need|bring|have)|who you are|about you|you (?:have|bring|are|might)|must[- ]haves?|nice[- ]to[- ]haves?|"
                   r"education|experience|skills)\b", re.I)
_GATE = re.compile(r"bachelor|master'?s|ph\.?\s?d|doctora|degree|\bb\.?s\.?\b|\bm\.?s\.?\b|\d\+? years?|years? of|freshm[ae]n|sophomore|junior|"
                   r"senior standing|first[- ]year|second[- ]year|rising|class of|graduat|enrolled|pursuing|undergrad|\bgpa\b|citizen|permanent resident|"
                   r"clearance|authoriz|sponsor|visa|itar|export|u\.?s\.? persons?|on-?site|in[- ]office|in[- ]person|hybrid|remote|relocat|"
                   r"(?:summer|fall|autumn|spring|winter) 20\d\d|\bterm\b|semester|quarter|\d+ (?:weeks|months)|six months|"
                   r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* (?:\d{1,2},? )?20\d\d|start date|stipend|deadline|apply by|eligib|must be", re.I)
_FIT = re.compile(r"qualif|requir|prefer|experience|skill|proficien|knowledge|familiar|python|\bsql\b|\br\b|statistic|machine learning|model|"
                  r"research|data|you will|you'll|responsib|in this role|the role", re.I)
_ABOUT = re.compile(r"^\W*(?:about (?:us|the company|[A-Z][\w&.]*(?: [A-Z][\w&.]*)?)\W*$|company introduction|our (?:mission|values|story)|"
                    r"who we are|values\W*$|mission\W*$)", re.I)
_BOILER = re.compile(r"equal (?:employment )?opportunit|without regard|regardless of|protected (?:veteran|characteristic|class)|disabilit|"
                     r"accommodation|e-?verify|pay transparency|privacy (?:notice|policy)|benefits? (?:include|package)|401\(?k|paid time off|"
                     r"medical, dental|recruit\w* (?:agenc|fraud)|scam|background check|drug[- ]free|at-will|know your rights", re.I)
EXCERPT = 1800


def excerpt(row, limit=EXCERPT):
    """At most `limit` characters of the posting, picked for eligibility and fit: qualifications, degree, years, class standing,
    graduation window, citizenship or clearance, place and onsite. Lines keep their original order."""
    head = []
    for label, key, cap in (("Basic qualifications", "basic", 800), ("Preferred qualifications", "preferred", 400)):
        t = "; ".join(p for p in _pieces(re.sub(r"(?:^|\s)- ", "\n", row.get(key) or "")) if not _BOILER.search(p))
        if t:
            head.append(f"{label}: {t if len(t) <= cap else t[:cap - 1] + chr(0x2026)}")
    budget = limit - sum(len(h) + 1 for h in head)
    pieces, scored, after_head, lead = _pieces(row.get("description")), [], 0, 0
    for i, p in enumerate(pieces):
        s = 0
        if _HEAD.search(p):
            after_head = 10
        elif after_head:
            after_head -= 1
            s += 1
        s += 3 if _GATE.search(p) else 1 if _FIT.search(p) else 0
        if _BOILER.search(p) or _ABOUT.search(p):
            s -= 5
        elif lead < 3:
            lead += 1
            s += 1
        scored.append((s, i))
    keep = set()
    for s, i in sorted(scored, key=lambda x: (-x[0], x[1])):
        if s < 0 or budget <= 0:
            break
        if len(pieces[i]) + 1 <= budget:
            keep.add(i)
            budget -= len(pieces[i]) + 1
    return "\n".join(head + [pieces[i] for i in sorted(keep)])


# --- everything at once ----------------------------------------------------------------------------------------------

def facts(row):
    """Every signal for one posting row ({title, location, category, description, basic, preferred, ...})."""
    text = "\n".join(filter(None, (row.get("basic"), row.get("preferred"), row.get("description"))))
    yrs = years(row)
    lvl = level(row, yrs)
    return {
        "level": lvl,
        "years": yrs,
        "degree": degree(row),
        "clearance": clearance(text),
        "citizen": citizen(text),
        "no_sponsor": no_sponsor(text),
        "pay": pay(text),
        "term": term(row) if lvl in ("intern", "new-grad") or _TERM.search(row.get("title") or "") else None,
        "remote": remote(row),
        "states": states(row.get("location")),
        "family": family(row),
        "deadline": deadline(text),
        "gpa": gpa(text),
    }
