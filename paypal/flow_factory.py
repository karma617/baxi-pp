from __future__ import annotations

from paypal.flow import PayPalFlow
from paypal.ba_flow import PayPalBAFlow
from paypal.us_flow import PayPalUSFlow


def normalize_flow_country(country: str | None) -> str:
    value = (country or "BR").strip().upper()
    aliases = {"USA": "US", "UK": "GB", "GBR": "GB", "BRA": "BR"}
    value = aliases.get(value, value)
    if value not in {"BR", "US", "BA"}:
        raise ValueError(f"unsupported PayPal flow country: {country!r}")
    return value


def flow_class_for_country(country: str | None):
    country = normalize_flow_country(country)
    if country == "BA":
        return PayPalBAFlow
    if country == "US":
        return PayPalUSFlow
    return PayPalFlow
