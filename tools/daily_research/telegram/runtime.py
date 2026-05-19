from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

from ..core.feedback import clear_feedback, record_feedback
from ..core.roles import DEFAULT_ROLE, load_role_config, normalize_role, role_feedback_path, role_output_dir
from .common import (
    CALLBACK_ACTIONS,
    CALLBACK_LABELS,
    DEFAULT_CONFIG_PATH,
    PROJECT_ROOT,
    answer_callback_query,
    canonical_item_url,
    config_for_state,
    edit_message_reply_markup,
    escape_html,
    feedback_keyboard,
    format_empty_message,
    format_end_marker,
    format_help_message,
    format_interval,
    format_item_message,
    format_role_list,
    format_start_marker,
    get_active_role,
    get_interval_minutes,
    get_telegram_updates,
    item_feedback_id,
    item_from_callback_message,
    load_state,
    message_selected_feedback_action,
    next_due_timestamp,
    parse_command,
    parse_interval_minutes,
    project_path,
    role_options,
    save_state,
    select_new_items,
    send_telegram_message,
    today_iso,
)
from .dashboard import (
    format_status_message,
    start_dashboard_services,
    stop_dashboard_services,
)


def run_daily_research(config: dict[str, Any]) -> dict[str, Any]:
    target_date = str(config.get("date") or today_iso())
    role = normalize_role(str(config.get("role") or DEFAULT_ROLE))
    try:
        role_config = load_role_config(role)
    except Exception:
        role_config = {}
    daily_config = config.get("daily_research_config")
    command = [
        sys.executable,
        "-m",
        "tools.daily_research.daily_research_tool",
        "--date",
        target_date,
        "--timezone",
        str(config.get("timezone") or "Asia/Saigon"),
        "--profile-dir",
        str(project_path(config.get("profile_dir"), "profiles/x_profile")),
        "--role",
        role,
        "--output-dir",
        str(project_path(config.get("output_dir"), role_output_dir(role_config, role))),
        "--x-backend",
        "playwright",
    ]
    if daily_config:
        command.extend(["--config", str(project_path(str(daily_config), "tools/daily_research/config/selected_x_profiles.config.json"))])
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

    output_dir = project_path(config.get("output_dir"), role_output_dir(role_config, role))
    digest_path = output_dir / target_date / "daily_research_digest.json"
    if not digest_path.exists():
        raise FileNotFoundError(f"Digest not found: {digest_path}")
    return json.loads(digest_path.read_text(encoding="utf-8"))


def process_command_message(
    token: str,
    chat_id: str,
    state: dict[str, Any],
    state_path: Path,
    config: dict[str, Any],
    message: dict[str, Any],
) -> bool:
    message_chat = message.get("chat") or {}
    message_chat_id = str(message_chat.get("id") or "")
    if message_chat_id and message_chat_id != str(chat_id):
        return False

    command, args = parse_command(str(message.get("text") or ""))
    if not command:
        return False

    active_role = get_active_role(config, state)
    if command in {"/start", "/help"}:
        send_telegram_message(token, chat_id, format_help_message(active_role))
        return True

    if command == "/status":
        send_telegram_message(token, chat_id, format_status_message(config, state))
        return True

    if command == "/run":
        requested_role = active_role
        if args:
            requested_role = normalize_role(args[0])
            roles = role_options()
            if requested_role not in roles:
                send_telegram_message(token, chat_id, f"Unknown role: <code>{escape_html(requested_role)}</code>\n\n{format_role_list(active_role)}")
                return True
        state["run_requested"] = True
        state["run_requested_role"] = requested_role
        save_state(state_path, state)
        send_telegram_message(token, chat_id, f"Run requested. The next collection will start now with role <code>{escape_html(requested_role)}</code>.")
        return True

    if command == "/interval":
        if not args:
            interval_minutes = get_interval_minutes(config, state)
            send_telegram_message(
                token,
                chat_id,
                f"Current run interval: <code>{escape_html(format_interval(interval_minutes))}</code>\nUse <code>/interval 10m</code>, <code>/interval 1h</code>, or <code>/interval reset</code>.",
            )
            return True
        if args[0].lower() in {"reset", "default"}:
            state["interval_minutes"] = None
            save_state(state_path, state)
            interval_minutes = get_interval_minutes(config, state)
            send_telegram_message(token, chat_id, f"Run interval reset to config value: <code>{escape_html(format_interval(interval_minutes))}</code>.")
            return True
        parsed_interval = parse_interval_minutes(" ".join(args))
        if parsed_interval is None:
            send_telegram_message(token, chat_id, "Could not parse interval. Examples: <code>/interval 10m</code>, <code>/interval 30</code>, <code>/interval 1h</code>.")
            return True
        state["interval_minutes"] = parsed_interval
        save_state(state_path, state)
        send_telegram_message(token, chat_id, f"Run interval updated to <code>{escape_html(format_interval(parsed_interval))}</code>.")
        return True

    if command == "/roles":
        send_telegram_message(token, chat_id, format_role_list(active_role))
        return True

    if command == "/role":
        if not args:
            send_telegram_message(token, chat_id, f"Current role: <code>{escape_html(active_role)}</code>\n\n{format_role_list(active_role)}")
            return True
        requested_role = normalize_role(args[0])
        roles = role_options()
        if requested_role not in roles:
            send_telegram_message(token, chat_id, f"Unknown role: <code>{escape_html(requested_role)}</code>\n\n{format_role_list(active_role)}")
            return True
        state["active_role"] = requested_role
        save_state(state_path, state)
        label = roles[requested_role].get("label") or requested_role
        send_telegram_message(token, chat_id, f"Role changed to <code>{escape_html(requested_role)}</code> ({escape_html(label)}). Future digest runs will use this role.")
        return True

    if command == "/dashboard":
        if args and args[0].lower() in {"stop", "off", "down"}:
            send_telegram_message(token, chat_id, stop_dashboard_services(config))
            return True
        send_telegram_message(token, chat_id, start_dashboard_services(config))
        return True

    if command in {"/dashboard_stop", "/stop_dashboard"}:
        send_telegram_message(token, chat_id, stop_dashboard_services(config))
        return True

    send_telegram_message(token, chat_id, f"Unknown command: <code>{escape_html(command)}</code>\nUse <code>/help</code>.")
    return True


