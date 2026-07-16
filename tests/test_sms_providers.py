import unittest
from unittest.mock import patch

from paypal import sms_providers
from paypal.sms_providers import (
    HeroSmsReusePool,
    SmsActivateClient,
    SmsProviderConfig,
    extract_sms_code,
    normalize_sms_provider,
    parse_sms_countries,
    parse_sms_price_countries,
    parse_sms_price_services,
    parse_sms_services,
)


class FakeSmsActivateClient:
    counter = 0
    request_another_calls = 0
    cancelled = []
    done = []

    def __init__(self, config):
        self.config = config
        FakeSmsActivateClient.counter += 1
        self.index = FakeSmsActivateClient.counter

    def get_number(self):
        return f"+55119999999{self.index:02d}", f"aid-{self.index}"

    def request_another(self, activation_id):
        FakeSmsActivateClient.request_another_calls += 1
        return True

    def cancel(self, activation_id):
        FakeSmsActivateClient.cancelled.append(activation_id)

    def done(self, activation_id):
        FakeSmsActivateClient.done.append(activation_id)


class RecordingSmsClient(SmsActivateClient):
    def __init__(self, config):
        super().__init__(config)
        self.actions = []

    def _request(self, action, params=None):
        self.actions.append(action)
        if action == "getPrices":
            return '{"73":{"ot":{"cost":0.1,"count":202},"tg":{"cost":0.2,"count":5}}}'
        if action == "getServicesList":
            return '[{"code":"ot","name":"Other"},{"code":"tg","name":"Telegram"}]'
        raise AssertionError(f"unexpected action {action}")


class SmsProvidersTest(unittest.TestCase):
    def setUp(self):
        FakeSmsActivateClient.counter = 0
        FakeSmsActivateClient.request_another_calls = 0
        FakeSmsActivateClient.cancelled = []
        FakeSmsActivateClient.done = []

    def test_provider_alias_and_code_extract(self):
        self.assertEqual("smsbower", normalize_sms_provider("smsbrower"))
        self.assertEqual("herosms", normalize_sms_provider("hero-sms"))
        self.assertEqual("123456", extract_sms_code("PayPal code: 123456."))

    def test_config_from_payload_uses_provider_prefix(self):
        cfg = SmsProviderConfig.from_payload(
            {
                "sms_provider": "smsbrower",
                "smsbower_api_key": "key",
                "smsbower_service": "ot",
                "smsbower_country": "73",
                "sms_timeout_seconds": "60",
            }
        )
        self.assertEqual("smsbower", cfg.provider)
        self.assertEqual("key", cfg.api_key)
        cfg.validate()

    def test_parse_sms_activate_metadata_options(self):
        countries = parse_sms_countries(
            '{"73":{"id":73,"eng":"Brazil","rus":"Бразилия"},"0":{"eng":"Russia"}}'
        )
        self.assertIn({"code": "73", "label": "Brazil"}, countries)
        self.assertIn({"code": "0", "label": "Russia"}, countries)

        services = parse_sms_services(
            '{"ot":{"name":"Any other"},"ts":{"name":"PayPal"}}'
        )
        self.assertIn({"code": "ot", "label": "Any other"}, services)
        self.assertIn({"code": "ts", "label": "PayPal"}, services)

    def test_parse_prices_as_service_options(self):
        services = parse_sms_price_services(
            '{"73":{"ot":{"cost":0.1,"count":202},"ts":{"cost":0.2,"count":5}}}',
            "73",
        )
        self.assertIn({"code": "ot", "label": "ot 库存 202"}, services)
        self.assertIn({"code": "ts", "label": "ts 库存 5"}, services)

        countries = parse_sms_price_countries(
            '{"73":{"ot":{"cost":0.1,"count":202}},"187":{"ot":{"cost":0.2,"count":5}}}'
        )
        self.assertIn({"code": "73", "label": "73"}, countries)
        self.assertIn({"code": "187", "label": "187"}, countries)

    def test_parse_smsbower_services_list(self):
        services = parse_sms_services(
            '[{"code":"ot","name":"Other"},{"code":"tg","name":"Telegram"}]'
        )
        self.assertIn({"code": "ot", "label": "Other"}, services)
        self.assertIn({"code": "tg", "label": "Telegram"}, services)

    def test_service_list_action_matches_provider(self):
        hero_cfg = SmsProviderConfig(
            provider="herosms",
            api_key="key",
            base_url="https://example.test/api",
            service="ot",
            country="73",
        )
        hero = RecordingSmsClient(hero_cfg)
        hero_services = hero.get_services("73")
        self.assertIn({"code": "ot", "label": "Other 库存 202"}, hero_services)
        self.assertIn({"code": "tg", "label": "Telegram 库存 5"}, hero_services)
        self.assertEqual(["getServicesList", "getPrices"], hero.actions)

        smsbower_cfg = SmsProviderConfig(
            provider="smsbower",
            api_key="key",
            base_url="https://example.test/api",
            service="ot",
            country="73",
        )
        smsbower = RecordingSmsClient(smsbower_cfg)
        self.assertIn({"code": "ot", "label": "Other"}, smsbower.get_services("73"))
        self.assertEqual(["getServicesList"], smsbower.actions)

    def test_herosms_reuses_successful_phone_and_releases_bad_phone(self):
        cfg = SmsProviderConfig(
            provider="herosms",
            api_key="key",
            base_url="https://example.test/api",
            service="ot",
            country="73",
        )
        pool = HeroSmsReusePool()
        with patch.object(sms_providers, "SmsActivateClient", FakeSmsActivateClient):
            lease1 = pool.acquire(cfg)
            lease1.code_received = True
            pool.finish(cfg, lease1, keep=True)

            lease2 = pool.acquire(cfg)
            self.assertIs(lease1, lease2)
            self.assertEqual(1, FakeSmsActivateClient.request_another_calls)

            pool.finish(cfg, lease2, keep=False)
            self.assertEqual(["aid-1"], FakeSmsActivateClient.cancelled)


if __name__ == "__main__":
    unittest.main()
