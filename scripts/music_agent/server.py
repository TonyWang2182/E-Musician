"""Loopback-only HTTP companion. Tokens are capabilities, never provider keys."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit
from .secrets import redact

WEB = Path(__file__).with_name("web")
class AgentServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    request_queue_size = 8
    allow_reuse_address = False
    def __init__(self, runtime, port=0):
        self.runtime = runtime
        self.token = secrets.token_urlsafe(32)
        self.slots = threading.BoundedSemaphore(12)
        super().__init__(("127.0.0.1", port), Handler)
        self.authority = "127.0.0.1:" + str(self.server_port)
        self.origin = "http://" + self.authority
    def process_request(self, request, client_address):
        if not self.slots.acquire(False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise
    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()
    def handle_error(self, request, address):
        pass  # Never emit raw request data, paths, tokens or credentials.
    @property
    def launch_url(self):
        return self.origin + "/#token=" + self.token

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "E-musician-agent"
    def setup(self):
        super().setup()
        self.connection.settimeout(5)
    def log_message(self, *_):
        pass
    def _send(self, status, value, mime="application/json; charset=utf-8"):
        if not isinstance(value, bytes):
            value = redact(json.dumps(value, ensure_ascii=False, allow_nan=False)).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(value)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        try:
            self.wfile.write(value)
        except (BrokenPipeError, ConnectionResetError):
            pass
    def _allowed(self, api=False):
        if self.headers.get("Host") != self.server.authority:
            self._send(403, {"error":"仅接受本机地址。"})
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin != self.server.origin:
            self._send(403, {"error":"拒绝跨站请求。"})
            return False
        token = self.headers.get("X-Agent-Token","")
        if api and (not token.isascii() or not secrets.compare_digest(token, self.server.token)):
            self._send(403, {"error":"会话已失效，请使用本次助手启动入口。"})
            return False
        return True
    def do_GET(self):
        path = urlsplit(self.path).path
        if not self._allowed(path.startswith("/api/")):
            return
        if path == "/api/state":
            try:
                self._send(200, self.server.runtime.state())
            except Exception:
                self._send(500, {"error":"无法读取本地状态，请稍后重试。"})
            return
        assets = {"/":("index.html","text/html; charset=utf-8"),
                  "/app.js":("app.js","text/javascript; charset=utf-8"),
                  "/style.css":("style.css","text/css; charset=utf-8")}
        if path not in assets:
            self._send(404, {"error":"不存在该入口。"})
            return
        name, mime = assets[path]
        self._send(200, (WEB/name).read_bytes(), mime)
    def do_POST(self):
        if not self._allowed(True):
            return
        if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Type","").split(";")[0] != "application/json":
            self._send(415, {"error":"需要 JSON 请求。"})
            return
        try:
            length = int(self.headers.get("Content-Length","0"))
            if not 1 <= length <= 32768:
                self._send(413, {"error":"请求大小超限。"})
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("请求不完整。")
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("重复参数。")
                    result[key] = value
                return result
            def finite(_):
                raise ValueError("无效数字。")
            def number(text):
                value = float(text)
                if not math.isfinite(value):
                    raise ValueError("无效数字。")
                return value
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=finite, parse_float=number)
            if not isinstance(value,dict):
                raise ValueError("请求必须为对象。")
            runtime = self.server.runtime
            path = urlsplit(self.path).path
            if path == "/api/plan" and set(value) in ({"prompt"}, {"prompt","scope"}):
                result = runtime.plan_request(value["prompt"], value.get("scope","selection"))
            elif path == "/api/apply" and set(value) == {"plan_id"}:
                result = runtime.apply(value["plan_id"])
            elif path == "/api/cancel" and not value:
                result = runtime.cancel()
            elif path == "/api/undo" and not value:
                result = runtime.undo()
            elif path == "/api/settings":
                result = runtime.settings(value)
            elif path == "/api/shutdown" and set(value) == {"confirm"} and value["confirm"] is True:
                if getattr(runtime.bridge, "embedded", False):
                    raise ValueError("请用侧栏关闭按钮收起助手；DAW 由原生窗口管理。")
                runtime.close()
                self._send(200, {"closed":True})
                threading.Thread(target=self.server.shutdown,daemon=True).start()
                return
            else:
                raise ValueError("未知操作或参数。")
            self._send(200, result)
        except (ValueError, RuntimeError) as exc:
            self._send(400, {"error":redact(str(exc))[:700]})
        except Exception:
            self._send(500, {"error":"本地服务异常，未继续操作。"})
