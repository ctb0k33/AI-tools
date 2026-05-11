from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import socket
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


X_BASE_URL = "https://x.com/search"
ETHRESEARCH_BASE_URL = "https://ethresear.ch"

DEFAULT_CONFIG: dict[str, Any] = {
    "date_filter": {
        "lookback_days": 1,
    },
    "x_search": {
        "enabled": False,
    },
    "x_queries": [
        {
            "name": "DeFi Protocol",
            "category": "DeFi",
            "query": "defi protocol",
        },
        {
            "name": "DeFi Security",
            "category": "DeFi",
            "query": "defi security",
        },
        {
            "name": "Ethereum Core",
            "category": "Core Protocol",
            "query": "ethereum core",
        },
        {
            "name": "EIP",
            "category": "Core Protocol",
            "query": "EIP ethereum",
        },
        {
            "name": "MEV",
            "category": "Core Protocol",
            "query": "MEV PBS ethereum",
        },
    ],
    "ethresearch_endpoints": [
        "https://ethresear.ch/new.json",
        "https://ethresear.ch/latest.json",
    ],
    "keyword_categories": {
        "DeFi": [
            "defi",
            "decentralized finance",
            "aave",
            "uniswap",
            "curve",
            "maker",
            "sky",
            "ethena",
            "stablecoin",
            "rwa",
            "amm",
            "dex",
            "lending",
            "liquidity",
            "perp",
            "auction",
            "vault",
            "yield",
        ],
        "Core Protocol": [
            "ethereum core",
            "core dev",
            "eip",
            "peerdas",
            "peer das",
            "epbs",
            "focil",
            "gloas",
            "fusaka",
            "glamsterdam",
            "gas limit",
            "validator",
            "pbs",
            "mev",
            "stateless",
            "verkle",
            "consensus",
            "execution layer",
            "fork",
            "blob",
            "blobs",
        ],
        "L2 and Data Availability": [
            "rollup",
            "l2",
            "data availability",
            "danksharding",
            "blob",
            "blobs",
            "da layer",
            "based rollup",
            "validium",
        ],
        "ZK and Cryptography": [
            "zk",
            "zero knowledge",
            "snark",
            "stark",
            "proof",
            "prover",
            "kzg",
            "cryptography",
            "post-quantum",
            "signature",
        ],
        "Security": [
            "security",
            "audit",
            "exploit",
            "bug",
            "vulnerability",
            "formal verification",
            "fuzzing",
            "oracle",
            "bridge",
        ],
    },
    "x_quality_filter": {
        "min_technical_score": 4,
        "include_replies": False,
        "include_quotes": False,
    },
    "x_home": {
        "enabled": True,
        "max_items": 80,
    },
    "x_profiles": {
        "enabled": False,
        "handles": [],
        "max_items_per_profile": 4,
    },
    "x_following": {
        "enabled": False,
        "owner": "Ctb0k33",
        "max_profiles": 80,
        "max_items_per_profile": 4,
    },
}


@dataclasses.dataclass(slots=True)
class QuerySpec:
    name: str
    query: str
    category: str = ""


@dataclasses.dataclass(slots=True)
class ResearchItem:
    source: str
    section: str
    title: str
    url: str
    category: str = ""
    author: str = ""
    published_at: str = ""
    text: str = ""
    tags: list[str] = dataclasses.field(default_factory=list)
    score: int = 0
    raw: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_target_date(value: str | None, tz: tzinfo) -> date:
    if value:
        return datetime.strptime(value, "%Y-%m-%d").date()
    return datetime.now(tz).date()


def resolve_timezone(name: str) -> tzinfo:
    normalized = (name or "").strip()
    if normalized.lower() in {"asia/saigon", "asia/ho_chi_minh", "utc+7", "+07:00"}:
        return timezone(timedelta(hours=7), name="Asia/Saigon")
    if normalized.upper() == "UTC":
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(normalized)
    except Exception:
        return timezone.utc


def parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_same_local_day(timestamp: str, target_day: date, tz: tzinfo) -> bool:
    parsed = parse_iso_datetime(timestamp)
    if parsed is None:
        return False
    return parsed.astimezone(tz).date() == target_day


def local_dates_in_window(target_day: date, lookback_days: int) -> list[date]:
    safe_lookback = max(0, lookback_days)
    return [target_day - timedelta(days=offset) for offset in range(safe_lookback + 1)]


def is_in_local_date_window(timestamp: str, target_day: date, tz: tzinfo, lookback_days: int) -> bool:
    parsed = parse_iso_datetime(timestamp)
    if parsed is None:
        return False
    return parsed.astimezone(tz).date() in set(local_dates_in_window(target_day, lookback_days))


def format_date_window(target_day: date, lookback_days: int) -> str:
    dates = sorted(local_dates_in_window(target_day, lookback_days))
    if len(dates) == 1:
        return dates[0].isoformat()
    return f"{dates[0].isoformat()} to {dates[-1].isoformat()}"


def build_x_query(query: str, target_day: date) -> str:
    lowered = query.lower()
    if " since:" in lowered or " until:" in lowered:
        return query
    next_day = target_day + timedelta(days=1)
    return f"{query} since:{target_day.isoformat()} until:{next_day.isoformat()}"


def build_x_search_url(query: str, target_day: date, include_date_filters: bool = False) -> str:
    search_query = build_x_query(query, target_day) if include_date_filters else query
    encoded = quote(search_query, safe="")
    return f"{X_BASE_URL}?q={encoded}&src=typed_query&f=live"


def strip_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return normalize_whitespace(html.unescape(value))


def classify_text(text: str, keyword_categories: dict[str, list[str]]) -> list[str]:
    haystack = normalize_whitespace(text).lower()
    matches: list[str] = []
    for category, keywords in keyword_categories.items():
        if any(keyword.lower() in haystack for keyword in keywords):
            matches.append(category)
    return matches


TECHNICAL_POSITIVE_TERMS = {
    "architecture": 3,
    "mechanism": 3,
    "protocol": 2,
    "spec": 3,
    "specification": 3,
    "implementation": 3,
    "eip": 3,
    "erc": 2,
    "rfc": 2,
    "proposal": 2,
    "research": 2,
    "paper": 2,
    "benchmark": 2,
    "postmortem": 3,
    "audit": 3,
    "exploit": 3,
    "vulnerability": 3,
    "security": 2,
    "formal verification": 3,
    "fuzzing": 3,
    "oracle": 2,
    "liquidation": 2,
    "collateral": 2,
    "amm": 2,
    "liquidity": 1,
    "intent": 2,
    "solver": 2,
    "mev": 3,
    "pbs": 3,
    "builder": 1,
    "relay": 2,
    "validator": 2,
    "consensus": 3,
    "execution layer": 3,
    "client": 2,
    "rollup": 2,
    "blob": 2,
    "data availability": 3,
    "peerdas": 3,
    "focil": 3,
    "epbs": 3,
    "stateless": 3,
    "verkle": 3,
    "zk": 2,
    "proof": 2,
    "prover": 2,
    "deep dive": 2,
    "thread": 1,
    "design": 1,
}

LOW_VALUE_X_TERMS = [
    "drop your wallet",
    "airdrop",
    "giveaway",
    "whitelist",
    "wl",
    "minted on ethereum",
    "nft market",
    "portfolio",
    "price prediction",
    "bull loads",
    "loads up",
    "worth of eth",
    "support",
    "resistance",
    "rsi",
    "macd",
    "cashtag",
    "meme",
    "memecoin",
    "moon",
    "100x",
    "passive income",
    "made $",
    "roi",
    "no hype",
    "ai-powered defi experience",
    "what's prompt defi",
    "where's the pizza",
    "defi gods",
    "paid partnership",
    "next-gen crypto hub",
    "speeds up trades",
    "check it out",
    "mainnet is coming soon",
    "buzz about high defi yields",
    "meet arc terminal",
]

