from pathlib import Path

# --- session.py: import cookies helper ---
sess_path = Path("paypal/session.py")
sess = sess_path.read_text(encoding="utf-8")
if "def import_browser_cookies" not in sess:
    marker = "    def _sync_state_cookies(self):\n"
    idx = sess.find(marker)
    if idx < 0:
        raise SystemExit("sync cookies marker not found")
    helper = '''    def export_cookie_list(self) -> list[dict]:
        """Export current jar as browser-friendly cookie dicts."""
        out: list[dict] = []
        for cookie in self.client.cookies.jar:
            if not isinstance(cookie, Cookie):
                continue
            item = {
                "name": cookie.name,
                "value": cookie.value or "",
                "domain": cookie.domain or ".paypal.com",
                "path": cookie.path or "/",
                "secure": bool(cookie.secure),
            }
            out.append(item)
        return out

    def import_browser_cookies(self, cookies: list[dict] | None) -> int:
        """Import cookies produced by headed browser assist into httpx jar."""
        if not cookies:
            return 0
        imported = 0
        for c in cookies:
            name = str(c.get("name") or "").strip()
            value = c.get("value")
            if not name or value is None:
                continue
            domain = str(c.get("domain") or ".paypal.com").strip() or ".paypal.com"
            path = str(c.get("path") or "/").strip() or "/"
            try:
                self.client.cookies.set(name, str(value), domain=domain, path=path)
                imported += 1
            except Exception:
                try:
                    self.client.cookies.set(name, str(value))
                    imported += 1
                except Exception:
                    pass
        self._sync_state_cookies()
        return imported

'''
    sess = sess[:idx] + helper + sess[idx:]
    sess_path.write_text(sess, encoding="utf-8")
    print("session cookies helpers ok")
else:
    print("session helpers already present")

# --- flow.py integration ---
flow_path = Path("paypal/flow.py")
flow = flow_path.read_text(encoding="utf-8")

if "from paypal.browser_assist import" not in flow:
    flow = flow.replace(
        "from paypal.session import PayPalSession, sanitize_for_log\n",
        "from paypal.session import PayPalSession, sanitize_for_log\nfrom paypal.browser_assist import solve_with_headed_browser\n",
        1,
    )

# helper methods on PayPalFlow if missing
if "def _browser_assist_enabled" not in flow:
    insert_at = flow.find("    def _phase0_is_dirty")
    if insert_at < 0:
        # after page signals / dirty reason methods exist, insert before _phase0_reset
        insert_at = flow.find("    def _phase0_reset_partial_state")
    if insert_at < 0:
        raise SystemExit("insert point not found")
    helpers = '''    def _browser_assist_enabled(self) -> bool:
        import os
        raw = (os.getenv("PAYPAL_BROWSER_ASSIST") or "1").strip().lower()
        return raw not in {"0", "false", "no", "off"}

    def _browser_assist_timeout_sec(self) -> float:
        import os
        try:
            return max(30.0, float((os.getenv("PAYPAL_BROWSER_ASSIST_TIMEOUT") or "120").strip() or "120"))
        except Exception:
            return 120.0

    def _run_headed_browser_assist(self, url: str, *, purpose: str) -> bool:
        """Open headed browser for DataDome/authchallenge and import cookies."""
        if not self._browser_assist_enabled():
            logger.warning("Headed browser assist disabled by PAYPAL_BROWSER_ASSIST=0")
            return False
        if not url:
            return False
        seed = []
        try:
            seed = self.session.export_cookie_list()
        except Exception:
            seed = []
        logger.warning(
            "Launching headed browser assist for {} ... complete the challenge in the browser window",
            purpose,
        )
        result = solve_with_headed_browser(
            url,
            proxy_url=getattr(self.session, "proxy_url", None),
            seed_cookies=seed,
            timeout_sec=self._browser_assist_timeout_sec(),
            purpose=purpose,
        )
        if result.cookies:
            imported = self.session.import_browser_cookies(result.cookies)
            logger.info("Imported {} browser cookies after {}", imported, purpose)
        if not result.ok:
            logger.error(
                "Headed browser assist failed purpose={} reason={} final_url={} bytes={}",
                purpose,
                result.reason,
                (result.final_url or "")[:160],
                result.page_bytes,
            )
            return False
        # Refresh tokens from final URL when available.
        final_url = result.final_url or url
        ssrt_match = re.search(r"ssrt=(\\d+)", final_url)
        if ssrt_match:
            self.state.ssrt = ssrt_match.group(1)
        ec_match = re.search(r"EC-[A-Za-z0-9]+", final_url)
        if ec_match:
            self.state.ec_token = ec_match.group(0)
        logger.success(
            "Headed browser assist success purpose={} final_url={} bytes={}",
            purpose,
            final_url[:160],
            result.page_bytes,
        )
        return True

'''
    flow = flow[:insert_at] + helpers + flow[insert_at:]

