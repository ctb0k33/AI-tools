# AI Tools

AI Tools is a local research assistant for crypto workflows. It helps collect
signals from X and ethresear.ch, summarize YouTube talks from conferences, and
write structured research reports to Notion.

## Setup

Install Python dependencies:

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

Install frontend dependencies:

```powershell
cd frontend
npm.cmd install
```

Local-only folders:

```text
profiles/   # Signed-in browser profiles, ignored by git
outputs/    # Generated reports, transcripts, logs, ignored by git
```

Note: You need to set up browser profile for this tool to work

## 1. YouTube / Conference Report To Notion

Use this workflow when you want to summarize many YouTube talks from a
conference agenda and send the result to Notion.

Recommended prompt (codex):

```text
Use $youtube-report-skill to summarize all Day 1 topics in ETHCC9:
https://ethcc.io/ethcc-9/agenda?date=2026-03-30

Output report to https://www.notion.so/...
```

```
Note: youtube-report-skill & notion plugin need to be installed
```

What it does:

- Collects topic metadata from the agenda page.
- Finds archive / YouTube links for each topic.
- Extracts transcripts using the local YouTube profile.
- Summarizes each talk into structured research notes.
- Writes the final report to the target Notion page.

Before running:

- Make sure `profiles\chrome profile` is signed in to YouTube.
- Make sure the Notion connector/plugin is available if you want Notion output.
- Make sure your agent ready to use `youtube-report-skill`
- Generated artifacts are saved under `outputs\conference_reports\...`.

### Configure YouTube Profile

The YouTube transcript workflow uses a local Chrome profile that is separate
from the X research profile:

```text
profiles/chrome profile
```

Open Chrome once with that profile, sign in to YouTube, then close Chrome before
running a transcript batch:

```powershell
python -m tools.daily_research.open_chrome_profile `
  --profile-dir "profiles\chrome profile" `
  --start-url "https://www.youtube.com/"
```

On macOS/Linux:

```bash
python -m tools.daily_research.open_chrome_profile --profile-dir "profiles/chrome profile" --start-url "https://www.youtube.com/"
```

If Chrome is not auto-detected on macOS, pass the Chrome path explicitly:

```bash
python -m tools.daily_research.open_chrome_profile --profile-dir "profiles/chrome profile" --start-url "https://www.youtube.com/" --chrome-path "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```

Use this profile for YouTube transcript extraction:

```powershell
python -m tools.youtube.youtube_transcript_tool `
  "https://www.youtube.com/watch?v=<VIDEO_ID>" `
  --profile-dir "profiles\chrome profile"
```

Do not reuse the Docker X profile for YouTube. X and YouTube should have
separate browser profiles so login state and automation locks do not interfere.

Manual script version:

```powershell
python tools\conference_reports\ethcc9_collect_day.py `
  --date 2026-03-30 `
  --agenda-url "https://ethcc.io/ethcc-9/agenda?date=2026-03-30" `
  --output-dir "outputs\conference_reports\ethcc9_day1_2026-03-30"

python tools\conference_reports\ethcc9_extract_transcripts.py `
  --topics "outputs\conference_reports\ethcc9_day1_2026-03-30\metadata\topics.json" `
  --profile-dir "profiles\chrome profile" `
  --transcripts-root "outputs\conference_reports\ethcc9_day1_2026-03-30\transcripts" `
  --failures "outputs\conference_reports\ethcc9_day1_2026-03-30\failures.json" `
  --results "outputs\conference_reports\ethcc9_day1_2026-03-30\metadata\transcript_results.json"

python tools\conference_reports\ethcc9_build_report.py `
  --base-dir "outputs\conference_reports\ethcc9_day1_2026-03-30"
```

Main output:

```text
outputs/conference_reports/<event_slug>/
|-- metadata/topics.json
|-- metadata/transcript_results.json
|-- transcripts/
|-- summaries/
|-- failures.json
`-- report.md
```

## 2. X Research Telegram Bot

Use this workflow when you want important X / ethresear.ch updates pushed to
Telegram automatically.

### Code Layout

The daily research tool is split by responsibility:

