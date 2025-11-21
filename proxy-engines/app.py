#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple HTTP service (using the standard library), listens on 8080,
all paths return 200 and a friendly greeting.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import signal
import sys
from socketserver import ThreadingMixIn

HOST = "0.0.0.0"
PORT = 443

GREETING = "Helo, have a nice day!\n"

class GreetingHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self._send_greeting()

    def do_POST(self):
        # Also handle POST (ignore request body), return the greeting uniformly
        # If you need to read the request body:
        # length = int(self.headers.get('Content-Length', 0)); body = self.rfile.read(length)
        self._send_greeting()

    def do_PUT(self):
        self._send_greeting()

    def do_DELETE(self):
        self._send_greeting()

    def _send_greeting(self):
        body = GREETING.encode("utf-8")
        self.send_response(200, "OK")
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Custom log format (output to stderr), preserve client info
        sys.stderr.write("%s - - [%s] %s\n" %
                         (self.client_address[0],
                          self.log_date_time_string(),
                          format % args))

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """HTTPServer that supports concurrent request handling (one thread per request)"""
    daemon_threads = True

def run_server(host=HOST, port=PORT):
    server = ThreadedHTTPServer((host, port), GreetingHandler)

    def _shutdown(signum, frame):
        print("\nReceived termination signal, shutting down service...")
        server.shutdown()
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print(f"Service started, listening on http://{host}:{port} (press Ctrl+C to stop)")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        print("Service stopped.")

if __name__ == "__main__":
    run_server()
