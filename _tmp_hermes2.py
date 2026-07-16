from pathlib import Path
import re

# ---- browser_assist: bootstrap_url + hermes usable detection ----
ba = Path("paypal/browser_assist.py")
text = ba.read_text(encoding="utf-8")

# extend page usable for hermes/pay shells
old_usable = '''def _page_looks_usable(url: str, html: str) -> bool:
    text = html or ""
    low = text.lower()

    # Highest priority: real signup form already visible. Operator need do nothing.
    if _is_signup_form_html(url, text):
        return True

    if _is_hard_challenge_html(text):
        return False
'''
new_usable = '''def _page_looks_usable(url: str, html: str) -> bool:
    text = html or ""
    low = text.lower()
    url_l = (url or "").lower()

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
'''
if "webapps/hermes" not in text.split("def _page_looks_usable",1)[1][:800]:
    if old_usable not in text:
        raise SystemExit("usable block missing")
    text = text.replace(old_usable, new_usable, 1)
    print("usable hermes signals added")
else:
    print("usable already has hermes")

# add bootstrap_url param
old_sig = '''def solve_with_headed_browser(
    url: str,
    *,
    proxy_url: str | None = None,
    seed_cookies: list[dict[str, Any]] | None = None,
    user_agent: str | None = None,
    timeout_sec: float = 120.0,
    wait_for_manual: bool = True,
    purpose: str = "challenge",
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
) -> BrowserAssistResult:
'''
new_sig = '''def solve_with_headed_browser(
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
) -> BrowserAssistResult:
'''
if "bootstrap_url: str | None = None" not in text:
    if old_sig not in text:
        raise SystemExit("sig missing")
    text = text.replace(old_sig, new_sig, 1)
    print("bootstrap_url param added")

# replace page.goto(url...) with bootstrap then target
old_goto = '''            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            deadline = time.time() + max(15.0, float(timeout_sec))
'''
new_goto = '''            page = context.new_page()
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
'''
if "Headed browser bootstrap done" not in text:
    if old_goto not in text:
        raise SystemExit("goto block missing")
    text = text.replace(old_goto, new_goto, 1)
    print("bootstrap navigation added")

# soft-pass hermes large pages
old_soft = '''            if not usable and "checkoutweb/signup" in (last_url or "") and last_len > 20000 and not _is_hard_challenge_html(last_html):
                logger.warning(
                    "Headed browser timeout soft-pass on signup shell url={} bytes={}",
                    last_url[:160],
                    last_len,
                )
                usable = True
'''
new_soft = '''            if not usable and "checkoutweb/signup" in (last_url or "") and last_len > 20000 and not _is_hard_challenge_html(last_html):
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
'''
if "soft-pass on hermes/billing" not in text:
    if old_soft not in text:
        raise SystemExit("soft pass missing")
    text = text.replace(old_soft, new_soft, 1)
    print("hermes soft-pass added")

ba.write_text(text, encoding="utf-8")
print("browser_assist updated")

# ---- flow.py phase4 harden ----
fp = Path("paypal/flow.py")
flow = fp.read_text(encoding="utf-8")

# extend _run_headed_browser_assist with bootstrap_url
if "bootstrap_url: str | None = None" not in flow.split("def _run_headed_browser_assist",1)[1][:500]:
    flow = flow.replace(
        '''    def _run_headed_browser_assist(
        self,
        url: str,
        *,
        purpose: str,
        otp_phone_local: str | None = None,
        otp_token: str | None = None,
        signup_variables: dict | None = None,
        signup_token: str | None = None,
        signup_fn_sync_data: str | None = None,
    ):
''',
        '''    def _run_headed_browser_assist(
        self,
        url: str,
        *,
        purpose: str,
        otp_phone_local: str | None = None,
        otp_token: str | None = None,
        signup_variables: dict | None = None,
        signup_token: str | None = None,
        signup_fn_sync_data: str | None = None,
        bootstrap_url: str | None = None,
    ):
''',
        1,
    )
    flow = flow.replace(
        '''        kwargs = {
            "proxy_url": getattr(self.session, "proxy_url", None),
            "seed_cookies": seed,
            "timeout_sec": self._browser_assist_timeout_sec(),
            "purpose": purpose,
        }
''',
        '''        kwargs = {
            "proxy_url": getattr(self.session, "proxy_url", None),
            "seed_cookies": seed,
            "timeout_sec": self._browser_assist_timeout_sec(),
            "purpose": purpose,
            "bootstrap_url": bootstrap_url,
        }
''',
        1,
    )
    print("flow assist bootstrap_url wired")
else:
    print("flow assist already has bootstrap")

