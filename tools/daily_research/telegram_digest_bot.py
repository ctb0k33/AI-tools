from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "tools" / "daily_research" / "telegram_bot.config.example.json"


def project_path(value: str | None, fallback: str) -> Path:
    raw = value or fallback
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_config(path: str | None) -> dict[str, Any]:
    config_path = project_path(path, str(DEFAULT_CONFIG_PATH))
    return json.loads(config_path.read_text(encoding="utf-8"))


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sent_urls": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"sent_urls": []}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["sent_urls"] = list(dict.fromkeys(state.get("sent_urls", [])))[-1000:]
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def run_daily_research(config: dict[str, Any]) -> dict[str, Any]:
    target_date = str(config.get("date") or today_iso())
    command = [
        sys.executable,
        "-m",
        "tools.daily_research.daily_research_tool",
        "--date",
        target_date,
        "--timezone",
        str(config.get("timezone") or "Asia/Saigon"),
        "--profile-dir",
        str(project_path(config.get("profile_dir"), "profiles/ctb0k33")),
        "--config",
        str(project_path(config.get("daily_research_config"), "tools/daily_research/selected_x_profiles.config.json")),
        "--output-dir",
        str(project_path(config.get("output_dir"), "outputs/daily_research")),
        "--x-backend",
        "playwright",
    ]
    if config.get("headless"):
        command.append("--headless")
    if config.get("skip_ethresearch"):
        command.append("--skip-ethresearch")

    process = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=int(config.get("process_timeout_seconds") or 1200),
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or process.stdout.strip() or "daily_research_tool failed")

    output_dir = project_path(config.get("output_dir"), "outputs/daily_research")
    digest_path = output_dir / target_date / "daily_research_digest.json"
    if not digest_path.exists():
        raise FileNotFoundError(f"Digest not found: {digest_path}")
    return json.loads(digest_path.read_text(encoding="utf-8"))


def item_score(item: dict[str, Any]) -> int:
    raw = item.get("raw") or {}
    return int(raw.get("technical_score") or item.get("score") or 0)


def select_new_items(digest: dict[str, Any], state: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    sent = set(state.get("sent_urls", []))
    min_score = int(config.get("min_technical_score") or 6)
    max_items = int(config.get("max_items_per_run") or 8)
    candidates = []
    for item in digest.get("items", []):
        url = str(item.get("url") or "")
        if not url or url in sent:
            continue
        if item_score(item) < min_score:
            continue
        candidates.append(item)
    candidates.sort(key=lambda item: (item_score(item), str(item.get("published_at") or "")), reverse=True)
    return candidates[:max_items]


def format_item_message(item: dict[str, Any]) -> str:
    raw = item.get("raw") or {}
    title = str(item.get("title") or "Untitled")
    author = str(item.get("author") or "")
    section = str(item.get("section") or "")
    score = item_score(item)
    summary = str(raw.get("summary") or item.get("text") or "").strip()
    tags = ", ".join(str(tag) for tag in item.get("tags", [])[:5])
    url = str(item.get("url") or "")

    lines = [f"<b>{escape_html(title)}</b>"]
    meta = " | ".join(part for part in [author, section, f"score {score}", tags] if part)
    if meta:
        lines.append(escape_html(meta))
    if summary:
        lines.append("")
        lines.append(escape_html(summary[:900]))
    if url:
        lines.append("")
        lines.append(url)
    return "\n".join(lines)


def format_empty_message(digest: dict[str, Any]) -> str:
    return (
        f"No new high-signal DeFi/Core items for {digest.get('date')}.\n"
        f"Collected items: {digest.get('stats', {}).get('total_items', 0)}"
    )


def format_start_marker(digest: dict[str, Any], item_count: int) -> str:
    generated_at = str(digest.get("generated_at") or "")
    date_label = str(digest.get("date") or today_iso())
    lines = [
        "<b>--- New digest batch started ---</b>",
        f"Date: {escape_html(date_label)}",
        f"New posts: {item_count}",
    ]
    if generated_at:
        lines.append(f"Generated: {escape_html(generated_at)}")
    return "\n".join(lines)


def format_end_marker(digest: dict[str, Any], item_count: int) -> str:
    date_label = str(digest.get("date") or today_iso())
    return "\n".join(
        [
            "<b>--- New digest batch ended ---</b>",
            f"Date: {escape_html(date_label)}",
            f"Sent posts: {item_count}",
        ]
    )


def escape_html(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_telegram_message(token: str, chat_id: str, text: str) -> None:
    payload = urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        }
    ).encode("utf-8")
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("ok"):
        raise RuntimeError(f"Telegram sendMessage failed: {body}")


def run_once(config: dict[str, Any], dry_run: bool = False) -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not dry_run and (not token or not chat_id):
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID before running the bot.")

    state_path = project_path(config.get("state_path"), "outputs/daily_research/telegram_state.json")
    state = load_state(state_path)
    digest = run_daily_research(config)
    new_items = select_new_items(digest, state, config)
    send_markers = bool(config.get("send_run_markers", True))

    if not new_items and config.get("send_empty_digest"):
        message = format_empty_message(digest)
        if dry_run:
            print(message)
        else:
            send_telegram_message(token, chat_id, message)
        return 0

    if new_items and send_markers:
        marker = format_start_marker(digest, len(new_items))
        if dry_run:
            print(marker)
            print("\n" + "=" * 80 + "\n")
        else:
            send_telegram_message(token, chat_id, marker)
            time.sleep(1)

    for item in new_items:
        message = format_item_message(item)
        if dry_run:
            print(message)
            print("\n" + "-" * 80 + "\n")
        else:
            send_telegram_message(token, chat_id, message)
            time.sleep(1)
        state.setdefault("sent_urls", []).append(item.get("url"))

    if new_items and send_markers:
        marker = format_end_marker(digest, len(new_items))
        if dry_run:
            print(marker)
            print("\n" + "=" * 80 + "\n")
        else:
            send_telegram_message(token, chat_id, marker)

    save_state(state_path, state)
    print(f"Sent {len(new_items)} new item(s).")
    return len(new_items)


def run_loop(config: dict[str, Any], dry_run: bool = False) -> None:
    interval_seconds = max(60, int(config.get("interval_minutes") or 30) * 60)
    while True:
        try:
            run_once(config, dry_run=dry_run)
        except (HTTPError, URLError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            print(f"[telegram-bot] {exc}", file=sys.stderr)
        time.sleep(interval_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scheduled Telegram sender for daily DeFi/Core research digests.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Telegram bot config JSON.")
    parser.add_argument("--once", action="store_true", help="Run one collection/send cycle and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print messages instead of sending to Telegram.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_config(args.config)
    if args.once:
        run_once(config, dry_run=args.dry_run)
    else:
        run_loop(config, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
