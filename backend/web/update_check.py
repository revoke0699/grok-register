"""GitHub Release 版本检测与内存快照。

服务启动后立即检查一次，之后按固定间隔复查。这里只负责发现新版本和返回
Release 信息；镜像拉取与容器重建仍由部署侧执行。
"""

from __future__ import annotations

import datetime as _datetime
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional


LATEST_RELEASE_API = (
    "https://api.github.com/repos/kaibush/grok-register/releases/latest"
)
RELEASE_TAG_URL = "https://github.com/kaibush/grok-register/releases/tag/"
MAX_RELEASE_BYTES = 1 << 20
MAX_NOTES_CHARS = 4096
DEFAULT_CHECK_INTERVAL_SECONDS = 15 * 60

STATUS_UNCHECKED = "unchecked"
STATUS_UP_TO_DATE = "up_to_date"
STATUS_UPDATE_AVAILABLE = "update_available"
STATUS_CHECK_FAILED = "check_failed"

ReleaseFetcher = Callable[[str, Mapping[str, str], float], Mapping[str, Any]]


@dataclass(frozen=True)
class SemanticVersion:
    major: int
    minor: int
    patch: int
    prerelease: str = ""


_SEMVER_PATTERN = re.compile(
    r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)


def parse_semantic_version(value: object) -> Optional[SemanticVersion]:
    match = _SEMVER_PATTERN.fullmatch(str(value or "").strip())
    if not match:
        return None
    return SemanticVersion(
        major=int(match.group(1)),
        minor=int(match.group(2)),
        patch=int(match.group(3)),
        prerelease=str(match.group(4) or ""),
    )


def _project_hotfix(value: str) -> Optional[int]:
    match = re.fullmatch(r"hotfix\.(0|[1-9]\d*)", str(value or ""))
    return int(match.group(1)) if match else None


def compare_semantic_versions(left: SemanticVersion, right: SemanticVersion) -> int:
    for lhs, rhs in (
        (left.major, right.major),
        (left.minor, right.minor),
        (left.patch, right.patch),
    ):
        if lhs != rhs:
            return 1 if lhs > rhs else -1
    if left.prerelease == right.prerelease:
        return 0
    left_hotfix = _project_hotfix(left.prerelease)
    right_hotfix = _project_hotfix(right.prerelease)
    if left_hotfix is not None and right_hotfix is not None:
        return 1 if left_hotfix > right_hotfix else -1
    if left_hotfix is not None:
        return 1
    if right_hotfix is not None:
        return -1
    if not left.prerelease:
        return 1
    if not right.prerelease:
        return -1
    return (left.prerelease > right.prerelease) - (
        left.prerelease < right.prerelease
    )


def _utc_now_text() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat(
        timespec="seconds"
    )


def _default_fetcher(
    url: str,
    headers: Mapping[str, str],
    timeout: float,
) -> Mapping[str, Any]:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 0) or response.getcode() or 0)
            if status != 200:
                raise RuntimeError(f"GitHub Release 检查失败（HTTP {status}）")
            data = response.read(MAX_RELEASE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"GitHub Release 检查失败（HTTP {int(exc.code or 0)}）"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"检查 GitHub Release 失败: {exc.reason}") from exc
    if len(data) > MAX_RELEASE_BYTES:
        raise RuntimeError("GitHub Release 响应超过安全上限")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"解析 GitHub Release 响应失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub Release 响应格式错误")
    return payload


class ReleaseUpdateService:
    """线程安全的 Release 检测服务。"""

    def __init__(
        self,
        current_version: str,
        *,
        fetcher: Optional[ReleaseFetcher] = None,
        interval_seconds: float = DEFAULT_CHECK_INTERVAL_SECONDS,
        request_timeout: float = 10,
    ) -> None:
        self.current_version = str(current_version or "").strip() or "dev"
        self.fetcher = fetcher or _default_fetcher
        self.interval_seconds = max(float(interval_seconds or 0), 1)
        self.request_timeout = max(float(request_timeout or 0), 1)
        self._condition = threading.Condition(threading.RLock())
        self._checking = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._snapshot: Dict[str, Any] = {
            "currentVersion": self.current_version,
            "latestVersion": "",
            "updateAvailable": False,
            "status": STATUS_UNCHECKED,
            "checkedAt": None,
            "releaseUrl": "",
            "releaseNotes": "",
            "error": "",
        }

    def snapshot(self) -> Dict[str, Any]:
        with self._condition:
            return dict(self._snapshot)

    def check(self) -> Dict[str, Any]:
        with self._condition:
            if self._checking:
                self._condition.wait_for(lambda: not self._checking)
                return dict(self._snapshot)
            self._checking = True
        try:
            payload = self.fetcher(
                LATEST_RELEASE_API,
                {
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"grok-register/{self.current_version}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                self.request_timeout,
            )
            tag = str(payload.get("tag_name") or "").strip()
            if not tag:
                raise RuntimeError("GitHub Release 未返回版本号")
            current = parse_semantic_version(self.current_version)
            latest = parse_semantic_version(tag)
            if current is None or latest is None:
                raise RuntimeError("当前版本或最新版本不是有效的语义化版本，无法比较")
            release_url = str(payload.get("html_url") or "").strip()
            if not release_url:
                release_url = RELEASE_TAG_URL + urllib.parse.quote(tag, safe="")
            notes = str(payload.get("body") or "").strip()[:MAX_NOTES_CHARS]
            available = compare_semantic_versions(latest, current) > 0
            next_snapshot = {
                "currentVersion": self.current_version,
                "latestVersion": tag,
                "updateAvailable": available,
                "status": (
                    STATUS_UPDATE_AVAILABLE if available else STATUS_UP_TO_DATE
                ),
                "checkedAt": _utc_now_text(),
                "releaseUrl": release_url,
                "releaseNotes": notes,
                "error": "",
            }
            with self._condition:
                self._snapshot = next_snapshot
        except Exception as exc:
            with self._condition:
                self._snapshot = {
                    **self._snapshot,
                    "status": STATUS_CHECK_FAILED,
                    "error": str(exc)[:500],
                }
        finally:
            with self._condition:
                self._checking = False
                self._condition.notify_all()
        return self.snapshot()

    def start(self) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="github-release-check",
                daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        self.check()
        while not self._stop_event.wait(self.interval_seconds):
            self.check()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=min(self.request_timeout + 2, 15))
        with self._condition:
            self._thread = None
