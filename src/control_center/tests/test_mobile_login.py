from __future__ import annotations

import http.client
import threading

import pytest

import src.control_center.server as server_module
from src.control_center.server import ControlCenterServer


TOKEN = "test-bootstrap-token-that-is-long-enough"


@pytest.fixture
def control_server():
    server = ControlCenterServer(
        ("127.0.0.1", 0), object(), TOKEN,
        frozenset({"jarvis.example-tailnet.ts.net"}),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def request(server, path="/", headers=None, method="GET"):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
    connection.request(method, path, body=b"{}" if method == "POST" else None, headers=headers or {})
    response = connection.getresponse()
    body = response.read()
    result = response.status, dict(response.getheaders()), body
    connection.close()
    return result


def test_local_bootstrap_redirects_to_clean_local_origin(control_server):
    host = f"127.0.0.1:{control_server.server_port}"
    status, headers, _ = request(control_server, f"/?token={TOKEN}", {"Host": host})

    assert status == 303
    assert headers["Location"] == f"http://{host}/"
    assert TOKEN not in headers["Location"]
    assert "HttpOnly" in headers["Set-Cookie"]
    assert "SameSite=Strict" in headers["Set-Cookie"]
    assert "Max-Age=2592000" in headers["Set-Cookie"]
    assert "Secure" not in headers["Set-Cookie"]


@pytest.mark.parametrize("use_forwarded_host", [False, True])
def test_tailscale_bootstrap_preserves_https_host_and_cleans_token(control_server, use_forwarded_host):
    public_host = "jarvis.example-tailnet.ts.net"
    headers = {
        "Host": f"127.0.0.1:{control_server.server_port}" if use_forwarded_host else public_host,
        "X-Forwarded-Proto": "https",
        "Tailscale-User-Login": "owner@example.com",
    }
    if use_forwarded_host:
        headers["X-Forwarded-Host"] = public_host

    status, response_headers, _ = request(control_server, f"/?token={TOKEN}", headers)

    assert status == 303
    assert response_headers["Location"] == f"https://{public_host}/"
    assert TOKEN not in response_headers["Location"]
    assert "Secure" in response_headers["Set-Cookie"]
    assert TOKEN not in str(response_headers.get("Location"))


@pytest.mark.parametrize("headers", [
    {"Host": "evil.example"},
    {"Host": "evil.example", "X-Forwarded-Proto": "https"},
    {"Host": "evil.ts.net", "X-Forwarded-Proto": "https"},
    {"Host": "127.0.0.1:8765", "X-Forwarded-Proto": "https", "X-Forwarded-Host": "evil.example", "Tailscale-User-Login": "owner@example.com"},
    {"Host": "127.0.0.1:8765", "X-Forwarded-Proto": "https", "X-Forwarded-Host": "good.ts.net,evil.example", "Tailscale-User-Login": "owner@example.com"},
])
def test_invalid_or_untrusted_host_is_rejected(control_server, headers):
    status, _, _ = request(control_server, f"/?token={TOKEN}", headers)
    assert status == 400


def test_unconfigured_tailscale_hostname_is_rejected(control_server):
    status, _, _ = request(control_server, f"/?token={TOKEN}", {
        "Host": "other.example-tailnet.ts.net",
        "X-Forwarded-Proto": "https",
        "Tailscale-User-Login": "owner@example.com",
    })
    assert status == 400


def test_access_without_authentication_is_rejected(control_server):
    host = f"127.0.0.1:{control_server.server_port}"
    status, _, body = request(control_server, "/", {"Host": host})
    assert status == 401
    assert TOKEN.encode() not in body


def test_authenticated_tailscale_page_keeps_csp_and_same_origin(control_server):
    public_host = "jarvis.example-tailnet.ts.net"
    proxy_headers = {
        "Host": public_host,
        "X-Forwarded-Proto": "https",
        "Tailscale-User-Login": "owner@example.com",
        "Cookie": f"jarvis_session={TOKEN}",
    }

    status, headers, body = request(control_server, "/", proxy_headers)
    assert status == 200
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert TOKEN.encode() not in body

    status, _, _ = request(
        control_server,
        "/api/not-found",
        {**proxy_headers, "Origin": f"https://{public_host}", "Content-Type": "application/json"},
        "POST",
    )
    assert status == 404

    status, _, _ = request(
        control_server,
        "/api/not-found",
        {**proxy_headers, "Origin": "https://evil.example", "Content-Type": "application/json"},
        "POST",
    )
    assert status == 403


def test_serve_detection_requires_our_cert_https_loopback_proxy_and_no_funnel(monkeypatch):
    serve = {
        "TCP": {"443": {"HTTPS": True}},
        "Web": {"jarvis.example-tailnet.ts.net:443": {
            "Handlers": {"/": {"Proxy": "http://127.0.0.1:8765"}}
        }},
    }
    status = {
        "BackendState": "Running",
        "Self": {"DNSName": "jarvis.example-tailnet.ts.net."},
        "CertDomains": ["jarvis.example-tailnet.ts.net"],
    }
    monkeypatch.setattr(
        server_module, "_tailscale_json",
        lambda *args: serve if args[0] == "serve" else status,
    )
    assert server_module.detect_tailscale_serve_host(8765) == "jarvis.example-tailnet.ts.net"

    serve["AllowFunnel"] = {"jarvis.example-tailnet.ts.net:443": True}
    assert server_module.detect_tailscale_serve_host(8765) is None
    serve.pop("AllowFunnel")
    serve["Web"]["jarvis.example-tailnet.ts.net:443"]["Handlers"]["/"]["Proxy"] = "http://127.0.0.1:9999"
    assert server_module.detect_tailscale_serve_host(8765) is None