# Replace phase4 hermes prebind section with warmup + fail-closed
old = '''        hermes_base_url, hermes_review_url = self._build_hermes_urls()
        # Keep review referer as the contingency shell URL (no forced billingLite).
        review_referer = hermes_review_url
        review_url = hermes_review_url
        referer = (
            self.state.signup_url
            or f"https://www.paypal.com/checkoutweb/signup?token={billing_agreement_id}"
        )

        # 1) Bind buyer session on Hermes before authorize GraphQL.
        # HAR-proven order after card contingency:
        #   signup referer -> hermes(entry with reason/addFIContingency) -> hermes(review)
        hermes_bound = False
        try:
            logger.info(
                "Phase4 step1: GET Hermes contingency shell reason={}",
                self.state.signup_contingency_reason or "CARD_GENERIC_ERROR",
            )
            hermes_headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Referer": referer,
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-User": "?1",
            }
            if self.state.euat_token:
                hermes_headers["X-PayPal-Internal-EUAT"] = self.state.euat_token

            hermes_resp = self.session.get(hermes_base_url, headers=hermes_headers)
            redirect_url = hermes_resp.headers.get("Location", "")
            if hermes_resp.status_code in (301, 302, 303, 307, 308) and redirect_url:
                redirect_url = _urlparse.urljoin(hermes_base_url, redirect_url)
                hermes_resp = self.session.get(
                    redirect_url,
                    headers={**hermes_headers, "Referer": hermes_base_url},
                )
                logger.info("Hermes redirected to: {}", str(hermes_resp.url)[:180])

            # Second navigation: review shell without addFIContingency/redirectToHermes.
            if str(hermes_resp.url).split("#", 1)[0].rstrip("/") != hermes_review_url.rstrip("/"):
                logger.info("Phase4 step1b: GET Hermes review shell (fallback+reason)...")
                hermes_resp = self.session.get(
                    hermes_review_url,
                    headers={**hermes_headers, "Referer": str(hermes_resp.url) if hermes_resp is not None else referer},
                )

            html = hermes_resp.text or ""
            hermes_bound = self._hermes_page_is_bound(hermes_resp, html)
            logger.info(
                "Hermes review bound: status={} bytes={} bound={} url={}",
                hermes_resp.status_code,
                len(hermes_resp.content or b""),
                hermes_bound,
                str(hermes_resp.url)[:180],
            )
            if hermes_bound:
                referer = str(hermes_resp.url) or hermes_review_url
            else:
                logger.warning(
                    "Hermes bind looks blocked/empty (status={} bytes={}). "
                    "BUYER_NOT_SET is likely if authorize continues without a real shell.",
                    hermes_resp.status_code,
                    len(hermes_resp.content or b""),
                )
                # One recovery attempt: reopen headed browser on Hermes contingency URL
                # to restore cookies/session, then re-GET review shell.
                assist = self._run_headed_browser_assist(
                    hermes_base_url,
                    purpose="phase4_hermes",
                )
                if assist:
                    hermes_resp = self.session.get(
                        hermes_review_url,
                        headers={**hermes_headers, "Referer": self.state.signup_url or hermes_base_url},
                    )
                    html = hermes_resp.text or ""
                    hermes_bound = self._hermes_page_is_bound(hermes_resp, html)
                    logger.info(
                        "Hermes rebind after browser assist: status={} bytes={} bound={} url={}",
                        hermes_resp.status_code,
                        len(hermes_resp.content or b""),
                        hermes_bound,
                        str(hermes_resp.url)[:180],
                    )
                    if hermes_bound:
                        referer = str(hermes_resp.url) or hermes_review_url
        except Exception as e:
            logger.warning(
                "Hermes pre-bind failed (will still try authorize): {}",
                e,
            )
'''

