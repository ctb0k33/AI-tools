from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


FEEDBACK_ACTION_WEIGHTS = {
    "interested": 3,
    "save": 4,
    "more_like_this": 2,
    "not_relevant": -4,
    "less_like_this": -2,
    "hide_author": -8,
}

MAX_AUTHOR_WEIGHT = 8
MAX_TERM_WEIGHT = 6
MAX_PERSONALIZATION_ADJUSTMENT = 12

BROAD_TOPIC_SIGNALS = {
    "defi",
    "core protocol",
    "l2 and data availability",
    "zk and cryptography",
    "security",
    "partnerships",
    "product launches",
    "customers and adoption",
    "defi market structure",
    "funding and strategy",
    "narratives",
    "campaigns",
    "competitors",
    "product messaging",
    "kol and media",
    "incidents",
    "network and protocol ops",
    "governance and deadlines",
    "monitoring",
}

POSITIVE_FEEDBACK_ACTIONS = {"interested", "save", "more_like_this"}
NEGATIVE_FEEDBACK_ACTIONS = {"not_relevant", "less_like_this", "hide_author"}


def empty_feedback_store() -> dict[str, Any]:
    return {
        "version": 1,
        "events": [],
        "items": {},
    }


def load_feedback_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_feedback_store()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return empty_feedback_store()
    if not isinstance(payload, dict):
        return empty_feedback_store()
    payload.setdefault("version", 1)
    payload.setdefault("events", [])
    payload.setdefault("items", {})
    return payload


