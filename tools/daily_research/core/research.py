from __future__ import annotations

import copy
import dataclasses
import hashlib
import html
import json
import os
import re
import sqlite3
import socket
import time
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from .feedback import score_item_with_preferences
from .roles import DEFAULT_ROLE, deep_merge, load_role_config, normalize_role

X_BASE_URL = "https://x.com/search"
ETHRESEARCH_BASE_URL = "https://ethresear.ch"

DEFAULT_CONFIG: dict[str, Any] = {
    "date_filter": {
        "lookback_days": 1,
    },
    "x_search": {
        "enabled": False,
    },
    "x_queries": [],
    "ethresearch_endpoints": [
        "https://ethresear.ch/new.json",
        "https://ethresear.ch/latest.json",
    ],
    "keyword_categories": {},
    "x_quality_filter": {
        "min_technical_score": 4,
        "include_replies": False,
        "include_quotes": False,
        "positive_terms": {},
        "low_value_terms": [],
        "generic_terms": [],
    },
    "personalization": {
        "enabled": True,
        "feedback_path": "outputs/daily_research/feedback_store.json",
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
        "owner": "",
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


FALLBACK_POSITIVE_TERMS = {
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

FALLBACK_LOW_VALUE_TERMS = [
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


def technical_score_text(
    text: str,
    positive_terms: dict[str, int] | None = None,
    low_value_terms: list[str] | None = None,
    generic_terms: set[str] | None = None,
) -> tuple[int, list[str]]:
    lowered = normalize_whitespace(text).lower()
    score = 0
    lexical_score = 0
    reasons: list[str] = []
    lexical_reasons: list[str] = []
    if positive_terms is None:
        positive_terms = FALLBACK_POSITIVE_TERMS
    if low_value_terms is None:
        low_value_terms = FALLBACK_LOW_VALUE_TERMS
    if generic_terms is None:
        generic_terms = {"protocol", "security", "research", "builder", "liquidity", "thread", "design"}

    for term, weight in positive_terms.items():
        if term in lowered:
            score += weight
            lexical_score += weight
            reasons.append(term)
            lexical_reasons.append(term)

    for term in low_value_terms:
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

    generic_reason_set = set(generic_terms)
    if lexical_score <= 4 and lexical_reasons and set(lexical_reasons).issubset(generic_reason_set):
        score -= 2
        reasons.append("generic_only")

    return score, dedupe_preserve_order(reasons)


def filter_x_items_by_quality(
    items: list[ResearchItem],
    min_technical_score: int,
    include_replies: bool,
    include_quotes: bool,
    preference_model: dict[str, Any] | None = None,
    quality_terms: dict[str, Any] | None = None,
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
        technical_score, reasons = technical_score_text(
            item.text,
            positive_terms=quality_terms.get("positive_terms") if quality_terms else None,
            low_value_terms=quality_terms.get("low_value_terms") if quality_terms else None,
            generic_terms=quality_terms.get("generic_terms") if quality_terms else None,
        )
        item.raw["technical_score"] = technical_score
        item.raw["technical_reasons"] = reasons
        personalization_adjustment, personalization_reasons = score_item_with_preferences(item, preference_model)
        final_score = technical_score + personalization_adjustment
        item.score = final_score
        item.raw["personalized_score"] = final_score
        item.raw["personalization_adjustment"] = personalization_adjustment
        item.raw["personalization_reasons"] = personalization_reasons
        item.raw["is_reply"] = reply
        item.raw["is_quote"] = quote
        item.raw["summary"] = item.raw.get("summary") or summarize_x_post(item.text)

        if reply and not include_replies:
            stats["replies"] += 1
            continue
        if quote and not include_quotes:
            stats["quotes"] += 1
            continue
        if final_score < min_technical_score:
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
    cookie_candidates = [
        profile_dir / "Default" / "Network" / "Cookies",
        profile_dir / "Default" / "Cookies",
    ]
    cookies_db = next((candidate for candidate in cookie_candidates if candidate.exists()), cookie_candidates[0])
    if not cookies_db.exists():
        visible_candidates = ", ".join(str(candidate) for candidate in cookie_candidates)
        return False, f"X profile cookies DB not found. Checked: {visible_candidates}"
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


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def unlock_stale_chromium_profile(profile_dir: Path) -> list[str]:
    lock_path = profile_dir / "SingletonLock"
    if not lock_path.exists() and not lock_path.is_symlink():
        return []

    try:
        lock_target = os.readlink(lock_path) if lock_path.is_symlink() else lock_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return [f"Could not inspect Chromium profile lock {lock_path}: {exc}"]

    current_host = socket.gethostname()
    stale = True
    detail = lock_target or "unknown lock target"
    if "-" in lock_target:
        lock_host, lock_pid_text = lock_target.rsplit("-", 1)
        if lock_host == current_host:
            try:
                lock_pid = int(lock_pid_text)
            except ValueError:
                stale = True
            else:
                stale = not _process_exists(lock_pid)
                if not stale:
                    return [f"Chromium profile is actively locked by PID {lock_pid} on this container."]

    if not stale:
        return []

    removed: list[str] = []
    errors: list[str] = []
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        path = profile_dir / name
        if not path.exists() and not path.is_symlink():
            continue
        try:
            path.unlink()
            removed.append(name)
        except OSError as exc:
            errors.append(f"{name}: {exc}")
    if errors:
        return [f"Could not remove stale Chromium profile locks ({detail}): {'; '.join(errors)}"]
    if removed:
        return [f"Removed stale Chromium profile locks ({detail}): {', '.join(removed)}."]
    return []


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


def extract_roundup_titles(text: str) -> list[str]:
    cleaned = normalize_whitespace(text)
    if not cleaned:
        return []
    if "weekly roundup" not in cleaned.lower() and len(re.findall(r"ethresear\.ch/t/\d+", cleaned, flags=re.I)) < 3:
        return []
    normalized = re.sub(r"https?://\s*ethresear\.ch/t/\d+", " <ETHRESEARCH_LINK> ", cleaned, flags=re.I)
    normalized = re.sub(r"\b\d+\s+comment\(s\)\s+this\s+week\b", " <ROUNDUP_BREAK> ", normalized, flags=re.I)
    normalized = re.sub(r"\b\d+\s+comments?\s+this\s+week\b", " <ROUNDUP_BREAK> ", normalized, flags=re.I)
    pieces = re.split(r"<ETHRESEARCH_LINK>|<ROUNDUP_BREAK>", normalized)
    titles: list[str] = []
    for piece in pieces:
        candidate = normalize_whitespace(piece)
        candidate = re.sub(r"^weekly roundup\s*", "", candidate, flags=re.I).strip(" -:;")
        candidate = re.sub(r"^(new post on\s+)?https?://\s*", "", candidate, flags=re.I).strip(" -:;")
        if len(candidate) < 12:
            continue
        if candidate.lower() in {"weekly roundup", "ethresearchbot"}:
            continue
        titles.append(candidate)
    return dedupe_preserve_order(titles)


def summarize_roundup_post(text: str, max_chars: int) -> str:
    titles = extract_roundup_titles(text)
    if len(titles) < 3:
        return ""
    selected: list[str] = []
    for title in titles:
        candidate = f"Weekly roundup covering {len(titles)} ethresear.ch posts: " + "; ".join([*selected, title])
        if len(candidate) > max_chars and selected:
            break
        selected.append(title)
        if len(selected) >= 8:
            break
    suffix = "" if len(selected) == len(titles) else f"; and {len(titles) - len(selected)} more"
    return truncate_at_word(
        f"Weekly roundup covering {len(titles)} ethresear.ch posts: " + "; ".join(selected) + suffix,
        max_chars,
    )


def sentence_signal_score(sentence: str) -> int:
    lowered = sentence.lower()
    score = 0
    for term, weight in FALLBACK_POSITIVE_TERMS.items():
        if term in lowered:
            score += weight
    if re.search(r"\b(eip|erc)-?\d{3,5}\b", lowered):
        score += 4
    if "http" in lowered:
        score -= 1
    return score


def summarize_x_post(text: str, max_chars: int = 700) -> str:
    embedded_summary = re.search(r"\bsummary:\s*(.+)", normalize_whitespace(text), flags=re.IGNORECASE)
    if embedded_summary:
        summary_tail = embedded_summary.group(1).strip()
        if len(summary_tail) >= 32:
            sentences = split_summary_sentences(summary_tail)
            if sentences:
                return truncate_at_word(" ".join(sentences[:2]), max_chars)
            return truncate_at_word(summary_tail, max_chars)

    roundup_summary = summarize_roundup_post(text, max_chars)
    if roundup_summary:
        return roundup_summary

    sentences = split_summary_sentences(text)
    if not sentences:
        return truncate_at_word(text, max_chars)

    if len(normalize_whitespace(text)) >= 550 and len(sentences) > 2:
        scored = sorted(
            enumerate(sentences),
            key=lambda pair: (sentence_signal_score(pair[1]), -pair[0]),
            reverse=True,
        )
        selected_indexes = sorted(index for index, _ in scored[:3])
        candidates = [sentences[index] for index in selected_indexes]
    else:
        candidates = sentences[:2]

    selected: list[str] = []
    for sentence in candidates:
        candidate = normalize_whitespace(" ".join([*selected, sentence]))
        if len(candidate) > max_chars and selected:
            break
        selected.append(sentence)
        if len(selected) >= 2:
            break
    return truncate_at_word(" ".join(selected), max_chars)


def derive_x_title(text: str, summary: str) -> str:
    titles = extract_roundup_titles(text)
    if len(titles) >= 3:
        return f"Weekly Roundup: {len(titles)} ethresear.ch research posts"
    return truncate_text(summary or text, 180)


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
    title = derive_x_title(tweet_text, summary)
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


def load_config(path: str | None, role: str | None = DEFAULT_ROLE, role_config: str | None = None) -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    normalized_role = normalize_role(role)
    if normalized_role or role_config:
        role_payload = load_role_config(normalized_role, role_config)
        config = deep_merge(config, role_payload)
        role_info = config.get("role", {}) if isinstance(config.get("role"), dict) else {}
        role_info.setdefault("id", normalized_role)
        config["role"] = role_info
    if not path:
        return config

    config_path = Path(path)
    if not config_path.exists():
        migrated_path = Path(__file__).resolve().parents[3] / "tools" / "daily_research" / "config" / config_path.name
        if migrated_path.exists():
            config_path = migrated_path
    user_config = json.loads(config_path.read_text(encoding="utf-8"))
    config = deep_merge(config, user_config)
    return config


def build_quality_terms(config: dict[str, Any]) -> dict[str, Any]:
    quality_config = config.get("x_quality_filter", {}) if isinstance(config.get("x_quality_filter"), dict) else {}
    configured_positive_terms = quality_config.get("positive_terms")
    positive_terms = dict(FALLBACK_POSITIVE_TERMS) if not configured_positive_terms else {}
    for term, weight in (configured_positive_terms or {}).items():
        try:
            positive_terms[str(term).lower()] = int(weight)
        except (TypeError, ValueError):
            continue

    configured_low_value_terms = quality_config.get("low_value_terms")
    low_value_terms = list(
        dict.fromkeys(
            (FALLBACK_LOW_VALUE_TERMS if not configured_low_value_terms else [])
            + list(configured_low_value_terms or [])
        )
    )
    configured_generic_terms = quality_config.get("generic_terms")
    generic_terms = set(configured_generic_terms or [])
    if not configured_generic_terms:
        generic_terms = {"protocol", "security", "research", "builder", "liquidity", "thread", "design"}

    return {
        "positive_terms": positive_terms,
        "low_value_terms": [str(term).lower() for term in low_value_terms],
        "generic_terms": {str(term).lower() for term in generic_terms},
    }


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
