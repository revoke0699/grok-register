"""iCloud 邮箱（Veilimage）渠道适配器。

邮箱不是现场生成的。主输入是多行文本，每行「基础邮箱----完整取码 URL」。
URL 必须自带 ?key= 整串。别名只在 @ 前加随机后缀，取码地址保持该行原文，
不会按别名重新计算 key。

取码仍是 GET {api_base}/api/v1/code?key={code_key}。api_base 和 code_key
从该行完整 URL 拆出来，再交给原来的 fetch_code / wait_for_code。

icloud_entries 为空时，才按旧的 icloud_email(s) / icloud_code_key(s) 配对。
两边都有时以 icloud_entries 为准。旧字段如果只给了十六进制后缀，
key_for_email 仍按对应基础邮箱补成 mail_<urlencoded邮箱>_<后缀>；
已经是整串时原样使用。
"""

from __future__ import annotations

import re
import secrets
import string
import threading
import time
from typing import Any, Callable, Dict, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, quote, urlsplit

from backend.mailbox.utilities import extract_verification_code

API_BASE_DEFAULT = "https://mail.veilimage.com"
PROVIDER_ID = "icloud"
ENTRY_SEPARATOR = "----"
CODE_PATH_SUFFIX = "/api/v1/code"
ALIAS_RETRY_LIMIT = 100
SPLIT_COUNT_ERROR = "icloud_split_count 必须是大于等于 0 的整数，不能为负数或小数"

HttpGet = Callable[..., Any]
EntryPair = Tuple[str, str]
_HEX_SUFFIX_RE = re.compile(r"^[0-9a-fA-F]+$")
_CODE_TOKEN_RE = re.compile(r"^[A-Za-z0-9-]{4,32}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
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


def parse_split_count(value) -> int:
    """解析分裂数量。

    空字符串不是整数，直接报错，不当成 0。缺省由调用方在键不存在时传入 0。
    布尔值即使是 int 的子类也拒绝。整数值的小数（如 2.0）收成整数。
    """
    if isinstance(value, bool) or value is None:
        raise Exception(SPLIT_COUNT_ERROR)
    if isinstance(value, int):
        if value < 0:
            raise Exception(SPLIT_COUNT_ERROR)
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise Exception(SPLIT_COUNT_ERROR)
        if not value.is_integer() or value < 0:
            raise Exception(SPLIT_COUNT_ERROR)
        return int(value)
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]+", text):
        raise Exception(SPLIT_COUNT_ERROR)
    return int(text)


def configured_split_count(config) -> int:
    """配置里没有 icloud_split_count 时用默认值 0；键在但值非法则报错。"""
    if not isinstance(config, dict) or "icloud_split_count" not in config:
        return 0
    return parse_split_count(config.get("icloud_split_count"))


def split_code_api_url(api_url: str) -> Tuple[str, str]:
    """从完整取码 URL 拆出 api_base 和 code_key。

    code_key 是 ?key= 的参数值（解码一次）。fetch_code 会再编码，
    因此这里不能把已经编码过的原文再原样交回去。
    不根据 key 里嵌的邮箱判断当前注册邮箱是否匹配。
    """
    raw = str(api_url or "").strip()
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.netloc:
        raise Exception("右边必须是 http(s) 完整取码地址")
    path = (parts.path or "").rstrip("/")
    if not path.lower().endswith(CODE_PATH_SUFFIX):
        raise Exception("右边的路径必须以 /api/v1/code 结尾")
    code_key = ""
    for name, value in parse_qsl(parts.query, keep_blank_values=True):
        if name == "key":
            code_key = str(value).strip()
            break
    if not code_key:
        raise Exception("右边必须包含 ?key= 后面的整串 code_key")
    prefix = path[: -len(CODE_PATH_SUFFIX)]
    api_base = f"{parts.scheme}://{parts.netloc}{prefix}".rstrip("/")
    return api_base, code_key


