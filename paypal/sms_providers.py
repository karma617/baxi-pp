"""SMS provider integrations for web OTP automation."""
from __future__ import annotations

import re
import json
import threading
import time
from dataclasses import dataclass
from typing import Callable

import httpx
from loguru import logger


DEFAULT_HEROSMS_URL = "https://hero-sms.com/stubs/handler_api.php"
DEFAULT_SMSBOWER_URL = "https://smsbower.page/stubs/handler_api.php"
DEFAULT_SERVICE = "ot"
DEFAULT_COUNTRY = "73"
DEFAULT_TIMEOUT_SECONDS = 60


def normalize_sms_provider(value: str) -> str:
    provider = (value or "manual").strip().lower().replace("-", "").replace("_", "")
    if provider in {"manual", ""}:
        return "manual"
    if provider in {"herosms", "hero"}:
        return "herosms"
    if provider in {"smsbower", "smsbrower", "bower", "brower"}:
        return "smsbower"
    raise ValueError("接码方式只能是 manual、herosms 或 smsbrower")


def normalize_phone(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) < 8:
        return ""
    return f"+{digits}"


def extract_sms_code(text: str) -> str:
    match = re.search(r"\b(\d{4,8})\b", str(text or ""))
    return match.group(1) if match else ""


@dataclass
class SmsProviderConfig:
    provider: str = "manual"
    api_key: str = ""
    base_url: str = ""
    service: str = DEFAULT_SERVICE
    country: str = DEFAULT_COUNTRY
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_payload(cls, payload: dict) -> "SmsProviderConfig":
        provider = normalize_sms_provider(str(payload.get("sms_provider", "manual") or "manual"))
        if provider == "manual":
            return cls(provider="manual")
        prefix = "herosms" if provider == "herosms" else "smsbower"
        timeout_raw = payload.get("sms_timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        try:
            timeout_seconds = int(timeout_raw or DEFAULT_TIMEOUT_SECONDS)
        except Exception:
            timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        timeout_seconds = max(15, min(timeout_seconds, 300))
        default_url = DEFAULT_HEROSMS_URL if provider == "herosms" else DEFAULT_SMSBOWER_URL
        return cls(
            provider=provider,
            api_key=str(payload.get(f"{prefix}_api_key", "") or "").strip(),
            base_url=str(payload.get(f"{prefix}_base_url", "") or "").strip() or default_url,
            service=str(payload.get(f"{prefix}_service", "") or "").strip() or DEFAULT_SERVICE,
            country=str(payload.get(f"{prefix}_country", "") or "").strip() or DEFAULT_COUNTRY,
            timeout_seconds=timeout_seconds,
        )

    @property
    def enabled(self) -> bool:
        return self.provider != "manual"

    def validate(self) -> None:
        if not self.enabled:
            return
        if not self.api_key:
            raise ValueError(f"{self.provider} API Key 不能为空")
        if not (self.base_url.startswith("http://") or self.base_url.startswith("https://")):
            raise ValueError(f"{self.provider} API 地址必须以 http:// 或 https:// 开头")

    def reuse_key(self) -> tuple[str, str, str, str]:
        return (self.base_url, self.api_key, self.service, self.country)


class SmsActivateClient:
    """Small SMS-Activate style client used by Hero-SMS and SMSBower."""

    def __init__(self, config: SmsProviderConfig):
        self.config = config

    def _request(self, action: str, params: dict | None = None) -> str:
        query = {"api_key": self.config.api_key, "action": action}
        if params:
            query.update(params)
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                with httpx.Client(timeout=30.0, trust_env=False) as client:
                    resp = client.get(self.config.base_url, params=query)
                resp.raise_for_status()
                return (resp.text or "").strip()
            except Exception as exc:
                last_exc = exc
                if attempt < 3:
                    time.sleep(2)
        raise RuntimeError(f"{self.config.provider} {action} failed: {last_exc}")

    def get_countries(self) -> list[dict[str, str]]:
        try:
            resp = self._request("getCountries")
        except Exception:
            resp = ""
        countries = parse_sms_countries(resp)
        if countries or self.config.provider != "herosms":
            return countries
        try:
            prices = self._request("getPrices")
        except Exception:
            return []
        return parse_sms_price_countries(prices)

    def get_services(self, country: str = "") -> list[dict[str, str]]:
        params = {"country": country} if country else {}
        if self.config.provider == "smsbower":
            try:
                resp = self._request("getServicesList")
                services = parse_sms_services(resp)
                if services:
                    return services
            except Exception:
                pass
            return []
        if self.config.provider == "herosms":
            service_names: list[dict[str, str]] = []
            try:
                resp = self._request("getServicesList")
                service_names = parse_sms_services(resp)
            except Exception:
                service_names = []
            try:
                prices = self._request("getPrices", params)
                price_services = parse_sms_price_services(prices, country)
            except Exception:
                price_services = []
            return merge_sms_service_labels(service_names, price_services)
        try:
            resp = self._request("getServices", params)
            services = parse_sms_services(resp)
            if services:
                return services
        except Exception:
            pass
        try:
            prices = self._request("getPrices", params)
        except Exception:
            return []
        return parse_sms_price_services(prices, country)

    def get_number(self) -> tuple[str, str]:
        resp = self._request(
            "getNumber",
            {"service": self.config.service, "country": self.config.country},
        )
        if resp.startswith("ACCESS_NUMBER:"):
            parts = resp.split(":")
            if len(parts) >= 3:
                phone = normalize_phone(parts[2])
                activation_id = parts[1].strip()
                if phone and activation_id:
                    return phone, activation_id
        raise RuntimeError(f"{self.config.provider} 获取手机号失败: {resp[:120]}")

    def wait_code(self, activation_id: str, timeout_seconds: int) -> str:
        deadline = time.monotonic() + max(1, int(timeout_seconds or DEFAULT_TIMEOUT_SECONDS))
        while time.monotonic() < deadline:
            resp = self._request("getStatus", {"id": activation_id})
            if resp.startswith("STATUS_OK:"):
                code = extract_sms_code(resp.split(":", 1)[1])
                if code:
                    return code
            if resp in {"STATUS_CANCEL", "STATUS_BANNED"}:
                return ""
            time.sleep(5)
        return ""

    def request_another(self, activation_id: str) -> bool:
        try:
            resp = self._request("setStatus", {"id": activation_id, "status": "3"})
            return "ACCESS_RETRY_GET" in resp or "ACCESS_READY" in resp
        except Exception:
            return False

    def done(self, activation_id: str) -> None:
        try:
            self._request("setStatus", {"id": activation_id, "status": "6"})
        except Exception:
            pass

    def cancel(self, activation_id: str) -> None:
        try:
            self._request("setStatus", {"id": activation_id, "status": "8"})
        except Exception:
            pass


@dataclass
class SmsLease:
    provider: str
    phone: str
    activation_id: str
    client: SmsActivateClient
    reusable: bool = False
    code_received: bool = False

    def wait_code(self, timeout_seconds: int) -> str:
        code = self.client.wait_code(self.activation_id, timeout_seconds)
        if code:
            self.code_received = True
        return code

    def release_bad(self) -> None:
        self.client.cancel(self.activation_id)

    def release_done(self) -> None:
        self.client.done(self.activation_id)


class HeroSmsReusePool:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._leases: dict[tuple[str, str, str, str], SmsLease] = {}
        self._busy: set[tuple[str, str, str, str]] = set()

    def acquire(self, config: SmsProviderConfig) -> SmsLease:
        key = config.reuse_key()
        with self._lock:
            if key in self._busy:
                return self._new_lease_locked(config, key, store_reusable=False)
            lease = self._leases.get(key)
            if lease:
                self._busy.add(key)
                lease.client.request_another(lease.activation_id)
                logger.info("Hero-SMS 复用上轮手机号: {}", _mask_phone(lease.phone))
                return lease
            return self._new_lease_locked(config, key, store_reusable=True)

    def _new_lease_locked(
        self,
        config: SmsProviderConfig,
        key: tuple[str, str, str, str],
        *,
        store_reusable: bool,
    ) -> SmsLease:
        client = SmsActivateClient(config)
        phone, activation_id = client.get_number()
        lease = SmsLease(
            provider="herosms",
            phone=phone,
            activation_id=activation_id,
            client=client,
            reusable=store_reusable,
        )
        if store_reusable:
            self._leases[key] = lease
            self._busy.add(key)
        logger.info("Hero-SMS 获取新手机号: {}", _mask_phone(phone))
        return lease

    def finish(self, config: SmsProviderConfig, lease: SmsLease, *, keep: bool) -> None:
        key = config.reuse_key()
        with self._lock:
            if not lease.reusable:
                if keep and lease.code_received:
                    lease.release_done()
                else:
                    lease.release_bad()
                return
            self._busy.discard(key)
            if keep and lease.code_received:
                self._leases[key] = lease
                return
            stored = self._leases.get(key)
            if stored is lease:
                self._leases.pop(key, None)
            lease.release_bad()


HERO_SMS_POOL = HeroSmsReusePool()


def _mask_phone(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + digits[-4:]


def acquire_sms_lease(config: SmsProviderConfig) -> SmsLease:
    config.validate()
    if config.provider == "herosms":
        return HERO_SMS_POOL.acquire(config)
    if config.provider == "smsbower":
        client = SmsActivateClient(config)
        phone, activation_id = client.get_number()
        logger.info("SMSBower 获取手机号: {}", _mask_phone(phone))
        return SmsLease(
            provider="smsbower",
            phone=phone,
            activation_id=activation_id,
            client=client,
            reusable=False,
        )
    raise ValueError("手动模式不需要接码平台")


def finish_sms_lease(config: SmsProviderConfig, lease: SmsLease | None, *, keep: bool) -> None:
    if not lease:
        return
    if lease.provider == "herosms":
        HERO_SMS_POOL.finish(config, lease, keep=keep)
        return
    if keep and lease.code_received:
        lease.release_done()
    else:
        lease.release_bad()


def wait_with_log(lease: SmsLease, timeout_seconds: int, log_fn: Callable[[str], None] | None = None) -> str:
    if log_fn:
        log_fn(f"等待 {lease.provider} 短信验证码，超时 {timeout_seconds}s")
    return lease.wait_code(timeout_seconds)


def _load_json_text(text: str):
    value = (text or "").strip()
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def _stringify(value) -> str:
    return str(value if value is not None else "").strip()


def _label_from_dict(item: dict, fallback: str) -> str:
    for key in ("name", "eng", "title", "service", "short_name", "rus", "chn"):
        value = _stringify(item.get(key))
        if value:
            return value
    return fallback


def parse_sms_countries(text: str) -> list[dict[str, str]]:
    data = _load_json_text(text)
    rows: list[dict[str, str]] = []
    if isinstance(data, dict):
        source = data.get("countries") if isinstance(data.get("countries"), (dict, list)) else data
        if isinstance(source, dict):
            iterable = source.items()
        else:
            iterable = enumerate(source or [])
        for key, item in iterable:
            if isinstance(item, dict):
                code = _stringify(item.get("id") or item.get("country") or item.get("code") or key)
                label = _label_from_dict(item, code)
            else:
                code = _stringify(key)
                label = _stringify(item) or code
            if code:
                rows.append({"code": code, "label": label})
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                code = _stringify(item.get("id") or item.get("country") or item.get("code"))
                label = _label_from_dict(item, code)
            else:
                code = _stringify(item)
                label = code
            if code:
                rows.append({"code": code, "label": label})
    return _dedupe_options(rows)


def parse_sms_services(text: str) -> list[dict[str, str]]:
    data = _load_json_text(text)
    rows: list[dict[str, str]] = []
    if isinstance(data, dict):
        source = data.get("services") if isinstance(data.get("services"), (dict, list)) else data
        if isinstance(source, dict):
            iterable = source.items()
        else:
            iterable = enumerate(source or [])
        for key, item in iterable:
            if isinstance(item, dict):
                code = _stringify(item.get("code") or item.get("service") or item.get("id") or key)
                label = _label_from_dict(item, code)
            else:
                code = _stringify(key)
                label = _stringify(item) or code
            if code:
                rows.append({"code": code, "label": label})
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                code = _stringify(item.get("code") or item.get("service") or item.get("id"))
                label = _label_from_dict(item, code)
            else:
                code = _stringify(item)
                label = code
            if code:
                rows.append({"code": code, "label": label})
    return _dedupe_options(rows)


def parse_sms_price_services(text: str, country: str = "") -> list[dict[str, str]]:
    data = _load_json_text(text)
    rows: list[dict[str, str]] = []
    if not isinstance(data, dict):
        return rows
    source = data.get("prices") if isinstance(data.get("prices"), dict) else data
    country_key = _stringify(country)
    if country_key and isinstance(source.get(country_key), dict):
        source = source[country_key]
    for key, item in source.items():
        if not isinstance(item, dict):
            continue
        # SMS-Activate getPrices is usually country -> service -> {cost,count}.
        if "cost" in item or "count" in item:
            code = _stringify(key)
            count = _stringify(item.get("count"))
            label = f"{code} 库存 {count}" if count else code
            rows.append({"code": code, "label": label})
            continue
        for service_key, detail in item.items():
            code = _stringify(service_key)
            if not code:
                continue
            count = _stringify(detail.get("count")) if isinstance(detail, dict) else ""
            label = f"{code} 库存 {count}" if count else code
            rows.append({"code": code, "label": label})
    return _dedupe_options(rows)


def parse_sms_price_countries(text: str) -> list[dict[str, str]]:
    data = _load_json_text(text)
    if not isinstance(data, dict):
        return []
    source = data.get("prices") if isinstance(data.get("prices"), dict) else data
    rows: list[dict[str, str]] = []
    for key, item in source.items():
        code = _stringify(key)
        if code and isinstance(item, dict):
            rows.append({"code": code, "label": code})
    return _dedupe_options(rows)


def merge_sms_service_labels(
    service_names: list[dict[str, str]],
    price_services: list[dict[str, str]],
) -> list[dict[str, str]]:
    if not service_names:
        return price_services
    name_by_code = {
        _stringify(item.get("code")): _stringify(item.get("label"))
        for item in service_names
        if _stringify(item.get("code"))
    }
    if not price_services:
        return service_names
    rows: list[dict[str, str]] = []
    for item in price_services:
        code = _stringify(item.get("code"))
        if not code:
            continue
        label = name_by_code.get(code)
        if label:
            count = _extract_stock_count(_stringify(item.get("label")))
            label = f"{label} 库存 {count}" if count else label
        else:
            label = _stringify(item.get("label")) or code
        rows.append({"code": code, "label": label})
    return _dedupe_options(rows)


def _extract_stock_count(label: str) -> str:
    match = re.search(r"库存\s*(\d+)", label or "")
    return match.group(1) if match else ""


def _dedupe_options(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for row in rows:
        code = _stringify(row.get("code"))
        if not code or code in seen:
            continue
        seen.add(code)
        result.append({"code": code, "label": _stringify(row.get("label")) or code})
    return sorted(result, key=lambda item: (item["label"].lower(), item["code"]))


def fetch_sms_options(config: SmsProviderConfig, country: str = "") -> dict[str, list[dict[str, str]]]:
    config.validate()
    client = SmsActivateClient(config)
    countries = client.get_countries()
    services = client.get_services(country or config.country or "")
    return {"countries": countries, "services": services}
