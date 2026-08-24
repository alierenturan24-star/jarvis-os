from __future__ import annotations

import argparse
import ipaddress
import json
import secrets
import os
import re
import subprocess
import threading
import time
import errno
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from src.control_center.service import CapabilityCandidateNotFound, ControlCenterService


WEB_ROOT = Path(__file__).with_name("web")
TOKEN_PATH = Path("workspace/control_center/session.token")
INSTANCE_DIR = Path("workspace/control_center")
TAILSCALE_IDENTITY_HEADERS = ("Tailscale-User-Login", "Tailscale-User-Name")
TAILSCALE_HOST_RE = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+ts\.net\Z"
)


def _split_authority(value: str) -> tuple[str, int | None] | None:
    """Parse a single HTTP authority without accepting URL/header tricks."""
    if not value or value != value.strip() or "," in value or any(char in value for char in "/\\?#@"):
        return None
    try:
        parsed = urlparse(f"//{value}")
        host, port = parsed.hostname, parsed.port
    except ValueError:
        return None
    if not host or parsed.username or parsed.password:
        return None
    return host.casefold().rstrip("."), port


def trusted_request_origin(headers, trusted_tailscale_hosts: frozenset[str] | None = None) -> str | None:
    """Return the browser-facing origin only for local or Tailscale Serve requests."""
    direct = _split_authority(headers.get("Host", ""))
    forwarded_proto = headers.get("X-Forwarded-Proto", "")
    forwarded_host = headers.get("X-Forwarded-Host", "")

    if not forwarded_proto and not forwarded_host and direct:
        host, port = direct
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = host == "localhost"
        if is_loopback:
            authority = f"[{host}]" if ":" in host else host
            if port is not None:
                authority += f":{port}"
            return f"http://{authority}"
        return None

    # Serve strips caller-supplied Tailscale identity headers before adding its
    # own. Because this server is loopback-only, their presence is the proxy
    # trust signal; forwarded headers alone are never sufficient.
    if forwarded_proto.casefold() != "https" or "," in forwarded_proto:
        return None
    if not any(headers.get(name, "").strip() for name in TAILSCALE_IDENTITY_HEADERS):
        return None
    public = _split_authority(forwarded_host) if forwarded_host else direct
    if not public:
        return None
    host, port = public
    if not TAILSCALE_HOST_RE.fullmatch(host) or (port is not None and port != 443):
        return None
    if trusted_tailscale_hosts is not None and host not in trusted_tailscale_hosts:
        return None
    authority = host if port is None else f"{host}:{port}"
    return f"https://{authority}"


def _tailscale_json(*arguments: str) -> dict:
    try:
        completed = subprocess.run(
            ["tailscale", *arguments], capture_output=True, text=True,
            encoding="utf-8", timeout=5, check=True,
        )
        value = json.loads(completed.stdout)
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, subprocess.SubprocessError, UnicodeError, json.JSONDecodeError):
        return {}


def detect_tailscale_serve_host(port: int) -> str | None:
    """Return our verified private Serve hostname only when it proxies this port."""
    serve = _tailscale_json("serve", "status", "--json")
    status = _tailscale_json("status", "--json")
    self_node = status.get("Self") if isinstance(status.get("Self"), dict) else {}
    dns_name = str(self_node.get("DNSName", "")).casefold().rstrip(".")
    cert_domains = {
        str(item).casefold().rstrip(".") for item in status.get("CertDomains", [])
        if isinstance(item, str)
    }
    if (status.get("BackendState") != "Running" or not TAILSCALE_HOST_RE.fullmatch(dns_name)
            or dns_name not in cert_domains):
        return None

    web = serve.get("Web")
    tcp = serve.get("TCP")
    if not isinstance(web, dict) or not isinstance(tcp, dict):
        return None
    tcp_443 = tcp.get("443")
    if not isinstance(tcp_443, dict) or tcp_443.get("HTTPS") is not True:
        return None
    site = web.get(f"{dns_name}:443")
    handlers = site.get("Handlers") if isinstance(site, dict) else None
    root = handlers.get("/") if isinstance(handlers, dict) else None
    proxy = root.get("Proxy") if isinstance(root, dict) else None
    allowed_proxies = {f"http://127.0.0.1:{port}", f"http://localhost:{port}", f"http://[::1]:{port}"}
    if proxy not in allowed_proxies:
        return None
    funnel = serve.get("AllowFunnel", {})
    if isinstance(funnel, dict) and funnel.get(f"{dns_name}:443") is True:
        return None
    return dns_name


