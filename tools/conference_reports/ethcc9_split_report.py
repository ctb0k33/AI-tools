from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "ETHCC_REPORT_APPEND_MARKER"


def split_report(report_path: Path, output_dir: Path, topics_per_chunk: int) -> list[Path]:
    text = report_path.read_text(encoding="utf-8")
    appendix_heading = "\n## Failure / Skipped-Topic Appendix"
    topic_heading = "## Topic Summaries"
    if topic_heading not in text or appendix_heading not in text:
        raise ValueError("Report does not have expected topic and appendix headings.")

    before_topics, rest = text.split(topic_heading, 1)
    topic_text, appendix = rest.split(appendix_heading, 1)
    topic_text = topic_text.strip()
    appendix = (appendix_heading.strip() + appendix).strip()

    raw_blocks = topic_text.split("\n\n<details>\n\n<summary>")
    blocks: list[str] = []
    for index, block in enumerate(raw_blocks):
        block = block.strip()
        if not block:
            continue
        if index == 0 and block.startswith("<details>"):
            blocks.append(block)
        else:
            blocks.append("<details>\n\n<summary>" + block)

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    header = (before_topics + topic_heading).strip() + "\n\n" + MARKER + "\n"
    header_path = output_dir / "chunk_00_header.md"
    header_path.write_text(header, encoding="utf-8")
    paths.append(header_path)

    for start in range(0, len(blocks), topics_per_chunk):
        chunk_blocks = blocks[start : start + topics_per_chunk]
        chunk_index = (start // topics_per_chunk) + 1
        path = output_dir / f"chunk_{chunk_index:02d}_topics_{start + 1:03d}_{start + len(chunk_blocks):03d}.md"
        path.write_text("\n\n".join(chunk_blocks).strip() + "\n", encoding="utf-8")
        paths.append(path)

    appendix_path = output_dir / "chunk_99_appendix.md"
    appendix_path.write_text(appendix + "\n", encoding="utf-8")
    paths.append(appendix_path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Split the ETHCC report into Notion-sized chunks.")
    parser.add_argument(
        "--report",
        default="outputs/conference_reports/ethcc9_day1_2026-03-30/report.md",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/conference_reports/ethcc9_day1_2026-03-30/notion_chunks",
    )
    parser.add_argument("--topics-per-chunk", type=int, default=15)
    args = parser.parse_args()

    paths = split_report(Path(args.report), Path(args.output_dir), args.topics_per_chunk)
    for path in paths:
        print(f"{path}\t{path.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
