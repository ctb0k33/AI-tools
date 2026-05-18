from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..core.feedback import feedback_key_for_item
from ..core.roles import DEFAULT_ROLE, available_roles, normalize_role


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "tools" / "daily_research" / "config" / "telegram_bot.config.example.json"

CALLBACK_ACTIONS = {
    "i": "interested",
    "s": "save",
    "n": "not_relevant",
    "h": "hide_author",
}

CALLBACK_LABELS = {
    "interested": "Interested",
    "save": "Save",
    "not_relevant": "Not relevant",
    "hide_author": "Hide author",
}

STATE_FILE_LOCK = threading.RLock()


def project_path(value: str | None, fallback: str) -> Path:
    raw = value or fallback
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def config_path_with_fallback(value: str | None, fallback: str) -> Path:
    path = project_path(value, fallback)
    if path.exists():
        return path
    migrated = PROJECT_ROOT / "tools" / "daily_research" / "config" / path.name
    if migrated.exists():
        return migrated
    return path


class SingleInstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            self.handle = None
            return False
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(str(os.getpid()))
        self.handle.flush()
        return True

    def release(self) -> None:
        if not self.handle:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


def bot_lock_path(config: dict[str, Any]) -> Path:
    return project_path(config.get("lock_path"), "outputs/daily_research/telegram_bot.lock")


def today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def canonical_item_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw = raw.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    raw = re.sub(r"/analytics$", "", raw)
    match = re.search(r"https?://(?:www\.)?(?:x|twitter)\.com/([^/\s]+)/status/(\d+)", raw, flags=re.IGNORECASE)
    if match:
        return f"https://x.com/{match.group(1)}/status/{match.group(2)}"
    return raw


def canonical_url_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(url for url in (canonical_item_url(value) for value in values) if url))


def load_config(path: str | None) -> dict[str, Any]:
    config_path = config_path_with_fallback(path, str(DEFAULT_CONFIG_PATH))
    return json.loads(config_path.read_text(encoding="utf-8"))


def default_state() -> dict[str, Any]:
    return {
            "active_role": "",
            "interval_minutes": None,
            "run_requested": False,
            "run_requested_role": "",
            "last_run_at": "",
            "last_run_role": "",
            "last_run_date": "",
            "last_sent_count": 0,
            "collection_running": False,
            "collection_started_at": "",
            "collection_finished_at": "",
            "sent_urls": [],
            "sent_urls_by_role": {},
            "sent_items": {},
            "item_feedback": {},
            "telegram_update_offset": 0,
        }


def recover_state_from_legacy(path: Path) -> dict[str, Any] | None:
    legacy_path = path.with_name("telegram_state.json")
    if legacy_path == path or not legacy_path.exists() or legacy_path.stat().st_size == 0:
        return None
    try:
        state = json.loads(legacy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict):
        return None
    return state


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        state = recover_state_from_legacy(path) or default_state()
    else:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            corrupt_path = path.with_suffix(path.suffix + ".corrupt")
            try:
                os.replace(path, corrupt_path)
            except OSError:
                pass
            state = recover_state_from_legacy(path) or default_state()
        if not isinstance(state, dict):
            state = default_state()
    state.setdefault("active_role", "")
    state.setdefault("interval_minutes", None)
    state.setdefault("run_requested", False)
    state.setdefault("run_requested_role", "")
    state.setdefault("last_run_at", "")
    state.setdefault("last_run_role", "")
    state.setdefault("last_run_date", "")
    state.setdefault("last_sent_count", 0)
    state.setdefault("collection_running", False)
    state.setdefault("collection_started_at", "")
    state.setdefault("collection_finished_at", "")
    state.setdefault("sent_urls", [])
    state.setdefault("sent_urls_by_role", {})
    state.setdefault("sent_items", {})
    state.setdefault("item_feedback", {})
    state.setdefault("telegram_update_offset", 0)
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    with STATE_FILE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        sent_urls = canonical_url_list(state.get("sent_urls", []))[-1000:]
        state["sent_urls"] = sent_urls
        sent_urls_by_role = state.get("sent_urls_by_role", {}) if isinstance(state.get("sent_urls_by_role"), dict) else {}
        state["sent_urls_by_role"] = {
            str(role): canonical_url_list(urls)[-1000:]
            for role, urls in sent_urls_by_role.items()
            if isinstance(urls, list)
        }
        sent_items = state.get("sent_items", {}) if isinstance(state.get("sent_items"), dict) else {}
        item_feedback = state.get("item_feedback", {}) if isinstance(state.get("item_feedback"), dict) else {}
        if len(sent_items) > 1000:
            keep_ids = list(sent_items.keys())[-1000:]
            state["sent_items"] = {item_id: sent_items[item_id] for item_id in keep_ids}
            state["item_feedback"] = {item_id: item_feedback[item_id] for item_id in keep_ids if item_id in item_feedback}
        tmp_path = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{threading.get_ident()}")
        tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)


