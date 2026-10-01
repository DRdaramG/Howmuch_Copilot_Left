import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import api
import config
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

    @patch.dict(os.environ, {"OLLAMA_API_KEY": "test-token"}, clear=False)
    @patch("api._request_json")
    def test_ollama_cloud_plan_windows_and_resets(self, request_json):
        request_json.return_value = {
            "subscription": {"plan": "Pro"},
            "windows": {
                "five_hour": {
                    "used": 25,
                    "limit": 100,
                    "resets_at": "2026-10-01T10:00:00Z",
                },
                "weekly": {"percent_used": 40, "reset_at": "next week"},
            },
        }

        result = api.fetch_ollama({"url": "https://example.test/usage"})

        self.assertEqual(result.plan, "Pro")
        self.assertEqual([window.label for window in result.windows], ["5h", "weekly"])
        self.assertEqual(result.windows[0].resets_at, "2026-10-01T10:00:00Z")

    @patch.dict(
        os.environ, {"ANTIGRAVITY_ACCESS_TOKEN": "test-token"}, clear=False
    )
    @patch("api._request_json")
    def test_antigravity_quota_list(self, request_json):
        request_json.return_value = {
            "tier": "Ultra",
            "quotas": [
                {
                    "name": "weekly",
                    "remaining": 75,
                    "total": 100,
                    "next_reset": "Friday",
                }
            ],
        }

        result = api.fetch_antigravity({"url": "https://example.test/quota"})

        self.assertEqual(result.plan, "Ultra")
        self.assertEqual(result.windows[0].used_percent, 25)
        self.assertEqual(result.windows[0].resets_at, "Friday")

    @patch.dict(os.environ, {}, clear=True)
    def test_cloud_provider_requires_credentials(self):
        result = api.fetch_ollama({})

        self.assertEqual(result.error, "set OLLAMA_API_KEY")

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

    def test_plan_and_reset_are_rendered(self):
        result = api.QuotaResult(
            "Ollama",
            [api.QuotaWindow("weekly", 10, resets_at="Friday")],
            plan="Pro",
        )

        output = main.render([result])

        self.assertIn("Ollama (Pro) weekly", output)
        self.assertIn("resets Friday", output)


class ConfigTests(unittest.TestCase):
    def test_menu_registers_key_in_private_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            answers = iter(["3", "4", "0"])

            settings = config.menu(
                path,
                input_fn=lambda _: next(answers),
                secret_input_fn=lambda _: "test-key",
                output_fn=lambda _: None,
            )

            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(settings["providers"]["nanogpt"]["token"], "test-key")
            self.assertTrue(settings["providers"]["nanogpt"]["enabled"])

    def test_menu_sets_api_url_and_interval(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            answers = iter(["1", "5", "https://example.test/usage", "5", "30", "0"])

            settings = config.menu(
                path,
                input_fn=lambda _: next(answers),
                output_fn=lambda _: None,
            )

            self.assertEqual(
                settings["providers"]["ollama"]["url"],
                "https://example.test/usage",
            )
            self.assertTrue(settings["providers"]["ollama"]["enabled"])
            self.assertEqual(settings["refresh_interval_seconds"], 30)

    def test_menu_runs_oauth_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            answers = iter(["2", "1", "0"])
            run = Mock(return_value=Mock(returncode=0))

            settings = config.menu(
                path,
                input_fn=lambda _: next(answers),
                output_fn=lambda _: None,
                run_fn=run,
            )

            run.assert_called_once_with(["codex", "login"], check=False)
            self.assertTrue(settings["providers"]["codex"]["enabled"])


if __name__ == "__main__":
    unittest.main()
