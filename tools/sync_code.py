"""Copy the scrapers and the board list from the private job-fit-board checkout into the skill.

Usage: python3 tools/sync_code.py [--from DIR] [--check]
  --from   the private checkout (default: $JOBBOARD_SRC or ~/projects/job-fit-board)
  --check  report what would change and exit 1 if anything would, without writing

What is copied, into skills/find-jobs/scripts/:
  ats.py, probe.py, detect_ats.py, adapters/*.py   verbatim
  companies.json                                    companies.json + companies.d/*.json merged, one board per line,
                                                    minus EXCLUDED_ATS, without the private "store_only" flag
Nothing is copied when a file trips the leak scan (home paths, e-mail addresses, API keys, private keys, and the
words listed in ~/.config/daily-jobs/private-words, which stays off the repo); the findings are printed, exit code 2.
"""
import glob, json, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(HERE, "..", "skills", "find-jobs", "scripts")
CODE = ["ats.py", "probe.py", "detect_ats.py"]
EXCLUDED_ATS = {"amazon", "neogov"}  # amazon.jobs terms forbid automated extraction; NEOGOV's robots.txt admits only search engines
DROP_KEYS = {"store_only"}

LEAKS = [
    (r"/home/[a-z]", "home path"), (r"/Users/[A-Za-z]", "home path"), (r"[\w.+-]+@(?:gmail|utexas|icloud|yahoo|outlook|hotmail)\.\w+", "e-mail"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY", "private key"), (r"\bsk-[A-Za-z0-9_-]{20,}", "API key"), (r"\bgh[pousr]_[A-Za-z0-9]{20,}", "GitHub token"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS key"), (r"\bxox[abprs]-[A-Za-z0-9-]{10,}", "Slack token"), (r"\bAIza[0-9A-Za-z_-]{30,}", "Google key"),
    (r"(?i)(?:api[_-]?key|secret|password|passwd)\s*[=:]\s*['\"][^'\"\s]{8,}['\"]", "credential"),
]
# Words that must never be published (names, hostnames, account ids) live outside the repo, one regex per line.
PRIVATE_WORDS = os.environ.get("DAILY_JOBS_PRIVATE_WORDS") or os.path.expanduser("~/.config/daily-jobs/private-words")
if os.path.exists(PRIVATE_WORDS):
    with open(PRIVATE_WORDS) as _f:
        LEAKS += [(r"(?i)" + w.strip(), "private word") for w in _f if w.strip() and not w.startswith("#")]


def leaks(text):
    """[(what, excerpt)] for every line of text that looks like it carries something private."""
    out = []
    for line in text.splitlines():
        for rx, what in LEAKS:
            if re.search(rx, line):
                out.append((what, line.strip()[:160]))
    return out


def boards(src):
    cfgs = []
    for path in [os.path.join(src, "companies.json")] + sorted(glob.glob(os.path.join(src, "companies.d", "*.json"))):
        with open(path) as f:
            cfgs += json.load(f)
    out, seen = [], set()
    for c in cfgs:
        if c.get("ats") in EXCLUDED_ATS:
            continue
        c = {k: v for k, v in c.items() if k not in DROP_KEYS}
        key = json.dumps(c, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(c)
    out.sort(key=lambda c: (c["company"].lower(), c["ats"], json.dumps(c, sort_keys=True)))
    return "[\n" + ",\n".join(json.dumps(c, ensure_ascii=False) for c in out) + "\n]\n"


def plan(src):
    """{relative dest path: new text} for every file the sync owns."""
    files = {name: open(os.path.join(src, name)).read() for name in CODE}
    for path in sorted(glob.glob(os.path.join(src, "adapters", "*.py"))):
        files["adapters/" + os.path.basename(path)] = open(path).read()
    files["companies.json"] = boards(src)
    return files


def main():
    args = sys.argv[1:]
    src = args[args.index("--from") + 1] if "--from" in args else os.environ.get("JOBBOARD_SRC") or os.path.expanduser("~/projects/job-fit-board")
    files = plan(src)
    found = [(name, *hit) for name, text in files.items() for hit in leaks(text)]
    if found:
        for name, what, line in found:
            print(f"LEAK? {name}: {what}: {line}", file=sys.stderr)
        sys.exit(2)
    changed = []
    for name, text in files.items():
        dest = os.path.join(DEST, name)
        old = open(dest).read() if os.path.exists(dest) else None
        if old != text:
            changed.append(name)
    gone = [os.path.relpath(p, DEST) for p in glob.glob(os.path.join(DEST, "adapters", "*.py")) if os.path.relpath(p, DEST) not in files]
    for name in changed:
        print(("would update " if "--check" in args else "updated ") + name)
    for name in gone:
        print(("would remove " if "--check" in args else "removed ") + name)
    if "--check" in args:
        sys.exit(1 if changed or gone else 0)
    for name in changed:
        dest = os.path.join(DEST, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest + ".tmp", "w") as f:
            f.write(files[name])
        os.replace(dest + ".tmp", dest)
    for name in gone:
        os.remove(os.path.join(DEST, name))
    shutil.rmtree(os.path.join(DEST, "adapters", "__pycache__"), ignore_errors=True)
    if not changed and not gone:
        print("scrapers already up to date")


if __name__ == "__main__":
    main()
