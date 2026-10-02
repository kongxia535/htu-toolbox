import http.client
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch
from web import network, server
from web.runtime import Controller


class WatcherIntegrationTests(unittest.TestCase):
    def test_http_config_starts_worker_and_authenticates_against_local_portal(self):
        authenticated = threading.Event()

        class Portal(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/connecttest.txt":
                    self.send_response(200 if authenticated.is_set() else 302)
                    if not authenticated.is_set():
                        self.send_header(
                            "Location", "http://10.101.2.194:6060/portal.do?test=1"
                        )
                    self.end_headers()
                    if authenticated.is_set():
                        self.wfile.write(b"Microsoft Connect Test")
                elif path == "/PortalJsonAction.do":
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"{}")
                elif path == "/quickauth.do":
                    if (
                        "userid=example%40lt" not in self.path
                        or "passwd=test-only" not in self.path
                    ):
                        self.send_response(400)
                        self.end_headers()
                        return
                    authenticated.set()
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"code":"0"}')
                else:
                    self.send_response(404)
                    self.end_headers()

        portal = ThreadingHTTPServer(("127.0.0.1", 0), Portal)
        portal_thread = threading.Thread(target=portal.serve_forever, daemon=True)
        portal_thread.start()
        original_request = network.request

        def local_request(url, timeout=4):
            parsed = urlsplit(url)
            return original_request(
                f"http://127.0.0.1:{portal.server_port}{parsed.path}?{parsed.query}",
                timeout,
            )

        try:
            with tempfile.TemporaryDirectory() as directory, patch(
                "web.network.request", side_effect=local_request
            ):
                controller = Controller(Path(directory), system="Linux")
                httpd = server.DashboardServer(
                    server.ServerConfig("127.0.0.1", 0), "test-token", controller
                )
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                try:
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", httpd.server_port, timeout=4
                    )
                    payload = {
                        "account": "example",
                        "operator": "lt",
                        "portalUrl": "http://10.101.2.194:6060/portal.do?test=1",
                        "password": "test-only",
                        "autoStart": False,
                    }
                    connection.request(
                        "POST",
                        "/api/config",
                        json.dumps(payload),
                        {"X-HTU-Token": "test-token"},
                    )
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertTrue(json.loads(response.read())["ok"])
                    connection.close()
                    self.assertTrue(
                        authenticated.wait(4), "watcher never authenticated"
                    )
                    deadline = time.monotonic() + 3
                    while (
                        not controller.watcher.last_result
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.01)
                    self.assertTrue(controller.watcher.last_result["ok"])
                    self.assertTrue(controller.watcher.last_result["online"])
                    self.assertTrue(controller.watcher.running())
                    self.assertNotIn("test-only", controller.store.path.read_text())
                    controller.action("stop")
                    controller.watcher.thread.join(3)
                    self.assertFalse(controller.watcher.running())
                finally:
                    controller.close()
                    httpd.shutdown()
                    httpd.server_close()
                    thread.join()
        finally:
            portal.shutdown()
            portal.server_close()
            portal_thread.join()


if __name__ == "__main__":
    unittest.main()