def print_terminal_qr(value: str) -> bool:
    """Print a local terminal QR when the optional small QR dependency exists."""
    try:
        import qrcode
    except ImportError:
        return False
    qr = qrcode.QRCode(border=2)
    qr.add_data(value)
    qr.make(fit=True)
    qr.print_ascii(invert=True)
    return True


def load_or_create_token(path: Path = TOKEN_PATH) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
    token = secrets.token_urlsafe(32)
    path.write_text(token, encoding="utf-8")
    try: os.chmod(path, 0o600)
    except OSError: pass
    return token


class ControlCenterServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False
    def __init__(self, address: tuple[str, int], service: ControlCenterService, token: str,
                 trusted_tailscale_hosts: frozenset[str] | None = None) -> None:
        super().__init__(address, ControlCenterHandler)
        self.service, self.token = service, token
        self.trusted_tailscale_hosts = trusted_tailscale_hosts


class ControlCenterInstanceLock:
    """Process lock scoped to one loopback host/port."""

    def __init__(self, host: str, port: int, folder: Path = INSTANCE_DIR) -> None:
        self.path = folder / f"{host.replace(':', '_')}_{port}.pid"
        self.acquired = False

    @staticmethod
    def _alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError as error:
            return error.errno == errno.EPERM

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                try:
                    pid = int(json.loads(self.path.read_text(encoding="utf-8")).get("pid", 0))
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    pid = 0
                if self._alive(pid):
                    raise RuntimeError(f"Control Center already running (PID {pid}).")
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump({"pid": os.getpid(), "created_at": time.time()}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            self.acquired = True
            return
        raise RuntimeError("Control Center instance lock could not be acquired.")

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            owner = json.loads(self.path.read_text(encoding="utf-8"))
            if int(owner.get("pid", 0)) == os.getpid():
                self.path.unlink(missing_ok=True)
        finally:
            self.acquired = False


class ControlCenterHandler(BaseHTTPRequestHandler):
    server: ControlCenterServer

    def log_message(self, fmt: str, *args) -> None:
        return

    def _authenticated(self) -> bool:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        supplied = cookie.get("jarvis_session")
        return bool(supplied and secrets.compare_digest(supplied.value, self.server.token))

    def _json(self, value, status=200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("X-Frame-Options", "DENY")
        self.end_headers(); self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 65536: raise ValueError("Request too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        trusted_origin = trusted_request_origin(self.headers, self.server.trusted_tailscale_hosts)
        return bool(trusted_origin and (not origin or origin == trusted_origin))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        origin = trusted_request_origin(self.headers, self.server.trusted_tailscale_hosts)
        if origin is None:
            return self._json({"error": "Untrusted request host"}, 400)
        if parsed.path == "/":
            token = parse_qs(parsed.query).get("token", [""])[0]
            if not self._authenticated() and not secrets.compare_digest(token, self.server.token):
                return self._json({"error": "Authentication required. Use the startup URL."}, 401)
            if token:
                secure = "; Secure" if origin.startswith("https://") else ""
                self.send_response(303)
                self.send_header("Location", f"{origin}/")
                self.send_header("Set-Cookie", f"jarvis_session={self.server.token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000{secure}")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            body = (WEB_ROOT / "index.html").read_bytes()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; media-src 'self'; connect-src 'self'; img-src 'self' data:")
            self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/api/oauth/google/callback":
            # Google's redirect never carries our jarvis_session cookie, so this exact path is
            # reachable without it. It stays safe because completion is gated entirely on a
            # single-use, time-limited, cryptographically random state token validated inside
            # complete_account_connection/GoogleYouTubeProvider.complete — any missing, invalid,
            # expired, or replayed state (or missing code) fails closed there. No other GET route
            # may be added above the _authenticated() check below.
            values = parse_qs(parsed.query)
            state = values.get("state", [""])[0]
            code = values.get("code", [""])[0]
            try:
                self.server.service.complete_account_connection(state, code)
            except Exception:
                body = b"Authorization failed or expired. Return to JARVIS Control Center and try again."
                self.send_response(400); self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store"); self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            body = b"Authorization completed. Return to JARVIS Control Center."
            self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store"); self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if not self._authenticated(): return self._json({"error": "Unauthorized"}, 401)
        if parsed.path == "/app.css" or parsed.path == "/app.js":
            file = WEB_ROOT / parsed.path[1:]; body = file.read_bytes(); mime = "text/css" if file.suffix == ".css" else "text/javascript"
            self.send_response(200); self.send_header("Content-Type", f"{mime}; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/api/status": return self._json(self.server.service.snapshot())
        if parsed.path == "/api/health": return self._json(self.server.service.health())
        if parsed.path == "/api/dashboard": return self._json(self.server.service.read_model.dashboard())
        if parsed.path == "/api/tasks": return self._json(self.server.service.read_model.tasks())
        if parsed.path == "/api/approvals": return self._json(self.server.service.read_model.approvals())
        if parsed.path == "/api/providers": return self._json(self.server.service.read_model.providers())
        if parsed.path == "/api/costs": return self._json(self.server.service.read_model.costs())
        if parsed.path == "/api/youtube": return self._json(self.server.service.read_model.youtube())
        if parsed.path == "/api/finance": return self._json(self.server.service.read_model.finance())
        if parsed.path == "/api/research": return self._json(self.server.service.read_model.research())
        if parsed.path == "/api/research/topics": return self._json(self.server.service.research_topics())
        if parsed.path == "/api/research/cycles": return self._json(self.server.service.research_state()["cycles"])
        if parsed.path == "/api/research/findings": return self._json(self.server.service.research_state()["findings"])
        if parsed.path == "/api/research/knowledge-changes": return self._json([x for x in self.server.service.research_state()["findings"] if x.get("decision") in {"ACCEPT_NEW", "UPDATE_EXISTING", "CONFLICT"}])
        if parsed.path == "/api/capabilities/tools": return self._json(self.server.service.research_state()["tools"])
        if parsed.path == "/api/capabilities/active": return self._json([x for x in self.server.service.research_state()["capabilities"] if x.get("status") == "ACTIVE_CAPABILITY"])
        if parsed.path == "/api/capabilities/proposals": return self._json(self.server.service.research_state()["proposals"])
        if parsed.path == "/api/capabilities/evaluations": return self._json(self.server.service.research_state()["evaluations"])
        if parsed.path == "/api/capabilities/integration-plans": return self._json(self.server.service.integration_plans())
        if parsed.path == "/api/logs": return self._json(self.server.service.read_model.logs())
        if parsed.path == "/api/accounts": return self._json(self.server.service.accounts.redacted_accounts())
        if parsed.path == "/api/workers": return self._json(self.server.service.read_model.workers())
        if parsed.path.startswith("/api/workers/"):
            return self._json(self.server.service.workforce.worker(parsed.path.rsplit("/", 1)[-1]))
        if parsed.path == "/api/artifacts": return self._json(self.server.service.artifacts())
        if parsed.path == "/api/finance/market":
            asset = parse_qs(parsed.query).get("asset", ["BTC"])[0]
            return self._json(self.server.service.finance.market.intelligence(asset))
        if parsed.path.startswith("/artifact/"):
            relative = unquote(parsed.path[len("/artifact/"):]); root = Path("workspace").resolve(); file = (root / relative).resolve()
            if root not in file.parents or not file.is_file(): return self._json({"error": "Not found"}, 404)
            body = file.read_bytes(); self.send_response(200); self.send_header("Content-Type", __import__("mimetypes").guess_type(file.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body))); self.send_header("Content-Disposition", f'inline; filename="{file.name}"'); self.end_headers(); self.wfile.write(body); return
        self._json({"error": "Not found"}, 404)

    def do_POST(self) -> None:
        if trusted_request_origin(self.headers, self.server.trusted_tailscale_hosts) is None:
            return self._json({"error": "Untrusted request host"}, 400)
        if not self._authenticated(): return self._json({"error": "Unauthorized"}, 401)
        if not self._same_origin(): return self._json({"error": "Cross-origin request rejected"}, 403)
        try:
            data, path = self._body(), urlparse(self.path).path
            if path == "/api/command":
                raw_hints = data.get("execution_hints")
                hints = raw_hints if isinstance(raw_hints, dict) else None
                return self._json(
                    self.server.service.submit_command(data.get("goal", ""), data.get("source", "text"), execution_hints=hints),
                    202,
                )
            if path == "/api/research/topics": return self._json(self.server.service.create_research_topic(data), 201)
            if path.startswith("/api/capabilities/"):
                parts = path.strip("/").split("/")
                if len(parts) == 4 and parts[3] == "evaluate":
                    return self._json(self.server.service.evaluate_capability(unquote(parts[2])))
                if len(parts) == 5 and parts[3] == "integration" and parts[4] == "plan":
                    return self._json(self.server.service.plan_capability_integration(unquote(parts[2])), 201)
                if len(parts) == 5 and parts[3] == "activation" and parts[4] == "propose":
                    return self._json(self.server.service.propose_capability_activation(unquote(parts[2])), 201)
                if len(parts) == 5 and parts[2] == "proposals" and parts[4] == "execute":
                    return self._json(self.server.service.execute_capability_proposal(unquote(parts[3])))
                if len(parts) == 5 and parts[2] == "integration-proposals" and parts[4] == "execute":
                    return self._json(self.server.service.execute_integration_proposal(unquote(parts[3])))
                if len(parts) == 5 and parts[2] == "activation-proposals" and parts[4] == "execute":
                    return self._json(self.server.service.execute_activation_proposal(unquote(parts[3])))
            if path.startswith("/api/research/topics/"):
                parts = path.strip("/").split("/"); topic_id, action = parts[3], parts[4]
                if action == "enable": return self._json(self.server.service.autonomous_research.set_enabled(topic_id, True))
                if action == "disable": return self._json(self.server.service.autonomous_research.set_enabled(topic_id, False))
                if action == "run": return self._json(self.server.service.autonomous_research.run_topic(topic_id), 202)
            if path == "/api/control/start": self.server.service.start(); return self._json({"ok": True})
            if path == "/api/control/pause": self.server.service.pause(); return self._json({"ok": True})
            if path == "/api/control/stop": self.server.service.stop(False); return self._json({"ok": True})
            if path == "/api/control/emergency-stop": self.server.service.stop(True); return self._json({"ok": True})
            if path == "/api/workers/stop-all": return self._json(self.server.service.workforce.stop_all())
            if path.startswith("/api/workers/"):
                parts = path.strip("/").split("/")
                if len(parts) == 4: return self._json(self.server.service.worker_control(parts[2], parts[3], data), 202)
            if path.startswith("/api/accounts/"):
                parts = path.strip("/").split("/")
                if len(parts) == 4 and parts[3] == "connect":
                    origin = trusted_request_origin(self.headers, self.server.trusted_tailscale_hosts)
                    return self._json(self.server.service.begin_account_connection(
                        parts[2], origin + "/api/oauth/google/callback"), 201)
                if len(parts) == 4 and parts[3] in {"verify", "disconnect"}:
                    return self._json(self.server.service.account_action(parts[2], parts[3]))
            if path.startswith("/api/publications/preflight/"):
                return self._json(self.server.service.publisher_preflight(path.rsplit("/", 1)[-1]))
            if path.startswith("/api/approvals/"):
                parts = path.strip("/").split("/"); action = parts[3]
                decision = True if action == "approve" else None if action == "request-changes" else False
                return self._json(self.server.service.decide_approval(parts[2], decision, data.get("reason", "")))
            if path == "/api/youtube/queue": return self._json(self.server.service.enqueue_youtube(data.get("goal", "")), 201)
            if path == "/api/youtube/run-next": return self._json(self.server.service.run_next_youtube(), 202)
            if path == "/api/finance/backtest": return self._json(self.server.service.finance.backtest(data.get("asset", "BTC")), 201)
            if path == "/api/finance/paper": return self._json(self.server.service.finance.paper_signal(data.get("asset", "BTC")), 201)
            if path == "/api/finance/mark": return self._json(self.server.service.finance.mark_to_market(data.get("prices")), 200)
            if path == "/api/finance/close": return self._json(self.server.service.finance.close_position(data.get("position_id", ""), data.get("reason", "MANUAL"), data.get("price")), 200)
            if path == "/api/finance/qualification": return self._json(self.server.service.finance.qualification(), 201)
            if path == "/api/finance/live-request": return self._json(self.server.service.finance.request_live_trade(data), 201)
            if path == "/api/notifications/read": self.server.service.mark_notifications_read(); return self._json({"ok": True})
            if path == "/api/notifications/test": return self._json(self.server.service.test_notification(), 201)
            self._json({"error": "Not found"}, 404)
        except CapabilityCandidateNotFound as error: self._json({"error": str(error)}, 404)
        except (ValueError, RuntimeError, KeyError) as error: self._json({"error": str(error)}, 409)
        except Exception as error: self._json({"error": f"Operation failed: {error}"}, 500)


def run(host: str = "127.0.0.1", port: int = 8765, token: str | None = None,
        bootstrap_output: bool = True) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Direct non-loopback binding is disabled. Keep JARVIS on loopback and use an authenticated private VPN HTTPS proxy.")
    instance_lock = ControlCenterInstanceLock(host, port)
    instance_lock.acquire()
    token = token or load_or_create_token()
    tailscale_host = detect_tailscale_serve_host(port)
    trusted_hosts = frozenset({tailscale_host}) if tailscale_host else frozenset()
    try:
        server = ControlCenterServer((host, port), ControlCenterService(), token, trusted_hosts)
    except Exception:
        instance_lock.release()
        raise
    def scheduler_loop() -> None:
        while True:
            try: server.service.scheduler_tick()
            except Exception: pass
            time.sleep(30)
    threading.Thread(target=scheduler_loop, daemon=True, name="jarvis-workforce-scheduler").start()
    local_url = f"http://{host}:{port}/"
    local_bootstrap_url = f"{local_url}?token={token}"
    if bootstrap_output:
        print("JARVIS CONTROL CENTER")
        print(f"LOCAL URL: {local_url}")
        print(f"LOCAL BOOTSTRAP URL: {local_bootstrap_url}")
    if tailscale_host and bootstrap_output:
        mobile_url = f"https://{tailscale_host}/?token={token}"
        print(f"MOBILE BOOTSTRAP URL: {mobile_url}")
        if not print_terminal_qr(mobile_url):
            print("MOBILE BOOTSTRAP QR: unavailable (install the 'qrcode' dependency)")
    elif bootstrap_output:
        print("MOBILE BOOTSTRAP URL: unavailable (no verified private Tailscale Serve mapping)")
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.server_close()
        instance_lock.release()


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--host", default="127.0.0.1"); parser.add_argument("--port", type=int, default=8765); parser.add_argument("--token")
    parser.add_argument("--no-bootstrap-output", action="store_true")
    args = parser.parse_args(); run(args.host, args.port, args.token, not args.no_bootstrap_output)


if __name__ == "__main__":
    main()
