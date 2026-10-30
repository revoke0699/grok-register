import unittest
from unittest import mock

from backend.registration import login_flow


class _Page:
    def __init__(self, error=None):
        self.error = error
        self.url = "https://accounts.x.ai/sign-in"
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error


class LoginNavigationTests(unittest.TestCase):
    def test_navigation_waits_only_for_dom_content(self):
        page = _Page()
        with (
            mock.patch.object(login_flow, "_active_or_new_page", return_value=page),
            mock.patch.object(
                login_flow,
                "_wait_for_signin_page",
                return_value={
                    "url": page.url,
                    "ready": True,
                    "region_blocked": False,
                    "text": "Log into your account",
                },
            ),
        ):
            login_flow._navigate_signin()

        self.assertEqual(
            page.calls,
            [
                (
                    login_flow.SIGNIN_URL,
                    {
                        "wait_until": "domcontentloaded",
                        "timeout": login_flow.SIGNIN_NAVIGATION_TIMEOUT_MS,
                    },
                )
            ],
        )

    def test_navigation_timeout_is_soft_when_login_ui_is_ready(self):
        page = _Page(TimeoutError("fixture load timeout"))
        logs = []
        with (
            mock.patch.object(login_flow, "_active_or_new_page", return_value=page),
            mock.patch.object(
                login_flow,
                "_wait_for_signin_page",
                return_value={
                    "url": page.url,
                    "ready": True,
                    "region_blocked": False,
                    "text": "Log into your account",
                },
            ),
        ):
            login_flow._navigate_signin(log_callback=logs.append)

        self.assertTrue(any("登录控件已经可用" in message for message in logs))

    def test_region_block_restarts_browser_and_recovers(self):
        first = _Page()
        second = _Page()
        logs = []
        states = [
            {
                "url": first.url,
                "ready": False,
                "region_blocked": True,
                "text": "This service is not available in your region.",
            },
            {
                "url": second.url,
                "ready": True,
                "region_blocked": False,
                "text": "Log into your account",
            },
        ]
        with (
            mock.patch.object(
                login_flow,
                "_active_or_new_page",
                side_effect=[first, second],
            ) as acquire,
            mock.patch.object(
                login_flow,
                "_wait_for_signin_page",
                side_effect=states,
            ),
        ):
            login_flow._navigate_signin(log_callback=logs.append)

        self.assertFalse(acquire.call_args_list[0].kwargs["restart"])
        self.assertTrue(acquire.call_args_list[1].kwargs["restart"])
        self.assertTrue(any("代理出口地区不可用" in message for message in logs))

    def test_repeated_region_block_reports_specific_reason(self):
        page = _Page()
        state = {
            "url": page.url,
            "ready": False,
            "region_blocked": True,
            "text": "This service is not available in your region.",
        }
        with (
            mock.patch.object(login_flow, "SIGNIN_NAVIGATION_ATTEMPTS", 2),
            mock.patch.object(login_flow, "_active_or_new_page", return_value=page),
            mock.patch.object(login_flow, "_wait_for_signin_page", return_value=state),
        ):
            with self.assertRaisesRegex(RuntimeError, "代理出口地区不可用"):
                login_flow._navigate_signin()


