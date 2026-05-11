from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def transcript_exists(topic_dir: Path) -> bool:
    return any(topic_dir.glob("*/transcript.txt"))


def run_one(
    topic: dict[str, Any],
    profile_dir: Path,
    transcripts_root: Path,
    timeout_ms: int,
    segment_timeout_ms: int,
    headless: bool,
) -> dict[str, Any]:
    slug = topic["slug"]
    topic_dir = transcripts_root / slug
    topic_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "tools.youtube.youtube_transcript_tool",
        topic["youtubeUrl"],
        "--profile-dir",
        str(profile_dir),
        "--output-dir",
        str(topic_dir),
        "--timeout-ms",
        str(timeout_ms),
        "--segment-timeout-ms",
        str(segment_timeout_ms),
    ]
    if headless:
        cmd.append("--headless")

    completed = subprocess.run(
        cmd,
        cwd=Path.cwd(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=(timeout_ms + segment_timeout_ms + 30000) / 1000,
    )
    payload: dict[str, Any] | None = None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = None

    segment_count = int(payload.get("segment_count", 0)) if payload else 0
    return {
        "slug": slug,
        "title": topic["title"],
        "youtubeUrl": topic["youtubeUrl"],
        "returncode": completed.returncode,
        "segment_count": segment_count,
        "output": payload,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
        "status": "success" if completed.returncode == 0 and segment_count > 0 else "failed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch extract ETHCC YouTube UI transcripts.")
    parser.add_argument(
        "--topics",
        default="outputs/conference_reports/ethcc9_day1_2026-03-30/metadata/topics.json",
    )
    parser.add_argument("--profile-dir", default="profiles/chrome profile")
    parser.add_argument(
        "--transcripts-root",
        default="outputs/conference_reports/ethcc9_day1_2026-03-30/transcripts",
    )
    parser.add_argument(
        "--failures",
        default="outputs/conference_reports/ethcc9_day1_2026-03-30/failures.json",
    )
    parser.add_argument(
        "--results",
        default="outputs/conference_reports/ethcc9_day1_2026-03-30/metadata/transcript_results.json",
    )
    parser.add_argument("--timeout-ms", type=int, default=90000)
    parser.add_argument("--segment-timeout-ms", type=int, default=25000)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    topics_path = Path(args.topics)
    topics_payload = json.loads(topics_path.read_text(encoding="utf-8"))
    profile_dir = Path(args.profile_dir)
    transcripts_root = Path(args.transcripts_root)
    failures_path = Path(args.failures)
    results_path = Path(args.results)
    transcripts_root.mkdir(parents=True, exist_ok=True)
    failures_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.parent.mkdir(parents=True, exist_ok=True)

    candidates = [topic for topic in topics_payload["topics"] if topic.get("youtubeUrl")]
    if args.limit:
        candidates = candidates[: args.limit]

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, topic in enumerate(candidates, 1):
        topic_dir = transcripts_root / topic["slug"]
        if not args.force and transcript_exists(topic_dir):
            existing = {
                "slug": topic["slug"],
                "title": topic["title"],
                "youtubeUrl": topic["youtubeUrl"],
                "status": "skipped_existing",
                "segment_count": None,
            }
            results.append(existing)
            print(f"[{index}/{len(candidates)}] skipped existing: {topic['slug']}", flush=True)
            continue

        print(f"[{index}/{len(candidates)}] extracting: {topic['slug']}", flush=True)
        try:
            result = run_one(
                topic,
                profile_dir,
                transcripts_root,
                args.timeout_ms,
                args.segment_timeout_ms,
                args.headless,
            )
        except subprocess.TimeoutExpired as exc:
            result = {
                "slug": topic["slug"],
                "title": topic["title"],
                "youtubeUrl": topic["youtubeUrl"],
                "status": "failed",
                "returncode": None,
                "segment_count": 0,
                "stdout": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
                "stderr": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
                "reason": "timeout",
            }
        results.append(result)
        if result["status"] == "failed":
            failures.append(
                {
                    "topic": topic["title"],
                    "slug": topic["slug"],
                    "stage": "transcript_extraction",
                    "reason": result.get("reason")
                    or result.get("stderr")
                    or result.get("stdout")
                    or "No transcript segments extracted.",
                    "youtubeUrl": topic["youtubeUrl"],
                }
            )
        print(
            f"[{index}/{len(candidates)}] {result['status']} segments={result.get('segment_count')}",
            flush=True,
        )

        results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        failures_path.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")

    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    failures_path.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "candidates": len(candidates),
                "success": sum(1 for item in results if item["status"] in {"success", "skipped_existing"}),
                "failed": len(failures),
                "results": str(results_path),
                "failures": str(failures_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
