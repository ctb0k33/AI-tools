from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Split compact Notion appendix into small chunks.")
    parser.add_argument(
        "--input",
        default="outputs/conference_reports/ethcc9_day1_2026-03-30/notion_compact_append.md",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/conference_reports/ethcc9_day1_2026-03-30/notion_compact_chunks",
    )
    parser.add_argument("--topics-per-chunk", type=int, default=30)
    args = parser.parse_args()

    text = Path(args.input).read_text(encoding="utf-8")
    lines = text.splitlines()
    header = lines[:2]
    topic_lines = [line for line in lines if line.startswith("- **")]
    appendix_start = next(i for i, line in enumerate(lines) if line == "## Failure / Skipped-Topic Appendix")
    appendix = lines[appendix_start:]

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for start in range(0, len(topic_lines), args.topics_per_chunk):
        chunk_index = start // args.topics_per_chunk + 1
        body = []
        if start == 0:
            body.extend(header)
            body.append("")
        body.extend(topic_lines[start : start + args.topics_per_chunk])
        path = out_dir / f"compact_{chunk_index:02d}_{start + 1:03d}_{min(start + args.topics_per_chunk, len(topic_lines)):03d}.md"
        path.write_text("\n".join(body).strip() + "\n", encoding="utf-8")
        paths.append(path)

    appendix_path = out_dir / "compact_99_appendix.md"
    appendix_path.write_text("\n".join(appendix).strip() + "\n", encoding="utf-8")
    paths.append(appendix_path)

    for path in paths:
        print(f"{path}\t{path.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
