import tempfile
import unittest
from pathlib import Path

from tools.daily_research.following_account_audit import FollowingAccountAuditor, render_markdown


class FollowingAccountAuditTests(unittest.TestCase):
    def test_prefilter_scores_following_card_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            auditor = FollowingAccountAuditor(
                profile_dir=Path(tmpdir) / "profile",
                owner="Ctb0k33",
                output_dir=Path(tmpdir) / "out",
                config_path=None,
                max_profiles=10,
                posts_per_profile=3,
                min_post_score=4,
                min_account_score=12,
                min_profile_score=1,
                profile_delay_seconds=0,
                jitter_seconds=0,
                cooldown_seconds=0,
                stop_on_rate_limit=True,
                use_cached_following=True,
                refresh_following=False,
                cache_only=False,
                timeout_ms=1000,
                headless=True,
                slow_mo=0,
            )

            candidate = auditor._candidate_from_following_cell(
                "ChainLabo",
                "ChainLabo @ChainLabo Ethereum EIP validator restaking DeFi research",
            )

            self.assertEqual(candidate.handle, "ChainLabo")
            self.assertGreaterEqual(candidate.pre_score, 4)
            self.assertIn("Core Protocol", candidate.tags)

    def test_render_markdown_shows_candidate_count(self):
        markdown = render_markdown(
            {
                "owner": "Ctb0k33",
                "generated_at": "2026-05-10T00:00:00+00:00",
                "posts_per_profile": 3,
                "min_post_score": 4,
                "min_account_score": 12,
                "min_profile_score": 1,
                "stats": {
                    "profiles_scanned": 1,
                    "candidate_profiles": 5,
                    "selected": 0,
                    "filtered_out": 1,
                },
                "warnings": [],
                "selected": [],
                "filtered_out": [{"handle": "x", "filtered_reason": "x_rate_limited"}],
            }
        )

        self.assertIn("Candidate profiles after following-card prefilter: 5", markdown)
        self.assertIn("x_rate_limited", markdown)


if __name__ == "__main__":
    unittest.main()