# Phase0: on dirty, try headed browser before rotating proxy
old_phase0_dirty_handle = '''            dirty_reason = self._phase0_dirty_reason(resp, html) or "unknown"
            sig = self._phase0_page_signals(resp, html)
            logger.warning(
                "Phase0 dirty/blocked on attempt {}/{}: status={} bytes={} reason={} "
                "context={} modxo={} datadome={} captcha={} title={!r} proxy={}",
                attempt,
                max_attempts,
                last_status,
                last_bytes,
                dirty_reason,
                sig.get("has_context"),
                sig.get("has_modxo"),
                sig.get("has_datadome"),
                sig.get("has_captcha_delivery"),
                sig.get("title") or "",
                getattr(self.session, "proxy_label", self.proxy_config.label),
            )
            if attempt >= max_attempts:
                break
'''
new_phase0_dirty_handle = '''            dirty_reason = self._phase0_dirty_reason(resp, html) or "unknown"
            sig = self._phase0_page_signals(resp, html)
            logger.warning(
                "Phase0 dirty/blocked on attempt {}/{}: status={} bytes={} reason={} "
                "context={} modxo={} datadome={} captcha={} title={!r} proxy={}",
                attempt,
                max_attempts,
                last_status,
                last_bytes,
                dirty_reason,
                sig.get("has_context"),
                sig.get("has_modxo"),
                sig.get("has_datadome"),
                sig.get("has_captcha_delivery"),
                sig.get("title") or "",
                getattr(self.session, "proxy_label", self.proxy_config.label),
            )
            # Prefer headed browser on the current proxy before rotating away.
            assist_url = f"https://www.paypal.com/agreements/approve?ba_token={self.ba_token}"
            if self._run_headed_browser_assist(assist_url, purpose="phase0_datadome"):
                # Re-load via HTTP with imported cookies; if still dirty, continue rotate.
                try:
                    self._phase0_reset_partial_state()
                    resp2, html2 = self._phase0_attempt_once()
                    if not self._phase0_is_dirty(resp2, html2):
                        logger.success(
                            "Phase0 recovered after headed browser assist: status={} bytes={}",
                            getattr(resp2, "status_code", 0),
                            len(html2 or ""),
                        )
                        return
                    logger.warning(
                        "Headed browser assist finished but HTTP Phase0 still dirty: status={} bytes={} reason={}",
                        getattr(resp2, "status_code", 0),
                        len(html2 or ""),
                        self._phase0_dirty_reason(resp2, html2),
                    )
                except Exception as e:
                    logger.warning("Phase0 reload after browser assist failed: {}", e)
            if attempt >= max_attempts:
                break
'''
if old_phase0_dirty_handle not in flow:
    raise SystemExit("phase0 dirty handle block not found")
flow = flow.replace(old_phase0_dirty_handle, new_phase0_dirty_handle, 1)