X_REPLY_MARKERS = [
    "replying to",
    "đang trả lời",
    "trả lời",
    "en réponse à",
    "返信先",
]


X_REPLY_MARKERS.extend(
    [
        "\u0111ang tr\u1ea3 l\u1eddi",
        "tr\u1ea3 l\u1eddi",
        "en r\u00e9ponse \u00e0",
        "\u8fd4\u4fe1\u5148",
    ]
)

X_QUOTE_MARKERS = [
    "quote",
    "quoted",
    "tr\u00edch d\u1eabn",
]


def is_x_reply(text: str) -> bool:
    lowered = normalize_whitespace(text).lower()
    return any(marker in lowered for marker in X_REPLY_MARKERS)


def is_x_quote(text: str) -> bool:
    lowered = normalize_whitespace(text).lower()
    return any(marker in lowered for marker in X_QUOTE_MARKERS)


def technical_score_text(text: str) -> tuple[int, list[str]]:
    lowered = normalize_whitespace(text).lower()
    score = 0
    reasons: list[str] = []

    for term, weight in TECHNICAL_POSITIVE_TERMS.items():
        if term in lowered:
            score += weight
            reasons.append(term)

    for term in LOW_VALUE_X_TERMS:
        if term in lowered:
            score -= 4
            reasons.append(f"low_value:{term}")

    if len(lowered) >= 220:
        score += 1
        reasons.append("long_form")
    if "http://" in lowered or "https://" in lowered or " x.com/" in lowered:
        score += 1
        reasons.append("has_link")
    if re.search(r"\b(eip|erc)-?\d{3,5}\b", lowered):
        score += 4
        reasons.append("numbered_standard")
    if re.search(r"\b\$\w+\b", text) and score < 5:
        score -= 2
        reasons.append("ticker_heavy")

    positive_reasons = [reason for reason in reasons if not reason.startswith("low_value:")]
    generic_terms = {"protocol", "security", "research", "builder", "liquidity", "thread", "design"}
    if score <= 4 and positive_reasons and set(positive_reasons).issubset(generic_terms):
        score -= 2
        reasons.append("generic_only")

    return score, dedupe_preserve_order(reasons)


def filter_x_items_by_quality(
    items: list[ResearchItem],
    min_technical_score: int,
    include_replies: bool,
    include_quotes: bool,
) -> tuple[list[ResearchItem], dict[str, int]]:
    kept: list[ResearchItem] = []
    stats = {
        "replies": 0,
        "quotes": 0,
        "low_score": 0,
    }

    for item in items:
        article_text = str(item.raw.get("article_text", "")) if item.raw else ""
        tweet_texts = item.raw.get("tweet_texts", []) if item.raw else []
        reply = bool(item.raw.get("is_reply")) or is_x_reply(article_text) or is_x_reply(item.text)
        quote = bool(item.raw.get("is_quote")) or is_x_quote(article_text) or len(tweet_texts) > 1
        score, reasons = technical_score_text(item.text)
        item.score = score
        item.raw["technical_score"] = score
        item.raw["technical_reasons"] = reasons
        item.raw["is_reply"] = reply
        item.raw["is_quote"] = quote
        item.raw["summary"] = item.raw.get("summary") or summarize_x_post(item.text)

        if reply and not include_replies:
            stats["replies"] += 1
            continue
        if quote and not include_quotes:
            stats["quotes"] += 1
            continue
        if score < min_technical_score:
            stats["low_score"] += 1
            continue
        kept.append(item)

    kept.sort(key=lambda item: (item.score, item.published_at), reverse=True)
    return kept, stats


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def canonical_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return value
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


def dedupe_items(items: list[ResearchItem]) -> list[ResearchItem]:
    seen: set[str] = set()
    deduped: list[ResearchItem] = []
    for item in items:
        key = canonical_url(item.url) or short_hash(item.text or item.title)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def filter_items_by_local_date(
    items: list[ResearchItem],
    target_day: date,
    tz: tzinfo,
    lookback_days: int = 0,
) -> tuple[list[ResearchItem], dict[str, int]]:
    kept: list[ResearchItem] = []
    stats = {"missing_timestamp": 0, "outside_date": 0, "lookback_days": max(0, lookback_days)}
    for item in items:
        if not item.published_at:
            stats["missing_timestamp"] += 1
            continue
        if is_in_local_date_window(item.published_at, target_day, tz, lookback_days):
            kept.append(item)
        else:
            stats["outside_date"] += 1
    return kept, stats


def get_system_chrome_user_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is not set; cannot locate the system Chrome profile.")
    return Path(local_app_data) / "Google" / "Chrome" / "User Data"


def get_last_used_chrome_profile(user_data_dir: Path) -> str:
    local_state = user_data_dir / "Local State"
    if not local_state.exists():
        return "Default"
    try:
        payload = json.loads(local_state.read_text(encoding="utf-8"))
    except Exception:
        return "Default"
    return str(payload.get("profile", {}).get("last_used") or "Default")


def inspect_x_login_cookies(profile_dir: Path) -> tuple[bool | None, str]:
    cookies_db = profile_dir / "Default" / "Network" / "Cookies"
    if not cookies_db.exists():
        return False, f"X profile cookies DB not found: {cookies_db}"
    try:
        connection = sqlite3.connect(f"file:{cookies_db}?mode=ro", uri=True)
        try:
            cursor = connection.cursor()
            cursor.execute(
                "select name from cookies where host_key like ? or host_key like ?",
                ("%x.com%", "%twitter.com%"),
            )
            cookie_names = {str(row[0]) for row in cursor.fetchall()}
        finally:
            connection.close()
    except Exception as exc:
        return None, f"Could not inspect X login cookies in {cookies_db}: {exc}"

    if "auth_token" in cookie_names and "ct0" in cookie_names:
        return True, "X login cookies found."
    visible = ", ".join(sorted(cookie_names)) or "none"
    return (
        False,
        "X profile is not signed in: missing auth_token/ct0 cookies. "
        f"Visible X/Twitter cookie names: {visible}",
    )


def extract_x_author(status_url: str, text: str) -> str:
    parsed = urlparse(status_url)
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[1] == "status":
        return f"@{path_parts[0]}"
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first_line[:80]


def extract_x_handle_from_href(href: str) -> str:
    parsed = urlparse(href)
    path = parsed.path if parsed.scheme else href
    parts = [part for part in path.split("/") if part]
    if len(parts) != 1:
        return ""
    handle = parts[0].strip()
    if handle.lower() in {"home", "explore", "notifications", "messages", "i", "settings"}:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle):
        return ""
    return handle


def normalize_x_handle(value: str) -> str:
    cleaned = (value or "").strip().lstrip("@")
    if not cleaned:
        return ""
    if "://" in cleaned or cleaned.startswith("/"):
        return extract_x_handle_from_href(cleaned)
    if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", cleaned):
        return ""
    return cleaned


def normalize_x_handles(values: list[str]) -> list[str]:
    handles: dict[str, str] = {}
    for value in values:
        handle = normalize_x_handle(str(value))
        if handle:
            handles[handle.lower()] = handle
    return list(handles.values())


