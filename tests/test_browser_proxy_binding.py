import unittest
from urllib.parse import quote

from paypal.browser_assist import _mask_proxy_for_log, _proxy_for_playwright


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


if __name__ == "__main__":
    unittest.main()