# OTP: on authchallenge use headed browser then retry once
old_otp = '''            except Exception as e:
                logger.error("Failed to initiate OTP for {}: {}", self._masked_phone(), e)
                # authchallenge HTML means the session is already risk-blocked.
                # Changing phone on the same session almost never recovers it.
                if self._is_session_challenge_error(e):
                    raise RuntimeError(
                        "Session challenged during OTP send (authchallenge/non-JSON). "
                        "Phase2 likely hit genericError or a dirty proxy exit. "
                        "Reopen the task with a cleaner residential sticky session; "
                        "do not keep retrying phones on this session."
                    ) from e
'''
new_otp = '''            except Exception as e:
                logger.error("Failed to initiate OTP for {}: {}", self._masked_phone(), e)
                # authchallenge HTML: first try headed browser assist on signup URL.
                if self._is_session_challenge_error(e):
                    signup_url_for_assist = signup_url or self.state.signup_url or (
                        f"https://www.paypal.com/checkoutweb/signup?token={token}&ul=1"
                    )
                    if self._run_headed_browser_assist(
                        signup_url_for_assist,
                        purpose="otp_authchallenge",
                    ):
                        try:
                            auth_id, challenge_id = self._initiate_2fa_phone_confirmation(token, signup_url)
                            # success path continues below with returned ids
                            # by jumping into normal confirm loop via assignment
                            logger.success("OTP initiate recovered after headed browser assist")
                            # fall through by using a nested success path
                            pass
                        except Exception as e2:
                            raise RuntimeError(
                                "Session still challenged after headed browser assist "
                                f"({e2}). Reopen with a cleaner residential sticky session."
                            ) from e2
                        else:
                            # We have auth_id/challenge_id now; proceed to OTP prompt loop body.
                            # Emulate successful initiate by continuing with local vars set.
                            # (code below expects auth_id/challenge_id defined)
                            pass
                    else:
                        raise RuntimeError(
                            "Session challenged during OTP send (authchallenge/non-JSON). "
                            "Headed browser assist did not clear it. Reopen the task with a "
                            "cleaner residential sticky session."
                        ) from e
                    # If assist recovered, continue into confirm loop with new ids.
                    # The variables auth_id/challenge_id were set in the try above.
'''

# The OTP control flow is delicate because auth_id/challenge_id need to stay in scope.
# Use a cleaner rewrite of the whole initiate try-block in _confirm_phone_with_retry.
start = flow.find("    def _confirm_phone_with_retry(self, token: str, signup_url: str):")
if start < 0:
    raise SystemExit("confirm phone method not found")
end = flow.find("\n    def _", start + 1)
if end < 0:
    end = len(flow)
old_method = flow[start:end]
# Only replace the initiate exception branch carefully with a rewritten method body start
new_method = '''    def _confirm_phone_with_retry(self, token: str, signup_url: str):
        """Loop until OTP is confirmed; allow at most one phone change on send failure."""
        phone_changes = 0
        max_phone_changes = 1
        browser_assist_used = False
        while True:
            try:
                auth_id, challenge_id = self._initiate_2fa_phone_confirmation(token, signup_url)
            except Exception as e:
                logger.error("Failed to initiate OTP for {}: {}", self._masked_phone(), e)
                if self._is_session_challenge_error(e) and not browser_assist_used:
                    browser_assist_used = True
                    assist_url = signup_url or self.state.signup_url or (
                        f"https://www.paypal.com/checkoutweb/signup?token={token}&ul=1"
                        f"&locale.x={self.state.locale or 'pt_BR'}&country.x={self.address.country}"
                    )
                    if self._run_headed_browser_assist(assist_url, purpose="otp_authchallenge"):
                        try:
                            auth_id, challenge_id = self._initiate_2fa_phone_confirmation(token, signup_url)
                            logger.success("OTP initiate recovered after headed browser assist")
                        except Exception as e2:
                            raise RuntimeError(
                                "Session still challenged after headed browser assist "
                                f"({e2}). Reopen with a cleaner residential sticky session."
                            ) from e2
                    else:
                        raise RuntimeError(
                            "Session challenged during OTP send (authchallenge/non-JSON). "
                            "Headed browser assist did not clear it. Reopen the task with a "
                            "cleaner residential sticky session."
                        ) from e
                elif self._is_session_challenge_error(e):
                    raise RuntimeError(
                        "Session challenged during OTP send (authchallenge/non-JSON). "
                        "Headed browser assist already attempted. Reopen the task with a "
                        "cleaner residential sticky session."
                    ) from e
                elif phone_changes >= max_phone_changes:
                    raise RuntimeError(
                        "OTP send failed and phone-change limit reached. "
                        "Reopen the task instead of continuing on this session."
                    ) from e
                else:
                    while True:
                        value = input(
                            "\\n>>> 发送验证码失败。可再换 1 次手机号；"
                            "若继续失败请输入 q 并重开任务（如 +5591980133818）: "
                        ).strip()
                        if value.lower() in {"q", "quit", "exit"}:
                            raise RuntimeError("OTP confirmation cancelled by user") from e
                        try:
                            self._update_user_phone(value)
                            phone_changes += 1
                            break
                        except ValueError as phone_error:
                            logger.warning("手机号无效：{}。请重新输入。", phone_error)
                    continue

            logger.info("SMS verification code sent to phone: {}", self._masked_phone())
'''
# Keep the remainder of old method after first successful initiate log line.
# Find the rest from old_method after "SMS verification code sent"
rest_marker = "logger.info(\"SMS verification code sent to phone: {}\", self._masked_phone())"
rest_idx = old_method.find(rest_marker)
if rest_idx < 0:
    raise SystemExit("sms sent marker not found in old method")
