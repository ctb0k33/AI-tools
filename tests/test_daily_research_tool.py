import unittest
from datetime import date, timedelta, timezone

from tools.daily_research.daily_research_tool import (
    QuerySpec,
    ResearchItem,
    build_payload,
    build_x_item_from_raw_tweet,
    build_x_query,
    build_x_search_url,
    classify_text,
    clean_tweet_text,
    dedupe_items,
    extract_x_handle_from_href,
    extract_x_author,
    filter_items_by_local_date,
    filter_x_items_by_quality,
    looks_like_truncated_x_text,
    normalize_x_handle,
    normalize_x_handles,
    parse_query_specs,
    render_markdown_report,
    same_x_handle,
    summarize_x_post,
    technical_score_text,
)


class XQueryTests(unittest.TestCase):
    def test_adds_same_day_filters(self):
        query = build_x_query("PeerDAS lang:en", date(2026, 5, 9))

        self.assertIn("since:2026-05-09", query)
        self.assertIn("until:2026-05-10", query)

    def test_preserves_existing_date_filters(self):
        query = build_x_query("PeerDAS since:2026-01-01 until:2026-01-02", date(2026, 5, 9))

        self.assertEqual(query, "PeerDAS since:2026-01-01 until:2026-01-02")

    def test_builds_x_search_url(self):
        url = build_x_search_url("PeerDAS lang:en", date(2026, 5, 9))

        self.assertTrue(url.startswith("https://x.com/search?q="))
        self.assertIn("src=typed_query", url)
        self.assertNotIn("since%3A2026-05-09", url)

    def test_builds_x_search_url_with_optional_date_filters(self):
        url = build_x_search_url("PeerDAS lang:en", date(2026, 5, 9), include_date_filters=True)

        self.assertIn("PeerDAS%20lang%3Aen", url)
        self.assertIn("since%3A2026-05-09", url)

    def test_parse_query_specs_can_skip_configured_search(self):
        specs = parse_query_specs(
            {"x_queries": [{"name": "Search", "query": "ethereum", "category": "Core Protocol"}]},
            extra_queries=["Manual::peerdas"],
            include_config_queries=False,
        )

        self.assertEqual([(spec.name, spec.query) for spec in specs], [("Manual", "peerdas")])


class ClassificationTests(unittest.TestCase):
    def test_classifies_protocol_and_da_terms(self):
        categories = {
            "Core Protocol": ["peerdas", "epbs"],
            "L2 and Data Availability": ["blob", "data availability"],
        }

        labels = classify_text("PeerDAS improves blob data availability", categories)

        self.assertEqual(labels, ["Core Protocol", "L2 and Data Availability"])


class DedupeTests(unittest.TestCase):
    def test_dedupes_by_url(self):
        items = [
            ResearchItem(source="X", section="Core", title="A", url="https://x.com/a/status/1?s=20"),
            ResearchItem(source="X", section="Core", title="B", url="https://x.com/a/status/1"),
        ]

        self.assertEqual(len(dedupe_items(items)), 1)