def save_feedback_store(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return value.strip()
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


def normalize_author(value: str) -> str:
    return str(value or "").strip().lower()


def normalize_signal(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def is_broad_topic_signal(value: str) -> bool:
    return normalize_signal(value) in BROAD_TOPIC_SIGNALS


def author_weight_for_feedback(action: str, base_weight: int) -> int:
    if action == "hide_author":
        return base_weight
    if action in {"not_relevant", "less_like_this"}:
        return clamp(base_weight // 2, -2, 0)
    return base_weight


def signal_weight_for_feedback(action: str, signal: str, base_weight: int) -> int:
    if action in {"not_relevant", "less_like_this"}:
        if is_broad_topic_signal(signal):
            return 0
        return clamp(base_weight // 2, -2, 0)
    if action == "hide_author":
        return 0
    return base_weight


def item_get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def item_raw(item: Any) -> dict[str, Any]:
    raw = item_get(item, "raw", {}) or {}
    return raw if isinstance(raw, dict) else {}


def extract_item_signals(item: Any) -> list[str]:
    raw = item_raw(item)
    signals: list[str] = []
    for value in item_get(item, "tags", []) or []:
        signals.append(str(value))
    category = item_get(item, "category", "")
    if category:
        signals.append(str(category))
    for value in raw.get("technical_reasons", []) or []:
        value_text = str(value)
        if value_text.startswith("low_value:"):
            continue
        signals.append(value_text)
    return list(dict.fromkeys(signal for signal in (normalize_signal(value) for value in signals) if signal))


def feedback_key_for_item(item: Any) -> str:
    url = normalize_url(str(item_get(item, "url", "") or ""))
    if url:
        return url
    title = str(item_get(item, "title", "") or "")
    author = str(item_get(item, "author", "") or "")
    return f"{normalize_author(author)}::{normalize_signal(title)}"


def build_feedback_record(item: dict[str, Any], action: str, reason: str = "") -> dict[str, Any]:
    if action not in FEEDBACK_ACTION_WEIGHTS:
        raise ValueError(f"Unsupported feedback action: {action}")
    key = feedback_key_for_item(item)
    if not key:
        raise ValueError("Feedback item must include at least a URL or title/author.")
    raw = item.get("raw") or {}
    signals = extract_item_signals(item)
    return {
        "key": key,
        "action": action,
        "reason": reason.strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "url": normalize_url(str(item.get("url") or "")),
        "title": str(item.get("title") or ""),
        "author": str(item.get("author") or ""),
        "source": str(item.get("source") or ""),
        "section": str(item.get("section") or ""),
        "tags": list(item.get("tags") or []),
        "technical_reasons": list(raw.get("technical_reasons") or []),
        "signals": signals,
    }


def record_feedback(path: Path, item: dict[str, Any], action: str, reason: str = "") -> dict[str, Any]:
    store = load_feedback_store(path)
    record = build_feedback_record(item, action, reason)
    store["events"].append(record)
    store["items"][record["key"]] = record
    save_feedback_store(path, store)
    return {
        "record": record,
        "model": build_preference_model(store),
    }


def clear_feedback(path: Path, item: dict[str, Any], reason: str = "") -> dict[str, Any]:
    store = load_feedback_store(path)
    key = feedback_key_for_item(item)
    if not key:
        raise ValueError("Feedback item must include at least a URL or title/author.")

    raw = item.get("raw") or {}
    record = {
        "key": key,
        "action": "clear",
        "reason": reason.strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "url": normalize_url(str(item.get("url") or "")),
        "title": str(item.get("title") or ""),
        "author": str(item.get("author") or ""),
        "source": str(item.get("source") or ""),
        "section": str(item.get("section") or ""),
        "tags": list(item.get("tags") or []),
        "technical_reasons": list(raw.get("technical_reasons") or []),
        "signals": extract_item_signals(item),
    }
    store["events"].append(record)
    store["items"].pop(key, None)
    save_feedback_store(path, store)
    return {
        "record": record,
        "model": build_preference_model(store),
    }


def build_preference_model(store: dict[str, Any]) -> dict[str, Any]:
    author_weights: dict[str, int] = {}
    signal_weights: dict[str, int] = {}
    hidden_authors: set[str] = set()
    url_feedback: dict[str, str] = {}

    latest_records = list((store.get("items") or {}).values())
    for record in latest_records:
        action = str(record.get("action") or "")
        weight = FEEDBACK_ACTION_WEIGHTS.get(action, 0)
        author = normalize_author(str(record.get("author") or ""))
        if author:
            author_weight = author_weight_for_feedback(action, weight)
            author_weights[author] = clamp(
                author_weights.get(author, 0) + author_weight,
                -MAX_AUTHOR_WEIGHT,
                MAX_AUTHOR_WEIGHT,
            )
            if action == "hide_author":
                hidden_authors.add(author)
                continue
        for signal in record.get("signals", []) or []:
            normalized = normalize_signal(str(signal))
            if not normalized:
                continue
            signal_weight = signal_weight_for_feedback(action, normalized, weight)
            if not signal_weight:
                continue
            signal_weights[normalized] = clamp(
                signal_weights.get(normalized, 0) + signal_weight,
                -MAX_TERM_WEIGHT,
                MAX_TERM_WEIGHT,
            )
        url = normalize_url(str(record.get("url") or ""))
        if url:
            url_feedback[url] = action

    return {
        "author_weights": dict(sorted(author_weights.items())),
        "signal_weights": dict(sorted(signal_weights.items())),
        "hidden_authors": sorted(hidden_authors),
        "url_feedback": url_feedback,
        "feedback_count": len(latest_records),
        "broad_topic_signals": sorted(BROAD_TOPIC_SIGNALS),
    }


def score_item_with_preferences(item: Any, model: dict[str, Any] | None) -> tuple[int, list[str]]:
    if not model:
        return 0, []

    adjustment = 0
    reasons: list[str] = []
    author = normalize_author(str(item_get(item, "author", "") or ""))
    author_weights = model.get("author_weights", {}) or {}
    signal_weights = model.get("signal_weights", {}) or {}
    hidden_authors = set(model.get("hidden_authors", []) or [])
    url_feedback = model.get("url_feedback", {}) or {}
    url = normalize_url(str(item_get(item, "url", "") or ""))

    if url and url in url_feedback:
        action = str(url_feedback[url])
        if action in {"interested", "save", "more_like_this"}:
            adjustment += 4
            reasons.append(f"previous_feedback:{action}")
        elif action in {"not_relevant", "less_like_this", "hide_author"}:
            adjustment -= 6
            reasons.append(f"previous_feedback:{action}")

    if author in hidden_authors:
        adjustment -= MAX_PERSONALIZATION_ADJUSTMENT
        reasons.append(f"hidden_author:{author}")
    elif author and author in author_weights:
        weight = int(author_weights[author])
        adjustment += weight
        if weight:
            reasons.append(f"author:{author}:{weight:+d}")

    for signal in extract_item_signals(item):
        weight = int(signal_weights.get(signal, 0))
        if not weight:
            continue
        adjustment += weight
        reasons.append(f"signal:{signal}:{weight:+d}")

    adjustment = clamp(adjustment, -MAX_PERSONALIZATION_ADJUSTMENT, MAX_PERSONALIZATION_ADJUSTMENT)
    return adjustment, reasons[:8]