# old rest starts after that full line
line_end = old_method.find("\n", rest_idx)
rest = old_method[line_end+1:]
# But new_method already includes the sms log line; append rest
# Remove possible duplicate phone-change initiate exception handling already rewritten.
flow = flow[:start] + new_method + rest + flow[end:]

flow_path.write_text(flow, encoding="utf-8")
print("flow.py browser assist integrated")

# web.py OTP path
web_path = Path("web.py")
web = web_path.read_text(encoding="utf-8")
wstart = web.find("    def _confirm_phone_with_retry(self, token: str, signup_url: str):")
if wstart >= 0:
    wend = web.find("\n    def _", wstart + 1)
    if wend < 0:
        wend = len(web)
    old_w = web[wstart:wend]
    rest_marker = "logger.info(\"SMS verification code sent to phone: {}\", self._masked_phone())"
    rest_idx = old_w.find(rest_marker)
    if rest_idx < 0:
        print("web confirm method marker missing; skip rewrite")
    else:
        line_end = old_w.find("\n", rest_idx)
        rest = old_w[line_end+1:]
        new_w = '''    def _confirm_phone_with_retry(self, token: str, signup_url: str):
        """Web version of the CLI input loop with limited phone changes."""
        phone_changes = 0
        max_phone_changes = 1
        browser_assist_used = False
        while True:
            try:
                auth_id, challenge_id = self._initiate_2fa_phone_confirmation(token, signup_url)
            except Exception as e:
                logger.error("Failed to initiate OTP for {}: {}", self._masked_phone(), e)
                if self._is_session_challenge_error(e) and not browser_assist_used:
                    browser_assist_used = True
                    assist_url = signup_url or self.state.signup_url or (
                        f"https://www.paypal.com/checkoutweb/signup?token={token}&ul=1"
                        f"&locale.x={self.state.locale or 'pt_BR'}&country.x={self.address.country}"
                    )
                    if self._run_headed_browser_assist(assist_url, purpose="otp_authchallenge"):
                        try:
                            auth_id, challenge_id = self._initiate_2fa_phone_confirmation(token, signup_url)
                            logger.success("OTP initiate recovered after headed browser assist")
                        except Exception as e2:
                            raise RuntimeError(
                                "Session still challenged after headed browser assist "
                                f"({e2}). Reopen with a cleaner residential sticky session."
                            ) from e2
                    else:
                        raise RuntimeError(
                            "Session challenged during OTP send (authchallenge/non-JSON). "
                            "Headed browser assist did not clear it. Reopen the task with a "
                            "cleaner residential sticky session."
                        ) from e
                elif self._is_session_challenge_error(e):
                    raise RuntimeError(
                        "Session challenged during OTP send (authchallenge/non-JSON). "
                        "Headed browser assist already attempted. Reopen the task with a "
                        "cleaner residential sticky session."
                    ) from e
                elif phone_changes >= max_phone_changes:
                    raise RuntimeError(
                        "OTP send failed and phone-change limit reached. "
                        "Reopen the task instead of continuing on this session."
                    ) from e
                else:
                    while True:
                        value = self._prompt_operator(
                            "发送验证码失败。可再换 1 次手机号；"
                            "若继续失败请输入 q 并重开任务（如 +5591980133818）。"
                        )
                        if value.lower() in {"q", "quit", "exit"}:
                            raise RuntimeError("OTP confirmation cancelled by user") from e
                        try:
                            self._update_user_phone(value)
                            phone_changes += 1
                            break
                        except ValueError as phone_error:
                            logger.warning("手机号无效：{}。请重新输入。", phone_error)
                    continue

            logger.info("SMS verification code sent to phone: {}", self._masked_phone())
'''
        web = web[:wstart] + new_w + rest + web[wend:]
        web_path.write_text(web, encoding="utf-8")
        print("web.py otp browser assist integrated")
else:
    print("web confirm method not found")
