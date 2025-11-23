#!/usr/bin/env python3
import socketserver
import threading
import json
from collections import defaultdict
import time
import os 

import http.server
import http.client
import urllib.parse

# ================================
# Proxy Config
# ================================
BACKEND_HOST = "customer-site"
BACKEND_PORT = 443
PROXY_PORT = 50001
INTERVAL = 15   # 特征接口拉取间隔（秒）

FEATURES_URL = "http://worker-asia:8081/bot_features"

# ================================
# Bot Manager Switch
# ================================
IS_BOT_MANAGER_ON = os.getenv("IS_BOT_MANAGER_ON", "false").lower() == "true"
# true → 开启 bot 判断；否则关闭

# ================================
# 缓存 & 统计
# ================================
_ck_cache_lock = threading.Lock()
_ck_last_row_count = 0
_ck_last_update_ts = 0

_stats_lock = threading.Lock()
_stats = {
    "total": 0,
    "by_method": defaultdict(int),
    "by_path": defaultdict(int),
}

# 新增：bot 请求计数
_bot_lock = threading.Lock()
_bot_count = 0

# ================================
# 特征接口后台轮询
# ================================
def features_background_worker():
    global _ck_last_row_count, _ck_last_update_ts

    parsed = urllib.parse.urlparse(FEATURES_URL)
    conn_host = parsed.hostname
    conn_port = parsed.port or 80
    path = parsed.path + ("?" + parsed.query if parsed.query else "")

    while True:
        try:
            conn = http.client.HTTPConnection(conn_host, conn_port, timeout=8)
            conn.request("GET", path)
            resp = conn.getresponse()

            if resp.status == 200:
                raw = resp.read()
                data = json.loads(raw)
                rows = len(data.get("data", []))

                with _ck_cache_lock:
                    _ck_last_row_count = rows
                    _ck_last_update_ts = time.time()

                refreshed_at = data.get("refreshed_at", "N/A")
                print(f"[FEATURES] Updated rows = {rows} (refreshed_at={refreshed_at})")
            else:
                print(f"[FEATURES] HTTP {resp.status} {resp.reason}")

            conn.close()
        except Exception as e:
            print(f"[FEATURES] Request failed: {e}")

        time.sleep(INTERVAL)


# ================================
# Threading HTTP Server
# ================================
class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


# ================================
# Proxy Handler
# ================================
class ProxyHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ---------------------------
    # helpers
    # ---------------------------
    def _record(self, method, path):
        with _stats_lock:
            _stats["total"] += 1
            _stats["by_method"][method] += 1
            _stats["by_path"][path] += 1

    def _record_bot(self):
        global _bot_count
        with _bot_lock:
            _bot_count += 1

    def _serve_stats(self):
        with _stats_lock:
            payload = {
                "total": _stats["total"],
                "by_method": dict(_stats["by_method"]),
                "by_path": dict(_stats["by_path"]),
            }
        with _bot_lock:
            payload["bot_requests"] = _bot_count
            payload["human_requests"] = _stats["total"] - _bot_count

        payload["bot_manager_on"] = IS_BOT_MANAGER_ON

        body = json.dumps(payload, ensure_ascii=False, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------------------------
    # AI logic（带开关）
    # ---------------------------
    def _serve_ai_check(self):
        """
        if bot manager off, forward all requests
        """
        msg = "Hello bot, have a nice day!\n"
        self._record_bot()
                
        body = msg.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------------------------
    # Backend forward
    # ---------------------------
    def _forward(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length > 0 else None

        forward_headers = {k: v for k, v in self.headers.items()
                           if k.lower() not in (
                               "host", "connection", "keep-alive", "proxy-authenticate",
                               "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade"
                           )}
        forward_headers["Host"] = f"{BACKEND_HOST}:{BACKEND_PORT}"

        conn = http.client.HTTPConnection(BACKEND_HOST, BACKEND_PORT, timeout=10)
        try:
            conn.request(self.command, self.path, body=body, headers=forward_headers)
            resp = conn.getresponse()
            resp_body = resp.read()
        except Exception as e:
            self.send_error(502, f"Bad gateway: {e}")
            return
        finally:
            conn.close()

        self.send_response(resp.status, resp.reason)
        for header, value in resp.getheaders():
            if header.lower() in ("transfer-encoding", "connection", "keep-alive",
                                  "proxy-authenticate", "proxy-authorization",
                                  "te", "trailers", "upgrade", "content-length"):
                continue
            self.send_header(header, value)
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)

    # ---------------------------
    # Routes
    # ---------------------------
    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)

        if parsed.path == "/":
            # 如果开关关闭 → 始终正常代理
            if not IS_BOT_MANAGER_ON:
                self._record("GET", parsed.path)
                return self._forward()

            with _ck_cache_lock:
                rows = _ck_last_row_count

            if 2 < rows < 6:
                self._record("GET", parsed.path)
                return self._forward()
            else:
                return self._serve_ai_check()

        if parsed.path == "/stats":
            return self._serve_stats()

        self._record("GET", parsed.path)
        self._forward()

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)

        if parsed.path == "/":
            # 开关关闭 → 始终正常代理
            if not IS_BOT_MANAGER_ON:
                self._record("POST", parsed.path)
                return self._forward()

            with _ck_cache_lock:
                rows = _ck_last_row_count

            if 2 < rows < 6:
                self._record("POST", parsed.path)
                return self._forward()
            else:
                return self._serve_ai_check()

        if parsed.path == "/stats":
            return self._serve_stats()

        self._record("POST", parsed.path)
        self._forward()

    do_HEAD   = _forward
    do_PUT    = _forward
    do_DELETE = _forward
    do_PATCH  = _forward

    def log_message(self, fmt, *args):
        print(f"{self.client_address[0]} - - [{self.log_date_time_string()}] {fmt % args}")


# ================================
# Start Server
# ================================
def run_server():
    t = threading.Thread(target=features_background_worker, daemon=True)
    t.start()

    print(f"Bot manager ON? {IS_BOT_MANAGER_ON}")
    server = ThreadingHTTPServer(("", PROXY_PORT), ProxyHandler)
    print(f"Proxy FL listening on 0.0.0.0:{PROXY_PORT}")
    print(f"Background features worker active, pulling {FEATURES_URL} every {INTERVAL}s...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down proxy...")
        server.shutdown()


if __name__ == "__main__":
    run_server()