def get_active_role(config: dict[str, Any], state: dict[str, Any] | None = None) -> str:
    state_role = str((state or {}).get("active_role") or "").strip()
    return normalize_role(state_role or str(config.get("role") or DEFAULT_ROLE))


def config_for_state(config: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
    effective_config = dict(config)
    effective_config["role"] = get_active_role(config, state)
    return effective_config


def get_interval_minutes(config: dict[str, Any], state: dict[str, Any] | None = None) -> int:
    state_interval = (state or {}).get("interval_minutes")
    try:
        if state_interval not in (None, ""):
            return max(1, int(state_interval))
    except (TypeError, ValueError):
        pass
    return max(1, int(config.get("interval_minutes") or 30))


def state_timestamp(value: Any) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return None


def next_due_timestamp(config: dict[str, Any], state: dict[str, Any]) -> float:
    last_run = state_timestamp(state.get("last_run_at"))
    if last_run is None:
        return time.time()
    return last_run + get_interval_minutes(config, state) * 60


def item_score(item: dict[str, Any]) -> int:
    raw = item.get("raw") or {}
    return int(raw.get("personalized_score") or item.get("score") or raw.get("technical_score") or 0)


def select_new_items(digest: dict[str, Any], state: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    role = normalize_role(str(config.get("role") or DEFAULT_ROLE))
    sent_by_role = state.get("sent_urls_by_role", {}) if isinstance(state.get("sent_urls_by_role"), dict) else {}
    sent = set(canonical_url_list(state.get("sent_urls", [])))
    for urls in sent_by_role.values():
        sent.update(canonical_url_list(urls))
    sent.update(canonical_url_list(sent_by_role.get(role, [])))
    min_score = int(config.get("min_technical_score") or 6)
    max_items = int(config.get("max_items_per_run") or 8)
    candidates = []
    for item in digest.get("items", []):
        url = canonical_item_url(item.get("url"))
        if not url or url in sent:
            continue
        if item_score(item) < min_score:
            continue
        candidates.append(item)
    candidates.sort(key=lambda item: (item_score(item), str(item.get("published_at") or "")), reverse=True)
    return candidates[:max_items]


def normalize_message_text(value: str) -> str:
    lowered = value.lower().replace("\u2026", "...")
    lowered = lowered.replace("...", "")
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def is_redundant_summary(title: str, summary: str) -> bool:
    title_text = normalize_message_text(title)
    summary_text = normalize_message_text(summary)
    if not title_text or not summary_text:
        return False
    if title_text == summary_text:
        return True
    prefix = title_text[: min(len(title_text), 120)]
    return len(prefix) >= 40 and summary_text.startswith(prefix)


def format_message_title_and_summary(title: str, summary: str) -> tuple[str, str]:
    if not is_redundant_summary(title, summary):
        return title, summary
    if len(summary) <= 320:
        return summary, ""
    return title, ""


def format_item_message(item: dict[str, Any]) -> str:
    raw = item.get("raw") or {}
    title = str(item.get("title") or "Untitled")
    author = str(item.get("author") or "")
    section = str(item.get("section") or "")
    score = item_score(item)
    summary = str(raw.get("summary") or item.get("text") or "").strip()
    title, summary = format_message_title_and_summary(title, summary)
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


def telegram_api_request(token: str, method_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    encoded_payload = urlencode(payload).encode("utf-8")
    request = Request(
        f"https://api.telegram.org/bot{token}/{method_name}",
        data=encoded_payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method_name} failed: {body}")
    return body


def send_telegram_message(
    token: str,
    chat_id: str,
    text: str,
    reply_markup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "false",
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    return telegram_api_request(token, "sendMessage", payload)


def answer_callback_query(token: str, callback_query_id: str, text: str) -> None:
    telegram_api_request(
        token,
        "answerCallbackQuery",
        {
            "callback_query_id": callback_query_id,
            "text": text[:200],
            "show_alert": "false",
        },
    )


def edit_message_reply_markup(token: str, chat_id: str, message_id: int, reply_markup: dict[str, Any]) -> None:
    telegram_api_request(
        token,
        "editMessageReplyMarkup",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": json.dumps(reply_markup, ensure_ascii=False),
        },
    )


def get_telegram_updates(token: str, offset: int, timeout_seconds: int = 0) -> list[dict[str, Any]]:
    body = telegram_api_request(
        token,
        "getUpdates",
        {
            "offset": offset,
            "timeout": timeout_seconds,
            "allowed_updates": json.dumps(["callback_query", "message"]),
        },
    )
    return list(body.get("result") or [])


def item_feedback_id(item: dict[str, Any]) -> str:
    return hashlib.sha256(feedback_key_for_item(item).encode("utf-8")).hexdigest()[:12]


def feedback_keyboard(item_id: str, selected_action: str | None = None) -> dict[str, Any]:
    def button(label: str, action_code: str, action: str) -> dict[str, str]:
        suffix = " [x]" if action == selected_action else ""
        return {"text": f"{label}{suffix}", "callback_data": f"fb:{action_code}:{item_id}"}

    return {
        "inline_keyboard": [
            [
                button("Interested", "i", "interested"),
                button("Save", "s", "save"),
            ],
            [
                button("Not relevant", "n", "not_relevant"),
                button("Hide author", "h", "hide_author"),
            ],
        ]
    }


def role_options() -> dict[str, dict[str, str]]:
    return {role["id"]: role for role in available_roles()}


def format_role_list(active_role: str) -> str:
    roles = role_options()
    if not roles:
        return "No role configs found."
    lines = ["<b>Available roles</b>"]
    for role_id, role in roles.items():
        marker = " (active)" if role_id == active_role else ""
        description = f" - {role.get('description')}" if role.get("description") else ""
        lines.append(f"- <code>{escape_html(role_id)}</code>: {escape_html(role.get('label') or role_id)}{marker}{escape_html(description)}")
    lines.append("")
    lines.append("Use <code>/role researcher</code>, <code>/role bd</code>, <code>/role marketing</code>, or <code>/role operations</code>.")
    return "\n".join(lines)


def format_help_message(active_role: str) -> str:
    return "\n".join(
        [
            "<b>Daily Research Bot Commands</b>",
            f"Current role: <code>{escape_html(active_role)}</code>",
            "",
            "<code>/status</code> - show bot status",
            "<code>/run</code> - run collection now with the active role",
            "<code>/run bd</code> - run once with a specific role",
            "<code>/interval</code> - show current run interval",
            "<code>/interval 10m</code> - set run interval",
            "<code>/interval reset</code> - reset interval to config",
            "<code>/role</code> - show the active role",
            "<code>/roles</code> - list available roles",
            "<code>/role researcher</code> - switch role",
            "<code>/dashboard</code> - start/open the local dashboard",
            "<code>/dashboard_stop</code> - stop dashboard API/frontend started by the bot",
            "<code>/help</code> - show this help",
        ]
    )


def parse_command(text: str) -> tuple[str, list[str]]:
    cleaned = text.strip()
    if not cleaned.startswith("/"):
        return "", []
    parts = cleaned.split()
    command = parts[0].split("@", 1)[0].lower()
    return command, parts[1:]


def parse_interval_minutes(value: str) -> int | None:
    cleaned = value.strip().lower()
    match = re.fullmatch(r"(\d+)\s*(m|min|mins|minute|minutes)?", cleaned)
    if match:
        return max(1, int(match.group(1)))
    match = re.fullmatch(r"(\d+)\s*(h|hr|hrs|hour|hours)", cleaned)
    if match:
        return max(1, int(match.group(1)) * 60)
    return None


def format_interval(minutes: int) -> str:
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour" if hours == 1 else f"{hours} hours"
    return f"{minutes} minutes"


def item_from_callback_message(message: dict[str, Any]) -> dict[str, Any] | None:
    text = str(message.get("text") or message.get("caption") or "").strip()
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None

    title = lines[0]
    meta_line = lines[1] if len(lines) > 1 else ""
    url = ""
    for match in re.finditer(r"https?://\S+", text):
        url = match.group(0).rstrip(").,")
        break

    meta_parts = [part.strip() for part in meta_line.split("|") if part.strip()]
    author = meta_parts[0] if meta_parts else ""
    section = meta_parts[1] if len(meta_parts) > 1 else ""
    score = 0
    tags: list[str] = []
    for part in meta_parts[2:]:
        score_match = re.search(r"\bscore\s+(-?\d+)\b", part, flags=re.IGNORECASE)
        if score_match:
            score = int(score_match.group(1))
        else:
            tags.extend(tag.strip() for tag in part.split(",") if tag.strip())

    summary_lines = []
    for line in lines[2:]:
        if line == url or line.startswith("https://") or line.startswith("http://"):
            continue
        summary_lines.append(line)
    summary = "\n".join(summary_lines).strip()

    if not title and not url:
        return None
    return {
        "source": "X",
        "section": section,
        "category": tags[0] if tags else "",
        "title": title,
        "author": author,
        "url": url,
        "score": score,
        "tags": tags,
        "text": summary,
        "raw": {
            "summary": summary,
            "technical_score": score,
            "technical_reasons": tags,
            "feedback_source": "telegram_message_fallback",
        },
    }


def message_selected_feedback_action(message: dict[str, Any], callback_data: str) -> str | None:
    reply_markup = message.get("reply_markup") or {}
    for row in reply_markup.get("inline_keyboard", []) or []:
        for button in row or []:
            if str(button.get("callback_data") or "") != callback_data:
                continue
            text = str(button.get("text") or "")
            if "[x]" not in text:
                return None
            parts = callback_data.split(":")
            if len(parts) == 3 and parts[0] == "fb":
                return CALLBACK_ACTIONS.get(parts[1])
    return None
