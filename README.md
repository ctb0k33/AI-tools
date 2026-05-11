# AI Tools

Local automation tools for research, transcript collection, conference-report
generation, and lightweight dashboards.

## Repository Layout

```text
.
|-- demo/                         # Local video/media scratch space; ignored by git
|-- frontend/                     # React + TypeScript daily research dashboard
|   |-- public/sample/
|   |-- src/
|   |-- package.json
|   `-- vite.config.ts
|-- outputs/                      # Generated reports, transcripts, logs, temp deps; ignored by git
|-- profiles/                     # Local browser profiles for Playwright; ignored by git
|-- tests/
|   |-- test_daily_research_tool.py
|   |-- test_following_account_audit.py
|   `-- test_youtube_transcript_tool.py
|-- tools/
|   |-- conference_reports/        # ETHCC agenda, transcript, report, and Notion helpers
|   |-- daily_research/            # X + ethresear.ch collector, API bridge, Telegram bot
|   |-- skills/
|   |   `-- youtube-report-skill/
|   `-- youtube/
|       `-- youtube_transcript_tool.py
|-- ARCHITECTURE.md
|-- README.md
|-- SKILL.md
`-- requirements.txt
```

## Install

Python dependencies:

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

Frontend dependencies:

```powershell
cd frontend
npm.cmd install
```

## YouTube Transcript Tool

Scrapes YouTube transcripts through the visible YouTube UI with Playwright. Use
the project-local YouTube Chrome profile unless a workflow explicitly asks for a
different one.

```powershell
python -m tools.youtube.youtube_transcript_tool `
  "https://www.youtube.com/watch?v=VIDEO_ID" `
  --profile-dir "profiles\chrome profile"
```

Output:

```text
outputs/youtube_transcripts/<video_id>/
|-- metadata.json
|-- transcript.json
`-- transcript.txt
```

## Conference Reports

The `tools/conference_reports/` pipeline collects ETHCC agenda metadata,
resolves archive YouTube URLs, extracts UI transcripts, builds a five-section
Markdown report, and optionally splits it into Notion-sized chunks.

Typical Day 2 run:

```powershell
python tools\conference_reports\ethcc9_collect_day.py `
  --date 2026-03-31 `
  --agenda-url "https://ethcc.io/ethcc-9/agenda?date=2026-03-31" `
  --output-dir "outputs\conference_reports\ethcc9_day2_2026-03-31"

python tools\conference_reports\ethcc9_extract_transcripts.py `
  --topics "outputs\conference_reports\ethcc9_day2_2026-03-31\metadata\topics.json" `
  --profile-dir "profiles\chrome profile" `
  --transcripts-root "outputs\conference_reports\ethcc9_day2_2026-03-31\transcripts" `
  --failures "outputs\conference_reports\ethcc9_day2_2026-03-31\failures.json" `
  --results "outputs\conference_reports\ethcc9_day2_2026-03-31\metadata\transcript_results.json"

python tools\conference_reports\ethcc9_build_report.py `
  --base-dir "outputs\conference_reports\ethcc9_day2_2026-03-31"
```

Optional Notion helpers:

```powershell
python tools\conference_reports\ethcc9_build_notion_compact.py `
  --base-dir "outputs\conference_reports\ethcc9_day2_2026-03-31"

python tools\conference_reports\ethcc9_split_report.py `
  --report "outputs\conference_reports\ethcc9_day2_2026-03-31\report.md" `
  --output-dir "outputs\conference_reports\ethcc9_day2_2026-03-31\notion_chunks"

python tools\conference_reports\ethcc9_split_compact.py `
  --input "outputs\conference_reports\ethcc9_day2_2026-03-31\notion_compact_append.md" `
  --output-dir "outputs\conference_reports\ethcc9_day2_2026-03-31\notion_compact_chunks"
```

Output shape:

```text
outputs/conference_reports/<event_slug>/
|-- failures.json
|-- metadata/
|   |-- agenda.html
|   |-- topics.json
|   `-- transcript_results.json
|-- transcripts/<topic_slug>/<video_id>/
|   |-- metadata.json
|   |-- transcript.json
|   `-- transcript.txt
|-- summaries/<topic_slug>.md
|-- report.md
|-- notion_chunks/
`-- notion_compact_chunks/
```

The local skill copy for this workflow lives at:

```text
tools/skills/youtube-report-skill/SKILL.md
```

## Daily DeFi/Core Research Tool

Collects same-day DeFi and blockchain core signals from X, then combines them
with new ethresear.ch research posts.

X collection uses Playwright with a persistent Chrome profile because X is much
more reliable when the browser is already signed in. ethresear.ch collection
uses Discourse JSON endpoints.

The collector treats X as a curation source rather than a comment feed:

- It extracts only the original tweet body from X `tweetText` DOM nodes.
- It filters replies and quote/commentary posts by default.
- It reads an editable profile allowlist from
  `tools\daily_research\selected_x_profiles.config.json`.
- It can use accounts followed by `https://x.com/Ctb0k33/following` as a
  broader trusted-source list.
- It reads `https://x.com/home` as a timeline source by default.
- X keyword search is disabled by default; pass `--include-x-search` or
  `--x-query` when you explicitly want it.
- Date validation reads each tweet DOM timestamp instead of relying on search
  operators.
- It writes a short `Summary` plus the cleaned `Original post` for each X item.
- It filters out price chatter, NFT/portfolio posts, generic promotion, and low
  technical-score posts.

```powershell
python -m tools.daily_research.daily_research_tool `
  --date 2026-05-10 `
  --profile-dir "profiles\ctb0k33" `
  --config "tools\daily_research\selected_x_profiles.config.json" `
  --output-dir "outputs\daily_research"
```

