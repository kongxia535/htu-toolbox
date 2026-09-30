import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from web import server


class LogEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=server.ROOT_DIR)
        self.log_path = Path(self.temp_dir.name) / "campus-auto-login.log"
        self.log_patch = patch.object(server, "LOG_PATH", self.log_path)
        self.log_patch.start()
        self.http_server = server.DashboardServer(
            server.ServerConfig("127.0.0.1", 0), "test-token"
        )
        self.thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http_server.shutdown()
        self.http_server.server_close()
        self.thread.join(timeout=2)
        self.log_patch.stop()
        self.temp_dir.cleanup()

    def get_json(self, path):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.http_server.server_port, timeout=3
        )
        try:
            connection.request("GET", path, headers={"X-HTU-Token": "test-token"})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_status_does_not_read_or_return_log_tail(self):
        with (
            patch.object(server, "task_status", return_value={"state": "Running"}),
            patch.object(server, "network_status", return_value={"online": True}),
            patch.object(server, "load_config", return_value={}),
            patch.object(server, "read_log_tail", side_effect=AssertionError("status read logs")),
        ):
            status, payload = self.get_json("/api/status")
        self.assertEqual(status, 200)
        self.assertNotIn("log", payload["data"])

    def test_log_endpoint_reads_new_lines_after_append(self):
        self.log_path.write_text("first\n", encoding="utf-8")
        status, payload = self.get_json("/api/logs?tail=100")
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["lines"], ["first"])

        with self.log_path.open("a", encoding="utf-8") as log:
            log.write("second\n")
        status, payload = self.get_json("/api/logs?tail=100")
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["lines"], ["first", "second"])
        self.assertIsInstance(payload["data"]["lastWriteTime"], float)


if __name__ == "__main__":
    unittest.main()