new = '''        hermes_base_url, hermes_review_url = self._build_hermes_urls()
        # Keep review referer as the contingency shell URL (no forced billingLite).
        review_referer = hermes_review_url
        review_url = hermes_review_url
        signup_referer = (
            self.state.signup_url
            or f"https://www.paypal.com/checkoutweb/signup?token={billing_agreement_id}"
            f"&ul=1&locale.x={self.state.locale or 'pt_BR'}&country.x={self.address.country or 'BR'}"
        )
        referer = signup_referer

        # 1) Bind buyer session on Hermes before authorize GraphQL.
        # HAR-proven order after card contingency:
        #   reopen signup shell -> hermes(entry reason/addFIContingency) -> hermes(review)
        hermes_bound = False
        try:
            hermes_headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Referer": referer,
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-User": "?1",
            }
            if self.state.euat_token:
                hermes_headers["X-PayPal-Internal-EUAT"] = self.state.euat_token

            # Warm same-origin signup shell first (HAR referer source).
            try:
                logger.info("Phase4 step0: warm checkoutweb/signup before Hermes bind...")
                warm = self.session.get(
                    signup_referer,
                    headers={
                        **hermes_headers,
                        "Referer": signup_referer,
                    },
                )
                logger.info(
                    "Signup warm before Hermes: status={} bytes={}",
                    warm.status_code,
                    len(warm.content or b""),
                )
                referer = str(getattr(warm, "url", "") or signup_referer)
                hermes_headers["Referer"] = referer
            except Exception as warm_err:
                logger.warning("Signup warm before Hermes failed: {}", warm_err)

            logger.info(
                "Phase4 step1: GET Hermes contingency shell reason={}",
                self.state.signup_contingency_reason or "CARD_GENERIC_ERROR",
            )
            hermes_resp = self.session.get(hermes_base_url, headers=hermes_headers)
            redirect_url = hermes_resp.headers.get("Location", "")
            if hermes_resp.status_code in (301, 302, 303, 307, 308) and redirect_url:
                redirect_url = _urlparse.urljoin(hermes_base_url, redirect_url)
                hermes_resp = self.session.get(
                    redirect_url,
                    headers={**hermes_headers, "Referer": hermes_base_url},
                )
                logger.info("Hermes redirected to: {}", str(hermes_resp.url)[:180])

            # Second navigation: review shell without addFIContingency/redirectToHermes.
            if str(hermes_resp.url).split("#", 1)[0].rstrip("/") != hermes_review_url.rstrip("/"):
                logger.info("Phase4 step1b: GET Hermes review shell (fallback+reason)...")
                hermes_resp = self.session.get(
                    hermes_review_url,
                    headers={
                        **hermes_headers,
                        "Referer": str(hermes_resp.url) if hermes_resp is not None else referer,
                    },
                )

            html = hermes_resp.text or ""
            hermes_bound = self._hermes_page_is_bound(hermes_resp, html)
            logger.info(
                "Hermes review bound: status={} bytes={} bound={} url={}",
                hermes_resp.status_code,
                len(hermes_resp.content or b""),
                hermes_bound,
                str(hermes_resp.url)[:180],
            )
            if hermes_bound:
                referer = str(hermes_resp.url) or hermes_review_url
            else:
                logger.warning(
                    "Hermes bind looks blocked/empty (status={} bytes={}). "
                    "Recovering via headed browser: signup bootstrap -> Hermes.",
                    hermes_resp.status_code,
                    len(hermes_resp.content or b""),
                )
                # Recovery: open signup first (bootstrap), then Hermes target.
                assist = self._run_headed_browser_assist(
                    hermes_base_url,
                    purpose="phase4_hermes",
                    bootstrap_url=signup_referer,
                )
                if assist:
                    # Prefer final browser URL if it already landed on hermes/pay.
                    final_url = (getattr(assist, "final_url", "") or "").strip()
                    rebind_url = hermes_review_url
                    if "webapps/hermes" in final_url or "/pay/billing" in final_url:
                        rebind_url = final_url.split("#", 1)[0]
                    hermes_resp = self.session.get(
                        rebind_url,
                        headers={**hermes_headers, "Referer": signup_referer},
                    )
                    html = hermes_resp.text or ""
                    hermes_bound = self._hermes_page_is_bound(hermes_resp, html)
                    logger.info(
                        "Hermes rebind after browser assist: status={} bytes={} bound={} url={}",
                        hermes_resp.status_code,
                        len(hermes_resp.content or b""),
                        hermes_bound,
                        str(hermes_resp.url)[:180],
                    )
                    if hermes_bound:
                        referer = str(hermes_resp.url) or hermes_review_url
        except Exception as e:
            logger.warning("Hermes pre-bind failed: {}", e)

        if not hermes_bound:
            return {
                "status": "error",
                "error": (
                    "Hermes buyer session bind failed (403/empty shell). "
                    "Authorize skipped to avoid BUYER_NOT_SET. "
                    "Reopen with a cleaner residential sticky BR proxy/session."
                ),
                "billingAgreementId": billing_agreement_id,
                "euat_present": bool(self.state.euat_token),
                "signup_contingency_reason": self.state.signup_contingency_reason
                or "CARD_GENERIC_ERROR",
            }
'''

if old not in flow:
    raise SystemExit("phase4 prebind block not found exact")
flow = flow.replace(old, new, 1)

# remove old soft-continue guard if present
flow = flow.replace(
'''        if not hermes_bound:
            logger.warning(
                "Proceeding to authorize without confirmed Hermes bind; "
                "expect BUYER_NOT_SET if buyer session cookie/EUAT is incomplete"
            )

''',
    "",
    1,
)

fp.write_text(flow, encoding="utf-8")
print("flow phase4 fail-closed + warmup done")
