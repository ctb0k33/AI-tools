from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_AGENDA_URL = "https://ethcc.io/ethcc-9/agenda?date={date}"


def fetch_text(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def extract_flight_text(page_html: str) -> str:
    parts: list[str] = []
    for match in re.finditer(r"self\.__next_f\.push\((.*?)\)</script>", page_html):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        parts.extend(item for item in payload if isinstance(item, str))
    return "".join(parts)


def extract_dehydrated_state(page_html: str) -> dict[str, Any]:
    flight_text = extract_flight_text(page_html)
    start = flight_text.find('{"state":{"mutations"')
    if start < 0:
        raise ValueError("Could not find dehydrated query state in agenda page.")
    state, _ = json.JSONDecoder().raw_decode(flight_text[start:])
    return state


def get_query_data(state: dict[str, Any], key: list[str]) -> Any:
    for query in state["state"]["queries"]:
        query_key = query.get("queryKey")
        if query_key and query_key[0] == key:
            return query["state"]["data"]
    raise KeyError(f"Could not find query data for {key!r}.")


def speaker_text(speakers: list[dict[str, Any]]) -> str:
    values = []
    for speaker in speakers:
        name = (speaker.get("displayName") or "").strip()
        org = (speaker.get("organization") or "").strip()
        if name and org:
            values.append(f"{name} ({org})")
        elif name:
            values.append(name)
    return ", ".join(values) if values else "Unknown"


def organization_text(speakers: list[dict[str, Any]]) -> str:
    orgs: list[str] = []
    seen: set[str] = set()
    for speaker in speakers:
        org = (speaker.get("organization") or "").strip()
        if org and org not in seen:
            seen.add(org)
            orgs.append(org)
    return ", ".join(orgs) if orgs else "Unknown"


def iso_to_time_range(start: str, end: str) -> str:
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    return f"{start_dt:%A, %B %-d, %Y} {start_dt:%H:%M}-{end_dt:%H:%M}"


def safe_time_range(start: str, end: str) -> str:
    try:
        return iso_to_time_range(start, end)
    except ValueError:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        return f"{start_dt:%A, %B %#d, %Y} {start_dt:%H:%M}-{end_dt:%H:%M}"


def parse_archive_page(archive_html: str) -> tuple[str | None, str | None]:
    title_match = re.search(
        r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
        archive_html,
    )
    video_match = re.search(
        r'<meta\s+property=["\']og:video["\']\s+content=["\']([^"\']+)["\']',
        archive_html,
    )
    title = html.unescape(title_match.group(1)) if title_match else None
    video = html.unescape(video_match.group(1)) if video_match else None
    return title, video


def collect_topics(
    output_dir: Path,
    date: str,
    sleep_seconds: float,
    agenda_url: str | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir = output_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    source_agenda_url = agenda_url or DEFAULT_AGENDA_URL.format(date=date)
    agenda_html = fetch_text(source_agenda_url)
    (metadata_dir / "agenda.html").write_text(agenda_html, encoding="utf-8")

    state = extract_dehydrated_state(agenda_html)
    talks = get_query_data(state, ["talksRouter", "getTalks"])
    locations = {
        location["id"]: location for location in get_query_data(state, ["talksRouter", "getLocations"])
    }

    topics: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for talk in talks:
        if not str(talk.get("start", "")).startswith(date):
            continue
        props = talk.get("extendedProps") or {}
        if not props.get("hasApplicationId") or not talk.get("slug"):
            continue

        slug = talk["slug"]
        speakers = props.get("speakersData") or []
        room = props.get("roomName") or locations.get(talk.get("resourceId"), {}).get("title") or "Unknown"
        agenda_url = f"https://ethcc.io/ethcc-9/agenda/{slug}"
        archive_url = f"https://ethcc.io/archives/{slug}"
        youtube_url = None
        archive_status = "unknown"

        try:
            archive_html = fetch_text(archive_url)
            archive_title, youtube_url = parse_archive_page(archive_html)
            if youtube_url:
                archive_status = "found"
            elif archive_title and not archive_title.lower().startswith("undefined"):
                archive_status = "found_without_video"
            else:
                archive_status = "not_found"
            (metadata_dir / f"archive_{slug}.html").write_text(archive_html, encoding="utf-8")
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            archive_status = "fetch_failed"
            failures.append(
                {
                    "topic": talk.get("title", "Unknown"),
                    "slug": slug,
                    "stage": "archive_fetch",
                    "reason": str(exc),
                }
            )

        topics.append(
            {
                "id": talk.get("id"),
                "slug": slug,
                "title": talk.get("title") or "Unknown",
                "speaker": speaker_text(speakers),
                "organization": organization_text(speakers),
                "speakersData": speakers,
                "dateTime": safe_time_range(talk.get("start", ""), talk.get("end", "")),
                "start": talk.get("start"),
                "end": talk.get("end"),
                "track": props.get("track") or "Unknown",
                "trackSlug": props.get("trackSlug") or "",
                "type": props.get("type") or "Unknown",
                "room": room.strip() if isinstance(room, str) else room,
                "description": props.get("description") or "",
                "agendaUrl": agenda_url,
                "archiveUrl": archive_url,
                "archiveStatus": archive_status,
                "youtubeUrl": youtube_url,
            }
        )
        if sleep_seconds:
            time.sleep(sleep_seconds)

    topics.sort(key=lambda item: (item["start"] or "", item["room"] or "", item["title"]))

    result = {
        "event": "EthCC[9]",
        "date": date,
        "sourceAgendaUrl": source_agenda_url,
        "topicCount": len(topics),
        "youtubeCount": sum(1 for topic in topics if topic.get("youtubeUrl")),
        "topics": topics,
        "failures": failures,
    }
    (metadata_dir / "topics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect EthCC[9] Day 1 agenda metadata.")
    parser.add_argument("--date", default="2026-03-30")
    parser.add_argument("--agenda-url")
    parser.add_argument(
        "--output-dir",
        default="outputs/conference_reports/ethcc9_day1_2026-03-30",
    )
    parser.add_argument("--sleep-seconds", type=float, default=0.05)
    args = parser.parse_args()

    result = collect_topics(Path(args.output_dir), args.date, args.sleep_seconds, args.agenda_url)
    print(
        json.dumps(
            {
                "topic_count": result["topicCount"],
                "youtube_count": result["youtubeCount"],
                "output": str(Path(args.output_dir) / "metadata" / "topics.json"),
                "archive_fetch_failures": len(result["failures"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
