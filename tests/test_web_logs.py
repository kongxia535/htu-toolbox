import http.client
import json
import os
import socket
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from web import server
from web.runtime import Controller


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.log = self.directory / "campus-auto-login.log"
        self.log_patch = patch.object(server, "LOG_PATH", self.log)
        self.log_patch.start()
        self.controller = Controller(self.directory, system="Linux")
        self.httpd = server.DashboardServer(
            server.ServerConfig("127.0.0.1", 0), "test-token", self.controller
        )
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.controller.close()
        self.log_patch.stop()
        self.temporary.cleanup()

    def request(self, path, method="GET", body=None, headers=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.httpd.server_port, timeout=3
        )
        try:
            connection.request(
                method,
                path,
                body=body,
                headers={"X-HTU-Token": "test-token", **(headers or {})},
            )
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_status_does_not_read_logs_or_expose_password(self):
        with patch("web.server.network_status", return_value={"online": True}), patch(
            "web.server.read_log_tail", side_effect=AssertionError("status read logs")
        ):
            status, body = self.request("/api/status")
        self.assertEqual(status, 200)
        data = json.loads(body)["data"]
        self.assertNotIn("log", data)
        self.assertNotIn("password", data["config"])
        self.assertEqual(data["platform"]["name"], "Linux")

    def test_log_endpoint_tracks_append(self):
        self.log.write_text("first\n")
        status, body = self.request("/api/logs?tail=100")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["data"]["lines"], ["first"])
        with self.log.open("a") as handle:
            handle.write("second\n")
        status, body = self.request("/api/logs?tail=1")
        self.assertEqual(json.loads(body)["data"]["lines"], ["second"])

    def test_malformed_json_types_are_client_errors(self):
        for body in ["[]", "null", '"string"', "{bad", '{"action":null}']:
            with self.subTest(body=body):
                self.assertEqual(self.request("/api/action", "POST", body)[0], 400)

    def test_mutation_failure_does_not_report_success(self):
        with patch.object(
            self.controller, "action", side_effect=server.DashboardError("认证失败")
        ):
            status, body = self.request(
                "/api/action", "POST", '{"action":"force-login"}'
            )
        self.assertEqual(status, 400)
        self.assertFalse(json.loads(body)["ok"])

    def test_busy_operation_is_conflict(self):
        self.controller.operations.acquire()
        try:
            self.assertEqual(
                self.request("/api/action", "POST", '{"action":"stop"}')[0], 409
            )
        finally:
            self.controller.operations.release()

    def test_cross_origin_and_wrong_tokens_rejected(self):
        self.assertEqual(
            self.request("/api/logs", headers={"Origin": "http://localhost:9999"})[0],
            400,
        )
        self.assertEqual(
            self.request("/api/logs", headers={"X-HTU-Token": "wrong"})[0], 400
        )

    def test_home_token_and_assets(self):
        status, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"test-token", body)
        self.assertNotIn(b"{{HTU_TOKEN}}", body)
        for path in ["/static/app.js", "/static/styles.css"]:
            self.assertEqual(self.request(path)[0], 200)
        self.assertEqual(self.request("/static/../../README.md")[0], 404)

    def test_negative_content_length_is_rejected(self):
        self.assertEqual(
            self.request("/api/action", "POST", headers={"Content-Length": "-1"})[0],
            400,
        )

    def test_cancelled_status_request_does_not_raise_or_stop_server(self):
        probe_started = threading.Event()
        release_probe = threading.Event()
        completed = threading.Event()
        original_finish = self.httpd.finish_request

        def probe():
            probe_started.set()
            release_probe.wait(3)
            return {"online": False}

        def finish(*args):
            try:
                original_finish(*args)
            finally:
                completed.set()

        with patch("web.server.network_status", side_effect=probe), patch.object(
            self.httpd, "finish_request", side_effect=finish
        ), patch.object(self.httpd, "handle_error") as handle_error:
            client = socket.create_connection(("127.0.0.1", self.httpd.server_port))
            try:
                client.sendall(
                    f"GET /api/status HTTP/1.1\r\nHost: 127.0.0.1:{self.httpd.server_port}\r\nX-HTU-Token: test-token\r\n\r\n".encode()
                )
                self.assertTrue(probe_started.wait(3))
                # Force the connection reset a browser cancellation may cause.
                linger_format = "hh" if os.name == "nt" else "ii"
                client.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_LINGER,
                    struct.pack(linger_format, 1, 0),
                )
            finally:
                client.close()
                release_probe.set()
            self.assertTrue(completed.wait(3))
            handle_error.assert_not_called()
        self.assertEqual(self.request("/api/logs")[0], 200)


if __name__ == "__main__":
    unittest.main()
