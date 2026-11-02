# Running the publisher

`tools/publish.py daily` runs every morning on the machine that runs the scrapers (a user-level systemd timer; with
lingering on, it runs without a login session):

1. waits for the morning scan to release its pipeline lock (`<scanner checkout>/.lock`),
2. copies the latest scrapers and board list from the scanner checkout (`tools/sync_code.py`; refused if the leak scan
   finds anything, reverted if the tests fail),
3. parses the scanner's store (`<scanner checkout>/postings`) into `~/.local/state/daily-jobs/build/`,
4. rebuilds `jobs/*.md` and the README stats, commits and pushes `main`,
5. publishes release `data-YYYY-MM-DD` and deletes all but the newest 7.

A failure leaves the maintainer a note (`note`, when installed) with the error. Paths default to
`~/projects/job-fit-board`; override with `JOBBOARD_SRC` and `JOBBOARD_STORE`.

Install or update:

```sh
mkdir -p ~/.config/systemd/user
cp ops/daily-jobs-publish.service ops/daily-jobs-publish.timer ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now daily-jobs-publish.timer
```

Run now: `systemctl --user start daily-jobs-publish` (logs: `journalctl --user -u daily-jobs-publish`).
Run by hand without pushing: `python3 tools/publish.py daily --no-push`.

Pushing goes over HTTPS with `gh` as the git credential helper, and falls back to SSH. Releases go through `gh`.
