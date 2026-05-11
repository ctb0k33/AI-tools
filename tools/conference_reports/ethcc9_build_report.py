from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


REPORT_TITLE = "EthCC[9] Topic Summary"


STOPWORDS = {
    "about",
    "after",
    "again",
    "against",
    "also",
    "actually",
    "and",
    "are",
    "around",
    "because",
    "been",
    "being",
    "between",
    "both",
    "but",
    "can",
    "from",
    "going",
    "has",
    "have",
    "how",
    "into",
    "its",
    "just",
    "kind",
    "know",
    "like",
    "more",
    "new",
    "not",
    "now",
    "off",
    "onchain",
    "our",
    "really",
    "right",
    "say",
    "see",
    "some",
    "something",
    "that",
    "the",
    "their",
    "them",
    "there",
    "these",
    "they",
    "thing",
    "things",
    "think",
    "those",
    "this",
    "through",
    "want",
    "what",
    "when",
    "where",
    "with",
    "will",
    "would",
    "yeah",
    "you",
    "your",
}


def clean_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    return value or "No agenda description was published for this session."


def short_text(value: str, limit: int = 260) -> str:
    value = clean_text(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def transcript_path(topic: dict[str, Any], transcripts_root: Path) -> Path | None:
    topic_dir = transcripts_root / topic["slug"]
    matches = sorted(topic_dir.glob("*/transcript.txt"))
    return matches[0] if matches else None


def transcript_keywords(path: Path | None, limit: int = 8) -> list[str]:
    if not path or not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore").lower()
    words = re.findall(r"[a-z][a-z0-9-]{3,}", text)
    counts = Counter(word for word in words if word not in STOPWORDS and not word.isdigit())
    return [word for word, _ in counts.most_common(limit)]


def evidence_note(path: Path | None, keywords: list[str], has_youtube: bool) -> str:
    if path:
        keyword_text = ", ".join(keywords[:6]) if keywords else "no stable keywords extracted"
        return f"Transcript extracted; recurring transcript terms include: {keyword_text}."
    if has_youtube:
        return "A YouTube archive exists, but transcript extraction did not produce usable segments."
    return "No EthCC archive video was available when the report was generated; summary is based on agenda metadata."


def classify(topic: dict[str, Any]) -> str:
    text = f"{topic.get('title', '')} {topic.get('track', '')} {topic.get('description', '')}".lower()
    if any(token in text for token in ["stablecoin", "euro", "payment", "corridor", "currency"]):
        return "stablecoins/payments"
    if any(token in text for token in ["rwa", "tokenized", "tokenisation", "real asset", "real estate"]):
        return "rwa/tokenization"
    if any(token in text for token in ["regulation", "mica", "compliance", "law", "legal", "court", "lobbying"]):
        return "regulation/compliance"
    if any(token in text for token in ["privacy", "cypherpunk", "private"]):
        return "privacy"
    if any(token in text for token in ["aave", "lending", "yield", "liquidity", "dex", "perp", "defi", "auction", "trading"]):
        return "defi/market-structure"
    return "ethereum/ecosystem"


def problem_bullets(topic: dict[str, Any], category: str) -> list[str]:
    base = {
        "stablecoins/payments": [
            "Stablecoin usage is moving from crypto-native settlement toward regulated payments, treasury, and cross-border flows.",
            "The session examines the product, liquidity, legal, or currency-design gap implied by the agenda title.",
        ],
        "rwa/tokenization": [
            "Tokenized assets need credible issuance, legal enforceability, liquidity, and DeFi composability before they can scale past pilots.",
            "The session targets the mismatch between offchain asset constraints and the expectations of onchain markets.",
        ],
        "regulation/compliance": [
            "Builders and institutions need rules that can be operationalized without removing Ethereum's open, programmable properties.",
            "The session focuses on translating regulation, standards, or policy debates into practical market infrastructure.",
        ],
        "privacy": [
            "Privacy remains difficult to reconcile with usability, auditability, institutional access, and public-chain settlement.",
            "The session frames privacy as infrastructure rather than an optional product feature.",
        ],
        "defi/market-structure": [
            "DeFi systems are maturing from isolated protocols into institutional-grade markets with explicit risk, liquidity, and incentive design.",
            "The session addresses a production bottleneck in lending, trading, yield, collateral, or market infrastructure.",
        ],
        "ethereum/ecosystem": [
            "The session addresses a coordination, infrastructure, or adoption issue in the broader Ethereum ecosystem.",
            "It maps a practical gap between Ethereum's current capabilities and the next user or capital segment it wants to serve.",
        ],
    }
    bullets = [base[category][0]]
    return bullets


def mechanism_bullets(topic: dict[str, Any], category: str, keywords: list[str]) -> list[str]:
    keyword_note = f"Transcript signal: {', '.join(keywords[:6])}." if keywords else ""
    base = {
        "stablecoins/payments": [
            "Likely mechanism layer: issuance or custody model, payment routing, liquidity provisioning, compliance controls, and wallet/product distribution.",
            "Key design question: whether the stablecoin behaves mainly as settlement media, store-of-value, FX rail, or programmable treasury asset.",
        ],
        "rwa/tokenization": [
            "Likely mechanism layer: asset origination, token representation, legal claim mapping, settlement rail, oracle/data bridge, and secondary liquidity.",
            "For DeFi integration, the important interface is collateral eligibility, pricing/risk data, redemption, and transfer restrictions.",
        ],
        "regulation/compliance": [
            "Likely mechanism layer: legal classification, compliance workflow, attestation or registry design, and standards that wallets/protocols can consume.",
            "The implementation challenge is converting policy into deterministic checks without hard-coding brittle jurisdictional assumptions.",
        ],
        "privacy": [
            "Likely mechanism layer: selective disclosure, cryptographic proof, trusted execution, access policy, or offchain coordination around public-chain state.",
            "The hard boundary is preserving confidentiality while keeping enough verifiability for counterparties, regulators, or protocol risk systems.",
        ],
        "defi/market-structure": [
            "Likely mechanism layer: protocol parameters, collateral/risk models, incentives, liquidity routing, auction or matching logic, and monitoring.",
            "The production question is how the design behaves under stress: liquidity shocks, oracle movement, MEV, governance latency, and institutional constraints.",
        ],
        "ethereum/ecosystem": [
            "Likely mechanism layer: coordination process, product surface, developer workflow, or infrastructure primitive that compounds across the ecosystem.",
            "The technical lens is how the session connects Ethereum's neutrality and composability to concrete adoption paths.",
        ],
    }
    bullets = [base[category][0]]
    if keyword_note:
        bullets.append(keyword_note)
    return bullets


def comparison_lines(category: str) -> tuple[list[str], list[str]]:
    pros = {
        "stablecoins/payments": [
            "Onchain settlement can be more programmable and composable than card, bank, or closed-wallet rails.",
            "Stablecoin products can expose transparent liquidity and treasury mechanics when designed well.",
        ],
        "rwa/tokenization": [
            "Compared with paper-based or siloed digital assets, tokenized RWAs can plug into settlement, lending, and portfolio infrastructure.",
            "Composability can turn static assets into reusable financial primitives.",
        ],
        "regulation/compliance": [
            "Clear standards can reduce institutional uncertainty and make integrations repeatable.",
            "Policy-aware infrastructure can be reused across products instead of rebuilt per counterparty.",
        ],
        "privacy": [
            "Privacy-preserving designs can unlock use cases that transparent-by-default systems cannot serve.",
            "Selective disclosure can preserve audit paths without exposing all user or trade data publicly.",
        ],
        "defi/market-structure": [
            "Protocol-native mechanisms can react faster and expose more data than manual OTC or centralized workflows.",
            "Composable DeFi primitives can be reused across venues, collateral types, and capital sources.",
        ],
        "ethereum/ecosystem": [
            "Ethereum-native approaches benefit from neutrality, existing liquidity, and developer distribution.",
            "Open infrastructure can compound through permissionless integrations.",
        ],
    }[category]
    cons = {
        "stablecoins/payments": [
            "Regulatory, issuer, liquidity, and wallet distribution constraints can dominate the pure technology advantage.",
            "Non-USD or cross-border products face FX depth, compliance, and user-trust hurdles.",
        ],
        "rwa/tokenization": [
            "Legal enforceability, redemption, asset servicing, and data quality remain harder than token issuance.",
            "Permissioning can reduce composability if not designed as a first-class interface.",
        ],
        "regulation/compliance": [
            "Compliance-heavy designs can fragment liquidity or compromise permissionless access.",
            "Rules change faster than smart contracts, creating upgrade and governance risk.",
        ],
        "privacy": [
            "Privacy systems trade off transparency, compliance comfort, developer ergonomics, and sometimes performance.",
            "Incorrect threat models can create a false sense of confidentiality.",
        ],
        "defi/market-structure": [
            "Automated mechanisms can amplify stress if risk parameters, incentives, or oracle assumptions are wrong.",
            "Institutional adoption adds custody, reporting, governance, and compliance requirements that pure DeFi products often under-specify.",
        ],
        "ethereum/ecosystem": [
            "Open ecosystems require coordination across many actors and can move slower than vertically integrated platforms.",
            "Broad narratives need concrete implementation paths to avoid becoming conference-level abstraction.",
        ],
    }[category]
    return pros[:1], cons[:1]


def day_label(date: str) -> str:
    try:
        from datetime import date as date_type

        event_day = date_type.fromisoformat(date)
        start_day = date_type.fromisoformat("2026-03-30")
        offset = (event_day - start_day).days + 1
        return f"Day {offset}" if offset > 0 else date
    except ValueError:
        return date


def day_overview(payload: dict[str, Any], track_counts: Counter[str]) -> str:
    date = payload.get("date", "Unknown date")
    label = day_label(date)
    top_tracks = [track for track, _ in track_counts.most_common(4)]
    if top_tracks:
        track_phrase = ", ".join(top_tracks)
    else:
        track_phrase = "multiple Ethereum ecosystem tracks"
    return (
        f"{label} ({date}) spans {len(payload['topics'])} real agenda sessions. "
        f"The main recurring tracks are {track_phrase}. Read the summaries as a research map: "
        "transcript-backed items include extracted keyword signals, while sessions without usable "
        "transcripts are summarized from the agenda and archive metadata."
    )


def short_failure_reason(item: dict[str, Any]) -> str:
    reason = item.get("reason") or item.get("stderr") or item.get("stdout") or ""
    if "segment_count" in reason and "0" in reason:
        return "YouTube transcript panel opened no usable transcript segments."
    if "timeout" in reason.lower():
        return "Timed out while trying to extract the YouTube transcript."
    cleaned = re.sub(r"\s+", " ", reason).strip()
    return cleaned[:240] if cleaned else "No transcript segments extracted."


def metadata_block(topic: dict[str, Any], path: Path | None, keywords: list[str]) -> str:
    transcript_line = "Extracted" if path else "Unavailable"
    return "\n".join(
        [
            "### Metadata",
            "",
            f"- Speaker: {topic['speaker']}",
            f"- Organization: {topic['organization']}",
            f"- Date/Time: {topic['dateTime']}",
            f"- Track: {topic['track']}",
            f"- Room: {topic['room']}",
            f"- Agenda: {topic['agendaUrl']}",
            f"- Archive: {topic.get('archiveUrl') or 'Unknown'}",
            f"- YouTube: {topic.get('youtubeUrl') or 'YouTube unavailable'}",
            f"- Transcript: {transcript_line}",
        ]
    )


def summary_markdown(topic: dict[str, Any], path: Path | None, index: int) -> str:
    category = classify(topic)
    keywords = transcript_keywords(path)
    description = short_text(topic.get("description", ""))
    evidence = evidence_note(path, keywords, bool(topic.get("youtubeUrl")))
    problems = problem_bullets(topic, category)
    mechanisms = mechanism_bullets(topic, category, keywords)
    pros, cons = comparison_lines(category)

    return "\n".join(
        [
            metadata_block(topic, path, keywords),
            "",
            "### 1. Overall Summary",
            "",
            (
                f"{topic['title'].strip()} is a {topic['type'].lower()} in the "
                f"{topic['track']} track. {description} {evidence}"
            ),
            "",
            "### 2. Problem Being Solved",
            "",
            *(f"- {item}" for item in problems),
            "",
            "### 3. Architecture & Technical Mechanism",
            "",
            *(f"- {item}" for item in mechanisms),
            "",
            "### 4. Comparison with Similar Approaches",
            "",
            f"- Pros: {pros[0]}",
            f"- Cons / Tradeoffs: {cons[0]}",
            "",
        ]
    )


def details_topic(topic: dict[str, Any], summary: str, index: int) -> str:
    sections = re.split(r"\n(?=### )", summary)
    by_title: dict[str, str] = {}
    for section in sections:
        first = section.splitlines()[0].replace("### ", "").strip()
        by_title[first] = section

    def wrap(title: str, body: str) -> str:
        body_lines = body.splitlines()
        content = "\n".join(body_lines[2:] if len(body_lines) > 2 else body_lines[1:]).strip()
        return f"<details>\n<summary>{html.escape(title, quote=False)}</summary>\n\n{content}\n</details>"

    topic_summary = html.escape(
        f"{index:03d} - {topic['title'].strip()} ({topic['dateTime']} | {topic['track']} | {topic['room']})",
        quote=False,
    )
    return "\n\n".join(
        [
            "<details>",
            f"<summary>{topic_summary}</summary>",
            "",
            wrap("Metadata", by_title.get("Metadata", "")),
            "",
            wrap("1. Overall Summary", by_title.get("1. Overall Summary", "")),
            "",
            wrap("2. Problem Being Solved", by_title.get("2. Problem Being Solved", "")),
            "",
            wrap("3. Architecture & Technical Mechanism", by_title.get("3. Architecture & Technical Mechanism", "")),
            "",
            wrap("4. Comparison with Similar Approaches", by_title.get("4. Comparison with Similar Approaches", "")),
            "",
            "</details>",
        ]
    )


def build_report(base_dir: Path) -> dict[str, Any]:
    metadata_dir = base_dir / "metadata"
    summaries_dir = base_dir / "summaries"
    transcripts_root = base_dir / "transcripts"
    summaries_dir.mkdir(parents=True, exist_ok=True)

    payload = json.loads((metadata_dir / "topics.json").read_text(encoding="utf-8"))
    topics = payload["topics"]
    transcript_results_path = metadata_dir / "transcript_results.json"
    transcript_results = (
        json.loads(transcript_results_path.read_text(encoding="utf-8"))
        if transcript_results_path.exists()
        else []
    )
    transcript_success = {
        item["slug"]
        for item in transcript_results
        if item.get("status") in {"success", "skipped_existing"}
    }
    extraction_failures = [
        item for item in transcript_results if item.get("status") == "failed"
    ]
    missing_youtube = [topic for topic in topics if not topic.get("youtubeUrl")]

    topic_blocks: list[str] = []
    for index, topic in enumerate(topics, 1):
        path = transcript_path(topic, transcripts_root)
        summary = summary_markdown(topic, path, index)
        (summaries_dir / f"{topic['slug']}.md").write_text(summary, encoding="utf-8")
        topic_blocks.append(details_topic(topic, summary, index))

    track_counts = Counter(topic["track"] for topic in topics)
    overview = "\n".join(
        [
            f"# EthCC[9] {day_label(payload.get('date', ''))} Topic Summary",
            "",
            f"Source agenda: {payload['sourceAgendaUrl']}",
            "",
            "## Collection Status",
            "",
            f"- Topics found: {len(topics)}",
            f"- Topics with YouTube URLs: {payload['youtubeCount']}",
            f"- Transcripts successfully extracted: {len(transcript_success)}",
            f"- Summaries written: {len(topics)}",
            f"- Topics without archive video: {len(missing_youtube)}",
            f"- Transcript extraction failures: {len(extraction_failures)}",
            "",
            "## Day-Level Overview",
            "",
            day_overview(payload, track_counts),
            "",
            "Track distribution:",
            *(f"- {track}: {count}" for track, count in sorted(track_counts.items())),
            "",
            "## Topic Index",
            "",
            *(
                f"- **{index:03d} - {topic['title'].strip()}** ({topic['dateTime']} | {topic['track']})"
                for index, topic in enumerate(topics, 1)
            ),
            "",
            "## Topic Summaries",
            "",
        ]
    )

    appendix = "\n".join(
        [
            "## Failure / Skipped-Topic Appendix",
            "",
            "### No archive video available",
            "",
            *(
                f"- {topic['title'].strip()} ({topic['dateTime']} | {topic['track']} | {topic['room']})"
                for topic in missing_youtube
            ),
            "",
            "### Transcript extraction failures",
            "",
            *(
                f"- {item['title']} ({item['youtubeUrl']}): {short_failure_reason(item)}"
                for item in extraction_failures
            ),
            "",
        ]
    )

    report = overview + "\n\n".join(topic_blocks) + "\n\n" + appendix
    report_path = base_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")
    return {
        "topics": len(topics),
        "youtube": payload["youtubeCount"],
        "transcripts": len(transcript_success),
        "summaries": len(topics),
        "missing_youtube": len(missing_youtube),
        "transcript_failures": len(extraction_failures),
        "report": str(report_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build ETHCC[9] Day 1 report markdown.")
    parser.add_argument(
        "--base-dir",
        default="outputs/conference_reports/ethcc9_day1_2026-03-30",
    )
    args = parser.parse_args()
    result = build_report(Path(args.base_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
