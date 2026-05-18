from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..core.feedback import build_preference_model, clear_feedback, load_feedback_store, record_feedback
from ..core.roles import DEFAULT_ROLE, available_roles, load_role_config, normalize_role, role_feedback_path, role_output_dir


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = "tools/daily_research/config/selected_x_profiles.config.json"
DEFAULT_OUTPUT_DIR = "outputs/daily_research"
DEFAULT_PROFILE_DIR = "profiles/ctb0k33"
DEFAULT_FEEDBACK_PATH = "outputs/daily_research/feedback_store.json"
DEFAULT_TIMEZONE = "Asia/Saigon"
COLLECTION_LOCK = threading.Lock()


def today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def project_path(value: str | None, fallback: str) -> Path:
    raw = value or fallback
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def safe_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path.resolve())


def load_digest(output_dir: Path, target_date: str | None = None) -> tuple[dict[str, Any], Path]:
    if target_date:
        digest_path = output_dir / target_date / "daily_research_digest.json"
    else:
        dated_dirs = sorted((p for p in output_dir.glob("*") if p.is_dir()), reverse=True)
        digest_path = next(
            (folder / "daily_research_digest.json" for folder in dated_dirs if (folder / "daily_research_digest.json").exists()),
            output_dir / today_iso() / "daily_research_digest.json",
        )
    if not digest_path.exists():
        raise FileNotFoundError(f"Digest not found: {safe_relative(digest_path)}")
    return json.loads(digest_path.read_text(encoding="utf-8")), digest_path


def role_defaults(role: str | None) -> dict[str, str]:
    role_id = normalize_role(role)
    try:
        config = load_role_config(role_id)
    except Exception:
        config = {}
    return {
        "role": role_id,
        "output_dir": role_output_dir(config, role_id),
        "feedback_path": role_feedback_path(config, role_id),
    }


def fail_on_blocking_collection_warnings(digest: dict[str, Any]) -> None:
    warnings = [str(item) for item in digest.get("warnings", [])]
    blocking_patterns = [
        "Could not launch any browser with the persistent X profile",
        "Could not launch Chrome with the persistent X profile",
        "X profile is not signed in",
    ]
    for warning in warnings:
        if any(pattern in warning for pattern in blocking_patterns):
            first_line = warning.splitlines()[0].strip()
            raise RuntimeError(first_line)


