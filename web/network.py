from __future__ import annotations

import html
import http.client
import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit

from .config import validate_portal
from .errors import DashboardError

MAX_BODY = 256 * 1024
PROBES = (
    ("http://www.msftconnecttest.com/connecttest.txt", 200, b"Microsoft Connect Test"),
    ("http://connectivitycheck.gstatic.com/generate_204", 204, b""),
)


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    location: str = ""


def request(url: str, timeout: float = 4) -> Response:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise DashboardError("请求地址无效。")
    cls = (
        http.client.HTTPSConnection
        if parsed.scheme == "https"
        else http.client.HTTPConnection
    )
    connection = cls(parsed.hostname, parsed.port, timeout=timeout)
    try:
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        connection.request(
            "GET",
            path,
            headers={"User-Agent": "HTU-Toolbox/2.0", "Connection": "close"},
        )
        response = connection.getresponse()
        data = response.read(MAX_BODY + 1)
        if len(data) > MAX_BODY:
            raise DashboardError("门户响应超过大小限制。")
        return Response(response.status, data, response.getheader("Location", ""))
    except (OSError, http.client.HTTPException) as error:
        # Never include URL/query strings: the authentication URL carries a password.
        raise DashboardError("网络请求失败或超时，请检查网络与门户地址。") from error
    finally:
        connection.close()


def network_status() -> dict:
    errors = []
    captive = False
    for url, code, body in PROBES:
        try:
            response = request(url, timeout=3)
            if response.status == code and response.body.strip() == body:
                return {
                    "online": True,
                    "state": "online",
                    "probe": urlsplit(url).hostname,
                    "errors": [],
                }
            captive |= bool(response.location) or response.status == 200
            errors.append(f"探针返回 HTTP {response.status}，内容与预期不符")
        except DashboardError as error:
            errors.append(str(error))
    return {
        "online": False,
        "state": "captive" if captive else "offline",
        "probe": "none",
        "errors": errors,
    }


def detect_portal_url() -> dict:
    for url, _, _ in PROBES:
        try:
            response = request(url)
            candidates = [response.location] + re.findall(
                r"https?://[^\s\"'<>]+/portal\.do\?[^\s\"'<>]+",
                response.body.decode("utf-8", errors="replace"),
            )
            for candidate in candidates:
                try:
                    return {"portalUrl": validate_portal(html.unescape(candidate))}
                except DashboardError:
                    pass
        except DashboardError:
            pass
    raise DashboardError("未找到校园门户，请连接校园网后重试，或粘贴完整门户地址。")


def login(config: dict, password: str) -> dict:
    portal = validate_portal(config["portalUrl"])
    try:
        portal = detect_portal_url()["portalUrl"]
    except DashboardError:
        pass
    parsed = urlsplit(portal)
    base = f"{parsed.scheme}://{parsed.netloc}"
    parameters = dict(parse_qsl(parsed.query, keep_blank_values=True))
    try:
        response = request(
            base
            + "/PortalJsonAction.do?"
            + urlencode({**parameters, "viewStatus": "1"})
        )
        metadata = json.loads(response.body) if response.status == 200 else {}
        if not isinstance(metadata, dict):
            metadata = {}
        for source, mapping in (
            ("serverForm", {"serverip": "wlanacIp", "portalVer": "version"}),
            (
                "portalconfig",
                {"id": "portalpageid", "timestamp": "timestamp", "uuid": "uuid"},
            ),
        ):
            values = metadata.get(source, {})
            if isinstance(values, dict):
                for key, target in mapping.items():
                    if values.get(key) is not None:
                        parameters[target] = str(values[key])
    except (DashboardError, ValueError):
        pass  # Older portals may not implement metadata; preserve captured query.
    parameters.update(
        userid=f"{config['account']}@{config['operator']}", passwd=password
    )
    for key, value in {
        "wlanuseripv6": "",
        "ssid": "",
        "portaltype": "0",
        "hostname": "HTU-Toolbox",
        "validateCode": "",
        "bindCtrlId": "",
    }.items():
        parameters.setdefault(key, value)
    response = request(base + "/quickauth.do?" + urlencode(parameters), timeout=8)
    if response.status != 200:
        raise DashboardError(f"认证请求返回 HTTP {response.status}。")
    try:
        result = json.loads(response.body)
    except ValueError as error:
        raise DashboardError("门户没有返回有效的认证结果。") from error
    if not isinstance(result, dict) or str(result.get("code")) != "0":
        # Portal messages may echo the request or password; display a stable code only.
        raise DashboardError("校园网认证失败，请检查账号、密码和运营商。")
    status = network_status()
    return {
        "authenticated": True,
        "online": status["online"],
        "message": (
            "登录成功，网络已恢复。"
            if status["online"]
            else "认证已通过，联网探针尚未通过。"
        ),
    }
