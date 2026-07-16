import unittest
from unittest.mock import MagicMock, patch

from paypal.flow import PayPalFlow
from paypal.models import BillingAddress, CardInfo, UserInfo


def _make_flow() -> PayPalFlow:
    user = UserInfo(
        first_name="Ana",
        last_name="Silva",
        email="ana@example.com",
        phone="+5511999999999",
        phone_local="11999999999",
        phone_country_code="55",
        password="Passw0rd!",
        dob="01/01/1990",
        cpf="123.456.789-09",
    )
    card = CardInfo(number="4111111111111111", expiry="12/2030", cvv="123")
    address = BillingAddress(
        street="Avenida Paulista",
        house_number="1000",
        district="Bela Vista",
        city="Sao Paulo",
        state="SP",
        postal_code="01310-100",
        country="BR",
    )
    flow = PayPalFlow(
        ba_token="BA-TEST12345678",
        user=user,
        card=card,
        address=address,
        proxy_enabled=False,
    )
    flow.state.ec_token = "EC-TEST123456"
    flow.state.ssrt = "1234567890"
    flow.state.signup_url = "https://www.paypal.com/checkoutweb/signup?token=EC-TEST123456"
    flow.state.euat_token = "EUAT_TEST_TOKEN_1234567890"
    flow.state.signup_contingency_reason = "INSTRUMENT_SHARING_LIMIT_EXCEEDED"
    return flow


class AuthorizeSuccessGateTests(unittest.TestCase):
    def test_has_buyer_not_set(self):
        payload = [
            {
                "errors": [
                    {
                        "data": {"contingency": "BUYER_NOT_SET"},
                        "message": "400",
                        "path": ["billing", "authorize"],
                    }
                ],
                "data": {"billing": {"authorize": None}},
            }
        ]
        self.assertTrue(PayPalFlow._has_buyer_not_set(payload))
        self.assertFalse(PayPalFlow._has_buyer_not_set({"data": {"billing": {"authorize": {}}}}))

    def test_parse_authorize_payload(self):
        payload = [
            {
                "data": {
                    "billing": {
                        "authorize": {
                            "returnURL": {"href": "https://merchant.example/return"},
                            "billingAgreementToken": "BA-OK",
                            "buyer": {"userId": "BUYER1"},
                        }
                    }
                }
            }
        ]
        return_url, ba, data = PayPalFlow._parse_authorize_payload(payload)
        self.assertEqual(return_url, "https://merchant.example/return")
        self.assertEqual(ba, "BA-OK")
        self.assertEqual(data["buyer"]["userId"], "BUYER1")

    def test_buyer_not_set_does_not_use_context_query_fake_success(self):
        flow = _make_flow()

        class FakeSession:
            def __init__(self):
                self.graphql_ops = []
                self.get_urls = []
                self.post_urls = []
                self.client = MagicMock()
                self.client.cookies = MagicMock()

            def graphql(self, operation_name, query, variables, **kwargs):
                self.graphql_ops.append(operation_name)
                if operation_name == "authorize":
                    return [
                        {
                            "errors": [
                                {
                                    "data": {"contingency": "BUYER_NOT_SET"},
                                    "message": "400",
                                    "path": ["billing", "authorize"],
                                }
                            ],
                            "data": {"billing": {"authorize": None}},
                        }
                    ]
                # Context query must not be used as success fallback anymore.
                return [
                    {
                        "data": {
                            "billing": {
                                "billingAgreementContext": {
                                    "billingAgreementToken": "BA-CONTEXT",
                                    "returnURL": {
                                        "href": "https://merchant.example/context-return"
                                    },
                                }
                            }
                        }
                    }
                ]

            def get(self, url, **kwargs):
                self.get_urls.append(url)
                resp = MagicMock()
                resp.status_code = 200
                resp.content = b"x" * 30000
                resp.text = (
                    "<html>billingweb checkoutuinodeweb approve hagrid pay/billing "
                    "returnurl balancepreference</html>" + ("y" * 25000)
                )
                resp.url = url
                resp.headers = {}
                return resp

            def post(self, url, **kwargs):
                self.post_urls.append(url)
                resp = MagicMock()
                resp.status_code = 200
                resp.content = b"{}"
                resp.text = "{}"
                resp.headers = {}
                resp.url = url
                return resp

            def close(self):
                return None

        fake = FakeSession()
        flow.session = fake

        with (
            patch.object(flow, "_run_headed_browser_assist", return_value=None),
            patch.object(flow, "_phase4_pay_billing_recovery", return_value=None),
            patch("paypal.flow.send_analytics_ts"),
        ):
            result = flow._phase4_authorize()

        self.assertEqual(result["status"], "error")
        self.assertIn("BUYER_NOT_SET", result["error"])
        self.assertIn("authorize", fake.graphql_ops)
        self.assertNotIn(
            "BillingAgreementContextQueryForAddCard",
            fake.graphql_ops,
        )
        flow.close()


if __name__ == "__main__":
    unittest.main()


class SignupOasFailClosedTests(unittest.TestCase):
    def test_is_create_member_account_error(self):
        errors = [
            {
                "message": "OAS_ERROR",
                "_name": "OAS_ERROR",
                "checkpoints": ["createMemberAccount"],
            }
        ]
        self.assertTrue(PayPalFlow._is_create_member_account_error(errors))
        self.assertFalse(
            PayPalFlow._is_create_member_account_error(
                [{"message": "CARD_GENERIC_ERROR", "checkpoints": ["addCard"]}]
            )
        )

    def test_is_anonymous_auth_error(self):
        payload = [
            {
                "errors": [
                    {
                        "message": (
                            "This resolver requires an auth state of either: "
                            "LOGGEDIN, REMEMBERED.  The current auth state is: ANONYMOUS."
                        )
                    }
                ]
            }
        ]
        self.assertTrue(PayPalFlow._is_anonymous_auth_error(payload))

    def test_create_member_oas_without_token_fails_closed(self):
        flow = _make_flow()
        flow.state.euat_token = ""

        class FakeSession:
            def graphql(self, *args, **kwargs):
                raise AssertionError("Phase4/graphql should not be reached")

            def close(self):
                return None

        flow.session = FakeSession()

        def fake_send(token, signup_url, allow_browser_assist=True):
            return [
                {
                    "errors": [
                        {
                            "message": "OAS_ERROR",
                            "_name": "OAS_ERROR",
                            "checkpoints": ["createMemberAccount"],
                            "path": ["onboardAccount"],
                        }
                    ],
                    "data": {"onboardAccount": None},
                }
            ]

        with patch.object(flow, "_send_signup_attempt", side_effect=fake_send):
            with self.assertRaises(RuntimeError) as ctx:
                flow._signup_with_card_retry("EC-TEST", flow.state.signup_url)
        self.assertIn("createMemberAccount/OAS_ERROR", str(ctx.exception))
        self.assertIn("without accessToken", str(ctx.exception))

