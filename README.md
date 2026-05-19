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
demo/       # Local media/demo files, ignored by git
```

Note: You need to set up browser profile for this tool to work

## 1. YouTube / Conference Report To Notion

Use this workflow when you want to summarize many YouTube talks from a
conference agenda and send the result to Notion.

Recommended prompt:

```text
Use $youtube-report-skill to summarize all Day 1 topics in ETHCC9:
https://ethcc.io/ethcc-9/agenda?date=2026-03-30

Output report to https://www.notion.so/...
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

Run the collector for a specific role:

```powershell
python -m tools.daily_research.daily_research_tool `
  --role researcher `
  --date 2026-05-16 `
  --profile-dir "profiles\x_profile"
```

Other roles:

```powershell
python -m tools.daily_research.daily_research_tool --role bd
python -m tools.daily_research.daily_research_tool --role marketing
python -m tools.daily_research.daily_research_tool --role operations
```

Default role output examples:

```text
outputs/daily_research/researcher/
outputs/daily_research/bd/
outputs/daily_research/marketing/
outputs/daily_research/operations/
```

Set Telegram credentials:

```powershell
$env:TELEGRAM_BOT_TOKEN="<YOUR_TOKEN>"
$env:TELEGRAM_CHAT_ID="<YOUR_CHAT_ID>"
```

Optional config file:

```text
tools/daily_research/config/telegram_bot.config.example.json
```

Important config fields:

- `role`: role profile used by the Telegram bot, usually `researcher`, `bd`, `marketing`, or `operations`.
- `interval_minutes`: default polling interval, usually `30`.
- `profile_dir`: browser profile for X, default `profiles/x_profile`.
- `daily_research_config`: optional extra override config. Leave empty to use the selected role config directly.
- `state_path`: local state file used for sent-post de-duplication and Telegram runtime settings.
- `lock_path`: process lock that prevents multiple Telegram bot instances from sending duplicate posts.
- `min_technical_score`: minimum score before sending an item.
- `max_items_per_run`: max Telegram items per run.
- `skip_ethresearch`: set `true` to only use X.
- `headless`: set `true` for the scheduled Telegram bot so Chrome runs in the background.
- `enable_telegram_feedback`: adds inline feedback buttons to each Telegram post.
- `enable_telegram_commands`: enables bot commands such as `/role` and `/dashboard`.
- `feedback_path`: shared feedback store used by the dashboard and Telegram bot.
- `feedback_poll_seconds`: command/feedback polling interval when the bot runs continuously, usually `5`.
- `dashboard`: local dashboard launcher settings used by the `/dashboard` Telegram command.

The Telegram bot defaults to `headless: true` to avoid browser popups. For manual
debugging, use the dashboard or run `daily_research_tool` without `--headless`.

Telegram feedback buttons:

```text
Interested | Save | Not relevant | Hide author
```

The bot writes button clicks to:

```text
outputs/daily_research/feedback/<role>.json
```

With the scheduled-task `--once` runner, feedback clicks are processed on the
next scheduled run. For immediate button feedback, run the bot continuously:

```powershell
python -m tools.daily_research.telegram_digest_bot
```

When continuous mode is active, Telegram button clicks are acknowledged within
the configured `feedback_poll_seconds` window and the selected button is marked
with `[x]`. Click the selected `[x]` button again to clear the active feedback
and return the post to its initial button state.

Telegram commands:

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

Register these commands in Telegram's command menu:

```powershell
python -m tools.daily_research.register_telegram_commands
```

Run this once after setting `TELEGRAM_BOT_TOKEN`. The bot can still process
typed commands before registration, but Telegram will not show them in the `/`
autocomplete menu until `setMyCommands` has been called.

The selected Telegram role is stored in the bot state file, so a user who only
uses Telegram can switch roles without opening the dashboard. Future collection
runs use that active role's profile list, scoring rules, output directory, and
feedback store.

`/status` shows the active role, current interval, last run, queued immediate
run status, and dashboard API/frontend status.

`/run` queues an immediate collection run with the active role. `/run bd` runs
one immediate collection with the BD role without permanently changing the
active role.

`/interval` shows the current interval. `/interval 10m`, `/interval 30`, and
`/interval 1h` update the running bot's interval without restarting it.
`/interval reset` returns to the config file value.

`/dashboard` starts the local Python API and Vite frontend if they are not
already running, opens the browser on the machine running the bot, and sends the
dashboard URL back to Telegram. The default URL is `http://127.0.0.1:5173/`.
That local URL only works on the same computer; from a phone, use a LAN host,
VPN, or tunnel if you need remote access.

`/dashboard_stop` stops only the dashboard API and frontend processes that were
started by `/dashboard`. The Telegram bot keeps running. You can also send
`/dashboard stop`.

