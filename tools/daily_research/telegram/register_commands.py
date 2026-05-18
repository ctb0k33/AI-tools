from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


COMMANDS: list[dict[str, str]] = [
    {"command": "help", "description": "Show available bot commands"},
    {"command": "status", "description": "Show bot status"},
    {"command": "run", "description": "Run collection now"},
    {"command": "interval", "description": "Show or change run interval"},
    {"command": "roles", "description": "List available digest roles"},
    {"command": "role", "description": "Show or switch active role"},
    {"command": "dashboard", "description": "Start and open the local dashboard"},
    {"command": "dashboard_stop", "description": "Stop the local dashboard API/frontend"},
]


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


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Set TELEGRAM_BOT_TOKEN before registering commands.", file=sys.stderr)
        return 1

    telegram_api_request(
        token,
        "setMyCommands",
        {
            "commands": json.dumps(COMMANDS, ensure_ascii=False),
        },
    )
    print("Registered Telegram bot commands:")
    for command in COMMANDS:
        print(f"/{command['command']} - {command['description']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
