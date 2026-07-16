import unittest
import urllib.parse
from unittest.mock import patch

import httpx
from socksio.exceptions import ProtocolError

from paypal.ba_flow import PayPalBAFlow
from paypal.models import generate_country_materials
from paypal.session import PayPalSession


class FakeResponse:
    def __init__(self, url: str, text: str = "", status_code: int = 200, headers=None):
        self.url = httpx.URL(url)
        self.text = text
        self.content = text.encode()
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {})


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.get_urls = []
        self.post_urls = []
        self.graphql_calls = []

    def get(self, url, **kwargs):
        self.get_urls.append(url)
        return self.response

    def post(self, url, **kwargs):
        self.post_urls.append(url)
        raise AssertionError("BA direct signup path should not submit ModXO fallback forms")

    def graphql(self, operation_name, query, variables, **kwargs):
        self.graphql_calls.append((operation_name, variables, kwargs))
        return {"data": {}}

    def close(self):
        return None


class Phase4Session:
    def __init__(self):
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        if "pm-redirects.stripe.com" in url:
            return FakeResponse("https://pay.openai.com/c/pay/test?redirect_status=succeeded")
        return FakeResponse(url, "<html>review</html>")

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return FakeResponse(
            url,
            '{"returnUrl":"https://pm-redirects.stripe.com/return/test"}',
        )

    def close(self):
        return None


