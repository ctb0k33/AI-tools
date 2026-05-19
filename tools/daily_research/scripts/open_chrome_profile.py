from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_chrome_path(explicit_path: str | None = None) -> str:
    if explicit_path:
        return explicit_path

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


def launch_profile(args: argparse.Namespace) -> dict[str, str | int]:
    chrome_path = find_chrome_path(args.chrome_path)
    if not chrome_path:
        raise RuntimeError("Chrome executable not found. Pass --chrome-path explicitly.")

    profile_dir = Path(args.profile_dir).expanduser().resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)

    command = [
        chrome_path,
        f"--remote-debugging-port={args.debug_port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--disable-first-run-ui",
    ]
    if os.environ.get("CHROME_NO_SANDBOX") == "1":
        command.append("--no-sandbox")
    if os.environ.get("CHROME_DISABLE_DEV_SHM", "1") != "0":
        command.append("--disable-dev-shm-usage")
    command.append(args.start_url)
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {
        "pid": process.pid,
        "profile_dir": str(profile_dir),
        "cdp_url": f"http://127.0.0.1:{args.debug_port}",
        "start_url": args.start_url,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open a dedicated Chrome profile with a DevTools endpoint for daily research collection."
    )
    parser.add_argument("--profile-dir", default="profiles/x_profile", help="Chrome user-data-dir to create/open.")
    parser.add_argument("--debug-port", type=int, default=9222, help="Chrome DevTools remote debugging port.")
    parser.add_argument("--start-url", default="https://x.com/home", help="Initial URL to open.")
    parser.add_argument("--chrome-path", help="Optional explicit Chrome executable path.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = launch_profile(args)
    except (OSError, RuntimeError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
