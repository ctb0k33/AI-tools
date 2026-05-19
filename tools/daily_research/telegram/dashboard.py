from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any

from ..core.roles import DEFAULT_ROLE, normalize_role
from .common import (
    PROJECT_ROOT,
    escape_html,
    format_interval,
    get_active_role,
    get_interval_minutes,
    project_path,
)


def is_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.6):
            return True
    except OSError:
        return False


def popen_hidden(args: list[str], cwd: Path, stdout_path: Path, stderr_path: Path) -> subprocess.Popen:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_file = stdout_path.open("a", encoding="utf-8")
    stderr_file = stderr_path.open("a", encoding="utf-8")
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    popen_kwargs: dict[str, Any] = {
        "args": args,
        "cwd": cwd,
        "stdout": stdout_file,
        "stderr": stderr_file,
        "stdin": subprocess.DEVNULL,
        "close_fds": False,
        "startupinfo": startupinfo,
        "creationflags": creationflags,
    }
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True
    return subprocess.Popen(**popen_kwargs)


def dashboard_log_dir(config: dict[str, Any]) -> Path:
    dashboard_config = config.get("dashboard", {}) if isinstance(config.get("dashboard"), dict) else {}
    return project_path(str(dashboard_config.get("log_dir") or ""), "outputs/daily_research/dashboard_logs")


def write_pid_file(path: Path, process: subprocess.Popen) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(process.pid), encoding="utf-8")


def read_pid_file(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def stop_pid_tree(pid: int) -> tuple[bool, str]:
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        process = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            startupinfo=startupinfo,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=20,
        )
        output = (process.stdout or process.stderr or "").strip()
        if process.returncode == 0:
            return True, output
        if "not found" in output.lower() or "not running" in output.lower():
            return True, output
        return False, output or f"taskkill exited with {process.returncode}"

    try:
        os.killpg(pid, signal.SIGTERM)
        return True, "sent SIGTERM to process group"
    except ProcessLookupError:
        return True, "process is not running"
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
            return True, "sent SIGTERM to process"
        except ProcessLookupError:
            return True, "process is not running"
        except OSError as exc:
            return False, str(exc)


def stop_dashboard_services(config: dict[str, Any]) -> str:
    log_dir = dashboard_log_dir(config)
    targets = [
        ("Dashboard API", log_dir / "dashboard_api.pid"),
        ("frontend", log_dir / "frontend.pid"),
    ]
    lines = ["<b>Stopping dashboard services</b>"]
    for label, pid_path in targets:
        pid = read_pid_file(pid_path)
        if not pid:
            lines.append(f"- {escape_html(label)}: no PID file found; nothing stopped.")
            continue
        stopped, detail = stop_pid_tree(pid)
        if stopped:
            try:
                pid_path.unlink(missing_ok=True)
            except OSError:
                pass
            lines.append(f"- {escape_html(label)}: stopped PID <code>{pid}</code>.")
        else:
            lines.append(f"- {escape_html(label)}: failed to stop PID <code>{pid}</code>. {escape_html(detail)}")
    lines.append("")
    lines.append("Telegram bot is still running.")
    return "\n".join(lines)


