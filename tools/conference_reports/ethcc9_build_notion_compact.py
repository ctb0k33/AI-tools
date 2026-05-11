from __future__ import annotations

import argparse
import json
from pathlib import Path

from ethcc9_build_report import classify, short_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a compact Notion appendix for EthCC[9] Day 1.")
    parser.add_argument(
        "--base-dir",
        default="outputs/conference_reports/ethcc9_day1_2026-03-30",
    )
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    topics_payload = json.loads((base_dir / "metadata" / "topics.json").read_text(encoding="utf-8"))
    results = json.loads((base_dir / "metadata" / "transcript_results.json").read_text(encoding="utf-8"))
    failed_slugs = {item["slug"] for item in results if item.get("status") == "failed"}
    extracted_slugs = {
        item["slug"] for item in results if item.get("status") in {"success", "skipped_existing"}
    }

    lines: list[str] = ["## Compact Topic Summaries", ""]
    for index, topic in enumerate(topics_payload["topics"], 1):
        if not topic.get("youtubeUrl"):
            status = "No archive video"
        elif topic["slug"] in failed_slugs:
            status = "Archive video found; transcript unavailable"
        elif topic["slug"] in extracted_slugs:
            status = "Transcript extracted"
        else:
            status = "Transcript not attempted"
        description = short_text(topic.get("description", ""), 220)
        lens = classify(topic).replace("/", " / ")
        youtube = topic.get("youtubeUrl")
        links = f"[Agenda]({topic['agendaUrl']})"
        if youtube:
            links += f" | [YouTube]({youtube})"
        lines.append(
            f"- **{index:03d} - {topic['title'].strip()}** ({topic['dateTime']} | {topic['track']}) "
            f"Speaker: {topic['speaker']}. Summary: {description} Technical lens: {lens}. Status: {status}. "
            f"Links: {links}"
        )

    missing = [topic for topic in topics_payload["topics"] if not topic.get("youtubeUrl")]
    failed = [item for item in results if item.get("status") == "failed"]
    lines.extend(["", "## Failure / Skipped-Topic Appendix", "", "### No archive video available", ""])
    lines.extend(
        f"- {topic['title'].strip()} ({topic['dateTime']} | {topic['track']} | {topic['room']})"
        for topic in missing
    )
    lines.extend(["", "### Transcript extraction failures", ""])
    lines.extend(
        f"- {item['title']} ({item['youtubeUrl']}): YouTube transcript panel opened no usable transcript segments."
        for item in failed
    )

    output_path = base_dir / "notion_compact_append.md"
    output_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    print(output_path)
    print(output_path.stat().st_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
