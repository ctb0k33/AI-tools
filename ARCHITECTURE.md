# Architecture

This repository keeps small, focused research automation tools under `tools/`.
Each tool is a Python module that can be run with `python -m ...`, writes output
under `outputs/`, and keeps browser state under `profiles/`.

## YouTube Transcript Flow

File:

```text
tools/youtube/youtube_transcript_tool.py
```

Flow:

```text
Input YouTube URL / video id
        |
        v
Normalize video id and watch URL
        |
        v
Open YouTube with Playwright persistent Chrome profile
        |
        v
Open the transcript panel in the YouTube UI
        |
        v
Scrape transcript segments from DOM
        |
        v
Write metadata.json, transcript.json, transcript.txt
```

The tool intentionally avoids transcript APIs because those endpoints are more
likely to hit CAPTCHA, rate limits, or API drift.

## Daily DeFi/Core Research Flow

File:

```text
tools/daily_research/daily_research_tool.py
```

Optional helper:

```text
tools/daily_research/open_chrome_profile.py
tools/daily_research/following_account_audit.py
```

This helper opens a project-local Chrome profile such as `profiles/x_profile` so
the user can sign in to X once. The daily collector should normally use
Playwright against that persistent profile.

`following_account_audit.py` is a slower optimization pass. It caches followed
account candidates, prefilters them from the following page text, samples recent
original posts from candidate profiles, writes a checkpoint after every profile,
and stops early if X shows rate-limit UI.

Flow:

```text
Target date + config
        |
        v
Load editable configured profile allowlist
        |
        v
Collect configured profile posts and X home timeline posts
        |
        v
Optionally collect followed profile handles for broader discovery
        |
        v
Extract original tweet text from tweetText DOM nodes
        |
        v
Filter X results by DOM timestamp for the target local date
        |
        v
Filter out replies, quote/commentary posts, marketing, price chatter, and low technical-score items
        |
        v
Fetch ethresear.ch Discourse JSON endpoints
        |
        v
Normalize items into ResearchItem records
        |
        v
Classify by keyword categories
        |
        v
Generate short summaries for X posts
        |
        v
Write daily_research_digest.md and daily_research_digest.json
```

### Extension Points

- The primary X sources are the editable `x_profiles.handles` allowlist and the
  home timeline. Keyword search is disabled by default.
- Edit `tools/daily_research/selected_x_profiles.config.json` to add or remove
  monitored profiles without changing code.
- Add or edit X query groups in `daily_research_config.example.json`, then pass
  `--include-x-search` when search is explicitly useful.
- Keep optional X queries human-sized but technical, for example `defi
  protocol`, `ethereum core`, `EIP ethereum`, and `MEV PBS ethereum`; date
  filtering happens after collection by reading tweet timestamps from the DOM.
- Tune the quality threshold with `--x-min-technical-score`; replies/comments
  are excluded unless `--include-replies` is passed, and quote/commentary posts
  are excluded unless `--include-quotes` is passed.
- X home timeline collection is enabled by default and can be disabled with
  `--skip-x-home`.
- Followed profile collection is enabled by default and can be disabled with
  `--skip-x-following`; speed can be tuned with `--max-following-profiles` and
  `--max-following-items-per-profile`.
- Use `following_account_audit.py` to build a smaller high-quality account set
  before increasing daily collector coverage. Keep delays high when X has
  recently returned `429 Too Many Requests`.
- Add keyword categories under `keyword_categories`.
- Use `tools.daily_research.open_chrome_profile` to create a dedicated
  project-local profile for the user's X account.
- Use `--x-backend chrome-cdp` only for advanced debugging or attaching to a
  Chrome instance that was explicitly started with a DevTools endpoint.
- Add another source by implementing a collector that returns `ResearchItem`
  objects, then append it inside `run()`.
- Keep source-specific scraping isolated from report rendering so tests can
  cover normalization and Markdown output without opening a browser.

### Output Contract

```text
outputs/daily_research/<YYYY-MM-DD>/
|-- daily_research_digest.md
`-- daily_research_digest.json
```

- `daily_research_digest.md`: human-readable daily report.
- `daily_research_digest.json`: normalized raw data, source metadata, warnings,
  and category counts.