def start_dashboard_services(config: dict[str, Any]) -> str:
    dashboard_config = config.get("dashboard", {}) if isinstance(config.get("dashboard"), dict) else {}
    api_host = str(dashboard_config.get("api_host") or "127.0.0.1")
    api_port = int(dashboard_config.get("api_port") or 8765)
    frontend_host = str(dashboard_config.get("frontend_host") or "127.0.0.1")
    frontend_port = int(dashboard_config.get("frontend_port") or 5173)
    open_browser = bool(dashboard_config.get("open_browser", True))
    log_dir = dashboard_log_dir(config)

    started: list[str] = []
    errors: list[str] = []
    if not is_port_open(api_host, api_port):
        try:
            process = popen_hidden(
                [sys.executable, "-m", "tools.daily_research.dashboard_api", "--host", api_host, "--port", str(api_port)],
                PROJECT_ROOT,
                log_dir / "dashboard_api.out.log",
                log_dir / "dashboard_api.err.log",
            )
            write_pid_file(log_dir / "dashboard_api.pid", process)
            started.append("API")
            time.sleep(1.5)
        except OSError as exc:
            errors.append(f"Dashboard API failed to start: {exc}")

    if not is_port_open(frontend_host, frontend_port):
        npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
        npm_path = shutil.which(npm_cmd)
        if not npm_path:
            errors.append("Frontend failed to start: npm was not found in this runtime.")
        else:
            try:
                process = popen_hidden(
                    [npm_path, "run", "dev", "--", "--host", frontend_host, "--port", str(frontend_port)],
                    PROJECT_ROOT / "frontend",
                    log_dir / "frontend.out.log",
                    log_dir / "frontend.err.log",
                )
                write_pid_file(log_dir / "frontend.pid", process)
                started.append("frontend")
                time.sleep(1.5)
            except OSError as exc:
                errors.append(f"Frontend failed to start: {exc}")

    frontend_display_host = str(
        dashboard_config.get("frontend_display_host")
        or ("127.0.0.1" if frontend_host in {"0.0.0.0", "::"} else frontend_host)
    )
    api_display_host = str(
        dashboard_config.get("api_display_host")
        or ("127.0.0.1" if api_host in {"0.0.0.0", "::"} else api_host)
    )
    frontend_url = str(dashboard_config.get("frontend_url") or f"http://{frontend_display_host}:{frontend_port}/")
    api_url = str(dashboard_config.get("api_url") or f"http://{api_display_host}:{api_port}/api/health")
    if open_browser:
        try:
            webbrowser.open(frontend_url)
        except Exception:
            pass

    status = ", ".join(started) if started else "already running"
    lines = [
        f"<b>Dashboard {escape_html(status)}</b>",
        f"Frontend: {frontend_url}",
        f"API health: {api_url}",
    ]
    if errors:
        lines.extend(
            [
                "",
                "<b>Startup warnings</b>",
                *[f"- {escape_html(error)}" for error in errors],
                f"- Logs: <code>{escape_html(str(log_dir))}</code>",
            ]
        )
    lines.extend(
        [
            "",
            "Note: <code>127.0.0.1</code> only opens on the machine running this bot. From a phone, use the same local network with a LAN host, VPN, or a tunnel.",
        ]
    )
    return "\n".join(lines)


def format_status_message(config: dict[str, Any], state: dict[str, Any]) -> str:
    dashboard_config = config.get("dashboard", {}) if isinstance(config.get("dashboard"), dict) else {}
    api_host = str(dashboard_config.get("api_host") or "127.0.0.1")
    api_port = int(dashboard_config.get("api_port") or 8765)
    frontend_host = str(dashboard_config.get("frontend_host") or "127.0.0.1")
    frontend_port = int(dashboard_config.get("frontend_port") or 5173)
    interval_minutes = get_interval_minutes(config, state)
    active_role = get_active_role(config, state)
    api_status = "running" if is_port_open(api_host, api_port) else "stopped"
    frontend_status = "running" if is_port_open(frontend_host, frontend_port) else "stopped"
    queued_role = str(state.get("run_requested_role") or state.get("active_role") or config.get("role") or DEFAULT_ROLE)
    queued_line = f"yes ({normalize_role(queued_role)})" if state.get("run_requested") else "no"
    collection_line = "yes"
    if state.get("collection_running") and state.get("collection_started_at"):
        collection_line = f"yes, since {state.get('collection_started_at')}"
    elif not state.get("collection_running"):
        collection_line = "no"
    last_run_at = str(state.get("last_run_at") or "never")
    last_run_role = str(state.get("last_run_role") or "-")
    last_run_date = str(state.get("last_run_date") or "-")
    last_sent_count = str(state.get("last_sent_count") or 0)

    return "\n".join(
        [
            "<b>Daily Research Bot Status</b>",
            f"Active role: <code>{escape_html(active_role)}</code>",
            f"Run interval: <code>{escape_html(format_interval(interval_minutes))}</code>",
            f"Immediate run queued: <code>{escape_html(queued_line)}</code>",
            f"Collection running: <code>{escape_html(collection_line)}</code>",
            "",
            f"Last run: <code>{escape_html(last_run_at)}</code>",
            f"Last run role/date: <code>{escape_html(last_run_role)}</code> / <code>{escape_html(last_run_date)}</code>",
            f"Last sent posts: <code>{escape_html(last_sent_count)}</code>",
            "",
            f"Dashboard API: <code>{escape_html(api_status)}</code> ({api_host}:{api_port})",
            f"Frontend: <code>{escape_html(frontend_status)}</code> ({frontend_host}:{frontend_port})",
        ]
    )
