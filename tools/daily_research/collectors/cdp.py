from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from ..core.research import (
    QuerySpec,
    ResearchItem,
    build_x_item_from_raw_tweet,
    dedupe_items,
    filter_items_by_local_date,
    get_last_used_chrome_profile,
    get_system_chrome_user_data_dir,
    inspect_x_login_cookies,
)

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
        preference_model: dict[str, Any] | None = None,
        quality_terms: dict[str, Any] | None = None,
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
        self.preference_model = preference_model or {}
        self.quality_terms = quality_terms or build_quality_terms({})

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
            preference_model=self.preference_model,
            quality_terms=self.quality_terms,
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
