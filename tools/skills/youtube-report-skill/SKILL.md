---
name: youtube-report-skill
description: >
  Use this skill when the user asks to analyze ETHCC, Devcon, ETHDenver, or similar
  conference agenda topics by collecting agenda metadata, extracting YouTube UI
  transcripts with the local youtube transcript tool, summarizing talks with the
  defi-transcript-analyzer skill, and optionally writing a structured report to
  a specified Notion page. Trigger on requests such as "Analyze all topics from
  ETHCC Day 1", "summarize these conference agenda topics", "use youtube transcript
  tool and Notion to create a report", or any workflow involving agenda URLs,
  YouTube talk transcripts, and five-section technical summaries.
---

# ETHCC YouTube Report Workflow

## Purpose

Turn a conference agenda URL or explicit list of topics into a reusable research report.
The workflow collects topic metadata, extracts YouTube transcripts, summarizes each talk,
and writes a Notion-ready report when a target Notion page is provided.

## Expected input

The user should provide at least one of:

- An agenda URL, e.g. `https://ethcc.io/ethcc-9/agenda?date=2026-03-30`
- A list of agenda/archive/YouTube URLs
- A manually curated list of topic titles and video links

Optional inputs:

- Target Notion page URL
- Reference Notion page URL for formatting only
- Output directory
- YouTube Chrome profile directory
- Topic filters or exclusions
- Language preference

If the user does not specify a language, write the report in English.

## Core rules

- Do not modify any Notion page except the explicit target page.
- Treat a reference Notion page as read-only formatting guidance.
- Do not skip topical talks unless the user explicitly asks for filtering.
- Ignore breaks, empty slots, registration blocks, and schedule placeholders.
- If a transcript fails, record the failure and continue.
- Keep all raw artifacts so the run is reproducible.
- Use concise, technical summaries. Avoid generic transcript summaries.

## Artifact layout

Use a deterministic output folder:

```text
outputs/conference_reports/<event_slug>/
  metadata/topics.json
  transcripts/<topic_slug>/
  summaries/<topic_slug>.md
  report.md
  failures.json
```

Example `event_slug`: `ethcc9_day1_2026-03-30`.

## Step 1: Collect topic metadata

Open the agenda URL and extract every real topic. For each topic, collect:

- Topic title
- Speaker
- Organization, if available
- Date/time
- Track
- Agenda URL
- Archive URL
- YouTube URL, if available

Use the agenda page first. If data is missing, open the topic agenda page or archive page.
Keep topics with missing fields and mark unknown values as `Unknown`.

Save the complete metadata list to `metadata/topics.json`.

## Step 2: Extract YouTube transcripts

Use the local YouTube transcript tool from the current project:

```powershell
python -m tools.youtube.youtube_transcript_tool "<youtube_url>" --profile-dir "profiles\chrome profile" --output-dir "outputs\conference_reports\<event_slug>\transcripts"
```

Default profile selection:

- Use `profiles\chrome profile` for YouTube transcript extraction. This is the project-local
  Chrome profile expected to be signed in to YouTube.
- Do not use `profiles\ctb0k33` for YouTube unless the user explicitly asks for it; that
  profile is intended for X/daily research workflows.
- If the user provides a different YouTube profile, use that exact path.
- If YouTube shows "Sign in to confirm that you're not a bot" or a visible "Sign in" button,
  stop and report that the active profile is not signed in or is not the expected YouTube
  profile. Do not continue a batch with an unsigned-in profile.

Do not use the YouTube transcript API; this workflow is based on the UI transcript method.

For each topic:

- Run the transcript tool when a YouTube URL exists.
- Store transcript output under the topic slug.
- Record missing YouTube URLs and failed transcript extraction in `failures.json`.
- Continue the batch even when individual videos fail.

## Step 3: Analyze each transcript

Use the `defi-transcript-analyzer` skill for transcript interpretation. Follow its cleaning,
technical-detail, and quality-check guidance, but emit exactly the five sections below for
each topic:

```markdown
### Metadata

- Speaker: ...
- Organization: ...
- Date/Time: ...
- Track: ...
- Agenda: ...
- Archive: ...
- YouTube: ...

### 1. Overall Summary

...

### 2. Problem Being Solved

- ...
- ...

### 3. Architecture & Technical Mechanism

- ...
- ...

### 4. Comparison with Similar Approaches

- Pros:
  - ...
- Cons / Tradeoffs:
  - ...
```

If there is no meaningful comparison in the talk, write:

```text
The talk does not provide a direct comparison, but the closest design contrast is ...
```

Keep the output research-oriented:

- Preserve important numbers, parameters, EIPs, protocols, and mechanisms.
- Call out assumptions and unclear transcript segments.
- Correct obvious auto-caption errors in crypto terminology.
- Prefer bullets for problem/mechanism/comparison sections.

Save one Markdown summary per topic in `summaries/`.

## Step 4: Build the combined report

Create `report.md` with:

- Report title
- Scope and source agenda URL
- Collection status
- Day-level overview
- Topic index
- One section per topic
- Failure/skipped-topic appendix

For Notion import/update, structure each topic as a toggle-like unit:

```markdown
<details>
<summary><strong>001 - Topic Title</strong> (Date/Time | Track)</summary>

<details>
<summary><strong>Metadata</strong></summary>

- Speaker: ...
- Organization: ...
- Date/Time: ...
- Track: ...
- Agenda: ...
- Archive: ...
- YouTube: ...

</details>

<details>
<summary><strong>1. Overall Summary</strong></summary>

...

</details>

<details>
<summary><strong>2. Problem Being Solved</strong></summary>

- ...

</details>

<details>
<summary><strong>3. Architecture & Technical Mechanism</strong></summary>

- ...

</details>

<details>
<summary><strong>4. Comparison with Similar Approaches</strong></summary>

- Pros: ...
- Cons / Tradeoffs: ...

</details>

</details>
```

Use normal prose and bullets inside toggles. Do not put topic bodies in code blocks.

## Step 5: Write to Notion when requested

When the user provides a target Notion page:

1. Fetch the reference page only if provided, and use it only for formatting.
2. Fetch the target page before editing.
3. Update only the target page.
4. Prefer replacing or inserting a clearly labeled report section.
5. Preserve existing child pages/databases. If the Notion tool warns that content deletion
   would remove child content, stop and ask the user before continuing.

The final Notion page should include:

- Day overview
- Topic index
- One toggle per topic
- Nested toggles for Metadata and the four summary sections
- Failure appendix, if any

## Final response checklist

Report these counts:

- Number of topics found
- Number of topics with YouTube URLs
- Number of transcripts successfully extracted
- Number of summaries written
- Failed or skipped topics with reasons
- Output folder
- Notion page updated, if applicable

Also mention any command or Notion update that could not be completed.
