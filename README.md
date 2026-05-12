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

Set Telegram credentials:

```powershell
$env:TELEGRAM_BOT_TOKEN="<YOUR_TOKEN>"
$env:TELEGRAM_CHAT_ID="<YOUR_CHAT_ID>"
```

Optional config file:

```text
tools/daily_research/telegram_bot.config.example.json
```

Important config fields:

- `interval_minutes`: default polling interval, usually `30`.
- `profile_dir`: browser profile for X, default `profiles/ctb0k33`.
- `daily_research_config`: source/filter config.
- `min_technical_score`: minimum score before sending an item.
- `max_items_per_run`: max Telegram items per run.
- `skip_ethresearch`: set `true` to only use X.
- `headless`: set `true` for the scheduled Telegram bot so Chrome runs in the background.

The Telegram bot defaults to `headless: true` to avoid browser popups. For manual
debugging, use the dashboard or run `daily_research_tool` without `--headless`.

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

- Pick a target date.
- Run collection for that date.
- Load the latest generated digest.
- Upload a JSON digest manually.

Direct script usage:

```powershell
python -m tools.daily_research.daily_research_tool `
  --date 2026-05-10 `
  --profile-dir "profiles\ctb0k33" `
  --config "tools\daily_research\selected_x_profiles.config.json" `
  --output-dir "outputs\daily_research"
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
