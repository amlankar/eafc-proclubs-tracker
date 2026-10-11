# Setup and operations

Run these commands from the project root.

## Get started

```bash
cp config.example.toml config.toml
# Edit config.toml: set your club name, numeric club ID, platform and edition.
python3 -m proclubs init
python3 -m proclubs collect
python3 -m proclubs serve
```

Open `http://127.0.0.1:8765` on the same machine. Manual serving defaults to loopback. Collection starts a baseline from the current available data; it cannot reconstruct older detailed matches. Club and edition identity are bound to the archive: use a separate data directory for another club or release.

On Linux with a systemd user manager, `bash scripts/setup.sh` installs the adaptive collector timer. It preserves existing data, initializes a new archive if necessary, and restarts the protected viewer when credentials exist. Setup itself does not fetch EA data. Services run while the machine and user manager are running; setup does not enable login lingering or wake a sleeping PC.

For an offline demonstration, use the anonymized test fixture in a separate directory:

```bash
python3 -m proclubs --config tests/fixtures/config.toml --data-dir data/demo import-seed tests/fixtures/seed
python3 -m proclubs --config tests/fixtures/config.toml --data-dir data/demo serve
```

## Dashboard and data

- **Overview:** results, goals, division history, skill rating, detailed shooting, passing, defending and ball control, plus team trends.
- **Players:** unified profiles, totals/per-match counts, detailed categories, pitch-third breakdowns and head-to-head comparisons.
- **Matches:** league, friendly and playoff results with team and individual drilldowns. Date and type filters apply to detailed stats.
- **Explanations:** hover, focus or tap dotted stat labels to see meanings and calculations.

Trends use captured detailed matches only. Rates pool attempts and successes; ratings average rated appearances. Missing values remain gaps. Pitch graphics show area totals, not event coordinates or heatmaps. All captured matches feed aggregates and histories; the match list displays the latest 500 filtered games.

EA cumulative snapshots and captured match totals have different coverage. They are stored separately and never blindly added together. A tracking ledger carries the baseline forward with captured league matches strictly after that baseline. Raw payloads and corrected versions are retained; repeated payloads and match IDs are deduplicated. See [the stat inventory](match-stats.md) and [decoder research and attribution](research.md).

## Collection policy

Idle collection runs hourly: six endpoints, with up to four metadata endpoints refreshed daily. Recent newly discovered matches activate ten-minute checks of the three match endpoints for a 30-minute window. The minute-by-minute timer checks eligibility without making requests when collection is not due. Requests are sequential and spaced at least three seconds apart, with no automatic retries or bypasses.

Ordinary errors impose a one-hour cooldown; HTTP 401/403/429 impose at least 24 hours. Longer `Retry-After` values are respected. Configuration validation prevents shortening these safeguards. Completed responses are retained if a later endpoint fails.

The first game in a session can take up to an hour to discover. EA's recent-match window is limited: an extended outage or window turnover can lose detailed games. Cumulative totals cannot recover those details. The subtle Playing marker reflects recent completed matches, not live presence. Browser refreshes read the local archive and never trigger collection.

## Protected sharing

With Tailscale installed, connected and Funnel authorized:

```bash
bash scripts/share.sh start
bash scripts/share.sh status
bash scripts/share.sh rotate
bash scripts/share.sh stop
```

The helper generates a random password and provisions the authenticated viewer on loopback port 8766. Username: `club`. Read the password from private `data/sharing-password.txt`; never commit or publish it. Funnel provides HTTPS on port 443. Account enablement or administrator permission may be required. The shared link requires this machine and its services to remain running.

Every viewer route requires authentication. GET is the only supported HTTP method, database connections are read-only, and the full raw archive export is unavailable on the protected viewer. Player CSV and match details remain available to signed-in friends. Requests have bounded workers, timeouts, security headers and failed-login throttling. Password verifiers use salted PBKDF2; legacy local verifiers migrate without changing the password. See [security and exposure limits](security.md).

The optional `scripts/funnel-watch.py` admin tool reads the hostname from private `data/funnel-host.txt`; it checks public DNS and HTTPS without altering Tailscale or calling EA. The optional `scripts/cloudflare-day.sh` fallback creates an explicitly requested, temporary 24-hour Quick Tunnel. Neither is required for normal collection.

## Backups and administration

Runtime data, configuration, credentials and original snapshots live outside Git. Back up the archive with SQLite's consistent backup operation rather than copying a live database:

```bash
python3 -m proclubs status
python3 -m proclubs backup data/backups/archive.sqlite3
python3 -m proclubs export data/exports/archive.json
journalctl --user -u pro-clubs-collect.service -n 40
systemctl --user stop pro-clubs-collect.timer
systemctl --user start pro-clubs-collect.timer
```

Choose a fresh backup filename. To restore, stop collection and the viewer, restore the backup into a new data directory, and use `--data-dir` before the CLI command. Keep the original archive until recovery is verified. JSON exports are for inspection; SQLite backups are the supported restoration path. Existing private starting snapshots can be imported from `data/seed/`.

## Development and checks

Development dependencies are pinned in `uv.lock` and `package-lock.json`:

```bash
uv sync --frozen --group dev
npm ci --ignore-scripts
uv run python scripts/check.py
uv run python -m unittest discover -s tests
uv run playwright install chromium
uv run python tests/browser_smoke.py
```

Checks cover Python lint/format/syntax, JavaScript syntax, frontend formatting, Bash syntax, TOML/JSON parsing. Tests exercise archive corrections, identity, weighted aggregates, trends, cooldowns, read-only HTTP access and security boundaries. Browser checks start an isolated authenticated server with anonymized fixtures, block external page requests, and cover desktop, mobile and keyboard interactions. They never read your live credentials or call EA.

Format changes with `uv run ruff format proclubs scripts tests` and `npm run format`. Checks run locally; collection stays on this machine. There are no GitHub Actions workflows or automated dependency-update jobs.