class LoginFormTests(unittest.TestCase):
    def test_password_field_retry_uses_explicit_kind(self):
        locator = mock.Mock()
        locator.input_value.return_value = ""
        element = mock.Mock(_raw=locator)
        fresh_locator = mock.Mock()
        fresh_locator.input_value.return_value = "fixture@password"
        fresh = mock.Mock(_raw=fresh_locator)

        with mock.patch.object(
            login_flow,
            "_native_input_candidates",
            return_value=[fresh],
        ) as candidates:
            self.assertTrue(
                login_flow._type_login_value(
                    element,
                    "fixture@password",
                    kind="password",
                )
            )

        candidates.assert_called_once_with("password")

    def test_type_value_retries_when_first_input_is_dropped(self):
        # 复刻真实故障：邮箱框刚渲染，首轮输入被受控组件冲掉（读回为空），
        # 重抓句柄再输入才稳住。验证会重试而非一次失败。
        stale = mock.Mock()
        stale._raw.input_value.return_value = ""  # 首轮写入被冲掉

        settled = mock.Mock()
        # 第二轮：click/fill/press 后读回正确值。
        settled._raw.input_value.return_value = "fixture@example.com"

        # 每次 _native_input_candidates 调用返回的候选：先给 stale（读回仍空），再给 settled。
        candidate_batches = iter([[stale], [settled], [settled]])

        with (
            mock.patch.object(
                login_flow, "_native_input_candidates",
                side_effect=lambda kind: next(candidate_batches),
            ),
            mock.patch.object(login_flow.time, "sleep"),
        ):
            ok = login_flow._type_login_value(
                stale, "fixture@example.com", kind="email", attempts=4
            )

        self.assertTrue(ok)

    def test_type_value_fails_after_exhausting_attempts(self):
        dead = mock.Mock()
        dead._raw.input_value.return_value = ""

        with (
            mock.patch.object(login_flow, "_native_input_candidates", return_value=[dead]),
            mock.patch.object(login_flow.time, "sleep"),
        ):
            ok = login_flow._type_login_value(dead, "x@y.com", kind="email", attempts=3)

        self.assertFalse(ok)

    def test_existing_email_form_is_resumed_without_clicking_entry_button(self):
        email_input = mock.Mock()
        password_input = mock.Mock()
        active = mock.Mock(url="https://grok.com/")

        def inputs(kind):
            return [email_input] if kind == "email" else [password_input]

        with (
            mock.patch.object(login_flow, "_navigate_signin"),
            mock.patch.object(login_flow, "_dismiss_cookie_consent"),
            mock.patch.object(login_flow, "_native_input_candidates", side_effect=inputs),
            mock.patch.object(login_flow, "_native_click_action") as entry_click,
            mock.patch.object(login_flow, "_type_login_value", return_value=True),
            mock.patch.object(login_flow, "_click_submit", return_value=True),
            mock.patch.object(login_flow, "_prepare_login_turnstile"),
            mock.patch.object(login_flow, "_visible_login_error", return_value=""),
            mock.patch.object(login_flow, "active_page", return_value=active),
            mock.patch.object(login_flow, "_wait_for_login_sso", return_value="sso-value"),
            mock.patch.object(login_flow.time, "sleep"),
        ):
            token = login_flow.login_with_password(
                "fixture@example.com",
                "fixture-password",
            )

        self.assertEqual(token, "sso-value")
        entry_click.assert_not_called()

    def test_single_page_form_skips_next_and_submits_login(self):
        # 单页表单：填完邮箱后密码框已在场，不应点“下一步”，直接填密码并提交登录。
        email_input = mock.Mock()
        password_input = mock.Mock()
        active = mock.Mock(url="https://grok.com/")

        def inputs(kind):
            return [email_input] if kind == "email" else [password_input]

        with (
            mock.patch.object(login_flow, "_navigate_signin"),
            mock.patch.object(login_flow, "_dismiss_cookie_consent"),
            mock.patch.object(login_flow, "_reveal_email_input", return_value=[email_input]),
            mock.patch.object(login_flow, "_native_input_candidates", side_effect=inputs),
            mock.patch.object(login_flow, "_type_login_value", return_value=True),
            mock.patch.object(login_flow, "_click_submit", return_value=True) as click_submit,
            mock.patch.object(login_flow, "_prepare_login_turnstile"),
            mock.patch.object(login_flow, "_visible_login_error", return_value=""),
            mock.patch.object(login_flow, "active_page", return_value=active),
            mock.patch.object(login_flow, "_wait_for_login_sso", return_value="sso-value"),
            mock.patch.object(login_flow.time, "sleep"),
        ):
            token = login_flow.login_with_password("fixture@example.com", "pw")

        self.assertEqual(token, "sso-value")
        # 只应有一次提交（Login），不应先点“下一步”。
        click_submit.assert_called_once()
        self.assertNotIn(("下一步", "next", "continue"), [c.args[0] for c in click_submit.call_args_list])

    def test_stepwise_form_clicks_next_before_password(self):
        # 分步表单：填完邮箱后密码框尚未出现，先点“下一步”，密码框才出现。
        email_input = mock.Mock()
        password_input = mock.Mock()
        active = mock.Mock(url="https://grok.com/")
        # password 首查为空（触发点“下一步”），点击后再查已出现。
        password_states = iter([[], [password_input], [password_input]])

        def inputs(kind):
            return [email_input] if kind == "email" else next(password_states)

        with (
            mock.patch.object(login_flow, "_navigate_signin"),
            mock.patch.object(login_flow, "_dismiss_cookie_consent"),
            mock.patch.object(login_flow, "_reveal_email_input", return_value=[email_input]),
            mock.patch.object(login_flow, "_native_input_candidates", side_effect=inputs),
            mock.patch.object(login_flow, "_type_login_value", return_value=True),
            mock.patch.object(login_flow, "_click_submit", return_value=True) as click_submit,
            mock.patch.object(login_flow, "_wait_until", return_value=True),
            mock.patch.object(login_flow, "_prepare_login_turnstile"),
            mock.patch.object(login_flow, "_visible_login_error", return_value=""),
            mock.patch.object(login_flow, "active_page", return_value=active),
            mock.patch.object(login_flow, "_wait_for_login_sso", return_value="sso-value"),
            mock.patch.object(login_flow.time, "sleep"),
        ):
            token = login_flow.login_with_password("fixture@example.com", "pw")

        self.assertEqual(token, "sso-value")
        submitted_keywords = [c.args[0] for c in click_submit.call_args_list]
        # 先点“下一步”推进，再点“登录”提交。
        self.assertIn(("下一步", "next", "continue"), submitted_keywords)
        self.assertEqual(click_submit.call_count, 2)


