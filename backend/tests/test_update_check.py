import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from backend.shared import version as app_version
from backend.web import application
from backend.web.update_check import (
    DEFAULT_CHECK_INTERVAL_SECONDS,
    LATEST_RELEASE_API,
    STATUS_CHECK_FAILED,
    STATUS_UPDATE_AVAILABLE,
    STATUS_UP_TO_DATE,
    ReleaseUpdateService,
    compare_semantic_versions,
    parse_semantic_version,
)


class ReleaseUpdateServiceTests(unittest.TestCase):
    def test_default_check_interval_is_fifteen_minutes(self):
        self.assertEqual(DEFAULT_CHECK_INTERVAL_SECONDS, 15 * 60)

    def test_check_finds_new_github_release(self):
        captured = {}

        def fetcher(url, headers, timeout):
            captured.update(url=url, headers=dict(headers), timeout=timeout)
            return {
                "tag_name": "v1.2.0",
                "html_url": "https://github.test/releases/tag/v1.2.0",
                "body": "Release notes",
            }

        service = ReleaseUpdateService("v1.1.0", fetcher=fetcher)
        snapshot = service.check()

        self.assertEqual(snapshot["status"], STATUS_UPDATE_AVAILABLE)
        self.assertTrue(snapshot["updateAvailable"])
        self.assertEqual(snapshot["latestVersion"], "v1.2.0")
        self.assertEqual(snapshot["releaseNotes"], "Release notes")
        self.assertTrue(snapshot["checkedAt"])
        self.assertEqual(captured["url"], LATEST_RELEASE_API)
        self.assertEqual(captured["headers"]["User-Agent"], "grok-register/v1.1.0")
        self.assertEqual(captured["timeout"], 10)

    def test_equal_release_is_up_to_date(self):
        service = ReleaseUpdateService(
            "v1.1.0",
            fetcher=lambda *_args: {"tag_name": "1.1.0", "body": ""},
        )
        snapshot = service.check()
        self.assertEqual(snapshot["status"], STATUS_UP_TO_DATE)
        self.assertFalse(snapshot["updateAvailable"])

    def test_failure_keeps_last_successful_release(self):
        calls = iter(
            [
                {"tag_name": "v1.2.0", "body": "Known release"},
                RuntimeError("network down"),
            ]
        )

        def fetcher(*_args):
            value = next(calls)
            if isinstance(value, Exception):
                raise value
            return value

        service = ReleaseUpdateService("v1.1.0", fetcher=fetcher)
        first = service.check()
        second = service.check()

        self.assertEqual(first["status"], STATUS_UPDATE_AVAILABLE)
        self.assertEqual(second["status"], STATUS_CHECK_FAILED)
        self.assertEqual(second["latestVersion"], "v1.2.0")
        self.assertTrue(second["updateAvailable"])
        self.assertIn("network down", second["error"])

    def test_semantic_version_supports_project_hotfix_order(self):
        base = parse_semantic_version("v1.0.0")
        hotfix1 = parse_semantic_version("v1.0.0-hotfix.1")
        hotfix2 = parse_semantic_version("v1.0.0-hotfix.2")
        next_version = parse_semantic_version("v1.0.1")
        self.assertIsNotNone(base)
        self.assertIsNotNone(hotfix1)
        self.assertIsNotNone(hotfix2)
        self.assertIsNotNone(next_version)
        self.assertGreater(compare_semantic_versions(hotfix1, base), 0)
        self.assertGreater(compare_semantic_versions(hotfix2, hotfix1), 0)
        self.assertGreater(compare_semantic_versions(next_version, hotfix2), 0)
        self.assertIsNone(parse_semantic_version("dev"))

    def test_background_service_checks_immediately_on_start(self):
        called = threading.Event()

        def fetcher(*_args):
            called.set()
            return {"tag_name": "v1.0.0", "body": ""}

        service = ReleaseUpdateService("v1.0.0", fetcher=fetcher)
        service.start()
        try:
            self.assertTrue(called.wait(1), "后台版本检测没有立即启动")
        finally:
            service.stop()
        self.assertEqual(service.snapshot()["status"], STATUS_UP_TO_DATE)


class ApplicationVersionTests(unittest.TestCase):
    def test_environment_version_overrides_version_file(self):
        with mock.patch.dict(os.environ, {"GROK_REGISTER_VERSION": "v9.8.7"}):
            self.assertEqual(app_version.current_version(), "v9.8.7")

    def test_version_file_is_used_without_environment_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "VERSION").write_text("v2.3.4\n", encoding="utf-8")
            with (
                mock.patch.dict(os.environ, {}, clear=True),
                mock.patch.object(app_version, "PROJECT_ROOT", Path(tmp)),
                mock.patch.object(app_version.Path, "cwd", return_value=Path(tmp)),
            ):
                self.assertEqual(app_version.current_version(), "v2.3.4")

    def test_application_registers_version_endpoints(self):
        with mock.patch.object(application, "current_version", return_value="v1.0.0"):
            app = application.create_app()
        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/system/version", paths)
        self.assertIn("/api/system/update/check", paths)
        self.assertEqual(app.version, "v1.0.0")


if __name__ == "__main__":
    unittest.main()
