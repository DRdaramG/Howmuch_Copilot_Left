import os
import tempfile
import unittest
from datetime import timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, call, patch

import api
import config
import main


class QuotaParsingTests(unittest.TestCase):
    def setUp(self):
        api._MEMORY_CACHE.clear()
        api._COOLDOWNS.clear()

    @patch("api.subprocess.run")

    @patch("api._request_json")
    def test_copilot_ai_credits(self, request_json, run):
        run.return_value = Mock(returncode=0, stdout="test-token\n")
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
        run.assert_called_once_with(
            ["gh", "auth", "token", "--hostname", "github.com"],
            check=False,
            capture_output=True,
            text=True,
        )

    @patch("api.subprocess.run", side_effect=FileNotFoundError)
    def test_copilot_requires_github_cli_login(self, _run):
        result = api.fetch_copilot({})

        self.assertIn("gh auth login --web", result.error)

    @patch.dict(os.environ, {"NANOGPT_API_KEY": "test-token"}, clear=False)
    @patch("api._request_json")
    def test_nanogpt_current_usage_shape(self, request_json):
        request_json.return_value = {
            "state": "active",
            "limits": {"daily": 100, "monthly": 1000},
            "daily": {
                "used": 25,
                "remaining": 75,
                "percentUsed": 0.25,
                "resetAt": 1790899200000,
            },
            "monthly": {
                "used": 400,
                "remaining": 600,
                "percentUsed": 0.4,
            },
            "period": {"currentPeriodEnd": "2026-11-01T00:00:00Z"},
        }

        result = api.fetch_nanogpt({})

        self.assertEqual([window.label for window in result.windows], ["daily", "monthly"])
        self.assertEqual([window.used_percent for window in result.windows], [25, 40])
        self.assertEqual(result.windows[0].total, 100)
        self.assertEqual(result.windows[1].resets_at, "2026-11-01T00:00:00Z")
        request_json.assert_called_once_with(
            "GET",
            "https://nano-gpt.com/api/subscription/v1/usage",
            "test-token",
            headers={"x-api-key": "test-token"},
        )

    @patch.dict(os.environ, {"NANOGPT_API_KEY": "test-token"}, clear=False)
    @patch("api._request_json")
    def test_nanogpt_legacy_usage_shape(self, request_json):
        request_json.return_value = {
            "limits": {"dailyInputTokens": 1000},
            "dailyInputTokens": {"used": 100, "remaining": 900},
        }

        result = api.fetch_nanogpt({})

        self.assertEqual(result.windows[0].label, "daily")
        self.assertEqual(result.windows[0].used_percent, 10)

    @patch.dict(os.environ, {"CLAUDE_ACCESS_TOKEN": "test-token"}, clear=False)
    @patch("api._request_json")
    def test_claude_percentage_and_scoped_limits(self, request_json):
        request_json.return_value = {
            "five_hour": {"utilization": 25, "resets_at": "soon"},
            "seven_day": {"utilization": 50},
            "limits": [
                {"kind": "session", "percent": 25},
                {"kind": "weekly_all", "percent": 50},
                {"kind": "weekly_scoped", "percent": 0},
                {"kind": "weekly_model", "percent": 10},
            ],
        }

        result = api.fetch_claude({})

        self.assertEqual([window.used_percent for window in result.windows], [25, 50, 10])
        self.assertEqual(
            [window.label for window in result.windows], ["5h", "7d", "7d model"]
        )

    @patch.dict(os.environ, {"CLAUDE_ACCESS_TOKEN": "test-token"}, clear=False)
    @patch("api._request_json")
    def test_claude_keeps_distinct_active_scoped_limits(self, request_json):
        request_json.return_value = {
            "limits": [
                {"kind": "weekly_scoped", "scope": "Opus", "percent": 10},
                {"kind": "weekly_scoped", "scope": "Fable", "percent": 20},
            ]
        }

        result = api.fetch_claude({})

        self.assertEqual(
            [window.label for window in result.windows], ["7d Opus", "7d Fable"]
        )

    @patch.dict(os.environ, {"CLAUDE_ACCESS_TOKEN": "test-token"}, clear=False)
    @patch("api._request_json")
    def test_claude_rate_limit_fallback_to_cache(self, request_json):
        import requests
        request_json.return_value = {
            "five_hour": {"utilization": 20, "resets_at": "soon"},
            "seven_day": {"utilization": 50},
        }

        first_result = api.fetch_claude({})
        self.assertIsNone(first_result.error)
        self.assertEqual(len(first_result.windows), 2)

        err_response = Mock(status_code=429)
        request_json.side_effect = requests.HTTPError(
            "429 Client Error: Too Many Requests", response=err_response
        )

        second_result = api.fetch_claude({})
        self.assertIsNone(second_result.error)
        self.assertEqual([w.used_percent for w in second_result.windows], [20, 50])
        self.assertIn("cached", second_result.plan or "")

    @patch.dict(os.environ, {"CLAUDE_ACCESS_TOKEN": "test-token"}, clear=False)
    @patch("api.Path.exists", return_value=False)
    @patch("api._request_json")
    def test_claude_rate_limit_without_cache(self, request_json, path_exists):
        import requests
        err_response = Mock(status_code=429)
        request_json.side_effect = requests.HTTPError(
            "429 Client Error: Too Many Requests", response=err_response
        )

        result = api.fetch_claude({})
        self.assertIn("rate limited", result.error or "")

    @patch.dict(os.environ, {"CODEX_ACCESS_TOKEN": "test-token"}, clear=False)

    @patch("api._request_json")
    def test_codex_separates_codex_chatgpt_and_review_limits(self, request_json):
        window = {
            "used_percent": 20,
            "limit_window_seconds": 18000,
            "reset_at": 1790846400,
        }
        request_json.return_value = {
            "plan_type": "plus",
            "rate_limit": {"primary_window": window},
            "code_review_rate_limit": {"primary_window": {**window, "used_percent": 30}},
            "chatpass": {"windows": [{**window, "used_percent": 40}]},
        }

        result = api.fetch_codex({})

        self.assertEqual(result.plan, "plus")
        self.assertEqual(
            [item.label for item in result.windows],
            ["Codex 5h", "code review 5h", "ChatGPT 5h"],
        )

    @patch.dict(os.environ, {"DEVPASS_API_KEY": "test-token"}, clear=False)
    @patch("api._request_json")
    def test_devpass_credit_windows(self, request_json):
        request_json.return_value = {
            "data": {
                "devPlan": "pro",
                "devPlanCreditsUsed": "30",
                "devPlanCreditsLimit": "100",
                "devPlanPremiumCreditsUsed": "5",
                "devPlanPremiumWeeklyLimit": "20",
            }
        }

        result = api.fetch_devpass({})

        self.assertEqual([window.used_percent for window in result.windows], [30, 25])
        self.assertEqual(result.plan, "pro")

    @patch.dict(
        os.environ,
        {
            "DEVPASS_API_KEY": "test-api-key",
            "DEVPASS_SESSION_COOKIE": (
                "__Secure-better-auth.session_token=test-session"
            )
        },
        clear=True,
    )
    @patch("api._request_json")
    def test_devpass_api_key_takes_precedence_over_session_cookie(self, request_json):
        request_json.return_value = {
            "data": {
                "devPlan": "max",
                "devPlanCreditsUsed": "45",
                "devPlanCreditsLimit": "300",
                "devPlanPremiumCreditsUsed": "10",
                "devPlanPremiumWeeklyLimit": "50",
                "devPlanPremiumWeekResetsAt": "2026-10-05T12:00:00Z",
                "devPlanExpiresAt": "2026-11-01T00:00:00Z",
            }
        }

        result = api.fetch_devpass({})

        self.assertEqual(result.plan, "max")
        self.assertEqual(
            [window.label for window in result.windows],
            ["monthly", "premium weekly"],
        )
        self.assertEqual([window.used_percent for window in result.windows], [15, 20])
        self.assertEqual(result.windows[0].resets_at, "2026-11-01T00:00:00Z")
        request_json.assert_called_once_with(
            "GET", "https://api.llmgateway.io/v1/key", "test-api-key"
        )

    @patch.dict(os.environ, {"OLLAMA_API_KEY": "test-token"}, clear=False)
    @patch("api._request_json")
    def test_ollama_cloud_usage_api(self, request_json):
        request_json.side_effect = [
            {
                "limits": {
                    "session": {"usage": 0.25},
                    "weekly": {"usage": 0.4},
                    "monthly": {"usage": 0.1},
                },
            },
            {"Plan": "pro"},
        ]

        result = api.fetch_ollama({})

        self.assertEqual(result.plan, "pro")
        self.assertEqual(
            [window.label for window in result.windows], ["5h", "weekly", "monthly"]
        )
        self.assertEqual(
            [window.used_percent for window in result.windows], [25, 40, 10]
        )
        self.assertEqual(
            request_json.call_args_list,
            [
                call("GET", api.OLLAMA_USAGE_URL, "test-token"),
                call("POST", api.OLLAMA_ACCOUNT_URL, "test-token"),
            ],
        )

    @patch.dict(
        os.environ,
        {"OLLAMA_SESSION_COOKIE": "__Secure-session=test"},
        clear=True,
    )
    @patch("api.requests.get")
    def test_ollama_settings_cookie_fallback(self, get):
        get.return_value.status_code = 200
        get.return_value.is_redirect = False
        get.return_value.text = """
            <span>Cloud Usage</span><span>Pro</span>
            <div aria-label="Session usage 18%"></div>
            <div class="local-time" data-time="2026-10-01T10:00:00Z"></div>
            <span>Weekly usage</span><span>67% used</span>
            <div class="local-time" data-time="2026-10-04T13:00:00Z"></div>
        """

        result = api.fetch_ollama({})

        self.assertEqual(result.plan, "Pro")
        self.assertEqual([window.used_percent for window in result.windows], [18, 67])
        self.assertEqual(result.windows[1].resets_at, "2026-10-04T13:00:00Z")
        get.assert_called_once_with(
            api.OLLAMA_SETTINGS_URL,
            headers={
                "Accept": "text/html",
                "Cookie": "__Secure-session=test",
                "User-Agent": "howmuch-left/1",
            },
            timeout=api.TIMEOUT,
            allow_redirects=False,
        )

    @patch.dict(
        os.environ,
        {"OLLAMA_SESSION_COOKIE": "__Secure-session=test"},
        clear=True,
    )
    @patch("api.requests.get")
    def test_ollama_settings_monthly_usage(self, get):
        get.return_value.status_code = 200
        get.return_value.is_redirect = False
        get.return_value.text = """
            <span>Included Usage</span><span>Max</span>
            <section>Monthly usage
              <span>$7.50 of $60 used</span>
              <div style="width: 12.5%"></div>
              <time data-time="2026-11-01T00:00:00Z"></time>
            </section>
        """

        result = api.fetch_ollama({})

        self.assertEqual(result.plan, "Max")
        self.assertEqual(result.windows[0].label, "monthly")
        self.assertEqual(result.windows[0].used_percent, 12.5)
        self.assertEqual(result.windows[0].used, 7.5)
        self.assertEqual(result.windows[0].total, 60)
        self.assertEqual(result.windows[0].resets_at, "2026-11-01T00:00:00Z")

    def test_ollama_settings_associates_reset_with_available_window(self):
        windows, _ = api._parse_ollama_settings(
            """
            <time data-time="unrelated"></time>
            <section>Weekly usage <span>67% used</span>
              <time data-time="2026-10-04T13:00:00Z"></time>
            </section>
            """
        )

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].label, "weekly")
        self.assertEqual(windows[0].resets_at, "2026-10-04T13:00:00Z")

    @patch.dict(
        os.environ,
        {
            "OLLAMA_API_KEY": "test-token",
            "OLLAMA_SESSION_COOKIE": "__Secure-session=test",
        },
        clear=True,
    )
    @patch(
        "api.requests.get",
        side_effect=api.requests.Timeout("settings timeout"),
    )
    @patch("api._request_json")
    def test_ollama_cookie_failure_keeps_api_usage(self, request_json, _get):
        request_json.side_effect = [
            {"limits": {"weekly": {"usage": 0.4}}},
            {"Plan": "pro"},
        ]

        result = api.fetch_ollama({})

        self.assertIsNone(result.error)
        self.assertEqual(result.windows[0].used_percent, 40)
        self.assertEqual(result.plan, "pro")

    @patch.dict(
        os.environ,
        {
            "OLLAMA_API_KEY": "test-token",
            "OLLAMA_SESSION_COOKIE": "__Secure-session=test",
        },
        clear=True,
    )
    @patch("api.requests.get")
    @patch("api._request_json")
    def test_ollama_merges_cookie_resets_with_api_windows(self, request_json, get):
        request_json.side_effect = [
            {
                "limits": {
                    "session": {"usage": 0.2},
                    "weekly": {"usage": 0.3},
                    "monthly": {"usage": 0.4},
                }
            },
            {"Plan": "pro"},
        ]
        get.return_value.status_code = 200
        get.return_value.is_redirect = False
        get.return_value.text = """
            Monthly usage <span>50% used</span>
            <time data-time="2026-11-01T00:00:00Z"></time>
        """

        result = api.fetch_ollama({})

        self.assertEqual(
            [window.label for window in result.windows], ["5h", "weekly", "monthly"]
        )
        self.assertEqual(
            [window.used_percent for window in result.windows], [20, 30, 50]
        )
        self.assertEqual(result.windows[2].resets_at, "2026-11-01T00:00:00Z")

    def test_ollama_settings_parses_reset_after_long_markup(self):
        windows, _ = api._parse_ollama_settings(
            "Weekly usage <span>0.7% used</span>"
            + ("<div></div>" * 150)
            + '<time data-time="2026-10-08T00:00:00Z"></time>'
        )

        self.assertEqual(windows[0].resets_at, "2026-10-08T00:00:00Z")

    @patch("api.subprocess.run")
    def test_antigravity_cli_usage(self, run):
        run.return_value = Mock(
            returncode=0,
            stdout=(
                "Quota:\n"
                "Gemini Models          Weekly Limit Remaining     100%  2026-10-08T09:41:32Z\n"
                "Gemini Models          Five Hour Limit Remaining  98%   2026-10-01T14:41:32Z\n"
                "Claude and GPT models  Weekly Limit Remaining     80%   2026-10-08T09:50:08Z\n"
                "Claude and GPT models  Five Hour Limit Remaining  50%   2026-10-01T14:50:08Z\n"
            ),
        )

        result = api.fetch_antigravity({})

        self.assertIsNone(result.error)
        self.assertEqual(
            [window.label for window in result.windows],
            [
                "Gemini Models weekly",
                "Gemini Models 5h",
                "Claude and GPT models weekly",
                "Claude and GPT models 5h",
            ],
        )
        self.assertEqual(
            [window.used_percent for window in result.windows],
            [0.0, 2.0, 20.0, 50.0],
        )
        self.assertEqual(result.windows[0].resets_at, "2026-10-08T09:41:32Z")

    @patch.dict(os.environ, {}, clear=True)

    def test_cloud_provider_requires_credentials(self):
        result = api.fetch_ollama({})

        self.assertEqual(
            result.error, "set OLLAMA_API_KEY or OLLAMA_SESSION_COOKIE"
        )

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

        self.assertIn("████░░░░░░ (40%)", output)
        self.assertIn("600/1500 credits", output)
        self.assertIn("┌", output)
        self.assertIn("├", output)
        self.assertIn("└", output)

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

        self.assertIn("Ollama (Pro)", output)
        self.assertIn("weekly", output)
        self.assertIn("Friday", output)


    def test_reset_is_rendered_in_local_24_hour_time(self):
        local = timezone(timedelta(hours=9))

        output = main.format_reset("2026-10-01T09:20:00+00:00", local)

        self.assertEqual(output, "2026-10-01 18:20")

    def test_millisecond_reset_timestamp_is_supported(self):
        local = timezone.utc

        output = main.format_reset("1790846400000", local)

        self.assertEqual(output, "2026-10-01 09:20")

    def test_provider_theme_wraps_output(self):
        result = api.QuotaResult("Claude", [api.QuotaWindow("5h", 18)])

        output = main.render([result], color=True)

        self.assertIn(main.PROVIDER_COLORS["claude"], output)
        self.assertIn(main.RESET, output)