def run_collection(payload: dict[str, Any]) -> dict[str, Any]:
    target_date = str(payload.get("date") or today_iso())
    timezone = str(payload.get("timezone") or DEFAULT_TIMEZONE)
    role = normalize_role(str(payload.get("role") or DEFAULT_ROLE))
    defaults = role_defaults(role)
    profile_dir = project_path(payload.get("profileDir"), DEFAULT_PROFILE_DIR)
    config_value = payload.get("config")
    config_path = project_path(config_value, DEFAULT_CONFIG) if config_value else None
    output_dir = project_path(payload.get("outputDir"), defaults["output_dir"])
    feedback_path = project_path(payload.get("feedbackPath"), defaults["feedback_path"])
    timeout_seconds = int(payload.get("processTimeoutSeconds") or 1200)

    command = [
        sys.executable,
        "-m",
        "tools.daily_research.daily_research_tool",
        "--date",
        target_date,
        "--timezone",
        timezone,
        "--profile-dir",
        str(profile_dir),
        "--role",
        role,
        "--output-dir",
        str(output_dir),
        "--feedback-path",
        str(feedback_path),
        "--x-backend",
        str(payload.get("xBackend") or "playwright"),
    ]
    if config_path:
        command.extend(["--config", str(config_path)])

    if payload.get("headless"):
        command.append("--headless")
    if payload.get("skipX"):
        command.append("--skip-x")
    if payload.get("skipEthresearch"):
        command.append("--skip-ethresearch")
    if payload.get("includeXSearch"):
        command.append("--include-x-search")

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    process = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )

    if process.returncode != 0:
        error_text = process.stderr.strip() or process.stdout.strip() or f"daily_research_tool exited with {process.returncode}"
        raise RuntimeError(error_text)

    digest, digest_path = load_digest(output_dir, target_date)
    fail_on_blocking_collection_warnings(digest)
    return {
        "digest": digest,
        "paths": {
            "json": safe_relative(digest_path),
            "markdown": safe_relative(digest_path.with_suffix(".md")),
            "outputDir": safe_relative(digest_path.parent),
        },
        "command": " ".join(command),
        "stdout": process.stdout.strip(),
    }


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "DailyResearchDashboardAPI/0.1"

    def do_OPTIONS(self) -> None:
        self.send_json({}, HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:
        route = urlparse(self.path)
        if route.path == "/api/health":
            self.send_json({"ok": True})
            return
        if route.path == "/api/roles":
            self.send_json({"roles": available_roles()})
            return
        if route.path == "/api/latest":
            self.handle_latest(route.query)
            return
        if route.path == "/api/feedback":
            self.handle_feedback_get(route.query)
            return
        self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        route_path = urlparse(self.path).path
        if route_path == "/api/feedback":
            self.handle_feedback_post()
            return
        if route_path != "/api/collect":
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        if not COLLECTION_LOCK.acquire(blocking=False):
            self.send_json({"error": "A collection job is already running."}, HTTPStatus.CONFLICT)
            return
        try:
            payload = self.read_json()
            result = run_collection(payload)
            self.send_json(result)
        except subprocess.TimeoutExpired as exc:
            self.send_json({"error": f"Collection timed out after {exc.timeout} seconds."}, HTTPStatus.GATEWAY_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 - surface local tool errors to UI.
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            COLLECTION_LOCK.release()

    def handle_latest(self, query: str) -> None:
        params = parse_qs(query)
        target_date = params.get("date", [None])[0] or None
        role = normalize_role(params.get("role", [DEFAULT_ROLE])[0])
        defaults = role_defaults(role)
        output_dir = project_path(params.get("outputDir", [None])[0], defaults["output_dir"])
        try:
            try:
                digest, digest_path = load_digest(output_dir, target_date)
            except Exception:
                legacy_output_dir = project_path(None, DEFAULT_OUTPUT_DIR)
                if params.get("outputDir", [None])[0] or output_dir == legacy_output_dir or role != DEFAULT_ROLE:
                    raise
                digest, digest_path = load_digest(legacy_output_dir, target_date)
            self.send_json(
                {
                    "digest": digest,
                    "paths": {
                        "json": safe_relative(digest_path),
                        "markdown": safe_relative(digest_path.with_suffix(".md")),
                        "outputDir": safe_relative(digest_path.parent),
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)

    def handle_feedback_get(self, query: str) -> None:
        params = parse_qs(query)
        role = normalize_role(params.get("role", [DEFAULT_ROLE])[0])
        defaults = role_defaults(role)
        feedback_path = project_path(params.get("feedbackPath", [None])[0], defaults["feedback_path"])
        store = load_feedback_store(feedback_path)
        self.send_json(
            {
                "feedback": {
                    "path": safe_relative(feedback_path),
                    "model": build_preference_model(store),
                    "events": store.get("events", [])[-50:],
                }
            }
        )

    def handle_feedback_post(self) -> None:
        try:
            payload = self.read_json()
            item = payload.get("item") or {}
            action = str(payload.get("action") or "")
            reason = str(payload.get("reason") or "")
            role = normalize_role(str(payload.get("role") or DEFAULT_ROLE))
            defaults = role_defaults(role)
            feedback_path = project_path(payload.get("feedbackPath"), defaults["feedback_path"])
            if action == "clear":
                result = clear_feedback(feedback_path, item, reason)
            else:
                result = record_feedback(feedback_path, item, action, reason)
            self.send_json(
                {
                    "ok": True,
                    "feedback": {
                        "path": safe_relative(feedback_path),
                        **result,
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = b"" if status == HTTPStatus.NO_CONTENT else json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[dashboard-api] {self.address_string()} - {format % args}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local API bridge for the daily research dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Daily research dashboard API listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard API.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