Test without sending:

```powershell
python -m tools.daily_research.telegram_digest_bot --once --dry-run
```

Send one run:

```powershell
python -m tools.daily_research.telegram_digest_bot --once
```

Run continuously:

```powershell
python -m tools.daily_research.telegram_digest_bot
```

Install as a Windows Scheduled Task:

```powershell
powershell -ExecutionPolicy Bypass -File tools\daily_research\install_telegram_scheduled_task.ps1
```

Install as a hidden Windows Scheduled Task, so no PowerShell window pops up:

```powershell
powershell -ExecutionPolicy Bypass -File tools\daily_research\install_telegram_scheduled_task_hidden.ps1
```

Install as a hidden continuous background task, so inline feedback buttons work
immediately between collection runs:

```powershell
powershell -ExecutionPolicy Bypass -File tools\daily_research\install_telegram_scheduled_task_hidden.ps1 -Continuous
Start-ScheduledTask -TaskName "DailyResearchTelegramBot"
```

Task controls:

```powershell
Start-ScheduledTask -TaskName "DailyResearchTelegramBot"
Stop-ScheduledTask -TaskName "DailyResearchTelegramBot"
Disable-ScheduledTask -TaskName "DailyResearchTelegramBot"
Enable-ScheduledTask -TaskName "DailyResearchTelegramBot"
powershell -ExecutionPolicy Bypass -File tools\daily_research\uninstall_telegram_scheduled_task.ps1
```

Logs are saved to:

```text
outputs/daily_research/telegram_logs/
```

### Docker / macOS Telegram Bot

Docker is the recommended cross-platform path for macOS and Linux users. It
replaces Windows Task Scheduler with Docker's `restart: unless-stopped` process
supervision.

The Docker setup defaults to `linux/amd64` because that is the safest target for
Windows Docker Desktop and Playwright Chromium. On Apple Silicon, Docker Desktop
can run this through emulation. If you explicitly want to try native ARM64, set
`DAILY_RESEARCH_DOCKER_PLATFORM=linux/arm64` before building.

Important: host Chrome cookies are usually encrypted by the host OS, so do not
copy a Windows or macOS Chrome profile into Docker and expect X login to work.
Instead, create a Docker-owned X profile once, then let the Telegram bot reuse
that profile.

Create a Telegram-only environment file from the template:

```bash
cp docker/env.example .env.telegram
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

One-time X login:

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

After login succeeds, stop the login service with `Ctrl+C`, then start the
Telegram bot:

```bash
docker compose up -d telegram-bot
```

Do not leave `x-login` running while the bot or dashboard collects X data.
`x-login` and `telegram-bot` share the same Docker profile, so a running login
container will lock `profiles/x_profile`.

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

Use this workflow when you want to run daily collection from a local web UI,
filter by date, inspect the generated digest, and load previous results.

Terminal 1: start the Python API server:

```powershell
python -m tools.daily_research.dashboard_api
```

Terminal 2: start the frontend:

```powershell
cd frontend
npm.cmd run dev
```

Open the URL printed by Vite. From the UI you can:

- Select a role profile: Researcher, BD, Marketing, or Operations.
- Pick a target date.
- Run collection for that date.
- Load the latest generated digest.
- Upload a JSON digest manually.
- Mark items as `Interested`, `Save`, `Not relevant`, or `Hide author`.

Feedback is stored locally at:

```text
outputs/daily_research/feedback_store.json
```

Future runs use this feedback to adjust ranking. Positive feedback boosts matching
authors and technical signals; negative feedback lowers similar items or hidden
authors. The raw technical score is preserved, while `personalized_score` is used
for dashboard sorting and Telegram selection.

Direct script usage:

```powershell
python -m tools.daily_research.daily_research_tool `
  --role researcher `
  --date 2026-05-10 `
  --profile-dir "profiles\x_profile" `
  --output-dir "outputs\daily_research\researcher"
```

Useful options:

```powershell
# Only collect ethresear.ch.
python -m tools.daily_research.daily_research_tool --skip-x

# Only collect X.
python -m tools.daily_research.daily_research_tool --skip-ethresearch

# Include configured X search sections.
python -m tools.daily_research.daily_research_tool --include-x-search

# Add one X profile for a single run.
python -m tools.daily_research.daily_research_tool `
  --x-profile "https://x.com/ethereum"

# Add one custom X query.
python -m tools.daily_research.daily_research_tool `
  --x-query "MEV::MEV PBS ethereum"

# Adjust quality filter.
python -m tools.daily_research.daily_research_tool `
  --x-min-technical-score 6
```

Output:

```text
outputs/daily_research/<YYYY-MM-DD>/
|-- daily_research_digest.md
`-- daily_research_digest.json
```
