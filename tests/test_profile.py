from datetime import date
import unittest
from unittest.mock import patch

from scripts.update_profile import language_shares, language_totals, parse_views, streak


class ProfileTests(unittest.TestCase):
    def test_language_percentages_round_to_one_hundred(self):
        shares = language_shares({"Rust": 1, "Python": 1, "C": 1})
        self.assertAlmostEqual(sum(value for _, value in shares), 100)
        self.assertEqual(language_shares({}), [])
        self.assertEqual(language_shares({"Rust": 0}), [])
        shares = language_shares({name: 1 for name in "ABCDEFG"})
        self.assertEqual(shares[-1], ("Other", 28.5))
        self.assertAlmostEqual(sum(value for _, value in shares), 100)

    @patch("scripts.update_profile.gh")
    def test_languages_exclude_forks_and_profile_and_weight_by_bytes(self, api):
        api.side_effect = lambda path: {"Rust": 300} if "one" in path else {"Python": 100}
        repos = [{"name": name, "fork": fork, "full_name": f"user/{name}"}
                 for name, fork in [("one", False), ("two", False), ("user", False), ("upstream", True)]]
        totals, count = language_totals(repos, "user")
        self.assertEqual(count, 2)
        self.assertEqual(language_shares(totals), [("Rust", 75.0), ("Python", 25.0)])
        self.assertEqual(api.call_count, 2)

    def test_streak_today_can_be_unfinished(self):
        days = [{"date": "2026-10-08", "contributionCount": 3},
                {"date": "2026-10-09", "contributionCount": 1},
                {"date": "2026-10-10", "contributionCount": 0}]
        self.assertEqual(streak(days, date(2026, 10, 10)), 2)
        days[-1]["contributionCount"] = 2
        self.assertEqual(streak(days, date(2026, 10, 10)), 3)

    def test_gap_breaks_streak_and_future_is_ignored(self):
        days = [{"date": "2026-10-08", "contributionCount": 3},
                {"date": "2026-10-11", "contributionCount": 5}]
        self.assertEqual(streak(days, date(2026, 10, 10)), 0)
        self.assertEqual(streak([], date(2026, 10, 10)), 0)

    def test_year_boundary(self):
        days = [{"date": "2025-12-31", "contributionCount": 1},
                {"date": "2026-01-01", "contributionCount": 1}]
        self.assertEqual(streak(days, date(2026, 1, 1)), 2)

    def test_counter_parsing(self):
        self.assertEqual(parse_views('<svg aria-label="Profile views: 1,234"/>'), 1234)
        self.assertEqual(parse_views('<svg xmlns="http://www.w3.org/2000/svg"><text>42</text></svg>'), 42)
        with self.assertRaises(ValueError):
            parse_views('<svg aria-label="Profile views: unavailable"/>')

    @patch("scripts.update_profile.time.sleep")
    @patch("scripts.update_profile.subprocess.run")
    def test_gh_retry_success_after_failure(self, mock_run, mock_sleep):
        import subprocess
        from scripts.update_profile import gh

        fail = subprocess.CalledProcessError(1, ["gh"], stderr="temporary glitch")
        success = unittest.mock.Mock(stdout='{"data": 123}')
        mock_run.side_effect = [fail, success]

        result = gh("test", retries=2, delay=0.01)
        self.assertEqual(result, {"data": 123})
        self.assertEqual(mock_run.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("scripts.update_profile.time.sleep")
    @patch("scripts.update_profile.subprocess.run")
    def test_gh_raises_runtime_error_with_stderr_after_all_retries(self, mock_run, mock_sleep):
        import subprocess
        from scripts.update_profile import gh

        fail = subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 502 Bad Gateway")
        mock_run.side_effect = fail

        with self.assertRaises(RuntimeError) as ctx:
            gh("test", retries=2, delay=0.01)
        self.assertIn("HTTP 502 Bad Gateway", str(ctx.exception))
        self.assertEqual(mock_run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
