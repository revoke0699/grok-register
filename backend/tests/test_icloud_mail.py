import inspect
import unittest
from unittest.mock import patch

from backend.integrations.network_checks import check_email_api
from backend.mailbox import icloud_mail
from backend.registration import engine as gr
from backend.web import application


class _Response:
    def __init__(self, payload=None, text=None, json_error=False):
        self.payload = payload
        self._text = text
        self.json_error = json_error

    def json(self):
        if self.json_error or self.payload is None:
            raise ValueError("not json")
        return self.payload

    @property
    def text(self):
        if self._text is not None:
            return self._text
        if isinstance(self.payload, (dict, list)):
            return __import__("json").dumps(self.payload)
        return "" if self.payload is None else str(self.payload)


class IcloudMailTests(unittest.TestCase):
    def setUp(self):
        self.original_config = dict(gr.config)
        icloud_mail.reset_next_email()

    def tearDown(self):
        gr.config.clear()
        gr.config.update(self.original_config)
        icloud_mail.reset_next_email()

    def test_fetch_code_reads_json_shapes(self):
        cases = [
            ({"data": {"code": "ABC-DEF"}}, "ABC-DEF"),
            ({"code": "654321"}, "654321"),
            ({"verification_code": "QWE-RTY"}, "QWE-RTY"),
            ({"data": {"verification_code": "111222"}}, "111222"),
            ({"code": 0, "data": {"data": {"code": "ZXC-VBN"}}}, "ZXC-VBN"),
        ]
        for payload, expected in cases:
            seen = {}

            def http_get(url, **kwargs):
                seen["url"] = url
                seen["timeout"] = kwargs.get("timeout")
                return _Response(payload=payload)

            with self.subTest(payload=payload):
                code = icloud_mail.fetch_code(http_get, "https://mail.veilimage.com/", "test-key")
                self.assertEqual(code, expected)
                self.assertEqual(seen["timeout"], 30)
                self.assertEqual(
                    seen["url"],
                    "https://mail.veilimage.com/api/v1/code?key=test-key",
                )

    def test_fetch_code_reads_plain_text(self):
        def http_get(url, **kwargs):
            return _Response(text="verification code: 246810", json_error=True)

        self.assertEqual(
            icloud_mail.fetch_code(http_get, "", "test-key"),
            "246810",
        )

        def bare_get(url, **kwargs):
            self.assertTrue(url.startswith(icloud_mail.API_BASE_DEFAULT))
            return _Response(text="654321", json_error=True)

        self.assertEqual(icloud_mail.fetch_code(bare_get, "  ", "test-key"), "654321")

    def test_fetch_code_returns_none_without_calling_when_key_is_empty(self):
        def http_get(url, **kwargs):
            raise AssertionError("empty code_key must not call the network")

        self.assertIsNone(icloud_mail.fetch_code(http_get, icloud_mail.API_BASE_DEFAULT, "  "))

    def test_email_key_map_rejects_length_mismatch(self):
        with self.assertRaises(Exception) as raised:
            icloud_mail.email_key_map("a@example.com, b@example.com", "test-key")
        self.assertIn("长度不一致", str(raised.exception))

        mapping = icloud_mail.email_key_map(" Fixture@Example.com ", " test-key ")
        self.assertEqual(mapping, {"fixture@example.com": "test-key"})

    def test_key_for_email_rejects_unknown_or_empty_key(self):
        mapping = {"fixture@example.com": "test-key"}
        self.assertEqual(
            icloud_mail.key_for_email("Fixture@Example.com", mapping, "", ""),
            "test-key",
        )
        with self.assertRaises(Exception) as missing:
            icloud_mail.key_for_email(
                "missing@example.com",
                mapping,
                "fixture@example.com",
                "test-key",
            )
        self.assertIn("missing@example.com", str(missing.exception))
        with self.assertRaises(Exception) as empty:
            icloud_mail.key_for_email("fixture@example.com", {}, "fixture@example.com", "  ")
        self.assertIn("为空", str(empty.exception))

    def test_suffix_only_key_is_expanded_and_full_key_is_kept(self):
        expanded = icloud_mail.key_for_email(
            "fixture@example.com",
            {},
            "fixture@example.com",
            "abcd",
        )
        self.assertTrue(expanded.startswith("mail_"))
        self.assertIn("fixture%40example.com", expanded)
        self.assertTrue(expanded.endswith("_abcd"))
        raw = "mail_keep-this-whole-string"
        self.assertEqual(
            icloud_mail.key_for_email("fixture@example.com", {}, "fixture@example.com", raw),
            raw,
        )
        self.assertEqual(
            icloud_mail.key_for_email("fixture@example.com", {}, "fixture@example.com", "test-key"),
            "test-key",
        )

    def test_wait_for_code_times_out(self):
        calls = {"n": 0}
        logs = []
        clock = {"now": 1000.0}

        def http_get(url, **kwargs):
            calls["n"] += 1
            return _Response(payload={"message": "waiting"})

        def fake_time():
            return clock["now"]

        def sleep_with_cancel(seconds, callback):
            clock["now"] += seconds

        with patch("backend.mailbox.icloud_mail.time.time", fake_time):
            with self.assertRaises(Exception) as raised:
                icloud_mail.wait_for_code(
                    http_get,
                    "fixture@example.com",
                    "test-key",
                    timeout=5,
                    poll_interval=3,
                    raise_if_cancelled=lambda callback: None,
                    sleep_with_cancel=sleep_with_cancel,
                    log_callback=logs.append,
                )
        self.assertIn("未收到验证码", str(raised.exception))
        self.assertGreaterEqual(calls["n"], 1)
        self.assertTrue(any("没有消息 id" in line and "触发邮件" in line for line in logs))

    def test_wait_for_code_default_timeout_is_60_seconds(self):
        default = inspect.signature(icloud_mail.wait_for_code).parameters["timeout"].default
        self.assertEqual(default, 60)

    def test_next_email_rotates_and_resets(self):
        self.assertEqual(
            icloud_mail.next_email("one@example.com, Two@Example.com"),
            "one@example.com",
        )
        self.assertEqual(
            icloud_mail.next_email(["one@example.com", "two@example.com"]),
            "two@example.com",
        )
        icloud_mail.reset_next_email()
        self.assertEqual(icloud_mail.next_email("one@example.com, two@example.com"), "one@example.com")

    def test_default_config_contains_icloud_fields(self):
        self.assertEqual(gr.DEFAULT_CONFIG["icloud_api_base"], "https://mail.veilimage.com")
        self.assertEqual(gr.DEFAULT_CONFIG["icloud_email"], "")
        self.assertEqual(gr.DEFAULT_CONFIG["icloud_code_key"], "")
        self.assertEqual(gr.DEFAULT_CONFIG["icloud_emails"], "")
        self.assertEqual(gr.DEFAULT_CONFIG["icloud_code_keys"], "")
        for key in ("icloud_api_base", "icloud_email", "icloud_code_key", "icloud_emails", "icloud_code_keys"):
            self.assertIn(key, application.CONFIG_PUBLIC_KEYS)
        self.assertIn("icloud_code_key", application.SENSITIVE_HINT_KEYS)
        self.assertIn("icloud_code_keys", application.SENSITIVE_HINT_KEYS)

    def test_engine_uses_configured_mailbox_without_network(self):
        gr.config["email_provider"] = "icloud"
        gr.config["icloud_email"] = "fixture@example.com"
        gr.config["icloud_emails"] = ""
        gr.config["icloud_code_key"] = "test-key"
        gr.config["icloud_code_keys"] = ""
        email, token = gr.get_email_and_token()
        self.assertEqual(email, "fixture@example.com")
        self.assertEqual(token, "_")
        self.assertEqual(gr.icloud_key_for_email(email), "test-key")

        gr.config["icloud_emails"] = "one@example.com, two@example.com"
        gr.config["icloud_code_keys"] = "test-key, test-key-2"
        icloud_mail.reset_next_email()
        self.assertEqual(gr.get_email_and_token()[0], "one@example.com")
        self.assertEqual(gr.get_email_and_token()[0], "two@example.com")
        self.assertEqual(gr.icloud_key_for_email("TWO@example.com"), "test-key-2")

        gr.config["icloud_email"] = " "
        gr.config["icloud_emails"] = ","
        with self.assertRaises(Exception) as raised:
            gr.get_email_and_token()
        self.assertIn("icloud_email", str(raised.exception))
        self.assertIn("icloud_emails", str(raised.exception))

    def test_engine_get_oai_code_polls_configured_key(self):
        gr.config["email_provider"] = "icloud"
        gr.config["icloud_api_base"] = "https://mail.veilimage.com"
        gr.config["icloud_email"] = "fixture@example.com"
        gr.config["icloud_emails"] = ""
        gr.config["icloud_code_key"] = "test-key"
        gr.config["icloud_code_keys"] = ""
        seen = {}
        logs = []

        def http_get(url, **kwargs):
            seen["url"] = url
            seen["timeout"] = kwargs.get("timeout")
            return _Response(payload={"data": {"code": "ABC-DEF"}})

        with patch.object(gr, "http_get", http_get):
            code = gr.get_oai_code(
                "_",
                "fixture@example.com",
                timeout=5,
                poll_interval=3,
                log_callback=logs.append,
            )
        self.assertEqual(code, "ABC-DEF")
        self.assertEqual(seen["url"], "https://mail.veilimage.com/api/v1/code?key=test-key")
        self.assertEqual(seen["timeout"], 30)
        self.assertTrue(any("触发邮件" in line for line in logs))

    def test_health_check_does_not_fetch_code(self):
        def http_get(*args, **kwargs):
            raise AssertionError("health check must not fetch a code")

        name, ok, detail = check_email_api(
            "icloud",
            {"icloud_email": "fixture@example.com", "icloud_code_key": "test-key"},
            http_get,
            http_get,
        )
        self.assertEqual(name, "邮箱API")
        self.assertTrue(ok)
        self.assertIn("已配置，探活不实际取码", detail)

        _, missing_ok, _missing_detail = check_email_api(
            "icloud",
            {"icloud_emails": "fixture@example.com"},
            http_get,
            http_get,
        )
        self.assertFalse(missing_ok)

    def test_config_update_keeps_icloud_provider(self):
        with patch.object(gr, "load_config", return_value=gr.config), patch.object(gr, "save_config"):
            result = application._apply_config_updates(
                {
                    "email_provider": "icloud",
                    "icloud_api_base": " https://mail.veilimage.com ",
                    "icloud_email": "fixture@example.com",
                    "icloud_code_key": "test-key",
                    "icloud_emails": "one@example.com, two@example.com",
                    "icloud_code_keys": "test-key, test-key-2",
                }
            )
        self.assertEqual(gr.config["email_provider"], "icloud")
        self.assertEqual(gr.config["icloud_api_base"], "https://mail.veilimage.com")
        self.assertEqual(gr.config["icloud_code_key"], "test-key")
        self.assertIn("icloud_code_key", result["config"]["_sensitive_keys"])


if __name__ == "__main__":
    unittest.main()