def same_x_handle(left: str, right: str) -> bool:
    return left.strip().lstrip("@").lower() == right.strip().lstrip("@").lower()


def clean_tweet_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    noisy = {
        "reply",
        "repost",
        "like",
        "views",
        "show more",
        "promoted",
    }
    filtered = [line for line in lines if line.lower() not in noisy]
    return normalize_whitespace(" ".join(filtered))


def truncate_text(text: str, limit: int, suffix: str = "...") -> str:
    cleaned = normalize_whitespace(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - len(suffix))].rstrip() + suffix


def truncate_at_word(text: str, limit: int, suffix: str = "") -> str:
    cleaned = normalize_whitespace(text)
    if len(cleaned) <= limit:
        return cleaned
    candidate = cleaned[: max(0, limit - len(suffix))].rstrip()
    if " " in candidate:
        candidate = candidate.rsplit(" ", 1)[0].rstrip()
    return candidate + suffix


def split_summary_sentences(text: str) -> list[str]:
    cleaned = normalize_whitespace(text)
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+|\s+[|]\s+|\s+-\s+", cleaned)
    return [part.strip() for part in parts if len(part.strip()) >= 24]


def summarize_x_post(text: str, max_chars: int = 700) -> str:
    embedded_summary = re.search(r"\bsummary:\s*(.+)", normalize_whitespace(text), flags=re.IGNORECASE)
    if embedded_summary:
        summary_tail = embedded_summary.group(1).strip()
        if len(summary_tail) >= 32:
            sentences = split_summary_sentences(summary_tail)
            if sentences:
                return truncate_at_word(" ".join(sentences[:2]), max_chars)
            return truncate_at_word(summary_tail, max_chars)

    sentences = split_summary_sentences(text)
    if not sentences:
        return truncate_at_word(text, max_chars)

    selected: list[str] = []
    for sentence in sentences:
        candidate = normalize_whitespace(" ".join([*selected, sentence]))
        if len(candidate) > max_chars and selected:
            break
        selected.append(sentence)
        if len(selected) >= 2:
            break
    return truncate_at_word(" ".join(selected), max_chars)


def looks_like_truncated_x_text(text: str, article_text: str = "") -> bool:
    cleaned = normalize_whitespace(text)
    if not cleaned:
        return False
    article_lowered = normalize_whitespace(article_text).lower()
    if "show more" in article_lowered or "hi\u1ec3n th\u1ecb th\u00eam" in article_lowered:
        return True
    if "..." in cleaned or "\u2026" in cleaned:
        return True
    if len(cleaned) >= 240 and not re.search(r"[.!?)](?:\s|$)", cleaned[-4:]):
        return True
    if re.search(r"\b(to|with|from|for|by|as|and|or|the|a|an|of|in|on|at|is|are|was|were)$", cleaned, re.I):
        return True
    return False


def build_x_item_from_raw_tweet(
    raw: dict[str, Any],
    spec: QuerySpec,
    keyword_categories: dict[str, list[str]],
    backend: str,
) -> ResearchItem | None:
    article_text = str(raw.get("article_text") or raw.get("text") or "")
    raw_tweet_texts = raw.get("tweet_texts") or []
    tweet_texts = [clean_tweet_text(str(value)) for value in raw_tweet_texts if clean_tweet_text(str(value))]
    tweet_text = clean_tweet_text(str(raw.get("tweet_text") or (tweet_texts[0] if tweet_texts else "")))
    if not tweet_text:
        tweet_text = clean_tweet_text(article_text)
    if not tweet_text:
        return None

    links = [str(link) for link in raw.get("links", []) if link]
    status_url = canonical_url(next((link for link in links if "/status/" in link), ""))
    tags = classify_text(tweet_text, keyword_categories)
    if spec.category and spec.category not in tags:
        tags.insert(0, spec.category)
    summary = summarize_x_post(tweet_text)
    title = truncate_text(summary or tweet_text, 180)
    raw_details = {
        "query": spec.query,
        "links": links[:10],
        "backend": backend,
        "article_text": article_text,
        "tweet_texts": tweet_texts[:4],
        "summary": summary,
        "is_reply": bool(raw.get("is_reply")) or is_x_reply(article_text),
        "is_quote": bool(raw.get("is_quote")) or is_x_quote(article_text) or len(tweet_texts) > 1,
        "source_profile": str(raw.get("source_profile", "")),
        "looks_truncated": looks_like_truncated_x_text(tweet_text, article_text),
    }
    return ResearchItem(
        source="X",
        section=spec.name,
        category=spec.category,
        title=title or "Untitled X item",
        url=status_url,
        author=extract_x_author(status_url, article_text or tweet_text),
        published_at=str(raw.get("time", "")),
        text=tweet_text,
        tags=tags,
        score=len(tags),
        raw=raw_details,
    )


def load_config(path: str | None) -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    if not path:
        return config

    user_config = json.loads(Path(path).read_text(encoding="utf-8"))
    for key, value in user_config.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            merged = copy.deepcopy(config[key])
            merged.update(value)
            config[key] = merged
        else:
            config[key] = value
    return config


def parse_query_specs(
    config: dict[str, Any],
    extra_queries: list[str] | None = None,
    include_config_queries: bool = True,
) -> list[QuerySpec]:
    specs: list[QuerySpec] = []
    if include_config_queries:
        for item in config.get("x_queries", []):
            specs.append(
                QuerySpec(
                    name=str(item.get("name", "Custom")),
                    query=str(item.get("query", "")),
                    category=str(item.get("category", "")),
                )
            )

    for raw_query in extra_queries or []:
        if "::" in raw_query:
            name, query = raw_query.split("::", 1)
        else:
            name, query = "Custom", raw_query
        specs.append(QuerySpec(name=name.strip() or "Custom", query=query.strip(), category=name.strip()))

    return [spec for spec in specs if spec.query]


