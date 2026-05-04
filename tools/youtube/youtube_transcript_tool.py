from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


TRANSCRIPT_SEGMENT_SELECTORS = [
    "ytd-transcript-segment-renderer",
    "yt-transcript-segment-renderer",
    "ytd-transcript-body-renderer ytd-transcript-segment-renderer",
]


def extract_video_id(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise ValueError("Video URL/ID khong duoc de trong.")

    direct_match = re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate)
    if direct_match:
        return candidate

    parsed = urlparse(candidate)
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    if host in {"youtu.be", "www.youtu.be"} and path_parts:
        return path_parts[0]

    if "youtube.com" in host or "youtube-nocookie.com" in host:
        query_video_id = parse_qs(parsed.query).get("v", [])
        if query_video_id:
            return query_video_id[0]

        for marker in ("shorts", "embed", "live", "v"):
            if marker in path_parts:
                index = path_parts.index(marker)
                if index + 1 < len(path_parts):
                    return path_parts[index + 1]

    raise ValueError(f"Khong tach duoc video id tu input: {value}")


def normalize_video_url(value: str) -> str:
    video_id = extract_video_id(value)
    return f"https://www.youtube.com/watch?v={video_id}"


def build_transcript_text(segments: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for segment in segments:
        timestamp = segment.get("timestamp", "").strip()
        text = segment.get("text", "").strip()
        if not text:
            continue
        lines.append(f"[{timestamp}] {text}" if timestamp else text)
    return "\n".join(lines)


def click_first(page, selectors: list[str], timeout: int = 2500) -> str | None:
    for selector in selectors:
        try:
            matches = page.locator(selector)
            count = matches.count()
            for index in range(min(count, 8)):
                locator = matches.nth(index)
                try:
                    if locator.is_visible(timeout=500):
                        locator.click(timeout=timeout)
                        return selector if index == 0 else f"{selector} [nth={index}]"
                except PlaywrightTimeoutError:
                    continue
                except Exception:
                    continue
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue
    return None


def accept_youtube_consent(page) -> None:
    click_first(
        page,
        [
            "button:has-text('Accept all')",
            "button:has-text('I agree')",
            "button:has-text('Accept')",
            "tp-yt-paper-button:has-text('Accept all')",
            "ytd-button-renderer:has-text('Accept all') button",
        ],
        timeout=2000,
    )


def open_transcript_panel(page) -> str | None:
    accept_youtube_consent(page)

    direct = click_first(
        page,
        [
            "button[aria-label*='Show transcript' i]",
            "button:has-text('Show transcript')",
            "ytd-button-renderer:has-text('Show transcript') button",
            "yt-button-view-model:has-text('Show transcript') button",
            "button:has-text('Transcript')",
        ],
    )
    if direct:
        return f"direct:{direct}"

    click_first(
        page,
        [
            "#expand",
            "#description tp-yt-paper-button:has-text('more')",
            "tp-yt-paper-button:has-text('more')",
            "button:has-text('...more')",
            "button:has-text('more')",
            "yt-formatted-string:has-text('...more')",
        ],
        timeout=1500,
    )
    page.wait_for_timeout(1000)

    expanded = click_first(
        page,
        [
            "button[aria-label*='Show transcript' i]",
            "button:has-text('Show transcript')",
            "ytd-button-renderer:has-text('Show transcript') button",
            "yt-button-view-model:has-text('Show transcript') button",
            "button:has-text('Transcript')",
        ],
    )
    if expanded:
        return f"expanded:{expanded}"

    click_first(
        page,
        [
            "button[aria-label='More actions']",
            "button[aria-label*='More actions' i]",
            "ytd-menu-renderer yt-icon-button button",
            "#button[aria-label*='More' i]",
        ],
        timeout=2000,
    )
    page.wait_for_timeout(1000)

    menu = click_first(
        page,
        [
            "ytd-menu-service-item-renderer:has-text('Show transcript')",
            "tp-yt-paper-item:has-text('Show transcript')",
            "yt-list-item-view-model:has-text('Show transcript')",
            "text='Show transcript'",
        ],
        timeout=2500,
    )
    if menu:
        return f"menu:{menu}"

    return None


def scrape_segments(page) -> list[dict[str, str]]:
    for selector in TRANSCRIPT_SEGMENT_SELECTORS:
        segments = page.locator(selector)
        try:
            count = segments.count()
        except Exception:
            count = 0
        if count == 0:
            continue

        rows: list[dict[str, str]] = []
        for index in range(count):
            segment = segments.nth(index)
            try:
                text = segment.inner_text(timeout=1000).strip()
            except Exception:
                continue
            if not text:
                continue

            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if not lines:
                continue

            timestamp = lines[0] if re.match(r"^\d{0,2}:?\d{1,2}:\d{2}$|^\d{1,2}:\d{2}$", lines[0]) else ""
            body = " ".join(lines[1:] if timestamp else lines)
            if body:
                rows.append({"timestamp": timestamp, "text": body})

        if rows:
            return rows

    return []


def wait_for_transcript_segments(page, timeout_ms: int = 15000, interval_ms: int = 500) -> list[dict[str, str]]:
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        rows = scrape_segments(page)
        if rows:
            return rows
        page.wait_for_timeout(interval_ms)
    return []


def extract_title(page) -> str:
    try:
        return page.locator("h1 yt-formatted-string, h1").first.inner_text(timeout=3000).strip()
    except Exception:
        return ""


def build_output_dir(root: Path, video_id: str) -> Path:
    output_dir = root / video_id
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def write_outputs(output_dir: Path, payload: dict) -> None:
    (output_dir / "metadata.json").write_text(
        json.dumps(
            {
                "video_id": payload["video_id"],
                "url": payload["url"],
                "title": payload["title"],
                "open_method": payload["open_method"],
                "segment_count": payload["segment_count"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (output_dir / "transcript.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "transcript.txt").write_text(
        build_transcript_text(payload["segments"]),
        encoding="utf-8",
    )


def run(args: argparse.Namespace) -> dict:
    profile_dir = Path(args.profile_dir).expanduser().resolve()
    if not profile_dir.exists():
        raise FileNotFoundError(f"Khong tim thay profile dir: {profile_dir}")

    video_id = extract_video_id(args.video)
    video_url = normalize_video_url(args.video)
    output_root = Path(args.output_dir).expanduser().resolve()
    output_dir = build_output_dir(output_root, video_id)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=args.headless,
            slow_mo=args.slow_mo,
            viewport={"width": 1365, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--disable-first-run-ui",
            ],
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(video_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
            page.wait_for_timeout(4000)

            open_method = open_transcript_panel(page)
            segments = wait_for_transcript_segments(page, timeout_ms=args.segment_timeout_ms)
            title = extract_title(page)

            payload = {
                "video_id": video_id,
                "url": video_url,
                "title": title,
                "open_method": open_method,
                "segment_count": len(segments),
                "segments": segments,
            }
            write_outputs(output_dir, payload)
            return {
                "video_id": video_id,
                "title": title,
                "open_method": open_method,
                "segment_count": len(segments),
                "output_dir": str(output_dir),
                "transcript_path": str(output_dir / "transcript.txt"),
                "metadata_path": str(output_dir / "metadata.json"),
            }
        finally:
            time.sleep(1)
            context.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lay transcript YouTube bang Playwright tu giao dien YouTube, khong dung transcript API."
    )
    parser.add_argument("video", help="YouTube URL hoac video ID.")
    parser.add_argument(
        "--profile-dir",
        required=True,
        help="Chrome user-data-dir se duoc dung de mo session that va lay transcript.",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/youtube_transcripts",
        help="Thu muc luu output transcript. Mac dinh: outputs/youtube_transcripts",
    )
    parser.add_argument("--timeout-ms", type=int, default=45000, help="Timeout cho page load.")
    parser.add_argument(
        "--segment-timeout-ms",
        type=int,
        default=15000,
        help="Timeout cho transcript segments xuat hien.",
    )
    parser.add_argument("--headless", action="store_true", help="Chay headless neu can.")
    parser.add_argument("--slow-mo", type=int, default=100, help="Do tre Playwright giua cac action.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        result = run(args)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["segment_count"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
