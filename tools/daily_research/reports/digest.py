from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ..core.research import ResearchItem, dedupe_preserve_order, local_dates_in_window, truncate_text


def group_items(items: list[ResearchItem], attr: str) -> dict[str, list[ResearchItem]]:
    grouped: dict[str, list[ResearchItem]] = {}
    for item in items:
        key = str(getattr(item, attr) or "Other")
        grouped.setdefault(key, []).append(item)
    return grouped


def build_payload(
    target_day: date,
    timezone_name: str,
    items: list[ResearchItem],
    warnings: list[str],
    config: dict[str, Any],
    date_lookback_days: int = 0,
) -> dict[str, Any]:
    category_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for item in items:
        source_counts[item.source] = source_counts.get(item.source, 0) + 1
        labels = item.tags or ([item.category] if item.category else ["Other"])
        for label in labels:
            category_counts[label] = category_counts.get(label, 0) + 1

    return {
        "date": target_day.isoformat(),
        "timezone": timezone_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date_filter": {
            "lookback_days": max(0, date_lookback_days),
            "included_dates": [value.isoformat() for value in sorted(local_dates_in_window(target_day, date_lookback_days))],
        },
        "stats": {
            "total_items": len(items),
            "source_counts": source_counts,
            "category_counts": dict(sorted(category_counts.items(), key=lambda pair: pair[1], reverse=True)),
        },
        "warnings": warnings,
        "items": [item.to_dict() for item in items],
        "config": {
            "role": config.get("role", {}),
            "output_dir": config.get("output_dir"),
            "x_search": config.get("x_search", {}),
            "x_queries": config.get("x_queries", []),
            "x_home": config.get("x_home", {}),
            "x_profiles": config.get("x_profiles", {}),
            "x_following": config.get("x_following", {}),
            "ethresearch_endpoints": config.get("ethresearch_endpoints", []),
        },
    }


def render_markdown_report(payload: dict[str, Any]) -> str:
    items = [ResearchItem(**item) for item in payload["items"]]
    lines: list[str] = []
    lines.append(f"# Daily DeFi/Core Research Digest - {payload['date']}")
    lines.append("")
    lines.append("## Metadata")
    lines.append("")
    lines.append(f"- Date: {payload['date']}")
    lines.append(f"- Timezone: {payload['timezone']}")
    lines.append(f"- Generated at: {payload['generated_at']}")
    date_filter = payload.get("date_filter", {})
    if date_filter.get("included_dates"):
        lines.append(f"- Included local dates: {', '.join(date_filter['included_dates'])}")
    lines.append(f"- Total collected items: {payload['stats']['total_items']}")
    lines.append("")

    if payload.get("warnings"):
        lines.append("## Collection Warnings")
        lines.append("")
        for warning in payload["warnings"]:
            lines.append(f"- {warning}")
        lines.append("")

    lines.append("## Signal Map")
    lines.append("")
    category_counts = payload["stats"].get("category_counts", {})
    if category_counts:
        for category, count in category_counts.items():
            lines.append(f"- {category}: {count}")
    else:
        lines.append("- No classified signals found.")
    lines.append("")

    x_items = [item for item in items if item.source == "X"]
    lines.append("## X Signals")
    lines.append("")
    if x_items:
        for section, section_items in group_items(x_items, "section").items():
            lines.append(f"### {section}")
            lines.append("")
            append_item_list(lines, section_items)
    else:
        lines.append("- No X items collected.")
        lines.append("")

    eth_items = [item for item in items if item.source == "ethresear.ch"]
    lines.append("## ethresear.ch New Research Posts")
    lines.append("")
    if eth_items:
        append_item_list(lines, eth_items)
    else:
        lines.append("- No new ethresear.ch posts collected for this date.")
        lines.append("")

    lines.append("## Raw Data")
    lines.append("")
    lines.append("- JSON output is written next to this Markdown report.")
    lines.append("")
    return "\n".join(lines)


def append_item_list(lines: list[str], items: list[ResearchItem]) -> None:
    for index, item in enumerate(items, start=1):
        title = item.title or "Untitled"
        lines.append(f"#### {index}. {title}")
        lines.append("")
        if item.author:
            lines.append(f"- Author: {item.author}")
        if item.published_at:
            lines.append(f"- Time: {item.published_at}")
        if item.url:
            lines.append(f"- URL: {item.url}")
        if item.tags:
            lines.append(f"- Tags: {', '.join(item.tags)}")
        technical_score = item.raw.get("technical_score") if item.raw else None
        personalized_score = item.raw.get("personalized_score") if item.raw else None
        personalization_adjustment = item.raw.get("personalization_adjustment") if item.raw else None
        personalization_reasons = item.raw.get("personalization_reasons") if item.raw else None
        technical_reasons = item.raw.get("technical_reasons") if item.raw else None
        if technical_score is not None:
            lines.append(f"- Technical score: {technical_score}")
        if personalized_score is not None and personalization_adjustment:
            lines.append(
                f"- Personalized score: {personalized_score} "
                f"({int(personalization_adjustment):+d} feedback adjustment)"
            )
        if technical_reasons:
            lines.append(f"- Matched technical signals: {', '.join(technical_reasons[:8])}")
        if personalization_reasons:
            lines.append(f"- Personalization signals: {', '.join(personalization_reasons[:6])}")
        if item.text:
            summary = item.raw.get("summary") if item.raw else ""
            if summary:
                lines.append(f"- Summary: {summary}")
            original_post = item.text if item.source == "X" else truncate_text(item.text, 600)
            label = "Original post" if item.source == "X" else "Snippet"
            lines.append(f"- {label}: {original_post}")
        lines.append("")


def write_outputs(payload: dict[str, Any], output_dir: Path) -> dict[str, str]:
    target_dir = output_dir / payload["date"]
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / "daily_research_digest.json"
    md_path = target_dir / "daily_research_digest.md"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown_report(payload), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path), "output_dir": str(target_dir)}
