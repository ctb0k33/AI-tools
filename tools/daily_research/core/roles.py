from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ROLE = "researcher"
ROLE_CONFIG_DIR = PROJECT_ROOT / "tools" / "daily_research" / "config" / "roles"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def normalize_role(value: str | None) -> str:
    return (value or DEFAULT_ROLE).strip().lower().replace(" ", "_") or DEFAULT_ROLE


def role_config_path(role: str | None, explicit_path: str | None = None) -> Path:
    if explicit_path:
        path = Path(explicit_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path
    return ROLE_CONFIG_DIR / f"{normalize_role(role)}.config.json"


def load_role_config(role: str | None = None, explicit_path: str | None = None) -> dict[str, Any]:
    path = role_config_path(role, explicit_path)
    if not path.exists():
        raise FileNotFoundError(f"Role config not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Role config must be a JSON object: {path}")
    payload.setdefault("role", {})
    payload["role"].setdefault("id", normalize_role(role or payload["role"].get("id")))
    payload["role"].setdefault("config_path", str(path))
    return payload


def available_roles() -> list[dict[str, str]]:
    roles: list[dict[str, str]] = []
    if not ROLE_CONFIG_DIR.exists():
        return roles
    for path in sorted(ROLE_CONFIG_DIR.glob("*.config.json")):
        try:
            payload = load_role_config(path.stem.replace(".config", ""), str(path))
        except Exception:
            continue
        role_info = payload.get("role", {}) if isinstance(payload.get("role"), dict) else {}
        role_id = normalize_role(str(role_info.get("id") or path.stem.replace(".config", "")))
        roles.append(
            {
                "id": role_id,
                "label": str(role_info.get("label") or role_id.replace("_", " ").title()),
                "description": str(role_info.get("description") or ""),
            }
        )
    return roles


def role_output_dir(config: dict[str, Any], role: str | None = None) -> str:
    return str(config.get("output_dir") or f"outputs/daily_research/{normalize_role(role)}")


def role_feedback_path(config: dict[str, Any], role: str | None = None) -> str:
    personalization = config.get("personalization", {}) if isinstance(config.get("personalization"), dict) else {}
    return str(personalization.get("feedback_path") or f"outputs/daily_research/feedback/{normalize_role(role)}.json")