class XCollector:
    def __init__(
        self,
        profile_dir: Path,
        max_items_per_query: int,
        timeout_ms: int,
        headless: bool,
        slow_mo: int,
        keyword_categories: dict[str, list[str]],
        min_technical_score: int,
        date_lookback_days: int,
        include_replies: bool,
        include_quotes: bool,
        include_home: bool,
        max_home_items: int,
        profile_handles: list[str],
        max_items_per_profile: int,
        include_following: bool,
        following_owner: str,
        max_following_profiles: int,
        max_items_per_following_profile: int,
    ) -> None:
        self.profile_dir = profile_dir
        self.max_items_per_query = max_items_per_query
        self.timeout_ms = timeout_ms
        self.headless = headless
        self.slow_mo = slow_mo
        self.keyword_categories = keyword_categories
        self.min_technical_score = min_technical_score
        self.date_lookback_days = max(0, date_lookback_days)
        self.include_replies = include_replies
        self.include_quotes = include_quotes
        self.include_home = include_home
        self.max_home_items = max_home_items
        self.profile_handles = normalize_x_handles(profile_handles)
        self.max_items_per_profile = max_items_per_profile
        self.include_following = include_following
        self.following_owner = following_owner.strip().lstrip("@")
        self.max_following_profiles = max_following_profiles
        self.max_items_per_following_profile = max_items_per_following_profile
        self._seen_x_item_keys: set[str] = set()
        self._hydrated_payload_cache: dict[str, dict[str, Any]] = {}

    def collect(
        self,
        query_specs: list[QuerySpec],
        target_day: date,
        tz: tzinfo,
    ) -> tuple[list[ResearchItem], list[str]]:
        warnings: list[str] = []
        items: list[ResearchItem] = []
        self._seen_x_item_keys = set()
        self._hydrated_payload_cache = {}
        if not query_specs and not self.include_home and not self.profile_handles and not self.include_following:
            return items, warnings

        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            return [], [f"Playwright import failed: {exc}"]

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        is_signed_in, login_message = inspect_x_login_cookies(self.profile_dir)
        if is_signed_in is False:
            warnings.append(
                f"{login_message} Open the profile once with: "
                f"python -m tools.daily_research.open_chrome_profile --profile-dir \"{self.profile_dir}\" "
                "--start-url https://x.com/home"
            )
        elif is_signed_in is None:
            warnings.append(login_message)

        with sync_playwright() as playwright:
            context = None
            try:
                try:
                    context = playwright.chromium.launch_persistent_context(
                        user_data_dir=str(self.profile_dir),
                        channel="chrome",
                        headless=self.headless,
                        slow_mo=self.slow_mo,
                        viewport={"width": 1400, "height": 950},
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--disable-session-crashed-bubble",
                            "--no-first-run",
                        ],
                    )
                except Exception as exc:
                    warnings.append(
                        "Chrome channel failed with the persistent X profile; "
                        f"falling back to bundled Chromium. Original error: {exc}"
                    )
                    try:
                        context = playwright.chromium.launch_persistent_context(
                            user_data_dir=str(self.profile_dir),
                            headless=self.headless,
                            slow_mo=self.slow_mo,
                            viewport={"width": 1400, "height": 950},
                            args=[
                                "--disable-blink-features=AutomationControlled",
                                "--disable-session-crashed-bubble",
                                "--no-first-run",
                            ],
                        )
                    except Exception as fallback_exc:
                        warnings.append(
                            "Could not launch any browser with the persistent X profile. "
                            f"Close any Chrome/Chromium window using '{self.profile_dir}', then retry. "
                            f"Fallback error: {fallback_exc}"
                        )
                        return [], warnings

                page = context.new_page()
                self._close_restored_pages(context, keep_page=page)
                for spec in query_specs:
                    url = build_x_search_url(spec.query, target_day, include_date_filters=False)
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                        page.wait_for_timeout(3500)
                        if self._looks_blocked_or_logged_out(page):
                            warnings.append(
                                f"X query '{spec.name}' may need a signed-in profile or was rate-limited."
                            )
                        try:
                            page.wait_for_selector("article[data-testid='tweet']", timeout=8000)
                        except PlaywrightTimeoutError:
                            warnings.append(f"No visible tweets found for X query '{spec.name}'.")
                            continue
                        items.extend(self._extract_tweets(page, spec))
                    except Exception as exc:
                        warnings.append(f"X query '{spec.name}' failed: {exc}")
                for handle in self.profile_handles:
                    spec = QuerySpec(name="Configured Profiles", query=f"https://x.com/{handle}", category="")
                    try:
                        page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded", timeout=self.timeout_ms)
                        page.wait_for_timeout(2500)
                        if self._looks_blocked_or_logged_out(page):
                            warnings.append(f"X configured profile '@{handle}' may be rate-limited or unavailable.")
                        try:
                            page.wait_for_selector("article[data-testid='tweet']", timeout=6000)
                        except PlaywrightTimeoutError:
                            continue
                        items.extend(
                            self._extract_tweets(
                                page,
                                spec,
                                max_items=self.max_items_per_profile,
                                profile_handle=handle,
                                scroll_rounds=2,
                            )
                        )
                    except Exception as exc:
                        warnings.append(f"X configured profile '@{handle}' failed: {exc}")
                if self.include_home:
                    spec = QuerySpec(name="Home Timeline", query="https://x.com/home", category="")
                    try:
                        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=self.timeout_ms)
                        page.wait_for_timeout(3500)
                        if self._looks_blocked_or_logged_out(page):
                            warnings.append("X home timeline may need a signed-in profile or was rate-limited.")
                        try:
                            page.wait_for_selector("article[data-testid='tweet']", timeout=8000)
                        except PlaywrightTimeoutError:
                            warnings.append("No visible tweets found on X home timeline.")
                        else:
                            items.extend(self._extract_tweets(page, spec, max_items=self.max_home_items))
                    except Exception as exc:
                        warnings.append(f"X home timeline failed: {exc}")
                if self.include_following:
                    try:
                        handles = self._collect_following_handles(page, self.following_owner, warnings)
                        if not handles:
                            warnings.append(f"No followed profiles found for @{self.following_owner}.")
                        for handle in handles:
                            spec = QuerySpec(name="Following Profiles", query=f"https://x.com/{handle}", category="")
                            try:
                                page.goto(
                                    f"https://x.com/{handle}",
                                    wait_until="domcontentloaded",
                                    timeout=self.timeout_ms,
                                )
                                page.wait_for_timeout(2500)
                                try:
                                    page.wait_for_selector("article[data-testid='tweet']", timeout=6000)
                                except PlaywrightTimeoutError:
                                    continue
                                items.extend(
                                    self._extract_tweets(
                                        page,
                                        spec,
                                        max_items=self.max_items_per_following_profile,
                                        profile_handle=handle,
                                        scroll_rounds=2,
                                    )
                                )
                            except Exception as exc:
                                warnings.append(f"X followed profile '@{handle}' failed: {exc}")
                    except Exception as exc:
                        warnings.append(f"X following collection failed: {exc}")
            finally:
                if context is not None:
                    context.close()

        dated_items, filter_stats = filter_items_by_local_date(
            dedupe_items(items),
            target_day,
            tz,
            lookback_days=self.date_lookback_days,
        )
        if filter_stats["missing_timestamp"] or filter_stats["outside_date"]:
            warnings.append(
                "X date validation skipped "
                f"{filter_stats['outside_date']} items outside {format_date_window(target_day, self.date_lookback_days)} and "
                f"{filter_stats['missing_timestamp']} items without timestamps."
            )
        quality_items, quality_stats = filter_x_items_by_quality(
            dated_items,
            min_technical_score=self.min_technical_score,
            include_replies=self.include_replies,
            include_quotes=self.include_quotes,
        )
        if quality_stats["replies"] or quality_stats["quotes"] or quality_stats["low_score"]:
            warnings.append(
                "X quality filter skipped "
                f"{quality_stats['replies']} replies/comments and "
                f"{quality_stats['quotes']} quote/commentary posts and "
                f"{quality_stats['low_score']} low-technical-score items."
            )
        return quality_items, warnings

    def _close_restored_pages(self, context: Any, keep_page: Any) -> None:
        for existing_page in list(context.pages):
            if existing_page == keep_page:
                continue
            try:
                existing_page.close()
            except Exception:
                pass

    def _looks_blocked_or_logged_out(self, page: Any) -> bool:
        try:
            text = page.locator("body").inner_text(timeout=2500).lower()
        except Exception:
            return False
        markers = [
            "sign in to x",
            "log in to x",
            "something went wrong",
            "rate limit",
            "unusual login activity",
            "verify you are human",
        ]
        return any(marker in text for marker in markers)

    def _collect_following_handles(self, page: Any, owner: str, warnings: list[str]) -> list[str]:
        if not owner:
            warnings.append("X following owner is empty; skipping followed profile collection.")
            return []

        handles: dict[str, str] = {}
        page.goto(f"https://x.com/{owner}/following", wait_until="domcontentloaded", timeout=self.timeout_ms)
        page.wait_for_timeout(3500)
        if self._looks_blocked_or_logged_out(page):
            warnings.append("X following page may need a signed-in profile or was rate-limited.")
        try:
            page.wait_for_selector("[data-testid='UserCell']", timeout=10000)
        except Exception:
            return []

        max_scrolls = max(6, min(40, self.max_following_profiles // 3 + 6))
        for _ in range(max_scrolls):
            cells = page.locator("[data-testid='UserCell']")
            count = cells.count()
            for index in range(count):
                try:
                    raw_links = cells.nth(index).locator("a[href]").evaluate_all(
                        "(els) => els.map((a) => a.getAttribute('href') || '').filter(Boolean)"
                    )
                except Exception:
                    raw_links = []
                for href in raw_links:
                    handle = extract_x_handle_from_href(str(href))
                    if handle and not same_x_handle(handle, owner):
                        handles[handle.lower()] = handle
                        break
                if len(handles) >= self.max_following_profiles:
                    return list(handles.values())
            try:
                page.mouse.wheel(0, 1800)
                page.wait_for_timeout(1200)
            except Exception:
                break
        return list(handles.values())

    def _extract_tweets(
        self,
        page: Any,
        spec: QuerySpec,
        max_items: int | None = None,
        profile_handle: str = "",
        scroll_rounds: int = 6,
    ) -> list[ResearchItem]:
        items_by_key: dict[str, ResearchItem] = {}
        item_limit = max_items or self.max_items_per_query
        for _ in range(scroll_rounds):
            articles = page.locator("article[data-testid='tweet']")
            count = articles.count()
            for index in range(count):
                article = articles.nth(index)
                raw = self._extract_tweet_payload(article)
                if profile_handle:
                    raw["source_profile"] = profile_handle
                item = build_x_item_from_raw_tweet(raw, spec, self.keyword_categories, backend="playwright")
                if item is None:
                    continue
                if profile_handle and not same_x_handle(item.author, profile_handle):
                    continue
                key = canonical_url(item.url) or short_hash(item.text)
                if key in items_by_key or key in self._seen_x_item_keys:
                    continue
                item = self._hydrate_if_truncated(page, item, spec, profile_handle)
                key = canonical_url(item.url) or key
                if key in items_by_key:
                    continue
                if key in self._seen_x_item_keys:
                    continue
                items_by_key[key] = item
                self._seen_x_item_keys.add(key)
                if len(items_by_key) >= item_limit:
                    return list(items_by_key.values())
            try:
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(1200)
            except Exception:
                break
        return list(items_by_key.values())

    def _hydrate_if_truncated(
        self,
        page: Any,
        item: ResearchItem,
        spec: QuerySpec,
        profile_handle: str,
    ) -> ResearchItem:
        if not item.url or not item.raw.get("looks_truncated"):
            return item
        status_key = canonical_url(item.url)
        raw = self._hydrated_payload_cache.get(status_key)
        if raw is None:
            raw = self._extract_status_tweet_payload(page, item.url)
            if raw:
                self._hydrated_payload_cache[status_key] = raw
        if not raw:
            return item
        if profile_handle:
            raw["source_profile"] = profile_handle
        hydrated = build_x_item_from_raw_tweet(raw, spec, self.keyword_categories, backend="playwright-status")
        if hydrated is None:
            return item
        if profile_handle and not same_x_handle(hydrated.author, profile_handle):
            return item
        if len(hydrated.text) <= len(item.text):
            return item
        hydrated.raw["hydrated_from_status"] = True
        return hydrated

    def _extract_status_tweet_payload(self, page: Any, status_url: str) -> dict[str, Any]:
        detail_page = None
        try:
            detail_page = page.context.new_page()
            detail_page.goto(status_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            detail_page.wait_for_timeout(2500)
            detail_page.wait_for_selector("article[data-testid='tweet']", timeout=7000)
            articles = detail_page.locator("article[data-testid='tweet']")
            canonical_status = canonical_url(status_url)
            count = articles.count()
            fallback: dict[str, Any] = {}
            for index in range(count):
                raw = self._extract_tweet_payload(articles.nth(index))
                links = [canonical_url(str(link)) for link in raw.get("links", [])]
                if not fallback:
                    fallback = raw
                if canonical_status in links:
                    return raw
            return fallback
        except Exception:
            return {}
        finally:
            if detail_page is not None:
                try:
                    detail_page.close()
                except Exception:
                    pass

    def _extract_tweet_payload(self, article: Any) -> dict[str, Any]:
        try:
            return dict(
                article.evaluate(
                    """
                    (article) => {
                      const links = Array.from(article.querySelectorAll('a[href]'))
                        .map((a) => a.href)
                        .filter(Boolean);
                      const tweetTexts = Array.from(article.querySelectorAll('[data-testid="tweetText"]'))
                        .map((el) => el.innerText || '')
                        .filter(Boolean);
                      const time = article.querySelector('time')?.getAttribute('datetime') || '';
                      const socialContext = article.querySelector('[data-testid="socialContext"]')?.innerText || '';
                      return {
                        article_text: article.innerText || '',
                        tweet_text: tweetTexts[0] || '',
                        tweet_texts: tweetTexts,
                        links,
                        time,
                        social_context: socialContext
                      };
                    }
                    """
                )
            )
        except Exception:
            text = self._safe_inner_text(article)
            return {
                "article_text": text,
                "tweet_text": text,
                "tweet_texts": [text] if text else [],
                "links": self._extract_links(article),
                "time": self._safe_attr(article.locator("time").first, "datetime"),
            }

    def _extract_links(self, article: Any) -> list[str]:
        try:
            return article.locator("a").evaluate_all("(els) => els.map((a) => a.href).filter(Boolean)")
        except Exception:
            return []

    def _extract_author(self, status_url: str, text: str) -> str:
        return extract_x_author(status_url, text)

    def _safe_inner_text(self, locator: Any) -> str:
        try:
            return locator.inner_text(timeout=1500).strip()
        except Exception:
            return ""

    def _safe_attr(self, locator: Any, attr: str) -> str:
        try:
            return locator.get_attribute(attr, timeout=1000) or ""
        except Exception:
            return ""

    def _clean_tweet_text(self, text: str) -> str:
        return clean_tweet_text(text)


class CDPSession:
    def __init__(self, websocket_url: str, timeout_seconds: int) -> None:
        try:
            from websocket import create_connection
        except Exception as exc:
            raise RuntimeError(
                "Missing dependency 'websocket-client'. Run: pip install -r requirements.txt"
            ) from exc

        self.websocket = create_connection(websocket_url, timeout=timeout_seconds)
        self.timeout_seconds = timeout_seconds
        self.message_id = 0

    def close(self) -> None:
        self.websocket.close()

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.message_id += 1
        message_id = self.message_id
        self.websocket.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))

        deadline = time.time() + self.timeout_seconds
        while time.time() < deadline:
            message = json.loads(self.websocket.recv())
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise RuntimeError(f"CDP error for {method}: {message['error']}")
            return message.get("result", {})
        raise TimeoutError(f"CDP command timed out: {method}")

    def evaluate(self, expression: str) -> Any:
        result = self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        if "exceptionDetails" in result:
            raise RuntimeError(f"CDP Runtime.evaluate exception: {result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    def wait_for_expression(self, expression: str, timeout_seconds: int, interval_seconds: float = 0.5) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                if self.evaluate(expression):
                    return True
            except Exception:
                pass
            time.sleep(interval_seconds)
        return False


class ChromeCDPXCollector:
    def __init__(
        self,
        profile_dir: Path,
        max_items_per_query: int,
        timeout_ms: int,
        headless: bool,
        keyword_categories: dict[str, list[str]],
        chrome_path: str | None,
        debug_port: int,
        chrome_profile_directory: str | None,
        attach_cdp_url: str | None,
        min_technical_score: int,
        date_lookback_days: int,
        include_replies: bool,
        include_quotes: bool,
        include_home: bool,
        max_home_items: int,
        profile_handles: list[str],
        max_items_per_profile: int,
        include_following: bool,
        following_owner: str,
        max_following_profiles: int,
        max_items_per_following_profile: int,
    ) -> None:
        self.profile_dir = profile_dir
        self.max_items_per_query = max_items_per_query
        self.timeout_seconds = max(5, timeout_ms // 1000)
        self.headless = headless
        self.keyword_categories = keyword_categories
        self.chrome_path = chrome_path
        self.debug_port = debug_port
        self.chrome_profile_directory = chrome_profile_directory
        self.attach_cdp_url = attach_cdp_url.rstrip("/") if attach_cdp_url else ""
        self.min_technical_score = min_technical_score
        self.date_lookback_days = max(0, date_lookback_days)
        self.include_replies = include_replies
        self.include_quotes = include_quotes
        self.include_home = include_home
        self.max_home_items = max_home_items
        self.profile_handles = normalize_x_handles(profile_handles)
        self.max_items_per_profile = max_items_per_profile
        self.include_following = include_following
        self.following_owner = following_owner
        self.max_following_profiles = max_following_profiles
        self.max_items_per_following_profile = max_items_per_following_profile

    def collect(
        self,
        query_specs: list[QuerySpec],
        target_day: date,
        tz: tzinfo,
    ) -> tuple[list[ResearchItem], list[str]]:
        warnings: list[str] = []
        items: list[ResearchItem] = []
        if not query_specs and not self.include_home and not self.profile_handles and not self.include_following:
            return items, warnings
        if self.profile_handles:
            warnings.append("X configured profile collection is only implemented for the Playwright backend.")
        if self.include_following:
            warnings.append("X following profile collection is only implemented for the Playwright backend.")

        process: subprocess.Popen[Any] | None = None
        base_url = self.attach_cdp_url
        try:
            if not base_url:
                port = self.debug_port or find_free_port()
                chrome_path = self._find_chrome_path()
                if not chrome_path:
                    return [], ["Chrome executable not found. Pass --chrome-path explicitly."]
                process = self._launch_chrome(chrome_path, port)
                base_url = f"http://127.0.0.1:{port}"
            self._wait_for_cdp(base_url, process)

            for spec in query_specs:
                url = build_x_search_url(spec.query, target_day, include_date_filters=False)
                try:
                    items.extend(self._collect_cdp_url(base_url, url, spec, warnings, self.max_items_per_query))
                except Exception as exc:
                    warnings.append(f"Chrome CDP X query '{spec.name}' failed: {exc}")
            if self.include_home:
                spec = QuerySpec(name="Home Timeline", query="https://x.com/home", category="")
                try:
                    items.extend(
                        self._collect_cdp_url(base_url, "https://x.com/home", spec, warnings, self.max_home_items)
                    )
                except Exception as exc:
                    warnings.append(f"Chrome CDP X home timeline failed: {exc}")
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()

        dated_items, filter_stats = filter_items_by_local_date(
            dedupe_items(items),
            target_day,
            tz,
            lookback_days=self.date_lookback_days,
        )
        if filter_stats["missing_timestamp"] or filter_stats["outside_date"]:
            warnings.append(
                "X date validation skipped "
                f"{filter_stats['outside_date']} items outside {format_date_window(target_day, self.date_lookback_days)} and "
                f"{filter_stats['missing_timestamp']} items without timestamps."
            )
        quality_items, quality_stats = filter_x_items_by_quality(
            dated_items,
            min_technical_score=self.min_technical_score,
            include_replies=self.include_replies,
            include_quotes=self.include_quotes,
        )
        if quality_stats["replies"] or quality_stats["quotes"] or quality_stats["low_score"]:
            warnings.append(
                "X quality filter skipped "
                f"{quality_stats['replies']} replies/comments and "
                f"{quality_stats['quotes']} quote/commentary posts and "
                f"{quality_stats['low_score']} low-technical-score items."
            )
        return quality_items, warnings

    def _collect_cdp_url(
        self,
        base_url: str,
        url: str,
        spec: QuerySpec,
        warnings: list[str],
        max_items: int,
    ) -> list[ResearchItem]:
        target = self._open_target(base_url)
        websocket_url = target.get("webSocketDebuggerUrl")
        target_id = target.get("id", "")
        if not websocket_url:
            warnings.append(f"Chrome CDP did not return a websocket URL for '{spec.name}'.")
            return []

        session = CDPSession(websocket_url, self.timeout_seconds)
        try:
            session.send("Page.enable")
            session.send("Runtime.enable")
            found = self._navigate_and_wait_for_tweets(session, url)
            if not found:
                if self._looks_blocked_or_logged_out(session):
                    warnings.append(f"X section '{spec.name}' may need a signed-in Chrome profile or was rate-limited.")
                else:
                    warnings.append(f"No visible tweets found for X section '{spec.name}'.")
                return []
            if self._looks_blocked_or_logged_out(session):
                warnings.append(f"X section '{spec.name}' may need a signed-in Chrome profile or was rate-limited.")
            return self._extract_tweets(session, spec, max_items=max_items)
        finally:
            session.close()
            if target_id:
                self._close_target(base_url, target_id)

    def _navigate_and_wait_for_tweets(self, session: CDPSession, url: str) -> bool:
        session.send("Page.navigate", {"url": url})
        found = session.wait_for_expression(
            "document.querySelectorAll('article[data-testid=\"tweet\"]').length > 0",
            timeout_seconds=15,
        )
        if found:
            return True
        return False

    def _find_chrome_path(self) -> str:
        if self.chrome_path:
            return self.chrome_path

        candidates: list[str | None] = [
            os.environ.get("CHROME_PATH"),
            shutil.which("chrome"),
            shutil.which("chrome.exe"),
            shutil.which("google-chrome"),
            shutil.which("google-chrome-stable"),
        ]
        for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            root = os.environ.get(env_name)
            if root:
                candidates.append(str(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"))

        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return candidate
        return ""

    def _launch_chrome(self, chrome_path: str, port: int) -> subprocess.Popen[Any]:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        args = [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--disable-first-run-ui",
            "--remote-allow-origins=*",
        ]
        if self.headless:
            args.append("--headless=new")
        if self.chrome_profile_directory:
            args.append(f"--profile-directory={self.chrome_profile_directory}")
        return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _wait_for_cdp(self, base_url: str, process: subprocess.Popen[Any] | None = None) -> None:
        deadline = time.time() + self.timeout_seconds
        while time.time() < deadline:
            try:
                self._fetch_json(f"{base_url}/json/version")
                return
            except Exception:
                if process is not None and process.poll() is not None:
                    raise RuntimeError(
                        "Chrome exited before the DevTools endpoint started. "
                        "This usually means Chrome is already running with the same profile. "
                        "Close all Chrome windows for that profile, then rerun the tool, "
                        "or start Chrome manually with --remote-debugging-port=9222 and use --attach-cdp-url."
                    )
                time.sleep(0.4)
        raise TimeoutError(
            f"Chrome DevTools endpoint did not start at {base_url}. "
            "If an about:blank tab appeared, close the existing Chrome instance for that profile first."
        )

    def _open_target(self, base_url: str) -> dict[str, Any]:
        encoded = quote("about:blank", safe="")
        endpoint = f"{base_url}/json/new?{encoded}"
        try:
            return self._fetch_json(endpoint, method="PUT")
        except Exception:
            return self._fetch_json(endpoint, method="GET")

    def _close_target(self, base_url: str, target_id: str) -> None:
        try:
            self._fetch_json(f"{base_url}/json/close/{target_id}")
        except Exception:
            pass

    def _fetch_json(self, url: str, method: str = "GET") -> dict[str, Any]:
        request = Request(url, method=method)
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _looks_blocked_or_logged_out(self, session: CDPSession) -> bool:
        text = str(
            session.evaluate(
                "(() => (document.body && document.body.innerText ? document.body.innerText : '').toLowerCase())()"
            )
            or ""
        )
        markers = [
            "sign in to x",
            "log in to x",
            "something went wrong",
            "rate limit",
            "unusual login activity",
            "verify you are human",
        ]
        return any(marker in text for marker in markers)

    def _extract_tweets(self, session: CDPSession, spec: QuerySpec, max_items: int | None = None) -> list[ResearchItem]:
        items_by_key: dict[str, ResearchItem] = {}
        item_limit = max_items or self.max_items_per_query
        for _ in range(6):
            raw_tweets = session.evaluate(
                """
                (() => Array.from(document.querySelectorAll('article[data-testid="tweet"]'))
                  .map((article) => {
                    const links = Array.from(article.querySelectorAll('a[href]')).map((a) => a.href).filter(Boolean);
                    const time = article.querySelector('time')?.getAttribute('datetime') || '';
                    const tweetTexts = Array.from(article.querySelectorAll('[data-testid="tweetText"]'))
                      .map((el) => el.innerText || '')
                      .filter(Boolean);
                    const socialContext = article.querySelector('[data-testid="socialContext"]')?.innerText || '';
                    return {
                      article_text: article.innerText || '',
                      tweet_text: tweetTexts[0] || '',
                      tweet_texts: tweetTexts,
                      links,
                      time,
                      social_context: socialContext
                    };
                  }))()
                """
            )
            for raw in raw_tweets or []:
                item = build_x_item_from_raw_tweet(raw, spec, self.keyword_categories, backend="chrome-cdp")
                if item is None:
                    continue
                key = item.url or short_hash(item.text)
                if key in items_by_key:
                    continue
                items_by_key[key] = item
                if len(items_by_key) >= item_limit:
                    return list(items_by_key.values())
            session.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 0.9))")
            time.sleep(1.2)
        return list(items_by_key.values())


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class EthResearchCollector:
    def __init__(
        self,
        endpoints: list[str],
        max_items: int,
        timeout_seconds: int,
        keyword_categories: dict[str, list[str]],
        date_lookback_days: int = 0,
    ) -> None:
        self.endpoints = endpoints
        self.max_items = max_items
        self.timeout_seconds = timeout_seconds
        self.keyword_categories = keyword_categories
        self.date_lookback_days = max(0, date_lookback_days)

    def collect(self, target_day: date, tz: tzinfo) -> tuple[list[ResearchItem], list[str]]:
        warnings: list[str] = []
        topics: dict[int, dict[str, Any]] = {}

        for endpoint in self.endpoints:
            try:
                payload = self._fetch_json(endpoint)
            except Exception as exc:
                warnings.append(f"ethresear.ch endpoint failed ({endpoint}): {exc}")
                continue
            for topic in payload.get("topic_list", {}).get("topics", []):
                topic_id = topic.get("id")
                if isinstance(topic_id, int):
                    topics[topic_id] = topic

        items: list[ResearchItem] = []
        for topic in topics.values():
            created_at = str(topic.get("created_at", ""))
            if not is_in_local_date_window(created_at, target_day, tz, self.date_lookback_days):
                continue
            title = str(topic.get("title", "Untitled ethresear.ch post"))
            slug = str(topic.get("slug", ""))
            topic_id = topic.get("id")
            url = f"{ETHRESEARCH_BASE_URL}/t/{slug}/{topic_id}" if slug and topic_id else ETHRESEARCH_BASE_URL
            tags = [str(tag) for tag in topic.get("tags", [])]
            excerpt = strip_html(str(topic.get("excerpt", "")))
            category_tags = classify_text(" ".join([title, excerpt, " ".join(tags)]), self.keyword_categories)
            author = self._extract_author(topic)
            items.append(
                ResearchItem(
                    source="ethresear.ch",
                    section="New research posts",
                    category=", ".join(category_tags) if category_tags else "Ethereum Research",
                    title=title,
                    url=url,
                    author=author,
                    published_at=created_at,
                    text=excerpt,
                    tags=dedupe_preserve_order(tags + category_tags),
                    score=len(category_tags) + len(tags),
                    raw={
                        "id": topic_id,
                        "posts_count": topic.get("posts_count"),
                        "reply_count": topic.get("reply_count"),
                        "views": topic.get("views"),
                    },
                )
            )

        items.sort(key=lambda item: item.published_at, reverse=True)
        return items[: self.max_items], warnings

    def _fetch_json(self, url: str) -> dict[str, Any]:
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/147.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://ethresear.ch/",
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _extract_author(self, topic: dict[str, Any]) -> str:
        posters = topic.get("posters") or []
        for poster in posters:
            description = str(poster.get("description", "")).lower()
            if "original poster" in description or "original" in description:
                user = poster.get("user") or {}
                username = user.get("username")
                if username:
                    return f"@{username}"
        return ""


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


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
        technical_reasons = item.raw.get("technical_reasons") if item.raw else None
        if technical_score is not None:
            lines.append(f"- Technical score: {technical_score}")
        if technical_reasons:
            lines.append(f"- Matched technical signals: {', '.join(technical_reasons[:8])}")
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


def run(args: argparse.Namespace) -> dict[str, Any]:
    tz = resolve_timezone(args.timezone)
    target_day = parse_target_date(args.date, tz)
    config = load_config(args.config)
    keyword_categories = config.get("keyword_categories", {})
    date_filter_config = config.get("date_filter", {})
    date_lookback_days = args.date_lookback_days
    if date_lookback_days is None:
        date_lookback_days = int(date_filter_config.get("lookback_days", 1))
    date_lookback_days = max(0, date_lookback_days)
    quality_config = config.get("x_quality_filter", {})
    min_technical_score = args.x_min_technical_score
    if min_technical_score is None:
        min_technical_score = int(quality_config.get("min_technical_score", 4))
    include_replies = bool(args.include_replies or quality_config.get("include_replies", False))
    include_quotes = bool(args.include_quotes or quality_config.get("include_quotes", False))
    home_config = config.get("x_home", {})
    include_home = bool(home_config.get("enabled", True)) and not args.skip_x_home
    max_home_items = int(args.max_x_home_items or home_config.get("max_items", 80))
    search_config = config.get("x_search", {})
    include_config_search = bool(args.include_x_search or search_config.get("enabled", False))
    profiles_config = config.get("x_profiles", {})
    configured_profile_values = list(profiles_config.get("handles", [])) + list(args.x_profile or [])
    configured_profile_handles = normalize_x_handles(configured_profile_values)
    include_configured_profiles = bool(profiles_config.get("enabled", False)) and not args.skip_x_profiles
    if args.x_profile:
        include_configured_profiles = True
    if not include_configured_profiles:
        configured_profile_handles = []
    max_items_per_configured_profile = int(
        args.max_x_profile_items or profiles_config.get("max_items_per_profile", 4)
    )
    following_config = config.get("x_following", {})
    include_following = bool(following_config.get("enabled", False)) and not args.skip_x_following
    following_owner = str(args.following_owner or following_config.get("owner", "Ctb0k33"))
    max_following_profiles = int(args.max_following_profiles or following_config.get("max_profiles", 80))
    max_items_per_following_profile = int(
        args.max_following_items_per_profile or following_config.get("max_items_per_profile", 4)
    )

    all_items: list[ResearchItem] = []
    warnings: list[str] = []

    if not args.skip_x:
        if args.x_backend == "chrome-cdp":
            profile_dir = (
                get_system_chrome_user_data_dir()
                if args.use_system_chrome_profile
                else Path(args.profile_dir).expanduser().resolve()
            )
            chrome_profile_directory = args.chrome_profile_directory
            if args.use_system_chrome_profile and not chrome_profile_directory:
                chrome_profile_directory = get_last_used_chrome_profile(profile_dir)
            x_collector = ChromeCDPXCollector(
                profile_dir=profile_dir,
                max_items_per_query=args.max_x_items,
                timeout_ms=args.timeout_ms,
                headless=args.headless,
                keyword_categories=keyword_categories,
                chrome_path=args.chrome_path,
                debug_port=args.chrome_debug_port,
                chrome_profile_directory=chrome_profile_directory,
                attach_cdp_url=args.attach_cdp_url,
                min_technical_score=min_technical_score,
                date_lookback_days=date_lookback_days,
                include_replies=include_replies,
                include_quotes=include_quotes,
                include_home=include_home,
                max_home_items=max_home_items,
                profile_handles=[],
                max_items_per_profile=max_items_per_configured_profile,
                include_following=False,
                following_owner=following_owner,
                max_following_profiles=max_following_profiles,
                max_items_per_following_profile=max_items_per_following_profile,
            )
        else:
            x_collector = XCollector(
                profile_dir=Path(args.profile_dir).expanduser().resolve(),
                max_items_per_query=args.max_x_items,
                timeout_ms=args.timeout_ms,
                headless=args.headless,
                slow_mo=args.slow_mo,
                keyword_categories=keyword_categories,
                min_technical_score=min_technical_score,
                date_lookback_days=date_lookback_days,
                include_replies=include_replies,
                include_quotes=include_quotes,
                include_home=include_home,
                max_home_items=max_home_items,
                profile_handles=configured_profile_handles,
                max_items_per_profile=max_items_per_configured_profile,
                include_following=include_following,
                following_owner=following_owner,
                max_following_profiles=max_following_profiles,
                max_items_per_following_profile=max_items_per_following_profile,
            )
        query_specs = parse_query_specs(
            config,
            args.x_query,
            include_config_queries=include_config_search,
        )
        x_items, x_warnings = x_collector.collect(query_specs, target_day, tz)
        all_items.extend(x_items)
        warnings.extend(x_warnings)

    if not args.skip_ethresearch:
        eth_collector = EthResearchCollector(
            endpoints=list(config.get("ethresearch_endpoints", [])),
            max_items=args.max_ethresearch_items,
            timeout_seconds=max(5, args.timeout_ms // 1000),
            keyword_categories=keyword_categories,
            date_lookback_days=date_lookback_days,
        )
        eth_items, eth_warnings = eth_collector.collect(target_day, tz)
        all_items.extend(eth_items)
        warnings.extend(eth_warnings)

    all_items = dedupe_items(all_items)
    payload = build_payload(target_day, args.timezone, all_items, warnings, config, date_lookback_days)
    paths = write_outputs(payload, Path(args.output_dir).expanduser().resolve())
    return {"paths": paths, "stats": payload["stats"], "warnings": warnings}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect same-day DeFi/core protocol signals from X and new posts from ethresear.ch."
    )
    parser.add_argument("--date", help="Target date in YYYY-MM-DD. Default: today in --timezone.")
    parser.add_argument(
        "--date-lookback-days",
        type=int,
        default=None,
        help="Also include this many local days before --date. Config default: 1.",
    )
    parser.add_argument("--timezone", default="Asia/Saigon", help="Timezone used for date filtering.")
    parser.add_argument("--profile-dir", default="profiles/ctb0k33", help="Persistent Chrome profile for X.")
    parser.add_argument("--output-dir", default="outputs/daily_research", help="Output root directory.")
    parser.add_argument("--config", help="Optional JSON config overriding queries and keyword categories.")
    parser.add_argument(
        "--x-query",
        action="append",
        help="Extra X query. Use 'Name::query' to name the section. Can be repeated.",
    )
    parser.add_argument(
        "--include-x-search",
        action="store_true",
        help="Include configured X search sections. Default source is following + home.",
    )
    parser.add_argument("--max-x-items", type=int, default=40, help="Max X items per query section.")
    parser.add_argument(
        "--x-min-technical-score",
        type=int,
        default=None,
        help="Minimum technical score for X items. Default comes from config, usually 4.",
    )
    parser.add_argument("--include-replies", action="store_true", help="Include X replies/comments.")
    parser.add_argument("--include-quotes", action="store_true", help="Include X quote/commentary posts.")
    parser.add_argument("--skip-x-home", action="store_true", help="Skip X home timeline collection.")
    parser.add_argument("--max-x-home-items", type=int, help="Max X home timeline items before filtering.")
    parser.add_argument("--x-profile", action="append", help="Extra X profile URL or handle to scan. Can be repeated.")
    parser.add_argument("--skip-x-profiles", action="store_true", help="Skip configured X profile collection.")
    parser.add_argument("--max-x-profile-items", type=int, help="Max recent posts per configured profile.")
    parser.add_argument("--skip-x-following", action="store_true", help="Skip followed profile collection.")
    parser.add_argument("--following-owner", help="X account whose following list should be used, e.g. Ctb0k33.")
    parser.add_argument("--max-following-profiles", type=int, help="Max followed profiles to scan.")
    parser.add_argument(
        "--max-following-items-per-profile",
        type=int,
        help="Max recent posts to collect from each followed profile before filtering.",
    )
    parser.add_argument("--max-ethresearch-items", type=int, default=50, help="Max ethresear.ch items.")
    parser.add_argument("--timeout-ms", type=int, default=45000, help="Browser/network timeout.")
    parser.add_argument(
        "--x-backend",
        choices=["playwright", "chrome-cdp"],
        default="playwright",
        help="X collection backend. Default: playwright.",
    )
    parser.add_argument("--chrome-path", help="Chrome executable path for --x-backend chrome-cdp.")
    parser.add_argument(
        "--use-system-chrome-profile",
        action="store_true",
        help="Use the Windows Chrome user data dir instead of --profile-dir for chrome-cdp.",
    )
    parser.add_argument(
        "--chrome-profile-directory",
        help="Chrome profile folder to open, e.g. Default or 'Profile 5'.",
    )
    parser.add_argument(
        "--attach-cdp-url",
        help="Attach to an already running Chrome DevTools endpoint, e.g. http://127.0.0.1:9222.",
    )
    parser.add_argument(
        "--chrome-debug-port",
        type=int,
        default=0,
        help="Remote debugging port for --x-backend chrome-cdp. Default 0 picks a free port.",
    )
    parser.add_argument("--headless", action="store_true", help="Run browser headless.")
    parser.add_argument("--slow-mo", type=int, default=50, help="Playwright slow_mo in milliseconds.")
    parser.add_argument("--skip-x", action="store_true", help="Skip X collection.")
    parser.add_argument("--skip-ethresearch", action="store_true", help="Skip ethresear.ch collection.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = run(args)
    except (HTTPError, URLError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