class XParsingTests(unittest.TestCase):
    def test_extracts_author_from_status_url(self):
        author = extract_x_author("https://x.com/ethereum/status/123", "Ethereum\nPost")

        self.assertEqual(author, "@ethereum")

    def test_extracts_profile_handle_from_following_links(self):
        self.assertEqual(extract_x_handle_from_href("/ChainLabo"), "ChainLabo")
        self.assertEqual(extract_x_handle_from_href("https://x.com/ChainLabo"), "ChainLabo")
        self.assertEqual(extract_x_handle_from_href("/ChainLabo/status/1"), "")
        self.assertTrue(same_x_handle("@ChainLabo", "chainlabo"))

    def test_normalizes_profile_config_values(self):
        self.assertEqual(normalize_x_handle("https://x.com/ethresearchbot"), "ethresearchbot")
        self.assertEqual(normalize_x_handle("@pashov"), "pashov")
        self.assertEqual(normalize_x_handles(["@pashov", "https://x.com/pashov", "bad/path"]), ["pashov"])

    def test_cleans_tweet_text_noise(self):
        text = clean_tweet_text("Useful update\nReply\nShow more\n42")

        self.assertEqual(text, "Useful update 42")

    def test_filters_items_by_local_date(self):
        tz = timezone(timedelta(hours=7))
        items = [
            ResearchItem(
                source="X",
                section="DeFi",
                title="A",
                url="https://x.com/a/status/1",
                published_at="2026-05-09T18:00:00Z",
            ),
            ResearchItem(
                source="X",
                section="DeFi",
                title="B",
                url="https://x.com/b/status/1",
                published_at="2026-05-08T18:00:00Z",
            ),
        ]

        filtered, stats = filter_items_by_local_date(items, date(2026, 5, 10), tz)

        self.assertEqual([item.title for item in filtered], ["A"])
        self.assertEqual(stats["outside_date"], 1)

        filtered_with_lookback, stats_with_lookback = filter_items_by_local_date(
            items,
            date(2026, 5, 10),
            tz,
            lookback_days=1,
        )

        self.assertEqual([item.title for item in filtered_with_lookback], ["A", "B"])
        self.assertEqual(stats_with_lookback["outside_date"], 0)

    def test_scores_technical_protocol_posts(self):
        score, reasons = technical_score_text(
            "New EIP proposal for Ethereum validator PBS architecture and implementation details"
        )

        self.assertGreaterEqual(score, 6)
        self.assertIn("eip", reasons)

    def test_quality_filter_removes_replies_and_low_value_posts(self):
        items = [
            ResearchItem(
                source="X",
                section="DeFi",
                title="Reply",
                url="https://x.com/a/status/1",
                text="Đang trả lời @someone What's prompt defi?",
                published_at="2026-05-09T18:00:00Z",
            ),
            ResearchItem(
                source="X",
                section="Core",
                title="Technical",
                url="https://x.com/b/status/1",
                text="EIP proposal: execution layer client implementation details for validator PBS",
                published_at="2026-05-09T18:00:00Z",
            ),
        ]

        filtered, stats = filter_x_items_by_quality(
            items,
            min_technical_score=3,
            include_replies=False,
            include_quotes=False,
        )

        self.assertEqual([item.title for item in filtered], ["Technical"])
        self.assertEqual(stats["replies"], 1)

    def test_quality_filter_removes_generic_comments(self):
        score, reasons = technical_score_text("ELM protocol for my soul DeFi gods, where's the pizza?")

        self.assertLess(score, 3)
        self.assertIn("generic_only", reasons)

    def test_builds_item_from_original_tweet_text_only(self):
        raw = {
            "article_text": "Author\n@alice\nReplying to @bob\n1/4 EIP-7251 changes validator operations.\nQuote\nold post",
            "tweet_text": "1/4 EIP-7251 changes validator operations and consolidation mechanics.",
            "tweet_texts": [
                "1/4 EIP-7251 changes validator operations and consolidation mechanics.",
                "old post",
            ],
            "links": ["https://x.com/alice/status/123"],
            "time": "2026-05-09T18:00:00Z",
        }

        item = build_x_item_from_raw_tweet(
            raw,
            QuerySpec(name="EIP", query="EIP ethereum", category="Core Protocol"),
            {"Core Protocol": ["eip", "validator"]},
            backend="test",
        )

        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.text, "1/4 EIP-7251 changes validator operations and consolidation mechanics.")
        self.assertNotIn("old post", item.text)
        self.assertEqual(item.author, "@alice")
        self.assertTrue(item.raw["is_reply"])
        self.assertTrue(item.raw["is_quote"])

    def test_summarizes_x_post_without_ui_text(self):
        summary = summarize_x_post(
            "EIP-7251 changes validator consolidation mechanics. "
            "It reduces operational overhead for large stakers while preserving consensus constraints. "
            "Extra UI text should not matter."
        )

        self.assertIn("EIP-7251 changes validator consolidation mechanics.", summary)
        self.assertLessEqual(len(summary), 360)

    def test_summarizes_embedded_summary_without_cutting_midword(self):
        summary = summarize_x_post(
            "Security Alert: Example exploit. Attack Tx: https://etherscan.io/tx/... "
            "Summary: An attacker used a 10 WETH Morpho flash loan to manipulate hook accounting and exit with profit."
        )

        self.assertTrue(summary.startswith("An attacker used a 10 WETH Morpho flash loan"))
        self.assertFalse(summary.endswith("..."))

    def test_detects_truncated_x_text(self):
        self.assertTrue(looks_like_truncated_x_text("An attacker used a 10 WETH Morpho flash loan to"))
        self.assertTrue(looks_like_truncated_x_text("A long post", "A long post\nShow more"))
        self.assertFalse(looks_like_truncated_x_text("A complete post about EIP-7251."))


class RenderTests(unittest.TestCase):
    def test_renders_report_sections(self):
        item = ResearchItem(
            source="ethresear.ch",
            section="New research posts",
            title="A PeerDAS research note",
            url="https://ethresear.ch/t/example/1",
            published_at="2026-05-09T01:00:00Z",
            text="PeerDAS note",
            tags=["Core Protocol"],
        )
        payload = build_payload(
            target_day=date(2026, 5, 9),
            timezone_name="UTC",
            items=[item],
            warnings=[],
            config={"x_queries": [], "ethresearch_endpoints": []},
            date_lookback_days=1,
        )

        markdown = render_markdown_report(payload)

        self.assertIn("# Daily DeFi/Core Research Digest - 2026-05-09", markdown)
        self.assertIn("Included local dates: 2026-05-08, 2026-05-09", markdown)
        self.assertIn("## ethresear.ch New Research Posts", markdown)
        self.assertIn("A PeerDAS research note", markdown)

    def test_renders_x_summary_and_original_post(self):
        item = ResearchItem(
            source="X",
            section="Ethereum Core",
            title="EIP-7251 update",
            url="https://x.com/ethereum/status/1",
            published_at="2026-05-09T01:00:00Z",
            text="EIP-7251 changes validator consolidation mechanics.",
            tags=["Core Protocol"],
            raw={"summary": "Validator consolidation mechanics changed."},
        )
        payload = build_payload(
            target_day=date(2026, 5, 9),
            timezone_name="UTC",
            items=[item],
            warnings=[],
            config={"x_queries": [], "ethresearch_endpoints": []},
        )

        markdown = render_markdown_report(payload)

        self.assertIn("- Summary: Validator consolidation mechanics changed.", markdown)
        self.assertIn("- Original post: EIP-7251 changes validator consolidation mechanics.", markdown)


if __name__ == "__main__":
    unittest.main()