def process_feedback_updates(
    token: str,
    chat_id: str,
    state: dict[str, Any],
    state_path: Path,
    config: dict[str, Any],
    dry_run: bool = False,
    poll_timeout_seconds: int = 0,
) -> int:
    offset = int(state.get("telegram_update_offset") or 0)
    updates = [] if dry_run else get_telegram_updates(token, offset, timeout_seconds=poll_timeout_seconds)
    processed = 0
    feedback_enabled = bool(config.get("enable_telegram_feedback", True))
    commands_enabled = bool(config.get("enable_telegram_commands", True))
    sent_items = state.get("sent_items", {}) if isinstance(state.get("sent_items"), dict) else {}
    item_feedback = state.get("item_feedback", {}) if isinstance(state.get("item_feedback"), dict) else {}

    for update in updates:
        update_id = int(update.get("update_id") or 0)
        state["telegram_update_offset"] = max(int(state.get("telegram_update_offset") or 0), update_id + 1)
        message_update = update.get("message") or {}
        if message_update and commands_enabled:
            if process_command_message(token, chat_id, state, state_path, config, message_update):
                processed += 1
                continue

        if not feedback_enabled:
            continue

        callback = update.get("callback_query") or {}
        callback_id = str(callback.get("id") or "")
        data = str(callback.get("data") or "")
        message = callback.get("message") or {}
        message_id = int(message.get("message_id") or 0)
        message_chat = message.get("chat") or {}
        callback_chat_id = str(message_chat.get("id") or "")
        if callback_chat_id and callback_chat_id != str(chat_id):
            if callback_id:
                answer_callback_query(token, callback_id, "This digest bot is not configured for this chat.")
            continue
        parts = data.split(":")
        if len(parts) != 3 or parts[0] != "fb":
            continue
        action = CALLBACK_ACTIONS.get(parts[1])
        item_id = parts[2]
        if not action:
            if callback_id:
                answer_callback_query(token, callback_id, "Unknown feedback action.")
            continue
        effective_config = config_for_state(config, state)
        role = normalize_role(str(effective_config.get("role") or DEFAULT_ROLE))
        try:
            role_config = load_role_config(role)
        except Exception:
            role_config = {}
        feedback_path = project_path(effective_config.get("feedback_path"), role_feedback_path(role_config, role))
        item = sent_items.get(item_id)
        if not item:
            item = item_from_callback_message(message)
            if item:
                sent_items[item_id] = item
                state["sent_items"] = sent_items
            else:
                if callback_id:
                    answer_callback_query(token, callback_id, "Feedback item expired. Open the dashboard to rate it.")
                continue
        already_selected = item_feedback.get(item_id) == action or message_selected_feedback_action(message, data) == action
        if already_selected:
            clear_feedback(feedback_path, item, reason="telegram_inline_toggle")
            item_feedback.pop(item_id, None)
            state["item_feedback"] = item_feedback
            processed += 1
            if callback_id:
                answer_callback_query(token, callback_id, "Cleared feedback")
            if callback_chat_id and message_id:
                try:
                    edit_message_reply_markup(token, callback_chat_id, message_id, feedback_keyboard(item_id))
                except RuntimeError:
                    pass
            continue

        record_feedback(feedback_path, item, action)
        item_feedback[item_id] = action
        state["item_feedback"] = item_feedback
        processed += 1
        if callback_id:
            answer_callback_query(token, callback_id, f"Saved feedback: {CALLBACK_LABELS[action]}")
        if callback_chat_id and message_id:
            try:
                edit_message_reply_markup(token, callback_chat_id, message_id, feedback_keyboard(item_id, action))
            except RuntimeError:
                pass

    if processed or updates:
        save_state(state_path, state)
    return processed


