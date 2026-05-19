from __future__ import annotations

import argparse
import dataclasses
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.research import (
    QuerySpec,
    build_x_item_from_raw_tweet,
    classify_text,
    extract_x_handle_from_href,
    load_config,
    same_x_handle,
    technical_score_text,
    truncate_text,
    unlock_stale_chromium_profile,
)


@dataclasses.dataclass(slots=True)
class AccountAudit:
    handle: str
    url: str
    status: str
    quality_score: int = 0
    posts_seen: int = 0
    technical_posts: int = 0
    top_score: int = 0
    tags: list[str] = dataclasses.field(default_factory=list)
    reasons: list[str] = dataclasses.field(default_factory=list)
    sample_posts: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    filtered_reason: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(slots=True)
class FollowingCandidate:
    handle: str
    profile_text: str = ""
    pre_score: int = 0
    tags: list[str] = dataclasses.field(default_factory=list)
    reasons: list[str] = dataclasses.field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://x.com/{self.handle}"

    def to_dict(self) -> dict[str, Any]:
        payload = dataclasses.asdict(self)
        payload["url"] = self.url
        return payload


class FollowingAccountAuditor:
    def __init__(
        self,
        profile_dir: Path,
        owner: str,
        output_dir: Path,
        config_path: str | None,
        max_profiles: int,
        posts_per_profile: int,
        min_post_score: int,
        min_account_score: int,
        min_profile_score: int,
        profile_delay_seconds: float,
        jitter_seconds: float,
        cooldown_seconds: int,
        stop_on_rate_limit: bool,
        use_cached_following: bool,
        refresh_following: bool,
        cache_only: bool,
        timeout_ms: int,
        headless: bool,
        slow_mo: int,
    ) -> None:
        self.profile_dir = profile_dir
        self.owner = owner.strip().lstrip("@")
        self.output_dir = output_dir
        self.config = load_config(config_path)
        self.keyword_categories = self.config.get("keyword_categories", {})
        self.max_profiles = max_profiles
        self.posts_per_profile = posts_per_profile
        self.min_post_score = min_post_score
        self.min_account_score = min_account_score
        self.min_profile_score = min_profile_score
        self.profile_delay_seconds = profile_delay_seconds
        self.jitter_seconds = jitter_seconds
        self.cooldown_seconds = cooldown_seconds
        self.stop_on_rate_limit = stop_on_rate_limit
        self.use_cached_following = use_cached_following
        self.refresh_following = refresh_following
        self.cache_only = cache_only
        self.timeout_ms = timeout_ms
        self.headless = headless
        self.slow_mo = slow_mo
        self.run_dir = self.output_dir / datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.following_cache_path = self.output_dir / f"{self.owner.lower()}_following_candidates.json"

    def run(self) -> dict[str, Any]:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise RuntimeError(f"Playwright import failed: {exc}") from exc

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        if os.environ.get("DAILY_RESEARCH_UNLOCK_STALE_PROFILE", "").lower() in {"1", "true", "yes"}:
            warnings.extend(unlock_stale_chromium_profile(self.profile_dir))
        self.run_dir.mkdir(parents=True, exist_ok=True)
        audits: list[AccountAudit] = []
        warnings: list[str] = []
        candidates: list[FollowingCandidate] = []
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
                    "args": ["--disable-blink-features=AutomationControlled", "--no-first-run"],
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
                        warnings.append(f"Chrome channel failed, falling back to bundled Chromium: {exc}")
                        context = playwright.chromium.launch_persistent_context(
                            **launch_kwargs,
                        )
                page = context.pages[0] if context.pages else context.new_page()
                candidates = self._load_or_collect_following_candidates(page, warnings)
                if not candidates:
                    warnings.append("No candidate profiles passed the following-card prefilter.")
                if self.cache_only:
                    warnings.append("Cache-only mode: collected following candidates without visiting profiles.")
                    payload = self._build_payload(audits, candidates, warnings)
                    paths = self._write_outputs(payload)
                    return {"paths": paths, "stats": payload["stats"], "warnings": warnings}
                for index, candidate in enumerate(candidates, start=1):
                    audit = self._audit_profile(page, candidate, PlaywrightTimeoutError)
                    audits.append(audit)
                    print(
                        f"[{index}/{len(candidates)}] @{candidate.handle}: {audit.status} score={audit.quality_score}",
                        flush=True,
                    )
                    self._write_checkpoint(audits, candidates, warnings)
                    if audit.status == "rate_limited":
                        message = f"Rate limit detected at @{candidate.handle}."
                        warnings.append(message)
                        if self.cooldown_seconds > 0:
                            warnings.append(f"Cooling down for {self.cooldown_seconds} seconds.")
                            self._write_checkpoint(audits, candidates, warnings)
                            time.sleep(self.cooldown_seconds)
                        if self.stop_on_rate_limit:
                            warnings.append("Stopped early to avoid more X 429s.")
                            break
                    self._sleep_between_profiles()
            finally:
                if context is not None:
                    context.close()

        payload = self._build_payload(audits, candidates, warnings)
        paths = self._write_outputs(payload)
        return {"paths": paths, "stats": payload["stats"], "warnings": warnings}

    def _load_or_collect_following_candidates(self, page: Any, warnings: list[str]) -> list[FollowingCandidate]:
        if self.use_cached_following and not self.refresh_following and self.following_cache_path.exists():
            try:
                payload = json.loads(self.following_cache_path.read_text(encoding="utf-8"))
                candidates = [
                    FollowingCandidate(
                        handle=str(item.get("handle", "")),
                        profile_text=str(item.get("profile_text", "")),
                        pre_score=int(item.get("pre_score", 0)),
                        tags=list(item.get("tags", [])),
                        reasons=list(item.get("reasons", [])),
                    )
                    for item in payload.get("candidates", [])
                    if item.get("handle")
                ]
                return candidates[: self.max_profiles]
            except Exception as exc:
                warnings.append(f"Could not read following cache: {exc}")

        candidates = self._collect_following_candidates(page, warnings)
        self.following_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.following_cache_path.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "owner": self.owner,
                    "min_profile_score": self.min_profile_score,
                    "candidates": [candidate.to_dict() for candidate in candidates],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return candidates

    def _collect_following_candidates(self, page: Any, warnings: list[str]) -> list[FollowingCandidate]:
        page.goto(f"https://x.com/{self.owner}/following", wait_until="domcontentloaded", timeout=self.timeout_ms)
        page.wait_for_timeout(3500)
        try:
            page.wait_for_selector("[data-testid='UserCell']", timeout=12000)
        except Exception:
            warnings.append(f"No following cells found at https://x.com/{self.owner}/following.")
            return []

        candidates_by_handle: dict[str, FollowingCandidate] = {}
        scanned_cells = 0
        max_scrolls = max(8, min(60, self.max_profiles // 3 + 8))
        for _ in range(max_scrolls):
            cells = page.locator("[data-testid='UserCell']")
            count = cells.count()
            for index in range(count):
                scanned_cells += 1
                try:
                    cell = cells.nth(index)
                    raw_links = cell.locator("a[href]").evaluate_all(
                        "(els) => els.map((a) => a.getAttribute('href') || '').filter(Boolean)"
                    )
                    profile_text = str(cell.inner_text(timeout=1000) or "")
                except Exception:
                    raw_links = []
                    profile_text = ""
                for href in raw_links:
                    handle = extract_x_handle_from_href(str(href))
                    if handle and not same_x_handle(handle, self.owner):
                        candidate = self._candidate_from_following_cell(handle, profile_text)
                        if candidate.pre_score >= self.min_profile_score:
                            candidates_by_handle[handle.lower()] = candidate
                        break
                if len(candidates_by_handle) >= self.max_profiles:
                    return self._sort_candidates(list(candidates_by_handle.values()))
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(1000)
        if not candidates_by_handle:
            warnings.append(f"Scanned {scanned_cells} following cells, but none passed prefilter.")
        return self._sort_candidates(list(candidates_by_handle.values()))

    def _candidate_from_following_cell(self, handle: str, profile_text: str) -> FollowingCandidate:
        score, reasons = technical_score_text(profile_text)
        tags = classify_text(profile_text, self.keyword_categories)
        return FollowingCandidate(
            handle=handle,
            profile_text=truncate_text(profile_text, 500),
            pre_score=score + len(tags),
            tags=tags,
            reasons=[reason for reason in reasons if not reason.startswith("low_value:")][:8],
        )

    def _sort_candidates(self, candidates: list[FollowingCandidate]) -> list[FollowingCandidate]:
        candidates.sort(key=lambda candidate: (candidate.pre_score, len(candidate.tags), candidate.handle.lower()), reverse=True)
        return candidates[: self.max_profiles]

    def _audit_profile(self, page: Any, candidate: FollowingCandidate, timeout_error: type[Exception]) -> AccountAudit:
        handle = candidate.handle
        audit = AccountAudit(handle=handle, url=f"https://x.com/{handle}", status="filtered")
        spec = QuerySpec(name="Following Profile Audit", query=audit.url, category="")
        try:
            page.goto(audit.url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            page.wait_for_timeout(2500)
            if self._page_has_rate_limit(page):
                audit.status = "rate_limited"
                audit.filtered_reason = "x_rate_limited"
                return audit
            try:
                page.wait_for_selector("article[data-testid='tweet']", timeout=7000)
            except timeout_error:
                if self._page_has_rate_limit(page):
                    audit.status = "rate_limited"
                    audit.filtered_reason = "x_rate_limited"
                    return audit
                audit.filtered_reason = "no_visible_posts"
                return audit

            items_by_url: dict[str, Any] = {}
            for _ in range(2):
                articles = page.locator("article[data-testid='tweet']")
                count = articles.count()
                for index in range(count):
                    raw = self._extract_tweet_payload(articles.nth(index))
                    raw["source_profile"] = handle
                    item = build_x_item_from_raw_tweet(raw, spec, self.keyword_categories, backend="profile-audit")
                    if item is None or not same_x_handle(item.author, handle):
                        continue
                    if item.raw.get("is_reply") or item.raw.get("is_quote"):
                        continue
                    key = item.url or item.text
                    if key in items_by_url:
                        continue
                    items_by_url[key] = item
                    if len(items_by_url) >= self.posts_per_profile:
                        break
                if len(items_by_url) >= self.posts_per_profile:
                    break
                page.mouse.wheel(0, 1300)
                page.wait_for_timeout(900)

            items = list(items_by_url.values())
            audit.posts_seen = len(items)
            if not items:
                audit.filtered_reason = "no_recent_original_posts"
                return audit

            tag_counts: dict[str, int] = {}
            reason_counts: dict[str, int] = {}
            scored_posts: list[dict[str, Any]] = []
            for item in items:
                score, reasons = technical_score_text(item.text)
                tags = item.tags or classify_text(item.text, self.keyword_categories)
                for tag in tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
                for reason in reasons:
                    if not reason.startswith("low_value:"):
                        reason_counts[reason] = reason_counts.get(reason, 0) + 1
                scored_posts.append(
                    {
                        "title": item.title,
                        "url": item.url,
                        "published_at": item.published_at,
                        "score": score,
                        "tags": tags,
                        "reasons": reasons,
                        "summary": item.raw.get("summary") or truncate_text(item.text, 280),
                        "text": item.text,
                    }
                )

            scored_posts.sort(key=lambda post: post["score"], reverse=True)
            audit.top_score = int(scored_posts[0]["score"]) if scored_posts else 0
            audit.technical_posts = sum(1 for post in scored_posts if int(post["score"]) >= self.min_post_score)
            audit.quality_score = sum(max(0, int(post["score"])) for post in scored_posts[:3]) + audit.technical_posts * 2
            audit.tags = [tag for tag, _ in sorted(tag_counts.items(), key=lambda pair: pair[1], reverse=True)[:6]]
            audit.reasons = [
                reason for reason, _ in sorted(reason_counts.items(), key=lambda pair: pair[1], reverse=True)[:8]
            ]
            audit.sample_posts = scored_posts[:3]
            if audit.quality_score >= self.min_account_score or audit.technical_posts >= 2 or audit.top_score >= 8:
                audit.status = "selected"
            else:
                audit.filtered_reason = "low_technical_signal"
            return audit
        except Exception as exc:
            audit.status = "error"
            audit.filtered_reason = "profile_error"
            audit.error = str(exc)
            return audit

    def _page_has_rate_limit(self, page: Any) -> bool:
        try:
            text = str(page.locator("body").inner_text(timeout=1500) or "").lower()
        except Exception:
            return False
        markers = [
            "something went wrong",
            "try reloading",
            "rate limit",
            "too many requests",
        ]
        return any(marker in text for marker in markers)

    def _sleep_between_profiles(self) -> None:
        delay = self.profile_delay_seconds
        if self.jitter_seconds > 0:
            delay += random.uniform(0, self.jitter_seconds)
        if delay > 0:
            time.sleep(delay)

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
                      return {
                        article_text: article.innerText || '',
                        tweet_text: tweetTexts[0] || '',
                        tweet_texts: tweetTexts,
                        links,
                        time
                      };
                    }
                    """
                )
            )
        except Exception:
            return {}

    def _split_audits(self, audits: list[AccountAudit]) -> tuple[list[AccountAudit], list[AccountAudit]]:
        selected = [audit for audit in audits if audit.status == "selected"]
        filtered = [audit for audit in audits if audit.status != "selected"]
        selected.sort(key=lambda audit: (audit.quality_score, audit.top_score, audit.technical_posts), reverse=True)
        filtered.sort(key=lambda audit: (audit.filtered_reason, audit.handle.lower()))
        return selected, filtered

    def _build_payload(
        self,
        audits: list[AccountAudit],
        candidates: list[FollowingCandidate],
        warnings: list[str],
    ) -> dict[str, Any]:
        selected, filtered = self._split_audits(audits)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "owner": self.owner,
            "max_profiles": self.max_profiles,
            "posts_per_profile": self.posts_per_profile,
            "min_post_score": self.min_post_score,
            "min_account_score": self.min_account_score,
            "min_profile_score": self.min_profile_score,
            "stats": {
                "profiles_scanned": len(audits),
                "candidate_profiles": len(candidates),
                "selected": len(selected),
                "filtered_out": len(filtered),
            },
            "warnings": warnings,
            "candidates": [candidate.to_dict() for candidate in candidates],
            "selected": [audit.to_dict() for audit in selected],
            "filtered_out": [audit.to_dict() for audit in filtered],
        }

    def _write_checkpoint(
        self,
        audits: list[AccountAudit],
        candidates: list[FollowingCandidate],
        warnings: list[str],
    ) -> None:
        payload = self._build_payload(audits, candidates, warnings)
        checkpoint_path = self.run_dir / "following_account_audit.checkpoint.json"
        checkpoint_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_outputs(self, payload: dict[str, Any]) -> dict[str, str]:
        target_dir = self.run_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        json_path = target_dir / "following_account_audit.json"
        md_path = target_dir / "following_account_audit.md"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(render_markdown(payload), encoding="utf-8")
        return {"json": str(json_path), "markdown": str(md_path), "output_dir": str(target_dir)}


def render_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# X Following Account Audit - @{payload['owner']}")
    lines.append("")
    lines.append("## Metadata")
    lines.append("")
    lines.append(f"- Generated at: {payload['generated_at']}")
    lines.append(f"- Profiles scanned: {payload['stats']['profiles_scanned']}")
    lines.append(f"- Candidate profiles after following-card prefilter: {payload['stats'].get('candidate_profiles', 0)}")
    lines.append(f"- Selected: {payload['stats']['selected']}")
    lines.append(f"- Filtered out: {payload['stats']['filtered_out']}")
    lines.append(f"- Posts sampled per profile: {payload['posts_per_profile']}")
    lines.append(f"- Min profile pre-score: {payload.get('min_profile_score', 0)}")
    lines.append(f"- Min post score: {payload['min_post_score']}")
    lines.append(f"- Min account score: {payload['min_account_score']}")
    lines.append("")
    if payload.get("warnings"):
        lines.append("## Warnings")
        lines.append("")
        for warning in payload["warnings"]:
            lines.append(f"- {warning}")
        lines.append("")

    lines.append("## Selected Accounts")
    lines.append("")
    selected = payload.get("selected", [])
    if not selected:
        lines.append("- No accounts selected.")
        lines.append("")
    for audit in selected:
        lines.append(f"### @{audit['handle']}")
        lines.append("")
        lines.append(f"- URL: {audit['url']}")
        lines.append(f"- Quality score: {audit['quality_score']}")
        lines.append(f"- Technical posts sampled: {audit['technical_posts']} / {audit['posts_seen']}")
        if audit.get("tags"):
            lines.append(f"- Main tags: {', '.join(audit['tags'])}")
        if audit.get("reasons"):
            lines.append(f"- Matched signals: {', '.join(audit['reasons'][:8])}")
        for post in audit.get("sample_posts", [])[:3]:
            lines.append(f"- Sample: {post['summary']} ({post['url']})")
        lines.append("")

    lines.append("## Filtered Out Accounts")
    lines.append("")
    filtered = payload.get("filtered_out", [])
    if not filtered:
        lines.append("- No accounts filtered out.")
        lines.append("")
        return "\n".join(lines)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for audit in filtered:
        reason = audit.get("filtered_reason") or audit.get("status") or "filtered"
        grouped.setdefault(reason, []).append(audit)
    for reason, audits in grouped.items():
        handles = ", ".join(f"@{audit['handle']}" for audit in audits[:80])
        suffix = "" if len(audits) <= 80 else f" ... (+{len(audits) - 80} more)"
        lines.append(f"- {reason}: {handles}{suffix}")
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit followed X accounts for DeFi/core research quality.")
    parser.add_argument("--profile-dir", default="profiles/x_profile", help="Persistent Chrome profile for X.")
    parser.add_argument("--owner", default="", help="X account whose following list should be audited.")
    parser.add_argument("--output-dir", default="outputs/daily_research/account_audit", help="Output directory.")
    parser.add_argument("--config", help="Optional daily research config path.")
    parser.add_argument("--max-profiles", type=int, default=80, help="Max followed profiles to audit.")
    parser.add_argument("--posts-per-profile", type=int, default=6, help="Max recent original posts per profile.")
    parser.add_argument("--min-post-score", type=int, default=4, help="Minimum score for a technical post.")
    parser.add_argument("--min-account-score", type=int, default=12, help="Minimum account quality score.")
    parser.add_argument("--min-profile-score", type=int, default=1, help="Minimum following-card prefilter score.")
    parser.add_argument("--profile-delay-seconds", type=float, default=8.0, help="Base delay between profile visits.")
    parser.add_argument("--jitter-seconds", type=float, default=4.0, help="Random extra delay between profile visits.")
    parser.add_argument("--cooldown-seconds", type=int, default=180, help="Cooldown after X rate-limit UI appears.")
    parser.add_argument(
        "--continue-on-rate-limit",
        action="store_true",
        help="Continue after cooldown instead of stopping at the first rate-limit UI.",
    )
    parser.add_argument(
        "--no-cached-following",
        action="store_true",
        help="Ignore the cached following candidate list and fetch it again.",
    )
    parser.add_argument("--refresh-following", action="store_true", help="Refresh and overwrite following cache.")
    parser.add_argument("--cache-only", action="store_true", help="Only collect/prefilter following candidates.")
    parser.add_argument("--timeout-ms", type=int, default=45000, help="Browser timeout.")
    parser.add_argument("--headless", action="store_true", help="Run browser headless.")
    parser.add_argument("--slow-mo", type=int, default=50, help="Playwright slow_mo in milliseconds.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        auditor = FollowingAccountAuditor(
            profile_dir=Path(args.profile_dir).expanduser().resolve(),
            owner=args.owner,
            output_dir=Path(args.output_dir).expanduser().resolve(),
            config_path=args.config,
            max_profiles=args.max_profiles,
            posts_per_profile=args.posts_per_profile,
            min_post_score=args.min_post_score,
            min_account_score=args.min_account_score,
            min_profile_score=args.min_profile_score,
            profile_delay_seconds=args.profile_delay_seconds,
            jitter_seconds=args.jitter_seconds,
            cooldown_seconds=args.cooldown_seconds,
            stop_on_rate_limit=not args.continue_on_rate_limit,
            use_cached_following=not args.no_cached_following,
            refresh_following=args.refresh_following,
            cache_only=args.cache_only,
            timeout_ms=args.timeout_ms,
            headless=args.headless,
            slow_mo=args.slow_mo,
        )
        result = auditor.run()
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
