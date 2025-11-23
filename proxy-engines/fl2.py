#!/usr/bin/env python3
import socketserver
import threading
import json
from collections import defaultdict
import time
import os
import sys
import traceback

import http.server
import http.client
import urllib.parse

# --- Ensure uncaught thread exceptions crash the whole process ---
def _thread_excepthook(args):
    # args has: exc_type, exc_value, exc_traceback, thread
    print(f"Uncaught exception in thread {args.thread.name}:", file=sys.stderr)
    traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback, file=sys.stderr)
    # Forcefully exit the whole process (container will stop). Exit code 1 indicates error.
    os._exit(1)

# Register the hook (Python 3.8+)
threading.excepthook = _thread_excepthook

# ================================
# Proxy Config
# ================================
BACKEND_HOST = "customer-site"
BACKEND_PORT = 443
PROXY_PORT = 50001
INTERVAL = 15   # 特征接口拉取间隔（秒）

FEATURES_URL = "http://worker-asia:8081/bot_features"

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

# bot 请求计数
_bot_lock = threading.Lock()
_bot_count = 0

# ================================
# Rust append_with_names 模拟：启动时预分配固定 4 个 slot
# ================================
_feature_lock = threading.Lock()
_prealloc_size = 4
_feature_names = [None] * _prealloc_size   # 固定长度 4


# ================================
# 特征接口后台轮询（含 Rust unwrap 行为模拟）
# ================================
def features_background_worker():
    global _ck_last_row_count, _ck_last_update_ts, _feature_names, _prealloc_size

    parsed = urllib.parse.urlparse(FEATURES_URL)
    conn_host = parsed.hostname
    conn_port = parsed.port or 80
    path = parsed.path + ("?" + parsed.query if parsed.query else "")

    while True:
        conn = http.client.HTTPConnection(conn_host, conn_port, timeout=8)
        conn.request("GET", path)
        resp = conn.getresponse()

        if resp.status == 200:
            raw = resp.read()
            data = json.loads(raw)
            rows = len(data.get("data", []))
            refreshed_at = data.get("refreshed_at", "N/A")

            incoming = data.get("data", [])
            names = [row[0] for row in incoming]

            # ======================================================
            # Rust append_with_names 行为模拟 —— 使用固定预分配空间
            # ======================================================

            seen = set()
            new_list = [None] * _prealloc_size

            for i, name in enumerate(names):

                # 重名 => no unwrap error
                if name in seen:
                    print(f"Duplicate feature name detected: {name}")

                seen.add(name)

                if i > _prealloc_size - 1:
                    raise RuntimeError("thread fl2_worker_thread panicked: called Result::unwrap() on an Err value")

            # 有效更新
            with _feature_lock:
                _feature_names = new_list

            with _ck_cache_lock:
                _ck_last_row_count = rows
                _ck_last_update_ts = time.time()

            print(f"[FEATURES] Updated names={_feature_names}, refreshed_at={refreshed_at}")

        else:
            print(f"[FEATURES] HTTP {resp.status} {resp.reason}")

        conn.close()

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

        body = json.dumps(payload, ensure_ascii=False, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ===============================
    # AI bot 判断逻辑（可自行修改）
    # ===============================
    def _serve_ai_check(self):
        msg = "Hello bot, have a nice day!"
        self._record_bot()      
        body = msg.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --------------------------- backend forward
    def _forward(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length > 0 else None

        forward_headers = {k: v for k, v in self.headers.items()
                           if k.lower() not in (
                               "host", "connection", "keep-alive", "proxy-authenticate",
                               "proxy-authorization", "te", "trailers",
                               "transfer-encoding", "upgrade"
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

    # --------------------------- routes
    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)

        if parsed.path == "/":
            rows = len(_feature_names)
            if 2 < rows < 6:
                self._record("POST", parsed.path)
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
    t = threading.Thread(target=features_background_worker, daemon=True, name="features_background_worker")
    t.start()

    server = ThreadingHTTPServer(("", PROXY_PORT), ProxyHandler)
    print(f"Proxy FL2 listening on 0.0.0.0:{PROXY_PORT}")
    print(f"Background features worker active, pulling {FEATURES_URL} every {INTERVAL}s...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down proxy...")
        server.shutdown()


if __name__ == "__main__":
    run_server()