def run_once(config: dict[str, Any], dry_run: bool = False, process_updates: bool = True) -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not dry_run and (not token or not chat_id):
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID before running the bot.")

    state_path = project_path(config.get("state_path"), "outputs/daily_research/telegram_state.json")
    state = load_state(state_path)
    if process_updates and not dry_run and token and chat_id:
        process_feedback_updates(token, chat_id, state, state_path, config)
    requested_role = str(state.get("run_requested_role") or "").strip()
    run_state = dict(state)
    if state.get("run_requested"):
        state["run_requested"] = False
        state["run_requested_role"] = ""
        if requested_role:
            run_state["active_role"] = requested_role
        save_state(state_path, state)

    effective_config = config_for_state(config, run_state)
    digest = run_daily_research(effective_config)
    new_items = select_new_items(digest, state, effective_config)
    send_markers = bool(config.get("send_run_markers", True))
    run_role = normalize_role(str(effective_config.get("role") or DEFAULT_ROLE))
    state["last_run_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    state["last_run_role"] = run_role
    state["last_run_date"] = str(digest.get("date") or today_iso())
    state["last_sent_count"] = len(new_items)

    if not new_items and config.get("send_empty_digest"):
        message = format_empty_message(digest)
        if dry_run:
            print(message)
        else:
            send_telegram_message(token, chat_id, message)
        save_state(state_path, state)
        return 0
    if not new_items:
        save_state(state_path, state)
        if process_updates and not dry_run and token and chat_id:
            process_feedback_updates(token, chat_id, state, state_path, config)
        print("Sent 0 new item(s).")
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
        item_id = item_feedback_id(item)
        state.setdefault("sent_items", {})[item_id] = item
        if dry_run:
            print(message)
            print("\n" + "-" * 80 + "\n")
        else:
            send_telegram_message(
                token,
                chat_id,
                message,
                reply_markup=feedback_keyboard(item_id) if config.get("enable_telegram_feedback", True) else None,
            )
            time.sleep(1)
        sent_url = canonical_item_url(item.get("url"))
        state.setdefault("sent_urls", []).append(sent_url)
        state.setdefault("sent_urls_by_role", {}).setdefault(run_role, []).append(sent_url)

    if new_items and send_markers:
        marker = format_end_marker(digest, len(new_items))
        if dry_run:
            print(marker)
            print("\n" + "=" * 80 + "\n")
        else:
            send_telegram_message(token, chat_id, marker)

    save_state(state_path, state)
    if process_updates and not dry_run and token and chat_id:
        process_feedback_updates(token, chat_id, state, state_path, config)
    print(f"Sent {len(new_items)} new item(s).")
    return len(new_items)


def mark_collection_state(config: dict[str, Any], running: bool) -> None:
    state_path = project_path(config.get("state_path"), "outputs/daily_research/telegram_state.json")
    state = load_state(state_path)
    state["collection_running"] = running
    if running:
        state["collection_started_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    else:
        state["collection_finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    save_state(state_path, state)


def run_collection_worker(config: dict[str, Any], dry_run: bool = False) -> None:
    mark_collection_state(config, True)
    try:
        run_once(config, dry_run=dry_run, process_updates=False)
    except (HTTPError, URLError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"[telegram-bot] {exc}", file=sys.stderr)
    finally:
        mark_collection_state(config, False)


def run_loop(config: dict[str, Any], dry_run: bool = False) -> None:
    poll_seconds = max(1, int(config.get("feedback_poll_seconds") or 5))
    state_path = project_path(config.get("state_path"), "outputs/daily_research/telegram_state.json")
    collection_thread: threading.Thread | None = None
    while True:
        if collection_thread and not collection_thread.is_alive():
            collection_thread = None
        state = load_state(state_path)
        deadline = next_due_timestamp(config, state)
        if (state.get("run_requested") or time.time() >= deadline) and collection_thread is None:
            collection_thread = threading.Thread(
                target=run_collection_worker,
                args=(config, dry_run),
                daemon=True,
            )
            collection_thread.start()

        while True:
            if collection_thread and not collection_thread.is_alive():
                collection_thread = None
            state = load_state(state_path)
            deadline = next_due_timestamp(config, state)
            if (state.get("run_requested") or time.time() >= deadline) and collection_thread is None:
                break
            sleep_for = min(poll_seconds, max(1, int(deadline - time.time())))
            poll_started = time.time()
            if not dry_run and (config.get("enable_telegram_feedback", True) or config.get("enable_telegram_commands", True)):
                token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
                chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
                if token and chat_id:
                    state = load_state(state_path)
                    processed_updates = 0
                    try:
                        processed_updates = process_feedback_updates(
                            token,
                            chat_id,
                            state,
                            state_path,
                            config,
                            poll_timeout_seconds=min(20, sleep_for),
                        )
                    except (HTTPError, URLError, OSError, RuntimeError) as exc:
                        print(f"[telegram-bot-feedback] {exc}", file=sys.stderr)
                    if processed_updates:
                        continue
            elapsed = time.time() - poll_started
            time.sleep(max(0, sleep_for - elapsed))
