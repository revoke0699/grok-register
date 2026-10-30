"""iCloud 邮箱（Veilimage）渠道适配器。

邮箱不是现场生成的，使用用户事先在 Veilimage 准备好的 iCloud 邮箱。
取码接口：GET {api_base}/api/v1/code?key={code_key}

code_key 是取码链接里 ?key= 后面的整串，形如
mail_<urlencoded邮箱>_<十六进制后缀>。
配置里如果只给了十六进制后缀，key_for_email 会按当前邮箱补成上述整串；
已经是整串时原样使用，不会再用邮箱去拼接。
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote

from backend.mailbox.utilities import extract_verification_code

API_BASE_DEFAULT = "https://mail.veilimage.com"
PROVIDER_ID = "icloud"

HttpGet = Callable[..., Any]
_HEX_SUFFIX_RE = re.compile(r"^[0-9a-fA-F]+$")
_CODE_TOKEN_RE = re.compile(r"^[A-Za-z0-9-]{4,32}$")
_PLACEHOLDER_CODES = {"null", "none", "false", "true", "undefined"}

_next_email_index = 0
_next_email_lock = threading.Lock()


def normalize_email(email: str) -> str:
    return "".join(str(email or "").split()).lower()


def _split_csv(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw_items = list(value)
    else:
        raw_items = re.split(r"[,，]", str(value))
    return [str(item).strip() for item in raw_items if str(item).strip()]


def parse_emails(emails) -> list:
    result = []
    for item in _split_csv(emails):
        normalized = normalize_email(item)
        if normalized:
            result.append(normalized)
    return result


def email_key_map(emails, keys) -> Dict[str, str]:
    """把邮箱列表和 code_key 列表按顺序配成字典。

    邮箱统一转小写并去掉空白。两边数量不一致时抛错，避免错位取码。
    """
    email_list = parse_emails(emails)
    key_list = _split_csv(keys)
    if len(email_list) != len(key_list):
        raise Exception(
            "icloud_emails 与 icloud_code_keys 长度不一致: "
            f"{len(email_list)} 个邮箱，{len(key_list)} 个 code_key"
        )
    return {email: key for email, key in zip(email_list, key_list)}


def resolve_code_key(email: str, raw_key: str) -> str:
    """得到可直接放进 ?key= 的完整 code_key。

    整串原样返回。只有纯十六进制、且没有 mail_ 前缀时，才视为“只给了后缀”，
    拼成 mail_<urlencoded邮箱>_<后缀>。
    """
    key = str(raw_key or "").strip()
    normalized = normalize_email(email)
    if not key:
        raise Exception(f"邮箱 {normalized or email} 的 iCloud code_key 为空，拒绝取码")
    if key.lower().startswith("mail_") or not _HEX_SUFFIX_RE.fullmatch(key):
        return key
    encoded = quote(normalized, safe="")
    return f"mail_{encoded}_{key}"


def key_for_email(email, mapping, single_email, single_key) -> str:
    """按邮箱找 code_key。找不到或 key 为空时抛错，不拿空 key 去调接口。"""
    normalized = normalize_email(email)
    if not normalized:
        raise Exception("iCloud 取码缺少邮箱，无法匹配 code_key")
    table: Dict[str, str] = {}
    if isinstance(mapping, dict):
        for raw_email, raw_value in mapping.items():
            name = normalize_email(raw_email)
            if name:
                table[name] = "" if raw_value is None else str(raw_value).strip()
    raw = None
    if normalized in table:
        raw = table[normalized]
    else:
        single = normalize_email(single_email)
        if single and single == normalized:
            raw = "" if single_key is None else str(single_key).strip()
    if raw is None:
        raise Exception(
            f"未找到邮箱 {normalized} 的 iCloud code_key，"
            "请在配置里填写 icloud_code_key 或 icloud_code_keys"
        )
    return resolve_code_key(normalized, raw)


def _as_code(value) -> Optional[str]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (dict, list)):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not float(value).is_integer():
            return None
        text = str(int(value))
    else:
        text = str(value).strip()
    if not text or text.lower() in _PLACEHOLDER_CODES:
        return None
    if text[0] in "{[":
        return extract_verification_code(text)
    extracted = extract_verification_code(text)
    if extracted:
        return extracted
    if _CODE_TOKEN_RE.fullmatch(text):
        return text
    return None


def _dig(payload, *path):
    current = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _code_from_payload(payload) -> Optional[str]:
    if isinstance(payload, (str, int, float)):
        return _as_code(payload)
    if not isinstance(payload, dict):
        return None
    for path in (
        ("data", "code"),
        ("code",),
        ("verification_code",),
        ("data", "verification_code"),
        ("data", "data", "code"),
    ):
        code = _as_code(_dig(payload, *path))
        if code:
            return code
    return None


def _response_text(resp) -> str:
    if resp is None:
        return ""
    text = getattr(resp, "text", "")
    if callable(text):
        try:
            text = text()
        except Exception:
            return ""
    if text is None:
        return ""
    return str(text)


def _response_payload(resp):
    if resp is None:
        return None
    json_method = getattr(resp, "json", None)
    if not callable(json_method):
        return None
    try:
        return json_method()
    except Exception:
        return None


def _code_from_response(resp) -> Optional[str]:
    payload = _response_payload(resp)
    if payload is not None:
        code = _code_from_payload(payload)
        if code:
            return code
    text = _response_text(resp)
    code = _as_code(text)
    if code:
        return code
    return extract_verification_code(text)


def fetch_code(http_get: HttpGet, api_base: str, code_key: str) -> Optional[str]:
    """GET 取码。解析不到验证码时返回 None，不因响应形状抛错。"""
    key = str(code_key or "").strip()
    if not key:
        return None
    base = str(api_base or "").strip().rstrip("/") or API_BASE_DEFAULT
    url = f"{base}/api/v1/code?key={quote(key, safe='')}"
    resp = http_get(url, timeout=30)
    return _code_from_response(resp)


def _redact_key(message: str, key: str) -> str:
    text = str(message)
    quoted = quote(key, safe="") if key else ""
    for secret in (key, quoted):
        if secret:
            text = text.replace(secret, "***")
    return text


def wait_for_code(
    http_get: HttpGet,
    email: str,
    code_key: str,
    *,
    timeout: int = 60,
    poll_interval: int = 3,
    raise_if_cancelled: Callable[[Optional[Callable[[], bool]]], None],
    sleep_with_cancel: Callable[[float, Optional[Callable[[], bool]]], None],
    log_callback: Optional[Callable[[str], None]] = None,
    cancel_callback: Optional[Callable[[], bool]] = None,
    api_base: str = "",
) -> str:
    """轮询最新验证码。

    这个接口没有消息 id，返回的是当前最新验证码，不能去重。
    调用时机应在注册流程触发邮件之后。
    """
    key = str(code_key or "").strip()
    if not key:
        raise Exception("iCloud code_key 为空，拒绝取码")
    deadline = time.time() + timeout
    if log_callback:
        log_callback(
            "[Debug] iCloud 取码接口返回最新验证码，没有消息 id，不能去重。"
            "请在注册触发邮件之后再开始轮询。"
        )
    while time.time() < deadline:
        raise_if_cancelled(cancel_callback)
        try:
            code = fetch_code(http_get, api_base, key)
        except Exception as exc:
            if log_callback:
                log_callback(f"[Debug] iCloud 取码失败: {_redact_key(exc, key)}")
            sleep_with_cancel(poll_interval, cancel_callback)
            continue
        if code:
            if log_callback:
                log_callback(f"[*] iCloud 从取码接口提取到验证码: {code}")
            return code
        sleep_with_cancel(poll_interval, cancel_callback)
    raise Exception(f"iCloud 在 {timeout}s 内未收到验证码")


def reset_next_email() -> None:
    global _next_email_index
    with _next_email_lock:
        _next_email_index = 0


def next_email(emails) -> str:
    """按模块级计数器轮流返回下一个已配置邮箱。"""
    global _next_email_index
    items = parse_emails(emails)
    if not items:
        raise Exception("请在配置里填 icloud_email 或 icloud_emails")
    with _next_email_lock:
        index = _next_email_index % len(items)
        _next_email_index += 1
    return items[index]
