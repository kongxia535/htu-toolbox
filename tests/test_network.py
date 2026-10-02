import unittest
from unittest.mock import patch
from web import network
from web.errors import DashboardError


class NetworkTests(unittest.TestCase):
    def test_captive_page_not_online(self):
        with patch(
            "web.network.request",
            return_value=network.Response(200, b"<html>login</html>"),
        ):
            result = network.network_status()
        self.assertFalse(result["online"])
        self.assertEqual(result["state"], "captive")

    def test_expected_probe_response_is_online(self):
        with patch(
            "web.network.request",
            return_value=network.Response(200, b"Microsoft Connect Test"),
        ):
            self.assertTrue(network.network_status()["online"])

    def test_rejects_untrusted_detected_portal(self):
        with patch(
            "web.network.request",
            return_value=network.Response(
                302, b"", "http://8.8.8.8:6060/portal.do?test=1"
            ),
        ):
            with self.assertRaises(DashboardError):
                network.detect_portal_url()

    def test_login_uses_metadata_and_reports_online_separately(self):
        config = {
            "portalUrl": "http://10.101.2.194:6060/portal.do?wlanuserip=10.0.0.1",
            "account": "example",
            "operator": "lt",
        }
        with patch(
            "web.network.detect_portal_url", side_effect=DashboardError("no redirect")
        ), patch("web.network.network_status", return_value={"online": False}), patch(
            "web.network.request",
            side_effect=[
                network.Response(200, b'{"serverForm":{"serverip":"10.0.0.2"}}'),
                network.Response(200, b'{"code":"0"}'),
            ],
        ) as request:
            result = network.login(config, "test-secret")
        self.assertTrue(result["authenticated"])
        self.assertFalse(result["online"])
        url = request.call_args_list[1].args[0]
        self.assertIn("wlanacIp=10.0.0.2", url)
        self.assertIn("userid=example%40lt", url)

    def test_failed_login_does_not_echo_portal_secrets(self):
        config = {
            "portalUrl": "http://10.101.2.194:6060/portal.do?test=1",
            "account": "example",
            "operator": "lt",
        }
        with patch(
            "web.network.detect_portal_url", side_effect=DashboardError()
        ), patch(
            "web.network.request",
            side_effect=[
                network.Response(404, b""),
                network.Response(200, b'{"code":"1","message":"passwd=test-secret"}'),
            ],
        ):
            with self.assertRaises(DashboardError) as error:
                network.login(config, "test-secret")
        self.assertNotIn("test-secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