def parse_icloud_entries(text) -> list:
    """解析「邮箱----接口地址」多行文本。

    空行跳过。格式不对的行按原始行号集中报错，不静默丢弃。
    返回的取码地址是去掉首尾空白后的原文，不会改写 key。
    """
    errors = []
    entries = []
    raw_text = "" if text is None else str(text)
    for line_no, raw_line in enumerate(raw_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if ENTRY_SEPARATOR not in line:
            errors.append(f"第 {line_no} 行: 应为“邮箱----接口地址”")
            continue
        email_raw, url_raw = line.split(ENTRY_SEPARATOR, 1)
        email = normalize_email(email_raw)
        api_url = url_raw.strip()
        if not _EMAIL_RE.fullmatch(email):
            errors.append(f"第 {line_no} 行: 左边必须是带 @ 的邮箱地址")
            continue
        try:
            split_code_api_url(api_url)
        except Exception as exc:
            errors.append(f"第 {line_no} 行: {exc}")
            continue
        entries.append((email, api_url))
    if errors:
        raise Exception("iCloud 邮箱列表格式错误:\n" + "\n".join(errors))
    return entries


def _random_alias_suffix() -> str:
    """IC邮箱分裂：2-4 位数字加 4-6 位小写字母，总长 6-10，再打乱顺序。

    用 secrets 取随机，不用固定种子，也不按序号递增。
    """
    digit_count = 2 + secrets.randbelow(3)
    letter_count = 4 + secrets.randbelow(3)
    chars = [secrets.choice(string.digits) for _ in range(digit_count)]
    chars.extend(secrets.choice(string.ascii_lowercase) for _ in range(letter_count))
    for index in range(len(chars) - 1, 0, -1):
        swap = secrets.randbelow(index + 1)
        chars[index], chars[swap] = chars[swap], chars[index]
    return "".join(chars)


def _unique_alias(local: str, domain: str, seen: set) -> str:
    for _ in range(ALIAS_RETRY_LIMIT):
        alias = f"{local}+{_random_alias_suffix()}@{domain}"
        if alias not in seen:
            seen.add(alias)
            return alias
    raise Exception(
        f"基础邮箱 {local}@{domain} 的别名连续 {ALIAS_RETRY_LIMIT} 次都与本次展开中的邮箱重复"
    )


def _pairs_from_sequence(entries: Sequence) -> list:
    if isinstance(entries, (str, bytes)) or not isinstance(entries, (list, tuple)):
        raise Exception("expand_icloud_entries 的 entries 必须是多行文本，或 (邮箱, 取码地址) 列表")
    pairs = []
    for item in entries:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise Exception("expand_icloud_entries 的 entries 必须是多行文本，或 (邮箱, 取码地址) 列表")
        pairs.append((item[0], item[1]))
    return pairs


def _expand_pairs(bases, split_count: int) -> list:
    prepared = []
    seen = set()
    for email, url in bases:
        name = normalize_email(email)
        api_url = str(url or "").strip()
        if not name:
            raise Exception("iCloud 展开遇到空邮箱")
        if not api_url:
            raise Exception(f"邮箱 {name} 缺少取码地址")
        split_code_api_url(api_url)
        prepared.append((name, api_url))
        seen.add(name)
    if split_count == 0:
        return prepared
    expanded = []
    for name, api_url in prepared:
        if name.count("@") != 1 or name.startswith("@") or name.endswith("@"):
            raise Exception(f"基础邮箱 {name} 无法生成别名，需要带 @ 的邮箱地址")
        local, domain = name.split("@", 1)
        expanded.append((name, api_url))
        for _ in range(split_count):
            expanded.append((_unique_alias(local, domain, seen), api_url))
    return expanded


def expand_icloud_entries(entries, split_count) -> list:
    """把基础邮箱展开成注册顺序。

    entries 可以是「邮箱----接口地址」多行文本，或 (邮箱, 取码地址) 列表。
    每个基础邮箱展开为 [基础邮箱, 别名1, …, 别名N]，再按输入顺序串起来。
    别名的取码地址就是该基础邮箱的原始 URL，不会改写。
    别名若与本次展开里已有邮箱重复（不区分大小写），会重试，最多 100 次。
    """
    count = parse_split_count(split_count)
    if entries is None or isinstance(entries, str):
        bases = parse_icloud_entries("" if entries is None else entries)
    else:
        bases = _pairs_from_sequence(entries)
    return _expand_pairs(bases, count)


def legacy_code_url(api_base: str, code_key: str) -> str:
    base = str(api_base or "").strip().rstrip("/") or API_BASE_DEFAULT
    return f"{base}{CODE_PATH_SUFFIX}?key={quote(str(code_key).strip(), safe='')}"


def _api_base_from_config(config: dict) -> str:
    base = str(config.get("icloud_api_base", "") or "").strip().rstrip("/")
    return base or API_BASE_DEFAULT


def legacy_base_entries(emails, keys, single_email, single_key, api_base: str) -> list:
    """旧配置按位置配对。逗号列表非空时优先于单个邮箱。"""
    email_list = parse_emails(emails)
    if email_list:
        mapping = email_key_map(emails, keys)
        return [
            (email, legacy_code_url(api_base, resolve_code_key(email, mapping[email])))
            for email in email_list
        ]
    single = normalize_email(single_email)
    if not single:
        raise Exception("请在配置里填 icloud_email 或 icloud_emails")
    return [(single, legacy_code_url(api_base, resolve_code_key(single, single_key)))]


def base_entries_from_config(config) -> list:
    """得到展开前的基础邮箱。

    icloud_entries 去空白后非空时只认它，不再回退旧字段。
    同时检查分裂数量。这里不生成别名，也不访问取码接口。
    """
    data = config if isinstance(config, dict) else {}
    problems = []
    try:
        configured_split_count(data)
    except Exception as exc:
        problems.append(str(exc))
    entries = None
    try:
        raw_entries = data.get("icloud_entries", "")
        if str(raw_entries or "").strip():
            entries = parse_icloud_entries(raw_entries)
            if not entries:
                raise Exception("icloud_entries 没有可用的邮箱行")
        else:
            entries = legacy_base_entries(
                data.get("icloud_emails", ""),
                data.get("icloud_code_keys", ""),
                data.get("icloud_email", ""),
                data.get("icloud_code_key", ""),
                _api_base_from_config(data),
            )
    except Exception as exc:
        problems.append(str(exc))
    if problems:
        raise Exception("\n".join(problems))
    return entries or []


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
