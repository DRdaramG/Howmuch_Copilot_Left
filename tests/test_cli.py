import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import api
import main


class QuotaParsingTests(unittest.TestCase):
    @patch.dict(os.environ, {"COPILOT_TOKEN": "test-token"}, clear=False)
    @patch("api._request_json")
    def test_copilot_ai_credits(self, request_json):
        request_json.return_value = {
            "quota_snapshots": {
                "ai_credits": {
                    "entitlement": 1500,
                    "quota_remaining": 900,
                }
            }
        }

        result = api.fetch_copilot({})

        self.assertIsNone(result.error)
        self.assertEqual(result.windows[0].used, 600)
        self.assertEqual(result.windows[0].used_percent, 40)

    @patch.dict(os.environ, {"CLAUDE_ACCESS_TOKEN": "test-token"}, clear=False)
    @patch("api._request_json")
    def test_claude_percentage_and_scoped_limits(self, request_json):
        request_json.return_value = {
            "five_hour": {"utilization": 25, "resets_at": "soon"},
            "seven_day": {"utilization": 50},
            "limits": [{"kind": "weekly_model", "percent": 10}],
        }

        result = api.fetch_claude({})

        self.assertEqual([window.used_percent for window in result.windows], [25, 50, 10])

    @patch.dict(os.environ, {"DEVPASS_API_KEY": "test-token"}, clear=False)
    @patch("api._request_json")
    def test_devpass_credit_windows(self, request_json):
        request_json.return_value = {
            "data": {
                "devPlanCreditsUsed": "30",
                "devPlanCreditsLimit": "100",
                "devPlanPremiumCreditsUsed": "5",
                "devPlanPremiumWeeklyLimit": "20",
            }
        }

        result = api.fetch_devpass({})

        self.assertEqual([window.used_percent for window in result.windows], [30, 25])

    @patch("api.requests.post")
    def test_codex_refresh_rotates_and_secures_credentials(self, post):
        response = post.return_value
        response.json.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth.json"
            auth = {"tokens": {"access_token": "old", "refresh_token": "old-refresh"}}

            token = api._refresh_codex_auth(path, auth)

            self.assertEqual(token, "new-access")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(api._read_json(path)["tokens"]["refresh_token"], "new-refresh")


class RenderingTests(unittest.TestCase):
    def test_bar_and_render(self):
        result = api.QuotaResult(
            "Copilot",
            [api.QuotaWindow("AI credits", 40, 600, 1500, "credits")],
        )

        output = main.render([result])

        self.assertIn("■■■■□□□□□□ (40%)", output)
        self.assertIn("600/1500 credits", output)

    def test_provider_failure_does_not_abort_output(self):
        output = main.render([api.QuotaResult("Claude", error="not logged in")])
        self.assertIn("Claude", output)
        self.assertIn("unavailable", output)


if __name__ == "__main__":
    unittest.main()
