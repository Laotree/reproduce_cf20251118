import socketserver
import threading
import json
from collections import defaultdict

#!/usr/bin/env python3

import http.server
import http.client
import urllib.parse

BACKEND_HOST = "customer-site"
BACKEND_PORT = 443
PROXY_PORT = 50001

_stats_lock = threading.Lock()
_stats = {
    "total": 0,
    "by_method": defaultdict(int),
    "by_path": defaultdict(int),
}

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

class ProxyHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_STATS(self):
        # Not a real HTTP verb; kept for completeness
        self.send_error(405)

    def _record(self, method, path):
        with _stats_lock:
            _stats["total"] += 1
            _stats["by_method"][method] += 1
            _stats["by_path"][path] += 1

    def _serve_stats(self):
        with _stats_lock:
            payload = {
                "total": _stats["total"],
                "by_method": dict(_stats["by_method"]),
                "by_path": dict(_stats["by_path"]),
            }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _forward(self):
        # Read request body if present
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length > 0 else None

        # Prepare headers for backend
        forward_headers = {}
        for k, v in self.headers.items():
            # Avoid sending hop-by-hop headers and override Host
            if k.lower() in ("host", "connection", "keep-alive", "proxy-authenticate",
                             "proxy-authorization", "te", "trailers", "transfer-encoding",
                             "upgrade"):
                continue
            forward_headers[k] = v
        forward_headers["Host"] = f"{BACKEND_HOST}:{BACKEND_PORT}"

        # Forward request to backend
        conn = http.client.HTTPConnection(BACKEND_HOST, BACKEND_PORT, timeout=10)
        try:
            conn.request(self.command, self.path, body=body, headers=forward_headers)
            resp = conn.getresponse()
            resp_body = resp.read()
        except Exception as e:
            # Backend error -> return 502
            self.send_error(502, f"Bad gateway: {e}")
            return
        finally:
            conn.close()

        # Relay response status and headers
        self.send_response(resp.status, resp.reason)
        for header, value in resp.getheaders():
            # Skip hop-by-hop headers
            if header.lower() in ("transfer-encoding", "connection", "keep-alive", "proxy-authenticate",
                                  "proxy-authorization", "te", "trailers", "upgrade"):
                continue
            # Avoid duplicate Content-Length if we'll set it
            if header.lower() == "content-length":
                continue
            self.send_header(header, value)
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()

        # Write body
        if resp_body:
            self.wfile.write(resp_body)

    def handle_one_request(self):
        # Override to avoid logging broken pipe exceptions to stderr repeatedly
        try:
            return super().handle_one_request()
        except BrokenPipeError:
            pass

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/stats":
            self._serve_stats()
            return
        self._record("GET", parsed.path)
        self._forward()

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/stats":
            self._serve_stats()
            return
        self._record("POST", parsed.path)
        self._forward()

    def do_PUT(self):
        parsed = urllib.parse.urlsplit(self.path)
        self._record("PUT", parsed.path)
        self._forward()

    def do_DELETE(self):
        parsed = urllib.parse.urlsplit(self.path)
        self._record("DELETE", parsed.path)
        self._forward()

    def do_PATCH(self):
        parsed = urllib.parse.urlsplit(self.path)
        self._record("PATCH", parsed.path)
        self._forward()

    def do_HEAD(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/stats":
            # HEAD for stats returns headers only
            with _stats_lock:
                payload = {
                    "total": _stats["total"],
                    "by_method": dict(_stats["by_method"]),
                    "by_path": dict(_stats["by_path"]),
                }
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return
        self._record("HEAD", parsed.path)
        self._forward()

    def log_message(self, format, *args):
        # Minimal logging to stdout
        print("%s - - [%s] %s" % (self.client_address[0], self.log_date_time_string(), format % args))

def run_server():
    server = ThreadingHTTPServer(("", PROXY_PORT), ProxyHandler)
    print(f"Proxy listening on 0.0.0.0:{PROXY_PORT} -> backend {BACKEND_HOST}:{BACKEND_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down proxy...")
        server.shutdown()

if __name__ == "__main__":
    run_server()