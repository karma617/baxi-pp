"""SMS-Activate style OTP providers for web jobs."""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass

import httpx
from loguru import logger


HERO_SMS_API = "https://hero-sms.com/stubs/handler_api.php"
SMSBOWER_API = "https://smsbower.page/stubs/handler_api.php"
DEFAULT_SERVICE = "ot"
DEFAULT_COUNTRY = "73"  # Brazil in SMS-Activate style APIs.
OTP_TIMEOUT_SECONDS = 60


@dataclass
class SmsActivation:
    provider: str
    activation_id: str
    phone: str
    local_phone: str
    api_key: str
    service: str
    country: str
    base_url: str
    last_code: str = ""


class SmsActivateClient:
    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        service: str = DEFAULT_SERVICE,
        country: str = DEFAULT_COUNTRY,
        max_price: str = "",
        proxy: str = "",
    ):
        self.provider = (provider or "").strip().lower()
        self.base_url = (base_url or "").strip()
        self.api_key = (api_key or "").strip()
        self.service = (service or "").strip() or DEFAULT_SERVICE
        self.country = (country or "").strip() or DEFAULT_COUNTRY
        self.max_price = (max_price or "").strip()
        self.proxy = (proxy or "").strip()

    def request(self, action: str, params: dict[str, str] | None = None) -> str:
        if not self.api_key:
            raise RuntimeError(f"{self.provider} API Key 未配置")
        query = {"api_key": self.api_key, "action": action}
        if params:
            query.update({k: v for k, v in params.items() if v != ""})
        kwargs: dict = {"timeout": 30}
        if self.proxy:
            kwargs["proxy"] = self.proxy
        with httpx.Client(**kwargs) as client:
            resp = client.get(self.base_url, params=query)
            resp.raise_for_status()
            return (resp.text or "").strip()

    def get_number(self) -> SmsActivation:
        params = {"service": self.service, "country": self.country}
        if self.max_price:
            params["maxPrice"] = self.max_price
        text = self.request("getNumber", params)
        if not text.startswith("ACCESS_NUMBER:"):
            raise RuntimeError(f"{self.provider} getNumber failed: {text}")
        parts = text.split(":")
        if len(parts) < 3:
            raise RuntimeError(f"{self.provider} getNumber malformed: {text}")
        phone_digits = re.sub(r"\D+", "", parts[2])
        if not phone_digits:
            raise RuntimeError(f"{self.provider} getNumber returned empty phone")
        return SmsActivation(
            provider=self.provider,
            activation_id=parts[1],
            phone=f"+{phone_digits}",
            local_phone=_local_phone_for_country(phone_digits, self.country),
            api_key=self.api_key,
            service=self.service,
            country=self.country,
            base_url=self.base_url,
        )

    def wait_code(
        self,
        activation_id: str,
        *,
        timeout_seconds: int = OTP_TIMEOUT_SECONDS,
        ignore_code: str = "",
    ) -> str:
        deadline = time.time() + max(1, int(timeout_seconds or OTP_TIMEOUT_SECONDS))
        ignore_code = (ignore_code or "").strip()
        while time.time() < deadline:
            text = self.request("getStatus", {"id": activation_id})
            if text.startswith("STATUS_OK:"):
                raw = text.split(":", 1)[1]
                match = re.search(r"\b(\d{4,8})\b", raw)
                code = match.group(1) if match else raw.strip()
                if ignore_code and code == ignore_code:
                    time.sleep(5)
                    continue
                return code
            if text in {"STATUS_CANCEL", "STATUS_FINISH"}:
                raise RuntimeError(f"{self.provider} activation ended: {text}")
            time.sleep(5)
        raise TimeoutError(f"{self.provider} 60秒内未收到验证码")

    def set_status(self, activation_id: str, status: int) -> str:
        return self.request("setStatus", {"id": activation_id, "status": str(status)})

    def done(self, activation_id: str) -> None:
        try:
            self.set_status(activation_id, 6)
        except Exception as exc:
            logger.debug("{} setStatus=6 failed: {}", self.provider, exc)

    def release(self, activation_id: str) -> None:
        try:
            self.set_status(activation_id, 8)
        except Exception as exc:
            logger.debug("{} setStatus=8 failed: {}", self.provider, exc)

    def request_another(self, activation_id: str) -> None:
        text = self.set_status(activation_id, 3)
        logger.info("{} setStatus=3: {}", self.provider, text)


def _local_phone_for_country(phone_digits: str, country: str) -> str:
    # Current PayPal BR flow expects the local number without +55.
    if str(country) == DEFAULT_COUNTRY and phone_digits.startswith("55") and len(phone_digits) > 11:
        return phone_digits[2:]
    return phone_digits


def make_sms_client(config: dict) -> SmsActivateClient:
    provider = (config.get("mode") or "manual").strip().lower()
    if provider == "herosms":
        return SmsActivateClient(
            provider="herosms",
            base_url=HERO_SMS_API,
            api_key=config.get("hero_api_key", ""),
            service=config.get("hero_service", DEFAULT_SERVICE),
            country=config.get("hero_country", DEFAULT_COUNTRY),
            max_price=config.get("hero_max_price", ""),
            proxy=config.get("hero_proxy", ""),
        )
    if provider == "smsbower":
        return SmsActivateClient(
            provider="smsbower",
            base_url=SMSBOWER_API,
            api_key=config.get("smsbower_api_key", ""),
            service=config.get("smsbower_service", DEFAULT_SERVICE),
            country=config.get("smsbower_country", DEFAULT_COUNTRY),
            max_price=config.get("smsbower_max_price", ""),
            proxy=config.get("smsbower_proxy", ""),
        )
    raise RuntimeError(f"unsupported sms provider: {provider}")


class HeroSmsReusePool:
    def __init__(self):
        self._lock = threading.RLock()
        self._activation: SmsActivation | None = None

    def acquire(self, config: dict) -> SmsActivation:
        client = make_sms_client(config)
        with self._lock:
            if self._activation and self._matches(self._activation, client):
                client.request_another(self._activation.activation_id)
                logger.info(
                    "HeroSMS reusing phone {} activation={}",
                    _mask_phone(self._activation.phone),
                    self._activation.activation_id,
                )
                return self._activation
            activation = client.get_number()
            self._activation = activation
            logger.info(
                "HeroSMS acquired phone {} activation={}",
                _mask_phone(activation.phone),
                activation.activation_id,
            )
            return activation

    def mark_success(self, activation: SmsActivation, code: str) -> None:
        with self._lock:
            activation.last_code = code
            self._activation = activation

    def release(self, activation: SmsActivation, config: dict) -> None:
        client = make_sms_client(config)
        with self._lock:
            client.release(activation.activation_id)
            if self._activation and self._activation.activation_id == activation.activation_id:
                self._activation = None

    @staticmethod
    def _matches(activation: SmsActivation, client: SmsActivateClient) -> bool:
        return (
            activation.provider == "herosms"
            and activation.api_key == client.api_key
            and activation.service == client.service
            and activation.country == client.country
            and activation.base_url == client.base_url
        )


HERO_SMS_REUSE_POOL = HeroSmsReusePool()


def _mask_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", value or "")
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * max(0, len(digits) - 4) + digits[-4:]
