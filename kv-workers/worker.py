#!/usr/bin/env python3
import http.server
import socketserver
import threading
import json
import time
import clickhouse_connect

# ========================= 配置区 =========================
HOST = "0.0.0.0"
PORT = 8081

# 只用一个 host（集群任意节点，e.g. node1），移除 hosts= 参数
CLICKHOUSE_HOSTS = [
    "clickhouse-node1",   # 选一个主节点
    # 其他节点注释掉
]

CLICKHOUSE_PORT = 8123  # HTTP 端口
CLICKHOUSE_USER = "test_user"
CLICKHOUSE_PASSWORD = "test"

QUERY = """
SELECT name, type 
FROM system.columns 
WHERE table = 'http_requests_features' 
ORDER BY name
"""

INTERVAL = 10
# ==========================================================

# 移除 hosts= 参数（兼容旧版）
client = clickhouse_connect.get_client(
    host=CLICKHOUSE_HOSTS[0],  # 只用第一个
    port=CLICKHOUSE_PORT,
    username=CLICKHOUSE_USER,
    password=CLICKHOUSE_PASSWORD,
    # hosts=CLICKHOUSE_HOSTS,  # <-- 注释掉或删除这行！
    # 如果需要负载均衡，手动轮询（见下面高级版）
)

_cached_data = {}
_cache_lock = threading.Lock()

def refresh_cache():
    global _cached_data
    while True:
        try:
            # 用 JSONEachRow 格式，直接得 list[dict]
            result = client.query(QUERY)
            data = result.result_rows  # 已是最小化 dict 列表

            with _cache_lock:
                _cached_data = {"data": data, "refreshed_at": int(time.time())}

            print(f"[CK] cache updated, {len(data)} columns")

        except Exception as e:
            print(f"[CK] query failed: {e}")

        time.sleep(INTERVAL)

# ... 其余代码不变（BotHandler, run_server 等）
class BotHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/bot_features":
            with _cache_lock:
                body = json.dumps(_cached_data, ensure_ascii=False).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.client_address[0], fmt % args))

def run_server():
    server = socketserver.ThreadingTCPServer((HOST, PORT), BotHandler)
    print(f"[BOT] listening on {HOST}:{PORT}")
    server.serve_forever()

if __name__ == "__main__":
    t = threading.Thread(target=refresh_cache, daemon=True)
    t.start()
    run_server()