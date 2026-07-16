import unittest
from urllib.parse import quote

from paypal.browser_assist import (
    _is_paypal_unavailable_or_invalid_link_html,
    _mask_proxy_for_log,
    _proxy_for_playwright,
    _signup_result_is_browser_submission_failure,
)


class BrowserProxyBindingTests(unittest.TestCase):
    def test_http_userinfo_is_unquoted_for_playwright(self):
        user = quote("a@b", safe="")
        password = quote("p:s/s", safe="")
        url = f"http://{user}:{password}@gate-us.kookeey.info:1000"
        conf = _proxy_for_playwright(url)
        self.assertEqual(conf["server"], "http://gate-us.kookeey.info:1000")
        self.assertEqual(conf["username"], "a@b")
        self.assertEqual(conf["password"], "p:s/s")

    def test_fragment_fingerprint_is_ignored(self):
        url = "http://user:pass@gate-sea.kookeey.info:1000#ab12cd"
        conf = _proxy_for_playwright(url)
        self.assertEqual(conf["server"], "http://gate-sea.kookeey.info:1000")
        self.assertEqual(conf["username"], "user")
        self.assertEqual(conf["password"], "pass")

    def test_mask_hides_credentials(self):
        masked = _mask_proxy_for_log("http://user:pass@gate-us.kookeey.info:1000")
        self.assertEqual(masked, "http://***:***@gate-us.kookeey.info:1000")
        self.assertEqual(_mask_proxy_for_log(None), "off")

    def test_empty_proxy_is_off(self):
        self.assertIsNone(_proxy_for_playwright(None))
        self.assertIsNone(_proxy_for_playwright(""))


class BrowserPageDetectionTests(unittest.TestCase):
    def test_portuguese_paypal_unavailable_page_is_terminal(self):
        html = """
        <html><title>PayPal</title><body>
        <div>Parece que as coisas não estão funcionando no momento.</div>
        </body></html>
        """
        self.assertTrue(
            _is_paypal_unavailable_or_invalid_link_html(
                "https://www.paypal.com/agreements/approve?ba_token=BA-123&h=1",
                html,
            )
        )

    def test_signup_form_is_not_terminal_error(self):
        html = """
        <html><body>
        <form action="/checkoutweb/signup">
        <input name="cardnumber"><input name="email">
        <span>Numero do cartao</span><span>Data de vencimento</span>
        </form>
        </body></html>
        """
        self.assertFalse(
            _is_paypal_unavailable_or_invalid_link_html(
                "https://www.paypal.com/checkoutweb/signup?token=EC-123",
                html,
            )
        )

    def test_browser_signup_exception_is_not_cleared(self):
        result = {
            "data": {},
            "errors": [{"message": "BROWSER_SIGNUP_EXCEPTION"}],
        }
        self.assertTrue(
            _signup_result_is_browser_submission_failure(
                result,
                "chrome-error://chromewebdata/",
            )
        )

    def test_browser_signup_error_with_access_token_can_continue(self):
        result = {
            "data": {"onboardAccount": None},
            "errors": [{
                "message": "INSTRUMENT_SHARING_LIMIT_EXCEEDED",
                "errorData": {"accessToken": "EUAT"},
            }],
        }
        self.assertFalse(
            _signup_result_is_browser_submission_failure(
                result,
                "https://www.paypal.com/checkoutweb/signup?token=EC-123",
            )
        )


if __name__ == "__main__":
    unittest.main()