```text
tools/daily_research/
|-- daily_research_tool.py        # public CLI entrypoint
|-- telegram_digest_bot.py        # public Telegram bot entrypoint
|-- dashboard_api.py              # public dashboard API entrypoint
|-- register_telegram_commands.py # public command-registration entrypoint
|-- core/                         # models, config, role loading, feedback, scoring
|-- collectors/                   # Playwright runner and Chrome CDP backend
|-- reports/                      # JSON/Markdown digest rendering
|-- telegram/                     # Telegram commands, state, API helpers, bot loop
|-- dashboard/                    # local HTTP API implementation
|-- audit/                        # following-account audit utility
|-- scripts/                      # Python helper scripts
`-- config/                       # tool, Telegram, profile, and role JSON config
```

### Role Profiles

The daily research collector and Telegram bot can be tuned for different roles.
Role configs live in:

```text
tools/daily_research/config/roles/
|-- researcher.config.json
|-- bd.config.json
|-- marketing.config.json
`-- operations.config.json
```

Each role controls:

- X profiles and home timeline scan limits.
- Keyword categories and scoring weights.
- Low-value filters.
- Output directory.
- Feedback store used for personalized ranking.

Default role output examples:

```text
outputs/daily_research/researcher/
outputs/daily_research/bd/
outputs/daily_research/marketing/
outputs/daily_research/operations/
```

### Customize Role Configs

Edit the role JSON file for the audience you want to tune. For example:

```text
tools/daily_research/config/roles/researcher.config.json
```

Add or remove X accounts in `x_profiles.handles`:

```json
"x_profiles": {
  "enabled": true,
  "max_items_per_profile": 4,
  "handles": [
    "https://x.com/ethresearchbot",
    "https://x.com/ethereum",
    "https://x.com/<another_account>"
  ]
}
```

Add keywords or scoring terms in `keyword_categories` and
`x_quality_filter.positive_terms`:

```json
"keyword_categories": {
  "Core Protocol": ["ethereum core", "eip", "peerdas", "focil"],
  "Security": ["audit", "exploit", "vulnerability", "oracle"]
},
"x_quality_filter": {
  "positive_terms": {
    "eip": 3,
    "security alert": 4,
    "postmortem": 3
  },
  "low_value_terms": ["airdrop", "giveaway", "price prediction"]
}
```

Common role tuning fields:

- `x_home.enabled`: include or skip the user's X home timeline.
- `x_home.max_items`: how many home timeline posts to scan before filtering.
- `x_profiles.handles`: curated accounts to scan directly.
- `x_quality_filter.min_technical_score`: minimum score before a post is kept.
- `x_quality_filter.low_value_terms`: phrases to filter out.
- `personalization.feedback_path`: per-role feedback store.

Feedback buttons from Telegram and the dashboard write to:

```text
outputs/daily_research/feedback/<role>.json
```

Future runs use that feedback to adjust ranking for the same role.

Useful Telegram commands after the Docker bot is running:

```text
/help
/status
/run
/run bd
/interval
/interval 10m
/interval 1h
/interval reset
/roles
/role
/role researcher
/role bd
/role marketing
/role operations
/dashboard
/dashboard_stop
```

`/dashboard` starts the dashboard API/frontend inside the Docker bot container
and returns `http://127.0.0.1:5173/`. `/dashboard_stop` stops only the dashboard;
the Telegram bot keeps running.

### Docker Telegram Bot Setup

Docker is the recommended cross-platform path for macOS and Linux users. It
replaces Windows Task Scheduler with Docker's `restart: unless-stopped` process
supervision.

The Docker setup defaults to `linux/amd64` because that is the safest target for
Windows Docker Desktop and Playwright Chromium. On Apple Silicon, Docker Desktop
can run this through emulation. If you explicitly want to try native ARM64, set
`DAILY_RESEARCH_DOCKER_PLATFORM=linux/arm64` before building; the Compose file
passes that platform to both the service and Dockerfile build stages.

Important: host Chrome cookies are usually encrypted by the host OS, so do not
copy a Windows or macOS Chrome profile into Docker and expect X login to work.
Instead, create a Docker-owned X profile once, then let the Telegram bot reuse
that profile.

Create a Telegram-only environment file from the template:

```bash
cp docker/env.example .env.telegram
```

On Windows PowerShell:

```powershell
Copy-Item docker\env.example .env.telegram
```

Edit `.env.telegram`:

```text
TELEGRAM_BOT_TOKEN=<YOUR_TELEGRAM_BOT_TOKEN>
TELEGRAM_CHAT_ID=<YOUR_TELEGRAM_CHAT_ID>
```

Keep `.env.telegram` local and do not share `docker compose config` output from
a machine that has real credentials loaded.

Build the Docker image:

```bash
docker compose build
```

#### Configure X Profile For Docker

Docker cannot reliably reuse a normal Windows or macOS Chrome profile because
host Chrome cookies are encrypted by the host OS. Create and use the Docker
profile instead:

