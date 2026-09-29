import unittest
from unittest.mock import patch

from web import server


class FirstRunTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "account": "example123",
            "operator": "lt",
            "portalUrl": "http://10.101.2.194:6060/portal.do?test=1",
            "password": "test-only-password",
        }

    @patch.object(server, "load_config", return_value={})
    def test_first_run_requires_password(self, _load_config):
        payload = {**self.payload, "password": ""}
        with self.assertRaisesRegex(server.DashboardError, "首次配置必须输入"):
            server.validate_config_update(payload)

    @patch.object(server, "load_config", return_value={})
    @patch.object(server, "run_powershell_script", return_value="installed")
    def test_first_run_installs_from_web_form(self, run_script, _load_config):
        self.assertEqual(server.update_config(self.payload), "installed")
        args, kwargs = run_script.call_args
        self.assertEqual(args[0], server.INSTALL_SCRIPT)
        self.assertNotIn("-PreservePassword", args[1])
        self.assertEqual(kwargs["env"]["HTU_AUTO_LOGIN_PASSWORD"], "test-only-password")

    @patch.object(server, "load_config", return_value={"password": "encrypted"})
    @patch.object(server, "run_powershell_script", return_value="updated")
    def test_existing_password_is_preserved(self, run_script, _load_config):
        payload = {**self.payload, "password": ""}
        self.assertEqual(server.update_config(payload), "updated")
        args, kwargs = run_script.call_args
        self.assertIn("-PreservePassword", args[1])
        self.assertNotIn("HTU_AUTO_LOGIN_PASSWORD", kwargs["env"])

    @patch.object(server, "run_powershell")
    def test_missing_task_is_a_setup_state(self, run_powershell):
        run_powershell.return_value = (
            '{"ok":true,"state":"NotInstalled","watcherCount":0,"processIds":[]}'
        )
        self.assertEqual(server.task_status()["state"], "NotInstalled")
        self.assertIn("NotInstalled", run_powershell.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