class RevealEmailInputTests(unittest.TestCase):
    def test_click_is_retried_until_email_input_appears(self):
        # 首次点击“假成功”（框未出现），第二次点击后邮箱框才出现。
        inputs_seq = iter([[], ["email-input"]])

        with (
            mock.patch.object(
                login_flow, "_native_input_candidates", side_effect=lambda kind: next(inputs_seq)
            ),
            mock.patch.object(login_flow, "_dismiss_cookie_consent") as dismiss,
            mock.patch.object(login_flow, "_native_click_action", return_value="Login with email") as click,
            mock.patch.object(login_flow, "_wait_until", side_effect=[False, True]),
            mock.patch.object(login_flow.time, "sleep"),
        ):
            result = login_flow._reveal_email_input()

        self.assertEqual(result, ["email-input"])
        self.assertEqual(click.call_count, 2)
        # 每轮点击前都重新关闭迟到的 Cookie 横幅。
        self.assertEqual(dismiss.call_count, 2)

    def test_existing_email_input_skips_click_entirely(self):
        with (
            mock.patch.object(login_flow, "_native_input_candidates", return_value=["email-input"]),
            mock.patch.object(login_flow, "_native_click_action") as click,
        ):
            result = login_flow._reveal_email_input()

        self.assertEqual(result, ["email-input"])
        click.assert_not_called()

    def test_persistent_failure_raises_after_all_attempts(self):
        with (
            mock.patch.object(login_flow, "_native_input_candidates", return_value=[]),
            mock.patch.object(login_flow, "_dismiss_cookie_consent"),
            mock.patch.object(login_flow, "_native_click_action", return_value="Login with email") as click,
            mock.patch.object(login_flow, "_wait_until", return_value=False),
            mock.patch.object(login_flow.time, "sleep"),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                login_flow._reveal_email_input()

        self.assertIn("邮箱输入框", str(ctx.exception))
        self.assertEqual(click.call_count, login_flow.EMAIL_STEP_ATTEMPTS)


class LoginCredentialErrorTests(unittest.TestCase):
    def test_wrong_password_phrase_is_credential_error(self):
        self.assertTrue(login_flow.looks_like_invalid_credentials("Wrong email address or password."))
        self.assertEqual(
            login_flow.credential_error_from_texts(
                "Log in with your email Email Password Wrong email address or password. Login"
            ),
            "Wrong email address or password.",
        )
        with self.assertRaises(login_flow.InvalidLoginCredentials) as ctx:
            login_flow.raise_if_login_error("Wrong email address or password.")
        self.assertIn("账号或密码错误", str(ctx.exception))
        self.assertFalse(login_flow.looks_like_invalid_credentials("This service is not available in your region."))

    def test_wrong_password_raises_before_waiting_for_sso(self):
        email_input = mock.Mock()
        password_input = mock.Mock()
        active = mock.Mock(url="https://accounts.x.ai/sign-in")

        def inputs(kind):
            return [email_input] if kind == "email" else [password_input]

        with (
            mock.patch.object(login_flow, "_navigate_signin"),
            mock.patch.object(login_flow, "_dismiss_cookie_consent"),
            mock.patch.object(login_flow, "_native_input_candidates", side_effect=inputs),
            mock.patch.object(login_flow, "_type_login_value", return_value=True),
            mock.patch.object(login_flow, "_click_submit", return_value=True),
            mock.patch.object(login_flow, "_prepare_login_turnstile"),
            mock.patch.object(login_flow, "_try_sync_turnstile") as turnstile,
            mock.patch.object(
                login_flow,
                "_visible_login_error",
                return_value="Wrong email address or password.",
            ),
            mock.patch.object(login_flow, "active_page", return_value=active),
            mock.patch.object(login_flow, "_read_sso_cookie", return_value=""),
            mock.patch.object(login_flow, "_wait_for_login_sso") as wait_sso,
            mock.patch.object(login_flow.time, "sleep"),
        ):
            with self.assertRaises(login_flow.InvalidLoginCredentials) as ctx:
                login_flow.login_with_password("khumowldgn@outlook.com", "secret")

        self.assertIn("Wrong email address or password", str(ctx.exception))
        wait_sso.assert_not_called()
        turnstile.assert_not_called()

    def test_prepare_turnstile_skips_sync_when_widget_never_mounts(self):
        logs = []
        with (
            mock.patch.object(login_flow, "_login_turnstile_solved", return_value=False),
            mock.patch.object(login_flow, "_login_turnstile_mounted", return_value=False),
            mock.patch.object(login_flow, "_wait_until", return_value=False),
            mock.patch.object(login_flow, "_try_click_turnstile_frame") as click_frame,
            mock.patch.object(login_flow, "_try_sync_turnstile") as turnstile,
        ):
            login_flow._prepare_login_turnstile(log_callback=logs.append)

        click_frame.assert_called_once()
        turnstile.assert_not_called()
        self.assertTrue(any("未出现 Turnstile" in message for message in logs))

    def test_prepare_turnstile_syncs_before_login_when_widget_mounted(self):
        with (
            mock.patch.object(login_flow, "_login_turnstile_solved", return_value=False),
            mock.patch.object(login_flow, "_login_turnstile_mounted", return_value=True),
            mock.patch.object(login_flow, "_try_sync_turnstile", return_value=True) as turnstile,
        ):
            login_flow._prepare_login_turnstile()

        turnstile.assert_called_once()

    def test_prepare_turnstile_raises_when_sync_fails(self):
        with (
            mock.patch.object(login_flow, "_login_turnstile_solved", return_value=False),
            mock.patch.object(login_flow, "_login_turnstile_mounted", return_value=True),
            mock.patch.object(login_flow, "_try_sync_turnstile", return_value=False),
        ):
            with self.assertRaisesRegex(RuntimeError, "登录安全验证未通过"):
                login_flow._prepare_login_turnstile()

    def test_login_waits_for_turnstile_before_clicking_login(self):
        email_input = mock.Mock()
        password_input = mock.Mock()
        active = mock.Mock(url="https://grok.com/")
        calls = []

        def inputs(kind):
            return [email_input] if kind == "email" else [password_input]

        def prepare(log_callback=None):
            calls.append("prepare")

        def click(keywords):
            calls.append(("click", keywords[0]))
            return True

        with (
            mock.patch.object(login_flow, "_navigate_signin"),
            mock.patch.object(login_flow, "_dismiss_cookie_consent"),
            mock.patch.object(login_flow, "_native_input_candidates", side_effect=inputs),
            mock.patch.object(login_flow, "_type_login_value", return_value=True),
            mock.patch.object(login_flow, "_prepare_login_turnstile", side_effect=prepare),
            mock.patch.object(login_flow, "_click_submit", side_effect=click),
            mock.patch.object(login_flow, "_visible_login_error", return_value=""),
            mock.patch.object(login_flow, "active_page", return_value=active),
            mock.patch.object(login_flow, "_read_sso_cookie", return_value="sso-value"),
            mock.patch.object(login_flow.time, "sleep"),
        ):
            token = login_flow.login_with_password("fixture@example.com", "pw")

        self.assertEqual(token, "sso-value")
        self.assertEqual(calls[0], "prepare")
        self.assertEqual(calls[1], ("click", "登录"))

    def test_login_retries_turnstile_click_when_still_on_signin(self):
        email_input = mock.Mock()
        password_input = mock.Mock()
        active = mock.Mock(url="https://accounts.x.ai/sign-in")

        def inputs(kind):
            return [email_input] if kind == "email" else [password_input]

        with (
            mock.patch.object(login_flow, "_navigate_signin"),
            mock.patch.object(login_flow, "_dismiss_cookie_consent"),
            mock.patch.object(login_flow, "_native_input_candidates", side_effect=inputs),
            mock.patch.object(login_flow, "_type_login_value", return_value=True),
            mock.patch.object(login_flow, "_prepare_login_turnstile"),
            mock.patch.object(login_flow, "_click_submit", return_value=True) as click_submit,
            mock.patch.object(login_flow, "_login_turnstile_needs_resubmit", return_value=True),
            mock.patch.object(login_flow, "_recover_login_turnstile") as recover,
            mock.patch.object(login_flow, "_visible_login_error", return_value=""),
            mock.patch.object(login_flow, "active_page", return_value=active),
            mock.patch.object(login_flow, "_read_sso_cookie", return_value=""),
            mock.patch.object(login_flow, "_wait_for_login_sso", return_value="sso-value") as wait_sso,
            mock.patch.object(login_flow, "POST_SUBMIT_ERROR_WINDOW", 0),
            mock.patch.object(login_flow.time, "sleep"),
        ):
            token = login_flow.login_with_password("fixture@example.com", "pw")

        self.assertEqual(token, "sso-value")
        recover.assert_called()
        self.assertFalse(recover.call_args.kwargs.get("full_sync"))
        wait_sso.assert_called_once()
        self.assertTrue(wait_sso.call_args.kwargs.get("turnstile_retried"))
        click_submit.assert_called_once()

    def test_sso_wait_retries_turnstile_clicks_while_stuck(self):
        cookies = iter(["", "", "", "sso-value"])
        with (
            mock.patch.object(login_flow, "_read_sso_cookie", side_effect=lambda: next(cookies)),
            mock.patch.object(login_flow, "_visible_login_error", return_value=""),
            mock.patch.object(login_flow, "_still_on_signin", return_value=True),
            mock.patch.object(login_flow, "_should_retry_cf", return_value=True),
            mock.patch.object(login_flow, "_recover_login_turnstile") as recover,
            mock.patch.object(login_flow.time, "sleep"),
        ):
            token = login_flow._wait_for_login_sso(timeout=30)

        self.assertEqual(token, "sso-value")
        self.assertGreaterEqual(recover.call_count, 2)
        self.assertTrue(any(call.kwargs.get("full_sync") for call in recover.call_args_list))

    def test_recover_clicks_turnstile_then_submits_when_solved(self):
        with (
            mock.patch.object(login_flow, "_still_on_signin", return_value=True),
            mock.patch.object(login_flow, "_login_turnstile_solved", side_effect=[False, True]),
            mock.patch.object(login_flow, "_try_click_turnstile_frame") as click_frame,
            mock.patch.object(login_flow, "_try_sync_turnstile") as sync,
            mock.patch.object(login_flow, "_click_submit") as submit,
        ):
            login_flow._recover_login_turnstile(full_sync=False)

        click_frame.assert_called_once()
        sync.assert_not_called()
        submit.assert_called_once()

    def test_recover_full_sync_retries_turnstile_then_login(self):
        with (
            mock.patch.object(login_flow, "_still_on_signin", return_value=True),
            mock.patch.object(login_flow, "_login_turnstile_solved", return_value=False),
            mock.patch.object(login_flow, "_try_click_turnstile_frame") as click_frame,
            mock.patch.object(login_flow, "_try_sync_turnstile", return_value=True) as sync,
            mock.patch.object(login_flow, "_click_submit") as submit,
        ):
            login_flow._recover_login_turnstile(full_sync=True)

        click_frame.assert_called_once()
        sync.assert_called_once()
        submit.assert_called_once()

    def test_turnstile_mounted_js_does_not_require_visible_box(self):
        page_obj = mock.Mock()
        page_obj.run_js.return_value = True
        with mock.patch.object(login_flow, "page", page_obj):
            self.assertTrue(login_flow._login_turnstile_mounted())
        script = page_obj.run_js.call_args[0][0]
        self.assertIn("cf-turnstile-response", script)
        self.assertIn('script[src*="turnstile"]', script)
        self.assertNotIn("rect.width > 8", script)

    def test_sso_wait_raises_invalid_credentials_instead_of_timeout(self):
        with (
            mock.patch.object(login_flow, "_read_sso_cookie", return_value=""),
            mock.patch.object(
                login_flow,
                "_visible_login_error",
                return_value="Wrong email address or password.",
            ),
            mock.patch.object(login_flow.time, "sleep"),
        ):
            with self.assertRaises(login_flow.InvalidLoginCredentials):
                login_flow._wait_for_login_sso(timeout=30)

    def test_classify_failure_maps_credential_error_before_sso_timeout(self):
        from backend.registration import engine

        exc = login_flow.InvalidLoginCredentials("账号或密码错误: Wrong email address or password.")
        self.assertEqual(engine.classify_failure(exc), engine.FAIL_INVALID_CREDENTIALS)
        self.assertEqual(
            engine.classify_failure(RuntimeError("Wrong email address or password.")),
            engine.FAIL_INVALID_CREDENTIALS,
        )

    def test_login_logs_low_traffic_mode(self):
        logs = []
        email_input = mock.Mock()
        password_input = mock.Mock()
        active = mock.Mock(url="https://grok.com/")

        def inputs(kind):
            return [email_input] if kind == "email" else [password_input]

        with (
            mock.patch.object(login_flow, "_navigate_signin"),
            mock.patch.object(login_flow, "_dismiss_cookie_consent"),
            mock.patch.object(login_flow, "_native_input_candidates", side_effect=inputs),
            mock.patch.object(login_flow, "_type_login_value", return_value=True),
            mock.patch.object(login_flow, "_click_submit", return_value=True),
            mock.patch.object(login_flow, "_prepare_login_turnstile"),
            mock.patch.object(login_flow, "_visible_login_error", return_value=""),
            mock.patch.object(login_flow, "active_page", return_value=active),
            mock.patch.object(login_flow, "_read_sso_cookie", return_value="sso-value"),
            mock.patch.object(login_flow, "low_traffic_enabled", return_value=True),
            mock.patch.object(login_flow, "traffic_savings_level", return_value="more"),
            mock.patch.object(login_flow.time, "sleep"),
        ):
            token = login_flow.login_with_password(
                "fixture@example.com",
                "pw",
                log_callback=logs.append,
            )

        self.assertEqual(token, "sso-value")
        self.assertTrue(any("低流量模式" in message and "更多节省" in message for message in logs))


if __name__ == "__main__":
    unittest.main()