class ConfigTests(unittest.TestCase):
    def test_provider_zero_is_rejected(self):
        messages = []
        provider = config._choose_provider(
            config.load(),
            lambda _: "0",
            messages.append,
        )

        self.assertIsNone(provider)
        self.assertEqual(messages[-1], "잘못된 번호입니다.")

    def test_menu_registers_key_in_private_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            answers = iter(["2", "3", "0"])

            settings = config.menu(
                path,
                input_fn=lambda _: next(answers),
                secret_input_fn=lambda _: "test-key",
                output_fn=lambda _: None,
            )

            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(settings["providers"]["nanogpt"]["token"], "test-key")
            self.assertTrue(settings["providers"]["nanogpt"]["enabled"])

    def test_menu_sets_interval_without_api_url_step(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            answers = iter(["4", "30", "0"])

            settings = config.menu(
                path,
                input_fn=lambda _: next(answers),
                output_fn=lambda _: None,
            )

            self.assertEqual(settings["refresh_interval_seconds"], 30)

    def test_menu_runs_oauth_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            answers = iter(["1", "2", "0"])
            run = Mock(return_value=Mock(returncode=0))

            settings = config.menu(
                path,
                input_fn=lambda _: next(answers),
                output_fn=lambda _: None,
                run_fn=run,
            )

            run.assert_called_once_with(["codex", "login"], check=False)
            self.assertTrue(settings["providers"]["codex"]["enabled"])

    def test_menu_authenticates_copilot_in_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            answers = iter(["1", "1", "0"])
            run = Mock(return_value=Mock(returncode=0))

            settings = config.menu(
                path,
                input_fn=lambda _: next(answers),
                output_fn=lambda _: None,
                run_fn=run,
            )

            run.assert_called_once_with(
                ["gh", "auth", "login", "--hostname", "github.com", "--web"],
                check=False,
            )
            self.assertTrue(settings["providers"]["copilot"]["enabled"])


if __name__ == "__main__":
    unittest.main()