Before running, close any normal Chrome window that is using
`profiles\ctb0k33`; Playwright needs the profile lock.

Useful options:

```powershell
# Include configured X search sections.
python -m tools.daily_research.daily_research_tool --include-x-search

# Add one profile for a single run without editing config.
python -m tools.daily_research.daily_research_tool --x-profile "https://x.com/ethereum"

# Add one extra X query section.
python -m tools.daily_research.daily_research_tool `
  --profile-dir "profiles\ctb0k33" `
  --x-query "MEV::MEV PBS ethereum"

# Skip X and only collect ethresear.ch posts.
python -m tools.daily_research.daily_research_tool --skip-x

# Skip the X home timeline.
python -m tools.daily_research.daily_research_tool --skip-x-home

# Skip followed profile scanning and only use the home timeline.
python -m tools.daily_research.daily_research_tool --skip-x-following

# Scan a smaller followed-profile sample for faster runs.
python -m tools.daily_research.daily_research_tool --max-following-profiles 30

# Include quote/commentary posts if you want a broader feed.
python -m tools.daily_research.daily_research_tool --include-quotes

# Run with a custom query/category config.
python -m tools.daily_research.daily_research_tool `
  --config "tools\daily_research\daily_research_config.example.json"
```

Output:

```text
outputs/daily_research/<YYYY-MM-DD>/
|-- daily_research_digest.md
`-- daily_research_digest.json
```

## Daily Research Dashboard

The dashboard has a small Python API bridge and a Vite frontend.

Start the API bridge from the project root:

```powershell
python -m tools.daily_research.dashboard_api
```

Start the frontend:

```powershell
cd frontend
npm.cmd run dev
```

The app can load `frontend/public/sample/daily_research_digest.json`, load the
latest generated output, upload a JSON digest, or call `POST /api/collect` to
run the collector from the UI.

## Dedicated X Profile

For a clean X session, create a dedicated project-local Chrome profile for the
`ctb0k33` account. This helper is only for the first login/bootstrap step:

```powershell
python -m tools.daily_research.open_chrome_profile `
  --profile-dir "profiles\ctb0k33" `
  --start-url "https://x.com/home"
```

Sign in to X once in that Chrome window, then close it before running the
Playwright collector.

To loosen or tighten the X quality filter:

```powershell
python -m tools.daily_research.daily_research_tool `
  --date 2026-05-10 `
  --profile-dir "profiles\ctb0k33" `
  --x-min-technical-score 4
```

## Following Account Audit

Use this before tuning the daily collector. It reads the accounts followed by
`@Ctb0k33`, prefilters them from following-card text, then slowly audits a small
number of recent original posts per candidate profile.

The audit writes a checkpoint after every profile and stops early by default if
X shows rate-limit UI.

```powershell
python -m tools.daily_research.following_account_audit `
  --profile-dir "profiles\ctb0k33" `
  --owner Ctb0k33 `
  --max-profiles 40 `
  --posts-per-profile 4 `
  --profile-delay-seconds 12 `
  --jitter-seconds 6
```

Useful options:

```powershell
# Use the cached following candidate list and audit fewer profiles.
python -m tools.daily_research.following_account_audit `
  --max-profiles 20 `
  --posts-per-profile 3

# Refresh the following list cache.
python -m tools.daily_research.following_account_audit --refresh-following --cache-only

# If X is already rate-limiting, wait before retrying.
python -m tools.daily_research.following_account_audit `
  --cooldown-seconds 300 `
  --max-profiles 10
```

## Telegram Digest Bot

Set your Telegram credentials in PowerShell:

```powershell
$env:TELEGRAM_BOT_TOKEN="<YOUR_TOKEN>"
$env:TELEGRAM_CHAT_ID="<YOUR_CHAT_ID>"
```

Test one run without sending messages:

```powershell
python -m tools.daily_research.telegram_digest_bot --once --dry-run
```

Send one run to Telegram:

```powershell
python -m tools.daily_research.telegram_digest_bot --once
```

Run continuously using the configured interval, default 30 minutes:

```powershell
python -m tools.daily_research.telegram_digest_bot
```

Copy and edit `tools/daily_research/telegram_bot.config.example.json` to adjust
the interval, score threshold, output path, state path, Chrome profile path, or
`send_run_markers` batch-boundary messages.

Install the Windows Scheduled Task:

```powershell
powershell -ExecutionPolicy Bypass -File tools\daily_research\install_telegram_scheduled_task.ps1
```

Task controls:

```powershell
Start-ScheduledTask -TaskName "DailyResearchTelegramBot"
Stop-ScheduledTask -TaskName "DailyResearchTelegramBot"
Disable-ScheduledTask -TaskName "DailyResearchTelegramBot"
Enable-ScheduledTask -TaskName "DailyResearchTelegramBot"
powershell -ExecutionPolicy Bypass -File tools\daily_research\uninstall_telegram_scheduled_task.ps1
```

Logs:

```text
outputs/daily_research/telegram_logs/
```

## Advanced CDP Backend

The CDP backend is optional and mostly useful for debugging or attaching to a
Chrome instance that was already started with a DevTools endpoint:

```powershell
python -m tools.daily_research.daily_research_tool `
  --x-backend chrome-cdp `
  --attach-cdp-url "http://127.0.0.1:9222"
```

## Local Media And Generated Files

- `profiles/` stores signed-in browser state and should not be committed.
- `outputs/` stores generated reports, transcripts, logs, chunks, and temporary
  runtime dependencies.
- `demo/` stores local media files and rendered demo videos.
- These folders are ignored by git.

## Testing

```powershell
python -m unittest discover -s tests -v
```
