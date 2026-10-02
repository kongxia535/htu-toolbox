import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from web.config import ConfigStore, validate_update, validate_portal
from web.errors import DashboardError, BusyError
from web.runtime import Controller

PAYLOAD = {
    "account": "example123",
    "operator": "lt",
    "portalUrl": "http://10.101.2.194:6060/portal.do?test=1",
    "password": "test-only-password",
}


class ConfigurationTests(unittest.TestCase):
    def test_first_run_requires_password(self):
        with self.assertRaisesRegex(DashboardError, "首次配置必须输入"):
            validate_update({**PAYLOAD, "password": ""}, {})

    def test_rejects_bad_portals_and_credential_urls(self):
        for url in [
            "http://999.999.999.999:6060/nope",
            "http://8.8.8.8:6060/portal.do",
            "http://10.101.2.194:80/portal.do",
            "http://10.101.2.194:6060/nope",
            "http://u:p@10.101.2.194:6060/portal.do",
            "http://10.101.2.194:6060/portal.do#fragment",
        ]:
            with self.subTest(url=url), self.assertRaises(DashboardError):
                validate_portal(url)

    def test_rejects_wrong_types(self):
        for key, value in [
            ("password", None),
            ("password", True),
            ("intervalSeconds", 5.9),
            ("intervalSeconds", True),
            ("autoStart", "false"),
            ("restartCount", "2"),
        ]:
            with self.subTest(key=key, value=value), self.assertRaises(DashboardError):
                validate_update({**PAYLOAD, key: value}, {})

    def test_password_is_encrypted_and_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory))
            config = store.save(PAYLOAD)
            self.assertNotIn(PAYLOAD["password"], store.path.read_text())
            self.assertEqual(store.password(config), PAYLOAD["password"])
            updated = store.save({**PAYLOAD, "password": "", "intervalSeconds": 15})
            self.assertEqual(updated["password"], config["password"])
            self.assertEqual(store.password(updated), PAYLOAD["password"])
            self.assertNotIn("password", store.summary())
            if os.name != "nt":
                self.assertEqual(store.key_path.stat().st_mode & 0o777, 0o600)

    def test_failed_atomic_save_preserves_previous_config(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory))
            store.save(PAYLOAD)
            before = store.path.read_bytes()
            with patch(
                "web.config.os.replace", side_effect=OSError("disk unavailable")
            ):
                with self.assertRaises(OSError):
                    store.save({**PAYLOAD, "account": "new-account", "password": ""})
            self.assertEqual(store.path.read_bytes(), before)
            self.assertEqual(len(list(Path(directory).glob(".htu-*"))), 0)

    def test_windows_backend_preserves_existing_password(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(Path(directory), system="Windows")
            with patch.object(
                controller.store, "load", return_value={"password": "encrypted"}
            ), patch(
                "web.windows.run_powershell_script", return_value="updated"
            ) as run:
                self.assertEqual(
                    controller.update({**PAYLOAD, "password": ""}), "updated"
                )
                self.assertIn("-PreservePassword", run.call_args.args[1])
                self.assertNotIn("HTU_AUTO_LOGIN_PASSWORD", run.call_args.kwargs["env"])

    def test_windows_first_run_uses_password_env(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(Path(directory), system="Windows")
            with patch(
                "web.windows.run_powershell_script", return_value="installed"
            ) as run:
                self.assertEqual(controller.update(PAYLOAD), "installed")
                self.assertEqual(
                    run.call_args.kwargs["env"]["HTU_AUTO_LOGIN_PASSWORD"],
                    PAYLOAD["password"],
                )

    def test_operations_are_serialized(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(Path(directory))
            controller.operations.acquire()
            try:
                with self.assertRaises(BusyError):
                    controller.mutate("action", {"action": "stop"})
            finally:
                controller.operations.release()


if __name__ == "__main__":
    unittest.main()
