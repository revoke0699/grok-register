import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.integrations import exit_ip
from backend.registration import engine
from backend.registration import signup_flow
from backend.registration.store import RegistrationRepository
from backend.web import application


class ParseExitIpTests(unittest.TestCase):
    def test_parses_cloudflare_trace(self):
        text = "fl=100\nh=www.cloudflare.com\nip=203.0.113.10\nts=1.0\n"
        self.assertEqual(exit_ip.parse_exit_ip(text), "203.0.113.10")

    def test_parses_plain_ipv4_and_ipv6(self):
        self.assertEqual(exit_ip.parse_exit_ip(" 198.51.100.7 \n"), "198.51.100.7")
        self.assertEqual(
            exit_ip.parse_exit_ip("2606:4700:4700::1111"),
            "2606:4700:4700::1111",
        )

    def test_extracts_ipv4_from_html(self):
        self.assertEqual(
            exit_ip.parse_exit_ip("<html><body>203.0.113.44</body></html>"),
            "203.0.113.44",
        )

    def test_rejects_empty_or_invalid(self):
        self.assertEqual(exit_ip.parse_exit_ip(""), "")
        self.assertEqual(exit_ip.parse_exit_ip("not-an-ip"), "")


class FlaggedExitIpStoreTests(unittest.TestCase):
    def test_remembers_and_matches_normalized_ip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RegistrationRepository(Path(tmp) / "results.sqlite3")
            self.assertFalse(store.is_flagged_exit_ip("203.0.113.8"))
            self.assertTrue(
                store.remember_flagged_exit_ip(
                    "203.0.113.8",
                    email="risk@example.com",
                    bot_flag_source=1,
                    failure_reason="botFlagSource=1",
                )
            )
            self.assertTrue(store.is_flagged_exit_ip("203.0.113.8"))
            self.assertTrue(store.remember_flagged_exit_ip("203.0.113.8"))
            with store._connect() as conn:
                row = conn.execute(
                    "SELECT hit_count, last_email FROM flagged_exit_ips WHERE ip = ?",
                    ("203.0.113.8",),
                ).fetchone()
            self.assertEqual(row["hit_count"], 2)
            self.assertEqual(row["last_email"], "risk@example.com")
            version = None
            with store._connect() as conn:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                tables = {
                    item[0]
                    for item in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            self.assertEqual(version, 8)
            self.assertIn("flagged_exit_ips", tables)

    def test_lists_and_deletes_flagged_exit_ips(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RegistrationRepository(Path(tmp) / "results.sqlite3")
            self.assertTrue(
                store.remember_flagged_exit_ip(
                    "203.0.113.8",
                    email="first@example.com",
                    bot_flag_source=1,
                    failure_reason="botFlagSource=1",
                )
            )
            self.assertTrue(
                store.remember_flagged_exit_ip(
                    "2606:4700:4700::1111",
                    email="v6@example.com",
                )
            )
            items = store.list_flagged_exit_ips()
            by_ip = {item["ip"]: item for item in items}
            self.assertEqual(set(by_ip), {"203.0.113.8", "2606:4700:4700::1111"})
            self.assertEqual(by_ip["203.0.113.8"]["last_email"], "first@example.com")
            self.assertEqual(by_ip["203.0.113.8"]["hit_count"], 1)
            self.assertEqual(by_ip["203.0.113.8"]["last_bot_flag_source"], "1")
            self.assertTrue(store.delete_flagged_exit_ip(" 203.0.113.8 "))
            self.assertFalse(store.is_flagged_exit_ip("203.0.113.8"))
            self.assertFalse(store.delete_flagged_exit_ip("203.0.113.8"))
            remaining = store.list_flagged_exit_ips()
            self.assertEqual([item["ip"] for item in remaining], ["2606:4700:4700::1111"])


class SerializeExitIpTests(unittest.TestCase):
    def test_serialized_record_exposes_exit_ip(self):
        item = application._serialize_record(
            {
                "id": 7,
                "extra_json": '{"exit_ip": "203.0.113.8", "exit_ip_at_start": "198.51.100.1"}',
            }
        )
        self.assertEqual(item["exit_ip"], "203.0.113.8")
        self.assertEqual(item["exit_ip_at_start"], "198.51.100.1")

    def test_flagged_exit_ip_routes_are_registered(self):
        paths = {route.path for route in application.create_app().routes}
        self.assertIn("/api/flagged-exit-ips", paths)
        self.assertIn("/api/flagged-exit-ips/delete", paths)


class EnsureUnflaggedExitIpTests(unittest.TestCase):
    def setUp(self):
        exit_ip.set_current_exit_ip("")

    def tearDown(self):
        exit_ip.set_current_exit_ip("")

    def test_skips_rotation_when_ip_is_clean(self):
        store = mock.Mock()
        store.is_flagged_exit_ip.return_value = False
        restart = mock.Mock()
        logs = []
        ip = exit_ip.ensure_unflagged_exit_ip(
            store=store,
            proxy_enabled=True,
            log_callback=logs.append,
            restart=restart,
            detect=lambda: "203.0.113.20",
            sleep=lambda _: None,
        )
        self.assertEqual(ip, "203.0.113.20")
        restart.assert_not_called()
        self.assertTrue(any("不在风控名单" in item for item in logs))

    def test_restarts_until_new_unflagged_ip(self):
        store = mock.Mock()
        store.is_flagged_exit_ip.side_effect = lambda value: value == "203.0.113.1"
        ips = iter(["203.0.113.1", "203.0.113.2"])
        restart = mock.Mock()
        logs = []
        ip = exit_ip.ensure_unflagged_exit_ip(
            store=store,
            proxy_enabled=True,
            log_callback=logs.append,
            restart=restart,
            detect=lambda: next(ips),
            sleep=lambda _: None,
        )
        self.assertEqual(ip, "203.0.113.2")
        restart.assert_called_once()
        self.assertEqual(exit_ip.current_exit_ip(), "203.0.113.2")
        self.assertTrue(any("变为 203.0.113.2" in item for item in logs))

    def test_continues_when_proxy_ip_does_not_change(self):
        store = mock.Mock()
        store.is_flagged_exit_ip.return_value = True
        restart = mock.Mock()
        logs = []
        ip = exit_ip.ensure_unflagged_exit_ip(
            store=store,
            proxy_enabled=True,
            log_callback=logs.append,
            max_attempts=3,
            restart=restart,
            detect=lambda: "203.0.113.9",
            sleep=lambda _: None,
        )
        self.assertEqual(ip, "203.0.113.9")
        self.assertEqual(restart.call_count, 2)
        self.assertTrue(any("一直是 203.0.113.9" in item for item in logs))

    def test_refresh_reports_changed_exit_ip(self):
        exit_ip.set_current_exit_ip("203.0.113.1", as_start=True)
        logs = []
        ip = exit_ip.refresh_browser_exit_ip(
            log_callback=logs.append,
            reason="注册风控时",
            detect=lambda: "203.0.113.99",
        )
        self.assertEqual(ip, "203.0.113.99")
        self.assertEqual(exit_ip.current_exit_ip(), "203.0.113.99")
        self.assertEqual(exit_ip.current_start_exit_ip(), "203.0.113.1")
        self.assertTrue(any("203.0.113.1 -> 203.0.113.99" in item for item in logs))

    def test_refresh_keeps_previous_when_detect_fails(self):
        exit_ip.set_current_exit_ip("203.0.113.1", as_start=True)
        ip = exit_ip.refresh_browser_exit_ip(detect=lambda: "")
        self.assertEqual(ip, "203.0.113.1")

    def test_does_not_restart_without_proxy(self):
        store = mock.Mock()
        store.is_flagged_exit_ip.return_value = True
        restart = mock.Mock()
        ip = exit_ip.ensure_unflagged_exit_ip(
            store=store,
            proxy_enabled=False,
            restart=restart,
            detect=lambda: "203.0.113.9",
            sleep=lambda _: None,
        )
        self.assertEqual(ip, "203.0.113.9")
        restart.assert_not_called()


class RegistrationRiskExitIpTests(unittest.TestCase):
    def setUp(self):
        exit_ip.set_current_exit_ip("198.51.100.23")
        self.original = dict(engine.config)

    def tearDown(self):
        exit_ip.set_current_exit_ip("")
        engine.config.clear()
        engine.config.update(self.original)

    def test_remembers_flagged_ip_on_bot_risk(self):
        store = mock.Mock()
        store.remember_flagged_exit_ip.return_value = True
        logs = []
        exc = engine.RegistrationRiskDenied(
            "注册风控拒绝，已跳过 OAuth: botFlagSource=1",
            bot_risk=True,
            bot_flag_source=1,
        )
        with (
            mock.patch.object(engine, "get_registration_repository", return_value=store),
            mock.patch.object(
                engine._exit_ip,
                "refresh_browser_exit_ip",
                return_value="198.51.100.23",
            ),
        ):
            saved = engine.remember_registration_risk_exit_ip(
                exc, email="risk@example.com", log_callback=logs.append
            )
        self.assertTrue(saved)
        store.remember_flagged_exit_ip.assert_called_once()
        kwargs = store.remember_flagged_exit_ip.call_args
        self.assertEqual(kwargs.args[0], "198.51.100.23")
        self.assertEqual(kwargs.kwargs["email"], "risk@example.com")
        self.assertTrue(any("已记录出口 IP 198.51.100.23" in item for item in logs))

    def test_remembers_exit_ip_detected_at_risk_time(self):
        exit_ip.set_current_exit_ip("198.51.100.23", as_start=True)
        store = mock.Mock()
        store.remember_flagged_exit_ip.return_value = True
        logs = []
        exc = engine.RegistrationRiskDenied(
            "注册风控拒绝，已跳过 OAuth: botFlagSource=1",
            bot_risk=True,
            bot_flag_source=1,
        )
        with (
            mock.patch.object(engine, "get_registration_repository", return_value=store),
            mock.patch.object(
                engine._exit_ip,
                "refresh_browser_exit_ip",
                return_value="203.0.113.77",
            ),
        ):
            saved = engine.remember_registration_risk_exit_ip(
                exc, email="risk@example.com", log_callback=logs.append
            )
        self.assertTrue(saved)
        self.assertEqual(
            store.remember_flagged_exit_ip.call_args.args[0], "203.0.113.77"
        )
        self.assertTrue(
            any("203.0.113.77（打开注册页时是 198.51.100.23）" in item for item in logs)
        )

    def test_skips_remember_when_not_bot_risk(self):
        store = mock.Mock()
        exc = engine.RegistrationRiskDenied("注册风控检查失败: sso 为空")
        with mock.patch.object(engine, "get_registration_repository", return_value=store):
            saved = engine.remember_registration_risk_exit_ip(exc, email="a@b.c")
        self.assertFalse(saved)
        store.remember_flagged_exit_ip.assert_not_called()


class OpenSignupPageExitIpTests(unittest.TestCase):
    def tearDown(self):
        signup_flow._deps.pop("prepare_exit_ip", None)

    def test_checks_exit_ip_before_opening_signup(self):
        prepare = mock.Mock()
        signup_flow.configure(prepare_exit_ip=prepare)
        page = mock.Mock()
        page.url = "https://accounts.x.ai/sign-up?redirect=grok-com"
        page.wait = mock.Mock()
        browser = mock.Mock()
        browser.get_tabs.return_value = [page]
        with (
            mock.patch.object(signup_flow, "active_browser", return_value=browser),
            mock.patch.object(signup_flow, "set_browser_session") as set_session,
            mock.patch.object(signup_flow, "sleep_with_cancel"),
            mock.patch.object(signup_flow, "click_email_signup_button"),
            mock.patch.object(signup_flow, "active_page", return_value=page),
        ):
            signup_flow.open_signup_page()
        prepare.assert_called_once()
        set_session.assert_called_once()
        page.get.assert_called_once_with(
            signup_flow.SIGNUP_URL,
            wait_until="domcontentloaded",
            timeout=signup_flow.SIGNUP_NAVIGATION_TIMEOUT_MS,
        )


if __name__ == "__main__":
    unittest.main()
