"""Headed browser assist for DataDome / authchallenge.

Uses Playwright Chromium in headed mode. Cookies (and optional OTP initiate
result) are exported back into the protocol httpx session so the rest of the
flow stays HTTP.
"""
from __future__ import annotations

import importlib
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlsplit

from loguru import logger


@dataclass
class BrowserAssistResult:
    ok: bool
    final_url: str = ""
    cookies: list[dict[str, Any]] | None = None
    reason: str = ""
    page_bytes: int = 0
    otp_auth_id: str = ""
    otp_challenge_id: str = ""
    otp_state: str = ""
    signup_result: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


_PLAYWRIGHT_INSTALL_ATTEMPTED = False


def _ensure_playwright():
    global _PLAYWRIGHT_INSTALL_ATTEMPTED
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return
    except Exception:
        pass
    if _PLAYWRIGHT_INSTALL_ATTEMPTED:
        raise RuntimeError("playwright is not available")
    _PLAYWRIGHT_INSTALL_ATTEMPTED = True
    logger.warning("Installing playwright + chromium for headed browser assist...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    importlib.invalidate_caches()
    from playwright.sync_api import sync_playwright  # noqa: F401


def _proxy_for_playwright(proxy_url: str | None) -> dict[str, str] | None:
    """Convert httpx proxy URL to Playwright proxy config.

    Credentials are unquoted. Fragment suffixes (log fingerprints) are ignored.
    Returns None only when proxy_url is empty/invalid.
    """
    if not proxy_url:
        return None
    raw = str(proxy_url).strip()
    if not raw:
        return None
    # Drop accidental log fingerprint like host:port#abcdef
    if "#" in raw and "://" in raw:
        raw = raw.split("#", 1)[0]
    parts = urlsplit(raw)
    host = parts.hostname
    if not host:
        return None
    scheme = (parts.scheme or "http").lower()
    try:
        port = parts.port
    except ValueError:
        return None
    if port is None:
        if scheme in {"http", "socks5", "socks5h"}:
            port = 80 if scheme == "http" else 1080
        elif scheme == "https":
            port = 443
        else:
            return None
    server = f"{scheme}://{host}:{port}"
    conf: dict[str, str] = {"server": server}
    username = unquote(parts.username) if parts.username else ""
    password = unquote(parts.password) if parts.password else ""
    if username:
        conf["username"] = username
    if password:
        conf["password"] = password
    return conf


def _mask_proxy_for_log(proxy_url: str | None) -> str:
    if not proxy_url:
        return "off"
    conf = _proxy_for_playwright(proxy_url)
    if not conf:
        return "invalid"
    server = conf.get("server", "")
    if conf.get("username") or conf.get("password"):
        return server.replace("://", "://***:***@", 1)
    return server or "on"


def _normalize_page_text(text: str) -> str:
    low = (text or "").lower()
    trans = str.maketrans({
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u", "ü": "u",
        "ç": "c",
    })
    return low.translate(trans)


def _is_paypal_unavailable_or_invalid_link_html(url: str, html: str) -> bool:
    """Detect PayPal generic failure/expired agreement pages that cannot be solved."""
    text = html or ""
    norm = _normalize_page_text(text)
    url_l = (url or "").lower()
    small_or_agreement = len(text) < 25000 or "agreements/approve" in url_l
    if not small_or_agreement:
        return False
    markers = (
        "parece que as coisas nao estao funcionando no momento",
        "things don't appear to be working at the moment",
        "things don t appear to be working at the moment",
        "things arent working at the moment",
        "things are not working at the moment",
        "something went wrong",
        "link is invalid or expired",
        "this link is invalid",
        "your session has expired",
    )
    if not any(marker in norm for marker in markers):
        return False
    success_markers = (
        "checkoutweb/signup",
        "numero do cartao",
        "card number",
        "EC-",
        "ctxId",
        "billingAgreementContext",
    )
    return not any(marker.lower() in norm for marker in success_markers)


def _is_hard_challenge_html(text: str) -> bool:
    """True only for real captcha/authchallenge shells, not normal signup pages."""
    low = (text or "").lower()
    hard = (
        "authchallengenodeweb",
        "geo.captcha-delivery.com",
        "ads-dd-captcha",
        "adsddtoken",
        "please verify you are a human",
        "confirm you are human",
        "move the slider",
        "slide the puzzle",
        "press and hold",
        "captcha__puzzle",
    )
    if any(m in low for m in hard):
        if "authchallengenodeweb" in low:
            return True
        if len(text or "") < 50000:
            return True
    if "datadome" in low and len(text or "") < 25000:
        return True
    return False


def _is_signup_form_html(url: str, html: str) -> bool:
    """True when headed browser already reached the real BR/US signup form."""
    low = (html or "").lower()
    # strip accents for robust matching
    trans = str.maketrans({
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u", "ü": "u",
        "ç": "c",
    })
    norm = low.translate(trans)
    form_markers = (
        "numero do cartao",
        "card number",
        "pague com cartao",
        "pay with debit",
        "pay with credit",
        "e-mail",
        "email",
        "data de vencimento",
        "expiration date",
        "seu endereco de cobranca",
        "billing address",
        "nome",
        "sobrenome",
        "first name",
        "last name",
        'name="cardnumber"',
        'autocomplete="cc-number"',
        'name="email"',
        'type="email"',
        "numero de telefone",
        "phone number",
    )
    hits = sum(1 for m in form_markers if m in norm)
    on_signup = "checkoutweb/signup" in (url or "").lower()
    return hits >= 3 and (len(html or "") > 12000 or on_signup)


def _page_looks_usable(url: str, html: str) -> bool:
    text = html or ""
    low = text.lower()
    url_l = (url or "").lower()

    if _is_paypal_unavailable_or_invalid_link_html(url, text):
        return False

    # Highest priority: real signup form already visible. Operator need do nothing.
    if _is_signup_form_html(url, text):
        return True

    # Hermes / pay billing shells after card contingency.
    if "webapps/hermes" in url_l or "/pay/billing" in url_l:
        if _is_hard_challenge_html(text):
            return False
        if len(text) >= 8000 and "paypal" in low:
            return True
        if len(text) >= 20000:
            return True

    if _is_hard_challenge_html(text):
        return False

    if re.search(r"EC-[A-Za-z0-9]+", f"{url}\n{text}"):
        if "checkoutweb/signup" in (url or "") or len(text) > 30000:
            return True
    if "checkoutweb/signup" in (url or "") and len(text) > 20000:
        return True
    if "agreements/approve" in (url or "") and len(text) > 40000:
        return True
    if "ssrt=" in (url or "") and len(text) > 30000 and "paypal" in low:
        return True
    return False


def _browser_initiate_otp(
    page,
    *,
    phone_local: str,
    country: str,
    lang: str,
    token: str,
    mutation: str,
) -> dict[str, str]:
    """Run InitiateRiskBasedTwoFactorPhoneConfirmationMutation inside page context."""
    payload = {
        "operationName": "InitiateRiskBasedTwoFactorPhoneConfirmationMutation",
        "variables": {
            "phoneNumber": phone_local,
            "locale": {"country": country, "lang": lang},
            "phoneCountry": country,
            "token": token,
        },
        "query": mutation,
    }
    result = page.evaluate(
        """async ({payload, token, country, lang}) => {
            const resp = await fetch(
              'https://www.paypal.com/graphql?InitiateRiskBasedTwoFactorPhoneConfirmationMutation',
              {
                method: 'POST',
                credentials: 'include',
                headers: {
                  'content-type': 'application/json',
                  'x-app-name': 'checkoutuinodeweb_weasley',
                  'x-requested-with': 'fetch',
                  'paypal-client-context': token,
                  'paypal-client-metadata-id': token,
                  'x-country': country,
                  'x-locale': `${lang}_${country}`,
                  'origin': 'https://www.paypal.com',
                  'referer': location.href,
                },
                body: JSON.stringify(payload),
              }
            );
            const text = await resp.text();
            return { status: resp.status, text, contentType: resp.headers.get('content-type') || '' };
        }""",
        {
            "payload": payload,
            "token": token,
            "country": country,
            "lang": lang,
        },
    )
    text = (result or {}).get("text") or ""
    status = (result or {}).get("status")
    logger.info(
        "Browser OTP initiate HTTP {} content_type={} bytes={}",
        status,
        (result or {}).get("contentType"),
        len(text),
    )
    if "authchallengenodeweb" in text.lower():
        return {"error": "authchallenge_html"}
    try:
        data = json.loads(text)
    except Exception:
        return {"error": f"non_json status={status} bytes={len(text)}"}
    node = None
    if isinstance(data, list) and data:
        node = (data[0].get("data") or {}).get("initiateRiskBasedTwoFactorPhoneConfirmation")
    elif isinstance(data, dict):
        node = (data.get("data") or {}).get("initiateRiskBasedTwoFactorPhoneConfirmation")
    if not isinstance(node, dict):
        return {"error": f"missing_node body={text[:300]}"}
    return {
        "authId": str(node.get("authId") or ""),
        "challengeId": str(node.get("challengeId") or ""),
        "state": str(node.get("state") or ""),
    }


def _browser_signup_new_member(
    page,
    *,
    variables: dict[str, Any],
    mutation: str,
    token: str,
    country: str,
    lang: str,
    fn_sync_data: str,
) -> dict[str, Any]:
    """Run SignUpNewMemberMutation inside page context with browser cookies."""
    payload = {
        "operationName": "SignUpNewMemberMutation",
        "variables": variables,
        "query": mutation,
        "fn_sync_data": fn_sync_data,
    }
    result = page.evaluate(
        """async ({payload, token, country, lang}) => {
            const resp = await fetch(
              'https://www.paypal.com/graphql?SignUpNewMemberMutation',
              {
                method: 'POST',
                credentials: 'include',
                headers: {
                  'content-type': 'application/json',
                  'x-app-name': 'checkoutuinodeweb_weasley',
                  'x-requested-with': 'fetch',
                  'paypal-client-context': token,
                  'paypal-client-metadata-id': token,
                  'x-country': country,
                  'x-locale': `${lang}_${country}`,
                  'origin': 'https://www.paypal.com',
                  'referer': location.href,
                },
                body: JSON.stringify(payload),
              }
            );
            const text = await resp.text();
            const headers = {};
            try {
              for (const [k, v] of resp.headers.entries()) {
                headers[k] = v;
              }
            } catch (e) {}
            return {
              status: resp.status,
              text,
              contentType: resp.headers.get('content-type') || '',
              headers,
            };
        }""",
        {
            "payload": payload,
            "token": token,
            "country": country,
            "lang": lang,
        },
    )
    text_body = (result or {}).get("text") or ""
    status = (result or {}).get("status")
    content_type = (result or {}).get("contentType") or ""
    headers = (result or {}).get("headers") or {}
    logger.info(
        "Browser SignUpNewMember HTTP {} content_type={} bytes={}",
        status,
        content_type,
        len(text_body),
    )
    if "authchallengenodeweb" in text_body.lower():
        return {
            "data": {},
            "errors": [{
                "message": "NON_JSON_RESPONSE",
                "errorData": {"browser": "authchallenge_html", "status": status},
            }],
        }
    try:
        data = json.loads(text_body)
    except Exception:
        token_match = re.search(
            r'(?:accessToken|euat|x-paypal-internal-euat)["\x27\s:=]+([A-Za-z0-9_\-]{40,})',
            text_body,
        )
        if token_match:
            extracted = token_match.group(1)
            logger.info("Extracted EUAT token from browser non-JSON SignUp response")
            return {
                "data": {
                    "onboardAccount": {
                        "buyer": {"auth": {"accessToken": extracted}, "userId": ""}
                    }
                },
                "errors": [],
            }
        header_euat = (
            headers.get("x-paypal-internal-euat")
            or headers.get("X-PayPal-Internal-EUAT")
            or ""
        )
        if header_euat:
            logger.info("Found EUAT token in browser SignUp response headers")
            return {
                "data": {
                    "onboardAccount": {
                        "buyer": {"auth": {"accessToken": header_euat}, "userId": ""}
                    }
                },
                "errors": [],
            }
        return {
            "data": {},
            "errors": [{
                "message": "NON_JSON_RESPONSE",
                "errorData": {
                    "browser": f"non_json status={status} bytes={len(text_body)}",
                    "status": status,
                },
            }],
        }
    if isinstance(data, list):
        return data[0] if data else {"data": {}, "errors": [{"message": "EMPTY_RESPONSE", "errorData": {}}]}
    if isinstance(data, dict):
        return data
    return {"data": {}, "errors": [{"message": "INVALID_RESPONSE", "errorData": {}}]}


def _dict_contains_key_with_value(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        for k, v in value.items():
            if k == key and v:
                return True
            if _dict_contains_key_with_value(v, key):
                return True
    elif isinstance(value, list):
        return any(_dict_contains_key_with_value(item, key) for item in value)
    return False


def _signup_result_is_browser_submission_failure(result: dict[str, Any] | None, final_url: str) -> bool:
    if not result:
        return False
    onboard = ((result.get("data") or {}).get("onboardAccount") or {})
    if onboard or _dict_contains_key_with_value(result, "accessToken"):
        return False
    errors = result.get("errors") or []
    messages = {str(e.get("message") or "") for e in errors if isinstance(e, dict)}
    if "BROWSER_SIGNUP_EXCEPTION" in messages:
        return True
    return (final_url or "").startswith("chrome-error://")


def _parse_browser_graphql_text(text: str, *, message: str, status: int | None = None) -> Any:
    try:
        return json.loads(text or "")
    except Exception:
        return {
            "errors": [{
                "message": message,
                "errorData": {"status": status, "bytes": len(text or "")},
            }]
        }


def _authorize_payload_has_return_url(payload: Any) -> bool:
    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        auth = (
            ((item or {}).get("data") or {})
            .get("billing", {})
            .get("authorize")
            or {}
        )
        if isinstance(auth, dict) and ((auth.get("returnURL") or {}).get("href") or ""):
            return True
    return False


def _synthetic_authorize_from_navigation(url: str, billing_agreement_id: str) -> dict[str, Any] | None:
    if not url:
        return None
    low = url.lower()
    if "paypal.com/" in low:
        return None
    if "status=success" not in low and "pm-redirects.stripe.com/return" not in low:
        return None
    return {
        "context_result": None,
        "authorize_result": [{
            "data": {
                "billing": {
                    "authorize": {
                        "billingAgreementToken": billing_agreement_id,
                        "returnURL": {"href": url},
                    }
                }
            }
        }],
        "status": 200,
        "mode": "native_navigation",
    }


def _click_native_billing_cta(page) -> str:
    """Click the visible Hagrid primary CTA instead of calling fetch directly."""
    allow = re.compile(
        r"(agree|continue|authorize|authorise|pay|confirm|"
        r"concordar|continuar|autorizar|pagar|confirmar)",
        re.I,
    )
    deny = re.compile(r"(cancel|back|voltar|cancelar|help|ajuda|privacy|legal)", re.I)
    locators = [
        page.get_by_role("button", name=allow),
        page.get_by_role("link", name=allow),
        page.locator(
            "button, [role=button], input[type=submit], "
            "[data-testid*=continue], [data-testid*=submit], "
            "[data-testid*=approve], [data-testid*=primary]"
        ),
    ]
    for locator in locators:
        try:
            count = min(locator.count(), 12)
        except Exception:
            count = 1
        for idx in range(count):
            item = locator.nth(idx)
            try:
                text = " ".join(
                    filter(
                        None,
                        [
                            item.inner_text(timeout=800) if item.count() else "",
                            item.get_attribute("aria-label", timeout=800) or "",
                            item.get_attribute("value", timeout=800) or "",
                            item.get_attribute("data-testid", timeout=800) or "",
                        ],
                    )
                )
                if deny.search(text or ""):
                    continue
                if text and not allow.search(text):
                    continue
                if not item.is_visible(timeout=800) or not item.is_enabled(timeout=800):
                    continue
                item.scroll_into_view_if_needed(timeout=1200)
                item.click(timeout=2500)
                return (text or "matched_primary_cta").strip()[:120]
            except Exception:
                continue
    return ""


def _browser_authorize_billing_via_native_click(
    page,
    *,
    billing_agreement_id: str,
) -> dict[str, Any] | None:
    captured: dict[str, Any] = {"authorize": None, "context": None}

    def on_response(resp):
        try:
            if "/graphql" not in (resp.url or ""):
                return
            req = resp.request
            post = req.post_data or ""
            if (
                "authorize" not in post
                and "BillingAgreementContextQueryForAddCard" not in post
            ):
                return
            text = resp.text()
            parsed = _parse_browser_graphql_text(
                text,
                message="BROWSER_NATIVE_GRAPHQL_NON_JSON",
                status=resp.status,
            )
            if "BillingAgreementContextQueryForAddCard" in post:
                captured["context"] = parsed
                logger.info(
                    "Browser native captured BillingAgreementContextQueryForAddCard HTTP {} bytes={}",
                    resp.status,
                    len(text or ""),
                )
            if "authorize" in post:
                captured["authorize"] = parsed
                logger.info(
                    "Browser native captured authorize HTTP {} bytes={}",
                    resp.status,
                    len(text or ""),
                )
        except Exception as e:
            logger.debug("Browser native response capture skipped: {}", e)

    page.on("response", on_response)
    try:
        page.wait_for_timeout(1200)
        clicked = _click_native_billing_cta(page)
        if not clicked:
            logger.warning("Browser native authorize: no clickable billing CTA found")
            return None
        logger.info("Browser native authorize clicked CTA: {}", clicked)
        for _ in range(10):
            if captured.get("authorize"):
                break
            nav_result = _synthetic_authorize_from_navigation(page.url, billing_agreement_id)
            if nav_result:
                logger.success("Browser native authorize reached merchant return URL")
                return nav_result
            page.wait_for_timeout(700)
        nav_result = _synthetic_authorize_from_navigation(page.url, billing_agreement_id)
        if nav_result:
            logger.success("Browser native authorize reached merchant return URL")
            return nav_result
        if captured.get("authorize"):
            return {
                "context_result": captured.get("context"),
                "authorize_result": captured.get("authorize"),
                "status": 200,
                "mode": "native_click",
            }
        return None
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass


def _browser_graphql_request_context(
    page,
    *,
    variables: dict[str, Any],
    mutation: str,
    context_query: str | None = None,
    euat: str = "",
    metadata_id: str = "",
) -> dict[str, Any]:
    common_headers = {
        "accept": "*/*",
        "content-type": "application/json",
        "x-app-name": "checkoutuinodeweb",
        "x-requested-with": "fetch",
        "paypal-client-metadata-id": metadata_id or variables.get("billingAgreementId", ""),
        "origin": "https://www.paypal.com",
        "referer": page.url,
    }
    if euat:
        common_headers["x-paypal-internal-euat"] = euat

    context_result = None
    if context_query:
        context_body = [{
            "operationName": "BillingAgreementContextQueryForAddCard",
            "variables": {
                "billingAgreementId": variables["billingAgreementId"],
                "billingAgreementOptions": {},
            },
            "query": context_query,
        }]
        context_resp = page.context.request.post(
            "https://www.paypal.com/graphql/",
            data=json.dumps(context_body),
            headers=common_headers,
            timeout=12000,
        )
        context_text = context_resp.text()
        logger.info(
            "Browser request-context BillingAgreementContextQueryForAddCard HTTP {} bytes={}",
            context_resp.status,
            len(context_text or ""),
        )
        context_result = _parse_browser_graphql_text(
            context_text,
            message="BROWSER_CONTEXT_NON_JSON",
            status=context_resp.status,
        )

    body = [{
        "operationName": "authorize",
        "variables": variables,
        "query": mutation,
    }]
    resp = page.context.request.post(
        "https://www.paypal.com/graphql/",
        data=json.dumps(body),
        headers=common_headers,
        timeout=12000,
    )
    text = resp.text()
    logger.info(
        "Browser request-context authorize HTTP {} bytes={}",
        resp.status,
        len(text or ""),
    )
    return {
        "context_result": context_result,
        "authorize_result": _parse_browser_graphql_text(
            text,
            message="BROWSER_AUTHORIZE_NON_JSON",
            status=resp.status,
        ),
        "status": resp.status,
        "mode": "browser_request_context",
    }


def _browser_authorize_billing(
    page,
    *,
    variables: dict[str, Any],
    mutation: str,
    context_query: str | None = None,
    euat: str = "",
    metadata_id: str = "",
) -> dict[str, Any]:
    """Run billing context warmup + authorize inside page context."""
    native_result = _browser_authorize_billing_via_native_click(
        page,
        billing_agreement_id=variables.get("billingAgreementId", ""),
    )
    if native_result and (
        _authorize_payload_has_return_url(native_result.get("authorize_result"))
        or native_result.get("authorize_result")
    ):
        logger.info("Browser authorize using mode={}", native_result.get("mode"))
        return native_result

    try:
        request_result = _browser_graphql_request_context(
            page,
            variables=variables,
            mutation=mutation,
            context_query=context_query,
            euat=euat,
            metadata_id=metadata_id,
        )
        logger.info("Browser authorize using mode={}", request_result.get("mode"))
        return request_result
    except Exception as e:
        logger.warning("Browser request-context authorize failed; falling back to page fetch: {}", e)

    result = page.evaluate(
        """async ({variables, mutation, contextQuery, euat, metadataId}) => {
            const commonHeaders = {
              'accept': '*/*',
              'content-type': 'application/json',
              'x-app-name': 'checkoutuinodeweb',
              'x-requested-with': 'fetch',
              'paypal-client-metadata-id': metadataId || variables.billingAgreementId,
              'origin': 'https://www.paypal.com',
              'referer': location.href,
            };
            if (euat) {
              commonHeaders['x-paypal-internal-euat'] = euat;
            }
            let contextResult = null;
            if (contextQuery) {
              const contextBody = [{
                operationName: 'BillingAgreementContextQueryForAddCard',
                variables: {
                  billingAgreementId: variables.billingAgreementId,
                  billingAgreementOptions: {},
                },
                query: contextQuery,
              }];
              const contextResp = await fetch('https://www.paypal.com/graphql/', {
                method: 'POST',
                credentials: 'include',
                headers: commonHeaders,
                body: JSON.stringify(contextBody),
              });
              const contextText = await contextResp.text();
              contextResult = {
                status: contextResp.status,
                text: contextText,
                contentType: contextResp.headers.get('content-type') || '',
              };
            }
            const body = [{
              operationName: 'authorize',
              variables,
              query: mutation,
            }];
            const resp = await fetch('https://www.paypal.com/graphql/', {
              method: 'POST',
              credentials: 'include',
              headers: commonHeaders,
              body: JSON.stringify(body),
            });
            const text = await resp.text();
            return {
              status: resp.status,
              text,
              contentType: resp.headers.get('content-type') || '',
              contextResult,
            };
        }""",
        {
            "variables": variables,
            "mutation": mutation,
            "contextQuery": context_query or "",
            "euat": euat or "",
            "metadataId": metadata_id or variables.get("billingAgreementId", ""),
        },
    )
    context_result = (result or {}).get("contextResult") or {}
    if context_result:
        logger.info(
            "Browser BillingAgreementContextQueryForAddCard HTTP {} content_type={} bytes={}",
            context_result.get("status"),
            context_result.get("contentType"),
            len(context_result.get("text") or ""),
        )
    text_body = (result or {}).get("text") or ""
    status = (result or {}).get("status")
    content_type = (result or {}).get("contentType") or ""
    logger.info(
        "Browser authorize HTTP {} content_type={} bytes={}",
        status,
        content_type,
        len(text_body),
    )
    parsed_context = None
    try:
        if context_result and context_result.get("text"):
            parsed_context = json.loads(context_result.get("text") or "")
    except Exception:
        parsed_context = {
            "errors": [{
                "message": "BROWSER_CONTEXT_NON_JSON",
                "errorData": {
                    "status": context_result.get("status"),
                    "bytes": len(context_result.get("text") or ""),
                },
            }]
        }
    try:
        parsed_authorize = json.loads(text_body)
    except Exception:
        parsed_authorize = {
            "errors": [{
                "message": "BROWSER_AUTHORIZE_NON_JSON",
                "errorData": {"status": status, "bytes": len(text_body)},
            }]
        }
    return {
        "context_result": parsed_context,
        "authorize_result": parsed_authorize,
        "status": status,
    }


def solve_with_headed_browser(
    url: str,
    *,
    proxy_url: str | None = None,
    seed_cookies: list[dict[str, Any]] | None = None,
    user_agent: str | None = None,
    timeout_sec: float = 120.0,
    wait_for_manual: bool = True,
    purpose: str = "challenge",
    bootstrap_url: str | None = None,
    otp_phone_local: str | None = None,
    otp_country: str = "BR",
    otp_lang: str = "pt",
    otp_token: str | None = None,
    otp_mutation: str | None = None,
    signup_variables: dict[str, Any] | None = None,
    signup_mutation: str | None = None,
    signup_token: str | None = None,
    signup_country: str = "BR",
    signup_lang: str = "pt",
    signup_fn_sync_data: str | None = None,
    authorize_variables: dict[str, Any] | None = None,
    authorize_mutation: str | None = None,
    authorize_context_query: str | None = None,
    authorize_euat: str | None = None,
    authorize_metadata_id: str | None = None,
) -> BrowserAssistResult:
    """Open headed Chromium, wait until challenge clears, return cookies.

    For otp_authchallenge / signup_authchallenge, once signup form is visible,
    also attempt OTP initiate or SignUpNewMember from the browser page context.
    Operator only needs to act if a real captcha/authchallenge UI appears.
    """
    _ensure_playwright()
    from playwright.sync_api import sync_playwright
    from config import USER_AGENT, VIEWPORT

    ua = user_agent or USER_AGENT
    proxy = _proxy_for_playwright(proxy_url)
    if proxy_url and not proxy:
        raise RuntimeError(
            f"Headed browser proxy parse failed; refusing bare connect. proxy={_mask_proxy_for_log(proxy_url)}"
        )
    logger.info(
        "Headed browser assist start purpose={} url={} proxy={} timeout={}s",
        purpose,
        (url or "")[:160],
        _mask_proxy_for_log(proxy_url) if proxy else "off",
        int(timeout_sec),
    )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            context = browser.new_context(
                user_agent=ua,
                viewport=VIEWPORT,
                locale="pt-BR",
                proxy=proxy,
            )
            if seed_cookies:
                try:
                    normalized = []
                    for c in seed_cookies:
                        item = {
                            "name": c.get("name"),
                            "value": c.get("value"),
                            "domain": c.get("domain") or ".paypal.com",
                            "path": c.get("path") or "/",
                        }
                        if c.get("secure") is not None:
                            item["secure"] = bool(c.get("secure"))
                        if item["name"] and item["value"] is not None:
                            normalized.append(item)
                    if normalized:
                        context.add_cookies(normalized)
                except Exception as e:
                    logger.warning("Seed cookies into browser failed: {}", e)

            page = context.new_page()
            # HAR-aligned navigation: for Hermes bind, first open signup shell
            # (same-origin referer + cookies), then navigate to target Hermes URL.
            # Cold-opening Hermes often yields 403 / connection closed.
            first_url = (bootstrap_url or "").strip() or url
            page.goto(first_url, wait_until="domcontentloaded", timeout=60000)
            if bootstrap_url and url and bootstrap_url.rstrip("/") != url.rstrip("/"):
                try:
                    page.wait_for_timeout(800)
                    logger.info(
                        "Headed browser bootstrap done; navigating to target purpose={} url={}",
                        purpose,
                        (url or "")[:160],
                    )
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                except Exception as e:
                    logger.warning(
                        "Headed browser target navigation failed purpose={} err={}; keeping bootstrap page",
                        purpose,
                        e,
                    )
            deadline = time.time() + max(15.0, float(timeout_sec))
            last_url = page.url
            last_len = 0
            last_html = ""
            usable = False
            while time.time() < deadline:
                try:
                    last_url = page.url
                    last_html = page.content()
                    last_len = len(last_html or "")
                    if _is_paypal_unavailable_or_invalid_link_html(last_url, last_html):
                        cookies = context.cookies()
                        browser.close()
                        logger.error(
                            "Headed browser saw PayPal unavailable/invalid agreement page; "
                            "stop waiting. url={} bytes={}",
                            last_url[:160],
                            last_len,
                        )
                        return BrowserAssistResult(
                            ok=False,
                            final_url=last_url,
                            cookies=cookies,
                            reason="paypal_unavailable_or_invalid_link",
                            page_bytes=last_len,
                        )
                    if _page_looks_usable(last_url, last_html):
                        if _is_signup_form_html(last_url, last_html):
                            logger.success(
                                "Headed browser already on signup form; no manual action needed. url={} bytes={}",
                                last_url[:160],
                                last_len,
                            )
                            usable = True
                            break
                        page.wait_for_timeout(1000)
                        last_html = page.content()
                        last_url = page.url
                        last_len = len(last_html or "")
                        if _page_looks_usable(last_url, last_html):
                            usable = True
                            break
                    if wait_for_manual:
                        if _is_hard_challenge_html(last_html):
                            logger.info(
                                "Headed browser: please complete captcha/authchallenge in the window... url={} bytes={}",
                                last_url[:140],
                                last_len,
                            )
                        else:
                            logger.info(
                                "Headed browser waiting page settle... url={} bytes={}",
                                last_url[:140],
                                last_len,
                            )
                    page.wait_for_timeout(1200)
                except Exception as e:
                    logger.warning("Headed browser poll error: {}", e)
                    page.wait_for_timeout(1000)

            # Soft success: large signup URL without hard challenge even if form
            # markers were partially missing (SPA hydration differences).
            if not usable and "checkoutweb/signup" in (last_url or "") and last_len > 20000 and not _is_hard_challenge_html(last_html):
                logger.warning(
                    "Headed browser timeout soft-pass on signup shell url={} bytes={}",
                    last_url[:160],
                    last_len,
                )
                usable = True
            if (
                not usable
                and ("webapps/hermes" in (last_url or "") or "/pay/billing" in (last_url or ""))
                and last_len > 8000
                and not _is_hard_challenge_html(last_html)
            ):
                logger.warning(
                    "Headed browser timeout soft-pass on hermes/billing shell url={} bytes={}",
                    last_url[:160],
                    last_len,
                )
                usable = True

            otp_auth_id = ""
            otp_challenge_id = ""
            otp_state = ""
            signup_result = None
            if (
                usable
                and purpose == "otp_authchallenge"
                and otp_phone_local
                and otp_token
                and otp_mutation
            ):
                try:
                    logger.info("Attempting OTP initiate from headed browser page context...")
                    otp_res = _browser_initiate_otp(
                        page,
                        phone_local=otp_phone_local,
                        country=otp_country,
                        lang=otp_lang,
                        token=otp_token,
                        mutation=otp_mutation,
                    )
                    if otp_res.get("authId") and otp_res.get("challengeId"):
                        otp_auth_id = otp_res["authId"]
                        otp_challenge_id = otp_res["challengeId"]
                        otp_state = otp_res.get("state") or ""
                        logger.success(
                            "Browser OTP initiate success state={} authId/challengeId present",
                            otp_state or "?",
                        )
                    else:
                        logger.warning("Browser OTP initiate failed: {}", otp_res.get("error") or otp_res)
                except Exception as e:
                    logger.warning("Browser OTP initiate exception: {}", e)

            if (
                usable
                and purpose == "signup_authchallenge"
                and signup_variables
                and signup_mutation
                and signup_token
                and signup_fn_sync_data is not None
            ):
                try:
                    logger.info("Attempting SignUpNewMember from headed browser page context...")
                    signup_result = _browser_signup_new_member(
                        page,
                        variables=signup_variables,
                        mutation=signup_mutation,
                        token=signup_token,
                        country=signup_country,
                        lang=signup_lang,
                        fn_sync_data=signup_fn_sync_data,
                    )
                    onboard = (signup_result or {}).get("data", {}).get("onboardAccount")
                    errs = (signup_result or {}).get("errors") or []
                    if onboard:
                        logger.success("Browser SignUpNewMember returned onboardAccount")
                    elif errs:
                        logger.warning(
                            "Browser SignUpNewMember returned errors: {}",
                            [str(e.get("message") or "") for e in errs if isinstance(e, dict)][:5],
                        )
                    else:
                        logger.warning("Browser SignUpNewMember returned empty onboardAccount")
                except Exception as e:
                    logger.warning("Browser SignUpNewMember exception: {}", e)
                    signup_result = {
                        "data": {},
                        "errors": [{"message": "BROWSER_SIGNUP_EXCEPTION", "errorData": {"detail": str(e)}}],
                    }

            authorize_result = None
            if (
                usable
                and authorize_variables
                and authorize_mutation
            ):
                try:
                    logger.info("Attempting billing authorize from headed browser page context...")
                    authorize_result = _browser_authorize_billing(
                        page,
                        variables=authorize_variables,
                        mutation=authorize_mutation,
                        context_query=authorize_context_query,
                        euat=authorize_euat or "",
                        metadata_id=authorize_metadata_id or "",
                    )
                    logger.info(
                        "Browser authorize result captured: status={}",
                        authorize_result.get("status"),
                    )
                except Exception as e:
                    logger.warning("Browser authorize exception: {}", e)
                    authorize_result = {
                        "authorize_result": {
                            "errors": [{
                                "message": "BROWSER_AUTHORIZE_EXCEPTION",
                                "errorData": {"detail": str(e)},
                            }]
                        }
                    }

            cookies = context.cookies()
            browser.close()
            if (
                purpose == "signup_authchallenge"
                and _signup_result_is_browser_submission_failure(signup_result, last_url)
            ):
                return BrowserAssistResult(
                    ok=False,
                    final_url=last_url,
                    cookies=cookies,
                    reason="signup_browser_submission_failed",
                    page_bytes=last_len,
                    signup_result=signup_result,
                )
            if not usable:
                return BrowserAssistResult(
                    ok=False,
                    final_url=last_url,
                    cookies=cookies,
                    reason="timeout_waiting_challenge_clear",
                    page_bytes=last_len,
                )
            reason = "cleared"
            if otp_auth_id and otp_challenge_id:
                reason = "cleared_with_otp"
            elif signup_result is not None:
                reason = "cleared_with_signup"
            logger.success(
                "Headed browser assist cleared purpose={} final_url={} bytes={} cookies={} otp={} signup={}",
                purpose,
                last_url[:160],
                last_len,
                len(cookies or []),
                bool(otp_auth_id and otp_challenge_id),
                signup_result is not None,
            )
            return BrowserAssistResult(
                ok=True,
                final_url=last_url,
                cookies=cookies,
                reason=reason,
                page_bytes=last_len,
                otp_auth_id=otp_auth_id,
                otp_challenge_id=otp_challenge_id,
                otp_state=otp_state,
                signup_result=signup_result,
                extra={"authorize": authorize_result} if authorize_result is not None else {},
            )
    except Exception as e:
        logger.error("Headed browser assist failed: {}", e)
        return BrowserAssistResult(ok=False, reason=f"browser_error:{e}")