class RetryClient:
    def __init__(self):
        self.calls = 0

    def request(self, method, url, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise ProtocolError("Malformed reply")
        return FakeResponse(url, "ok")


class DirectRetryClient:
    def __init__(self, fail_count: int):
        self.fail_count = fail_count
        self.calls = 0

    def request(self, method, url, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_count:
            raise httpx.ConnectError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred")
        return FakeResponse(url, "ok")


class BAHarContractTests(unittest.TestCase):
    def make_flow(self):
        user, card, address, _ = generate_country_materials("+38761123456", "BA")
        return PayPalBAFlow(
            "BA-TEST12345678",
            user,
            card,
            address,
            proxy_enabled=False,
        )

    def test_socks_malformed_reply_is_retryable_transport_error(self):
        self.assertTrue(PayPalSession._is_proxy_transport_error(ProtocolError("Malformed reply")))
        self.assertTrue(PayPalSession._is_proxy_transport_error(httpx.ConnectError("failed")))
        self.assertFalse(PayPalSession._is_proxy_transport_error(ValueError("business")))

    def test_socks_malformed_reply_retries_the_request(self):
        session = object.__new__(PayPalSession)
        session.proxy_url = "socks5://proxy.example:1080"
        session.proxy_label = "socks5://proxy.example:1080"
        session.proxy_entries = ()
        session.proxy_index = 0
        session.client = RetryClient()
        session._sync_state_cookies = lambda: None

        response = session._request_with_proxy_retries("POST", "https://www.paypal.com/graphql")
        self.assertEqual(200, response.status_code)
        self.assertEqual(2, session.client.calls)

    def test_direct_ssl_eof_retries_the_request(self):
        session = object.__new__(PayPalSession)
        session.proxy_url = None
        session.proxy_label = "代理关闭"
        session.client = DirectRetryClient(fail_count=1)
        session._sync_state_cookies = lambda: None

        response = session._request_with_proxy_retries(
            "GET",
            "https://www.paypal.com/agreements/approve?ba_token=BA-TEST12345678",
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual(2, session.client.calls)

    def test_direct_ssl_eof_after_retries_explains_proxy_disabled(self):
        session = object.__new__(PayPalSession)
        session.proxy_url = None
        session.proxy_label = "代理关闭"
        session.client = DirectRetryClient(fail_count=PayPalSession.PROXY_REQUEST_ATTEMPTS)
        session._sync_state_cookies = lambda: None

        with self.assertRaisesRegex(RuntimeError, "proxy is disabled"):
            session._request_with_proxy_retries(
                "GET",
                "https://www.paypal.com/agreements/approve?ba_token=BA-TEST12345678",
            )
        self.assertEqual(PayPalSession.PROXY_REQUEST_ATTEMPTS, session.client.calls)

    def test_ba_signup_and_billing_contract_matches_har(self):
        flow = self.make_flow()
        try:
            flow.state.ssrt = "1234567890"
            flow.state.ec_token = "EC-TEST123456"
            flow.state.content_identifier = "BA:en:HASH123:compliance.signupTerms"
            variables = flow._build_signup_variables(flow.state.ec_token)

            self.assertEqual("387", variables["phone"]["countryCode"])
            self.assertEqual("BA", variables["nationality"])
            self.assertIn("dateOfBirth", variables)
            self.assertIsNone(flow._signup_extra_body(flow.state.ec_token))
            self.assertEqual(
                {"line1", "city", "accountQuality", "country", "familyName", "givenName"},
                set(variables["shippingAddress"]),
            )

            hermes = urllib.parse.parse_qs(urllib.parse.urlsplit(flow._us_hermes_url()).query)
            review = urllib.parse.parse_qs(
                urllib.parse.urlsplit(flow._us_hermes_review_url()).query
            )
            billing = urllib.parse.parse_qs(
                urllib.parse.urlsplit(flow._us_billing_url()).query
            )
            self.assertEqual(["EC-TEST123456"], hermes["token"])
            self.assertIn("addFIContingency", hermes)
            self.assertNotIn("addFIContingency", review)
            self.assertEqual(["BA-TEST12345678"], billing["token"])
            self.assertEqual(
                ["modxo_vaulted_not_recurring-Approve_Billing_Agreement"],
                billing["paypal_client_cfci"],
            )

            form = {name: value for name, (_, value) in flow._us_billing_form_files()}
            self.assertEqual("594", form["_1_threeDsScreenHeight"])
            self.assertEqual("384", form["_1_threeDsScreenWidth"])
            self.assertEqual("-480", form["_1_threeDsTimeZoneOffset"])
            self.assertFalse(flow.billing_send_rsc_header)
        finally:
            flow.close()

    def test_phase0_extracts_ec_token_from_initial_approval_html(self):
        flow = self.make_flow()
        flow.session.close()
        html = (
            '<html><script>window.test="EC-TEST123456";</script>'
            '<div data-value="ssrt=1234567890"></div>'
            '<script>window.data={"ctxId":"ctx-test"}</script></html>'
        )
        flow.session = FakeSession(
            FakeResponse(
                "https://www.paypal.com/agreements/approve?ba_token=BA-TEST12345678",
                html,
            )
        )
        flow._phase0_initial_load()
        self.assertEqual("EC-TEST123456", flow.state.ec_token)
        self.assertEqual("1234567890", flow.state.ssrt)
        self.assertEqual("ctx-test", flow.state.ctx_id)

    def test_phase2_uses_initial_ec_token_and_skips_modxo_fallback(self):
        flow = self.make_flow()
        flow.session.close()
        flow.state.ec_token = "EC-TEST123456"
        flow.state.ssrt = "1234567890"
        signup_html = (
            '<script>window.__INITIAL_DATA__ = {"contentHash":"HASH123"};</script>'
            '"contentIdentifier":"BA:en:HASH123:compliance.signupTerms"'
        )
        fake_session = FakeSession(
            FakeResponse(
                "https://www.paypal.com/checkoutweb/signup?token=EC-TEST123456",
                signup_html,
            )
        )
        flow.session = fake_session

        with (
            patch("paypal.flow.send_tealeaf_data"),
            patch("paypal.flow.send_observability_emit"),
            patch("paypal.flow.send_weasley_log"),
            patch("paypal.flow.send_device_fingerprint"),
        ):
            flow._phase2_create_account()

        self.assertFalse(fake_session.post_urls)
        self.assertTrue(flow.state.signup_url)
        self.assertEqual("BA:en:HASH123:compliance.signupTerms", flow.state.content_identifier)
        deferred = next(call for call in fake_session.graphql_calls if call[0] == "DeferredFeature")
        self.assertEqual("MOBILE", deferred[1]["channel"])

    def test_phase4_follows_ba_hermes_billing_and_return_contract(self):
        flow = self.make_flow()
        flow.session.close()
        flow.state.ec_token = "EC-TEST123456"
        flow.state.ssrt = "1234567890"
        flow.state.signup_url = flow._build_signup_url()
        phase4_session = Phase4Session()
        flow.session = phase4_session

        with (
            patch("paypal.us_flow.send_tealeaf_data"),
            patch("paypal.us_flow.send_observability_emit"),
        ):
            result = flow._phase4_authorize()

        self.assertEqual("success", result["status"])
        self.assertEqual(3, len(phase4_session.get_calls))
        first_query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(phase4_session.get_calls[0][0]).query
        )
        review_query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(phase4_session.get_calls[1][0]).query
        )
        self.assertIn("addFIContingency", first_query)
        self.assertNotIn("addFIContingency", review_query)

        billing_url, billing_kwargs = phase4_session.post_calls[0]
        billing_query = urllib.parse.parse_qs(urllib.parse.urlsplit(billing_url).query)
        self.assertEqual(["BA-TEST12345678"], billing_query["token"])
        self.assertEqual(flow.billing_next_action_fallback, billing_kwargs["headers"]["Next-Action"])
        self.assertNotIn("RSC", billing_kwargs["headers"])
        referer_query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(billing_kwargs["headers"]["Referer"]).query
        )
        self.assertEqual(["BA-TEST12345678"], referer_query["token"])
        self.assertNotIn("paypal_client_cfci", referer_query)


if __name__ == "__main__":
    unittest.main()