```text
profiles/x_profile
```

Start the temporary login container:

```bash
docker compose --profile login up x-login
```

Open this URL on the host machine:

```text
http://localhost:7900/vnc.html
```

Use the browser shown in noVNC to sign in to X. The authenticated profile is
stored in:

```text
profiles/x_profile
```

After login succeeds, stop the login service with `Ctrl+C` or:

```bash
docker compose stop x-login
```

Only use `x-login` for first-time login or re-login. Do not leave it running
while the bot or dashboard collects X data. `x-login` and `telegram-bot` share
the same Docker profile, so a running login container will lock
`profiles/x_profile`.

The login container writes `profiles/x_profile/.x-login-active` while it is
running. If collection reports that this marker is active, stop `x-login` before
retrying. The bot only removes stale Chromium locks when this marker is absent.

If noVNC opens but only shows a black screen, Chrome probably exited during
login startup or the Docker X profile has a stale lock. Check the login logs:

```bash
docker compose logs --tail=120 x-login
```

Chrome startup logs are written inside the login container at:

```text
/tmp/chrome.log
```

If the profile keeps crashing and it has not been successfully signed in yet,
reset it by backing up the old Docker profile and creating a fresh one.

Windows PowerShell:

```powershell
docker compose stop x-login telegram-bot
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
Move-Item "profiles\x_profile" "profiles\x_profile.bak_$ts"
New-Item -ItemType Directory -Force "profiles\x_profile"
docker compose --profile login up -d --force-recreate x-login
```

macOS/Linux:

```bash
docker compose stop x-login telegram-bot
ts="$(date +%Y%m%d_%H%M%S)"
mv profiles/x_profile "profiles/x_profile.bak_$ts"
mkdir -p profiles/x_profile
docker compose --profile login up -d --force-recreate x-login
```

Then reopen `http://localhost:7900/vnc.html` and sign in again. Only reset the
profile when you are willing to sign in to X again, because the active Docker
login session is stored in `profiles/x_profile`.

Start the Telegram bot:

```bash
docker compose up -d telegram-bot
```

After a machine restart, open Docker Desktop and start only `telegram-bot`.
Starting it from the Docker Desktop UI is equivalent to:

```bash
docker compose up -d telegram-bot
```

Docker controls:

```bash
docker compose logs -f telegram-bot
docker compose restart telegram-bot
docker compose stop telegram-bot
docker compose down
```

Register Telegram commands from Docker:

```bash
docker compose run --rm telegram-bot python -m tools.daily_research.register_telegram_commands
```

Run this once after `.env.telegram` is configured. The bot can still process
typed commands before registration, but Telegram will not show them in the `/`
autocomplete menu until `setMyCommands` has been called.

Docker uses:

```text
tools/daily_research/config/telegram_bot.docker.json
```

The Docker config defaults to `profiles/x_profile`, runs headless, persists
outputs under `outputs/`, and keeps Telegram state under
`outputs/daily_research/telegram_state_researcher.json`.

Docker-specific runtime defaults are set in `docker-compose.yml`:

```text
DAILY_RESEARCH_PROFILE_DIR=profiles/x_profile
DAILY_RESEARCH_HEADLESS=1
DAILY_RESEARCH_PREFER_BUNDLED_CHROMIUM=1
DAILY_RESEARCH_UNLOCK_STALE_PROFILE=1
```

These keep the collector headless, use Playwright's bundled Chromium, and clean
stale Chromium profile locks left by an old login container.

## 3. X / ethresear.ch Dashboard

The dashboard is opened from the Telegram bot in the Docker flow. Send:

```text
/dashboard
```

The bot starts the API and frontend inside the `telegram-bot` container and
returns:

```text
http://127.0.0.1:5173/
```

Open that URL on the same machine that is running Docker. From the UI you can:

- Select a role profile: Researcher, BD, Marketing, or Operations.
- Pick a target date.
- Run collection for that date.
- Load the latest generated digest.
- Upload a JSON digest manually.
- Mark items as `Interested`, `Save`, `Not relevant`, or `Hide author`.

Stop only the dashboard, while keeping the Telegram bot alive:

```text
/dashboard_stop
```

Feedback is stored per role and shared by Telegram and the dashboard. Positive
feedback boosts matching authors and technical signals; negative feedback lowers
similar items or hidden authors. The raw technical score is preserved, while
`personalized_score` is used for dashboard sorting and Telegram selection.

Output:

```text
outputs/daily_research/<YYYY-MM-DD>/
|-- daily_research_digest.md
`-- daily_research_digest.json
```
