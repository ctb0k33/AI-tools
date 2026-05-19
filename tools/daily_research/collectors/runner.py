from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from ..core.research import *
from .cdp import ChromeCDPXCollector
from ..core.feedback import build_preference_model, load_feedback_store, score_item_with_preferences
from ..reports.digest import build_payload, write_outputs
from ..core.roles import DEFAULT_ROLE, normalize_role, role_feedback_path, role_output_dir

class XCollector:
    def __init__(
        self,
        profile_dir: Path,
        max_items_per_query: int,
        timeout_ms: int,
        headless: bool,
        slow_mo: int,
        keyword_categories: dict[str, list[str]],
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
        self.timeout_ms = timeout_ms
        self.headless = headless
        self.slow_mo = slow_mo
        self.keyword_categories = keyword_categories
        self.min_technical_score = min_technical_score
        self.date_lookback_days = max(0, date_lookback_days)
        self.include_replies = include_replies
        self.include_quotes = include_quotes
        self.include_home = include_home
        self.max_home_items = max_home_items
        self.profile_handles = normalize_x_handles(profile_handles)
        self.max_items_per_profile = max_items_per_profile
        self.include_following = include_following
        self.following_owner = following_owner.strip().lstrip("@")
        self.max_following_profiles = max_following_profiles
        self.max_items_per_following_profile = max_items_per_following_profile
        self.preference_model = preference_model or {}
        self.quality_terms = quality_terms or build_quality_terms({})
        self._seen_x_item_keys: set[str] = set()
        self._hydrated_payload_cache: dict[str, dict[str, Any]] = {}

    def collect(
        self,
        query_specs: list[QuerySpec],
        target_day: date,
        tz: tzinfo,
    ) -> tuple[list[ResearchItem], list[str]]:
        warnings: list[str] = []
        items: list[ResearchItem] = []
        self._seen_x_item_keys = set()
        self._hydrated_payload_cache = {}
        if not query_specs and not self.include_home and not self.profile_handles and not self.include_following:
            return items, warnings

        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            return [], [f"Playwright import failed: {exc}"]

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        is_signed_in, login_message = inspect_x_login_cookies(self.profile_dir)
        if is_signed_in is False:
            warnings.append(
                f"{login_message} Open the profile once with: "
                f"python -m tools.daily_research.open_chrome_profile --profile-dir \"{self.profile_dir}\" "
                "--start-url https://x.com/home"
            )
        elif is_signed_in is None:
            warnings.append(login_message)
        if os.environ.get("DAILY_RESEARCH_UNLOCK_STALE_PROFILE", "").lower() in {"1", "true", "yes"}:
            warnings.extend(unlock_stale_chromium_profile(self.profile_dir))

        with sync_playwright() as playwright:
            context = None
            try:
                prefer_bundled_chromium = os.environ.get("DAILY_RESEARCH_PREFER_BUNDLED_CHROMIUM", "").lower() in {
                    "1",
                    "true",
                    "yes",
                }
                launch_kwargs = {
                    "user_data_dir": str(self.profile_dir),
                    "headless": self.headless,
                    "slow_mo": self.slow_mo,
                    "viewport": {"width": 1400, "height": 950},
                    "args": [
                        "--disable-blink-features=AutomationControlled",
                        "--disable-session-crashed-bubble",
                        "--no-first-run",
                    ],
                }
                if prefer_bundled_chromium:
                    context = playwright.chromium.launch_persistent_context(
                        **launch_kwargs,
                    )
                else:
                    try:
                        context = playwright.chromium.launch_persistent_context(
                            channel="chrome",
                            **launch_kwargs,
                        )
                    except Exception as exc:
                        warnings.append(
                            "Chrome channel failed with the persistent X profile; "
                            f"falling back to bundled Chromium. Original error: {exc}"
                        )
                        try:
                            context = playwright.chromium.launch_persistent_context(
                                **launch_kwargs,
                            )
                        except Exception as fallback_exc:
                            warnings.append(
                                "Could not launch any browser with the persistent X profile. "
                                f"Close any Chrome/Chromium window using '{self.profile_dir}', then retry. "
                                f"Fallback error: {fallback_exc}"
                            )
                            return [], warnings

                page = context.new_page()
                self._close_restored_pages(context, keep_page=page)
                for spec in query_specs:
                    url = build_x_search_url(spec.query, target_day, include_date_filters=False)
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                        page.wait_for_timeout(3500)
                        if self._looks_blocked_or_logged_out(page):
                            warnings.append(
                                f"X query '{spec.name}' may need a signed-in profile or was rate-limited."
                            )
                        try:
                            page.wait_for_selector("article[data-testid='tweet']", timeout=8000)
                        except PlaywrightTimeoutError:
                            warnings.append(f"No visible tweets found for X query '{spec.name}'.")
                            continue
                        items.extend(self._extract_tweets(page, spec))
                    except Exception as exc:
                        warnings.append(f"X query '{spec.name}' failed: {exc}")
                for handle in self.profile_handles:
                    spec = QuerySpec(name="Configured Profiles", query=f"https://x.com/{handle}", category="")
                    try:
                        page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded", timeout=self.timeout_ms)
                        page.wait_for_timeout(2500)
                        if self._looks_blocked_or_logged_out(page):
                            warnings.append(f"X configured profile '@{handle}' may be rate-limited or unavailable.")
                        try:
                            page.wait_for_selector("article[data-testid='tweet']", timeout=6000)
                        except PlaywrightTimeoutError:
                            continue
                        items.extend(
                            self._extract_tweets(
                                page,
                                spec,
                                max_items=self.max_items_per_profile,
                                profile_handle=handle,
                                scroll_rounds=2,
                            )
                        )
                    except Exception as exc:
                        warnings.append(f"X configured profile '@{handle}' failed: {exc}")
                if self.include_home:
                    spec = QuerySpec(name="Home Timeline", query="https://x.com/home", category="")
                    try:
                        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=self.timeout_ms)
                        page.wait_for_timeout(3500)
                        if self._looks_blocked_or_logged_out(page):
                            warnings.append("X home timeline may need a signed-in profile or was rate-limited.")
                        try:
                            page.wait_for_selector("article[data-testid='tweet']", timeout=8000)
                        except PlaywrightTimeoutError:
                            warnings.append("No visible tweets found on X home timeline.")
                        else:
                            items.extend(self._extract_tweets(page, spec, max_items=self.max_home_items))
                    except Exception as exc:
                        warnings.append(f"X home timeline failed: {exc}")
                if self.include_following:
                    try:
                        handles = self._collect_following_handles(page, self.following_owner, warnings)
                        if not handles:
                            warnings.append(f"No followed profiles found for @{self.following_owner}.")
                        for handle in handles:
                            spec = QuerySpec(name="Following Profiles", query=f"https://x.com/{handle}", category="")
                            try:
                                page.goto(
                                    f"https://x.com/{handle}",
                                    wait_until="domcontentloaded",
                                    timeout=self.timeout_ms,
                                )
                                page.wait_for_timeout(2500)
                                try:
                                    page.wait_for_selector("article[data-testid='tweet']", timeout=6000)
                                except PlaywrightTimeoutError:
                                    continue
                                items.extend(
                                    self._extract_tweets(
                                        page,
                                        spec,
                                        max_items=self.max_items_per_following_profile,
                                        profile_handle=handle,
                                        scroll_rounds=2,
                                    )
                                )
                            except Exception as exc:
                                warnings.append(f"X followed profile '@{handle}' failed: {exc}")
                    except Exception as exc:
                        warnings.append(f"X following collection failed: {exc}")
            finally:
                if context is not None:
                    context.close()

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

    def _close_restored_pages(self, context: Any, keep_page: Any) -> None:
        for existing_page in list(context.pages):
            if existing_page == keep_page:
                continue
            try:
                existing_page.close()
            except Exception:
                pass

    def _looks_blocked_or_logged_out(self, page: Any) -> bool:
        try:
            text = page.locator("body").inner_text(timeout=2500).lower()
        except Exception:
            return False
        markers = [
            "sign in to x",
            "log in to x",
            "something went wrong",
            "rate limit",
            "unusual login activity",
            "verify you are human",
        ]
        return any(marker in text for marker in markers)

    def _collect_following_handles(self, page: Any, owner: str, warnings: list[str]) -> list[str]:
        if not owner:
            warnings.append("X following owner is empty; skipping followed profile collection.")
            return []

        handles: dict[str, str] = {}
        page.goto(f"https://x.com/{owner}/following", wait_until="domcontentloaded", timeout=self.timeout_ms)
        page.wait_for_timeout(3500)
        if self._looks_blocked_or_logged_out(page):
            warnings.append("X following page may need a signed-in profile or was rate-limited.")
        try:
            page.wait_for_selector("[data-testid='UserCell']", timeout=10000)
        except Exception:
            return []

        max_scrolls = max(6, min(40, self.max_following_profiles // 3 + 6))
        for _ in range(max_scrolls):
            cells = page.locator("[data-testid='UserCell']")
            count = cells.count()
            for index in range(count):
                try:
                    raw_links = cells.nth(index).locator("a[href]").evaluate_all(
                        "(els) => els.map((a) => a.getAttribute('href') || '').filter(Boolean)"
                    )
                except Exception:
                    raw_links = []
                for href in raw_links:
                    handle = extract_x_handle_from_href(str(href))
                    if handle and not same_x_handle(handle, owner):
                        handles[handle.lower()] = handle
                        break
                if len(handles) >= self.max_following_profiles:
                    return list(handles.values())
            try:
                page.mouse.wheel(0, 1800)
                page.wait_for_timeout(1200)
            except Exception:
                break
        return list(handles.values())

    def _extract_tweets(
        self,
        page: Any,
        spec: QuerySpec,
        max_items: int | None = None,
        profile_handle: str = "",
        scroll_rounds: int = 6,
    ) -> list[ResearchItem]:
        items_by_key: dict[str, ResearchItem] = {}
        item_limit = max_items or self.max_items_per_query
        for _ in range(scroll_rounds):
            articles = page.locator("article[data-testid='tweet']")
            count = articles.count()
            for index in range(count):
                article = articles.nth(index)
                raw = self._extract_tweet_payload(article)
                if profile_handle:
                    raw["source_profile"] = profile_handle
                item = build_x_item_from_raw_tweet(raw, spec, self.keyword_categories, backend="playwright")
                if item is None:
                    continue
                if profile_handle and not same_x_handle(item.author, profile_handle):
                    continue
                key = canonical_url(item.url) or short_hash(item.text)
                if key in items_by_key or key in self._seen_x_item_keys:
                    continue
                item = self._hydrate_if_truncated(page, item, spec, profile_handle)
                key = canonical_url(item.url) or key
                if key in items_by_key:
                    continue
                if key in self._seen_x_item_keys:
                    continue
                items_by_key[key] = item
                self._seen_x_item_keys.add(key)
                if len(items_by_key) >= item_limit:
                    return list(items_by_key.values())
            try:
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(1200)
            except Exception:
                break
        return list(items_by_key.values())

    def _hydrate_if_truncated(
        self,
        page: Any,
        item: ResearchItem,
        spec: QuerySpec,
        profile_handle: str,
    ) -> ResearchItem:
        if not item.url or not item.raw.get("looks_truncated"):
            return item
        status_key = canonical_url(item.url)
        raw = self._hydrated_payload_cache.get(status_key)
        if raw is None:
            raw = self._extract_status_tweet_payload(page, item.url)
            if raw:
                self._hydrated_payload_cache[status_key] = raw
        if not raw:
            return item
        if profile_handle:
            raw["source_profile"] = profile_handle
        hydrated = build_x_item_from_raw_tweet(raw, spec, self.keyword_categories, backend="playwright-status")
        if hydrated is None:
            return item
        if profile_handle and not same_x_handle(hydrated.author, profile_handle):
            return item
        if len(hydrated.text) <= len(item.text):
            return item
        hydrated.raw["hydrated_from_status"] = True
        return hydrated

    def _extract_status_tweet_payload(self, page: Any, status_url: str) -> dict[str, Any]:
        detail_page = None
        try:
            detail_page = page.context.new_page()
            detail_page.goto(status_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            detail_page.wait_for_timeout(2500)
            detail_page.wait_for_selector("article[data-testid='tweet']", timeout=7000)
            articles = detail_page.locator("article[data-testid='tweet']")
            canonical_status = canonical_url(status_url)
            count = articles.count()
            fallback: dict[str, Any] = {}
            for index in range(count):
                raw = self._extract_tweet_payload(articles.nth(index))
                links = [canonical_url(str(link)) for link in raw.get("links", [])]
                if not fallback:
                    fallback = raw
                if canonical_status in links:
                    return raw
            return fallback
        except Exception:
            return {}
        finally:
            if detail_page is not None:
                try:
                    detail_page.close()
                except Exception:
                    pass

    def _extract_tweet_payload(self, article: Any) -> dict[str, Any]:
        try:
            return dict(
                article.evaluate(
                    """
                    (article) => {
                      const links = Array.from(article.querySelectorAll('a[href]'))
                        .map((a) => a.href)
                        .filter(Boolean);
                      const tweetTexts = Array.from(article.querySelectorAll('[data-testid="tweetText"]'))
                        .map((el) => el.innerText || '')
                        .filter(Boolean);
                      const time = article.querySelector('time')?.getAttribute('datetime') || '';
                      const socialContext = article.querySelector('[data-testid="socialContext"]')?.innerText || '';
                      return {
                        article_text: article.innerText || '',
                        tweet_text: tweetTexts[0] || '',
                        tweet_texts: tweetTexts,
                        links,
                        time,
                        social_context: socialContext
                      };
                    }
                    """
                )
            )
        except Exception:
            text = self._safe_inner_text(article)
            return {
                "article_text": text,
                "tweet_text": text,
                "tweet_texts": [text] if text else [],
                "links": self._extract_links(article),
                "time": self._safe_attr(article.locator("time").first, "datetime"),
            }

    def _extract_links(self, article: Any) -> list[str]:
        try:
            return article.locator("a").evaluate_all("(els) => els.map((a) => a.href).filter(Boolean)")
        except Exception:
            return []

    def _extract_author(self, status_url: str, text: str) -> str:
        return extract_x_author(status_url, text)

    def _safe_inner_text(self, locator: Any) -> str:
        try:
            return locator.inner_text(timeout=1500).strip()
        except Exception:
            return ""

    def _safe_attr(self, locator: Any, attr: str) -> str:
        try:
            return locator.get_attribute(attr, timeout=1000) or ""
        except Exception:
            return ""

    def _clean_tweet_text(self, text: str) -> str:
        return clean_tweet_text(text)


class EthResearchCollector:
    def __init__(
        self,
        endpoints: list[str],
        max_items: int,
        timeout_seconds: int,
        keyword_categories: dict[str, list[str]],
        date_lookback_days: int = 0,
    ) -> None:
        self.endpoints = endpoints
        self.max_items = max_items
        self.timeout_seconds = timeout_seconds
        self.keyword_categories = keyword_categories
        self.date_lookback_days = max(0, date_lookback_days)

    def collect(self, target_day: date, tz: tzinfo) -> tuple[list[ResearchItem], list[str]]:
        warnings: list[str] = []
        topics: dict[int, dict[str, Any]] = {}

        for endpoint in self.endpoints:
            try:
                payload = self._fetch_json(endpoint)
            except Exception as exc:
                warnings.append(f"ethresear.ch endpoint failed ({endpoint}): {exc}")
                continue
            for topic in payload.get("topic_list", {}).get("topics", []):
                topic_id = topic.get("id")
                if isinstance(topic_id, int):
                    topics[topic_id] = topic

        items: list[ResearchItem] = []
        for topic in topics.values():
            created_at = str(topic.get("created_at", ""))
            if not is_in_local_date_window(created_at, target_day, tz, self.date_lookback_days):
                continue
            title = str(topic.get("title", "Untitled ethresear.ch post"))
            slug = str(topic.get("slug", ""))
            topic_id = topic.get("id")
            url = f"{ETHRESEARCH_BASE_URL}/t/{slug}/{topic_id}" if slug and topic_id else ETHRESEARCH_BASE_URL
            tags = [str(tag) for tag in topic.get("tags", [])]
            excerpt = strip_html(str(topic.get("excerpt", "")))
            category_tags = classify_text(" ".join([title, excerpt, " ".join(tags)]), self.keyword_categories)
            author = self._extract_author(topic)
            items.append(
                ResearchItem(
                    source="ethresear.ch",
                    section="New research posts",
                    category=", ".join(category_tags) if category_tags else "Ethereum Research",
                    title=title,
                    url=url,
                    author=author,
                    published_at=created_at,
                    text=excerpt,
                    tags=dedupe_preserve_order(tags + category_tags),
                    score=len(category_tags) + len(tags),
                    raw={
                        "id": topic_id,
                        "posts_count": topic.get("posts_count"),
                        "reply_count": topic.get("reply_count"),
                        "views": topic.get("views"),
                    },
                )
            )

        items.sort(key=lambda item: item.published_at, reverse=True)
        return items[: self.max_items], warnings

    def _fetch_json(self, url: str) -> dict[str, Any]:
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/147.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://ethresear.ch/",
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _extract_author(self, topic: dict[str, Any]) -> str:
        posters = topic.get("posters") or []
        for poster in posters:
            description = str(poster.get("description", "")).lower()
            if "original poster" in description or "original" in description:
                user = poster.get("user") or {}
                username = user.get("username")
                if username:
                    return f"@{username}"
        return ""


def run(args: argparse.Namespace) -> dict[str, Any]:
    tz = resolve_timezone(args.timezone)
    target_day = parse_target_date(args.date, tz)
    role_id = normalize_role(args.role)
    config = load_config(args.config, role=role_id, role_config=args.role_config)
    role_info = config.get("role", {}) if isinstance(config.get("role"), dict) else {}
    role_id = normalize_role(str(role_info.get("id") or role_id))
    keyword_categories = config.get("keyword_categories", {})
    date_filter_config = config.get("date_filter", {})
    date_lookback_days = args.date_lookback_days
    if date_lookback_days is None:
        date_lookback_days = int(date_filter_config.get("lookback_days", 1))
    date_lookback_days = max(0, date_lookback_days)
    quality_config = config.get("x_quality_filter", {})
    min_technical_score = args.x_min_technical_score
    if min_technical_score is None:
        min_technical_score = int(quality_config.get("min_technical_score", 4))
    include_replies = bool(args.include_replies or quality_config.get("include_replies", False))
    include_quotes = bool(args.include_quotes or quality_config.get("include_quotes", False))
    quality_terms = build_quality_terms(config)
    personalization_config = config.get("personalization", {})
    personalization_enabled = bool(personalization_config.get("enabled", True)) and not args.disable_personalization
    preference_model: dict[str, Any] = {}
    feedback_path = Path(args.feedback_path or role_feedback_path(config, role_id))
    if personalization_enabled:
        preference_model = build_preference_model(load_feedback_store(feedback_path.expanduser().resolve()))
    home_config = config.get("x_home", {})
    include_home = bool(home_config.get("enabled", True)) and not args.skip_x_home
    max_home_items = int(args.max_x_home_items or home_config.get("max_items", 80))
    search_config = config.get("x_search", {})
    include_config_search = bool(args.include_x_search or search_config.get("enabled", False))
    profiles_config = config.get("x_profiles", {})
    configured_profile_values = list(profiles_config.get("handles", [])) + list(args.x_profile or [])
    configured_profile_handles = normalize_x_handles(configured_profile_values)
    include_configured_profiles = bool(profiles_config.get("enabled", False)) and not args.skip_x_profiles
    if args.x_profile:
        include_configured_profiles = True
    if not include_configured_profiles:
        configured_profile_handles = []
    max_items_per_configured_profile = int(
        args.max_x_profile_items or profiles_config.get("max_items_per_profile", 4)
    )
    following_config = config.get("x_following", {})
    include_following = bool(following_config.get("enabled", False)) and not args.skip_x_following
    following_owner = str(args.following_owner or following_config.get("owner", ""))
    max_following_profiles = int(args.max_following_profiles or following_config.get("max_profiles", 80))
    max_items_per_following_profile = int(
        args.max_following_items_per_profile or following_config.get("max_items_per_profile", 4)
    )

    all_items: list[ResearchItem] = []
    warnings: list[str] = []

    if not args.skip_x:
        if args.x_backend == "chrome-cdp":
            profile_dir = (
                get_system_chrome_user_data_dir()
                if args.use_system_chrome_profile
                else Path(args.profile_dir).expanduser().resolve()
            )
            chrome_profile_directory = args.chrome_profile_directory
            if args.use_system_chrome_profile and not chrome_profile_directory:
                chrome_profile_directory = get_last_used_chrome_profile(profile_dir)
            x_collector = ChromeCDPXCollector(
                profile_dir=profile_dir,
                max_items_per_query=args.max_x_items,
                timeout_ms=args.timeout_ms,
                headless=args.headless,
                keyword_categories=keyword_categories,
                chrome_path=args.chrome_path,
                debug_port=args.chrome_debug_port,
                chrome_profile_directory=chrome_profile_directory,
                attach_cdp_url=args.attach_cdp_url,
                min_technical_score=min_technical_score,
                date_lookback_days=date_lookback_days,
                include_replies=include_replies,
                include_quotes=include_quotes,
                include_home=include_home,
                max_home_items=max_home_items,
                profile_handles=[],
                max_items_per_profile=max_items_per_configured_profile,
                include_following=False,
                following_owner=following_owner,
                max_following_profiles=max_following_profiles,
                max_items_per_following_profile=max_items_per_following_profile,
                preference_model=preference_model,
                quality_terms=quality_terms,
            )
        else:
            x_collector = XCollector(
                profile_dir=Path(args.profile_dir).expanduser().resolve(),
                max_items_per_query=args.max_x_items,
                timeout_ms=args.timeout_ms,
                headless=args.headless,
                slow_mo=args.slow_mo,
                keyword_categories=keyword_categories,
                min_technical_score=min_technical_score,
                date_lookback_days=date_lookback_days,
                include_replies=include_replies,
                include_quotes=include_quotes,
                include_home=include_home,
                max_home_items=max_home_items,
                profile_handles=configured_profile_handles,
                max_items_per_profile=max_items_per_configured_profile,
                include_following=include_following,
                following_owner=following_owner,
                max_following_profiles=max_following_profiles,
                max_items_per_following_profile=max_items_per_following_profile,
                preference_model=preference_model,
                quality_terms=quality_terms,
            )
        query_specs = parse_query_specs(
            config,
            args.x_query,
            include_config_queries=include_config_search,
        )
        x_items, x_warnings = x_collector.collect(query_specs, target_day, tz)
        all_items.extend(x_items)
        warnings.extend(x_warnings)

    if not args.skip_ethresearch:
        eth_collector = EthResearchCollector(
            endpoints=list(config.get("ethresearch_endpoints", [])),
            max_items=args.max_ethresearch_items,
            timeout_seconds=max(5, args.timeout_ms // 1000),
            keyword_categories=keyword_categories,
            date_lookback_days=date_lookback_days,
        )
        eth_items, eth_warnings = eth_collector.collect(target_day, tz)
        all_items.extend(eth_items)
        warnings.extend(eth_warnings)

    all_items = dedupe_items(all_items)
    payload = build_payload(target_day, args.timezone, all_items, warnings, config, date_lookback_days)
    payload["role"] = {
        "id": role_id,
        "label": str(role_info.get("label") or role_id.replace("_", " ").title()),
        "description": str(role_info.get("description") or ""),
    }
    payload["personalization"] = {
        "enabled": personalization_enabled,
        "feedback_path": str(feedback_path),
        "feedback_count": int(preference_model.get("feedback_count", 0) or 0),
    }
    output_dir = Path(args.output_dir or role_output_dir(config, role_id)).expanduser().resolve()
    paths = write_outputs(payload, output_dir)
    return {"paths": paths, "stats": payload["stats"], "warnings": warnings}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect same-day DeFi/core protocol signals from X and new posts from ethresear.ch."
    )
    parser.add_argument("--date", help="Target date in YYYY-MM-DD. Default: today in --timezone.")
    parser.add_argument(
        "--date-lookback-days",
        type=int,
        default=None,
        help="Also include this many local days before --date. Config default: 1.",
    )
    parser.add_argument("--timezone", default="Asia/Saigon", help="Timezone used for date filtering.")
    parser.add_argument("--profile-dir", default="profiles/x_profile", help="Persistent Chrome profile for X.")
    parser.add_argument(
        "--role",
        default=DEFAULT_ROLE,
        help="Role profile to use, e.g. researcher, bd, marketing, operations.",
    )
    parser.add_argument("--role-config", help="Explicit role config JSON path. Overrides --role lookup.")
    parser.add_argument("--output-dir", default=None, help="Output root directory. Default comes from the selected role.")
    parser.add_argument("--config", help="Optional JSON config overriding queries and keyword categories.")
    parser.add_argument(
        "--feedback-path",
        default=None,
        help="Path to the user feedback store used for personalized ranking.",
    )
    parser.add_argument(
        "--disable-personalization",
        action="store_true",
        help="Ignore feedback weights and rank only by technical score.",
    )
    parser.add_argument(
        "--x-query",
        action="append",
        help="Extra X query. Use 'Name::query' to name the section. Can be repeated.",
    )
    parser.add_argument(
        "--include-x-search",
        action="store_true",
        help="Include configured X search sections. Default source is following + home.",
    )
    parser.add_argument("--max-x-items", type=int, default=40, help="Max X items per query section.")
    parser.add_argument(
        "--x-min-technical-score",
        type=int,
        default=None,
        help="Minimum technical score for X items. Default comes from config, usually 4.",
    )
    parser.add_argument("--include-replies", action="store_true", help="Include X replies/comments.")
    parser.add_argument("--include-quotes", action="store_true", help="Include X quote/commentary posts.")
    parser.add_argument("--skip-x-home", action="store_true", help="Skip X home timeline collection.")
    parser.add_argument("--max-x-home-items", type=int, help="Max X home timeline items before filtering.")
    parser.add_argument("--x-profile", action="append", help="Extra X profile URL or handle to scan. Can be repeated.")
    parser.add_argument("--skip-x-profiles", action="store_true", help="Skip configured X profile collection.")
    parser.add_argument("--max-x-profile-items", type=int, help="Max recent posts per configured profile.")
    parser.add_argument("--skip-x-following", action="store_true", help="Skip followed profile collection.")
    parser.add_argument("--following-owner", help="X account whose following list should be used, e.g. your X handle.")
    parser.add_argument("--max-following-profiles", type=int, help="Max followed profiles to scan.")
    parser.add_argument(
        "--max-following-items-per-profile",
        type=int,
        help="Max recent posts to collect from each followed profile before filtering.",
    )
    parser.add_argument("--max-ethresearch-items", type=int, default=50, help="Max ethresear.ch items.")
    parser.add_argument("--timeout-ms", type=int, default=45000, help="Browser/network timeout.")
    parser.add_argument(
        "--x-backend",
        choices=["playwright", "chrome-cdp"],
        default="playwright",
        help="X collection backend. Default: playwright.",
    )
    parser.add_argument("--chrome-path", help="Chrome executable path for --x-backend chrome-cdp.")
    parser.add_argument(
        "--use-system-chrome-profile",
        action="store_true",
        help="Use the Windows Chrome user data dir instead of --profile-dir for chrome-cdp.",
    )
    parser.add_argument(
        "--chrome-profile-directory",
        help="Chrome profile folder to open, e.g. Default or 'Profile 5'.",
    )
    parser.add_argument(
        "--attach-cdp-url",
        help="Attach to an already running Chrome DevTools endpoint, e.g. http://127.0.0.1:9222.",
    )
    parser.add_argument(
        "--chrome-debug-port",
        type=int,
        default=0,
        help="Remote debugging port for --x-backend chrome-cdp. Default 0 picks a free port.",
    )
    parser.add_argument("--headless", action="store_true", help="Run browser headless.")
    parser.add_argument("--slow-mo", type=int, default=50, help="Playwright slow_mo in milliseconds.")
    parser.add_argument("--skip-x", action="store_true", help="Skip X collection.")
    parser.add_argument("--skip-ethresearch", action="store_true", help="Skip ethresear.ch collection.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = run(args)
    except (HTTPError, URLError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
