import requests
import time
import threading

URLS = [
    "http://proxy-server-fl-bot-manager-off:50001/", 
    "http://proxy-server-fl-bot-manager-on:50001/", 
    "http://proxy-server-fl2:50001/",   # FL2
]

REQUESTS_PER_SECOND = 10
TIMEOUT = 0.1  # 100 ms
STATS_INTERVAL = 100  # every 100 requests

stats = {
    url: {"success": 0, "blocked": 0, "total": 0}
    for url in URLS
}

lock = threading.Lock()


def check_request(url):
    try:
        r = requests.get(url, timeout=TIMEOUT)
        # 判断是否成功访问
        success = r.status_code == 200 and ("bot" not in r.text)

        with lock:
            stats[url]["total"] += 1
            if success:
                stats[url]["success"] += 1
            else:
                stats[url]["blocked"] += 1

    except Exception:
        # 超时也视为失败（被拦截）
        with lock:
            stats[url]["total"] += 1
            stats[url]["blocked"] += 1


def worker(url):
    """每个 URL 的请求线程"""
    while True:
        start_time = time.time()

        for _ in range(REQUESTS_PER_SECOND):
            check_request(url)

        # 保证每秒总请求数大致稳定
        sleep_time = 1 - (time.time() - start_time)
        if sleep_time > 0:
            time.sleep(sleep_time)


def print_stats():
    """定期打印成功率"""
    while True:
        time.sleep(1)

        for url in URLS:
            if stats[url]["total"] >= STATS_INTERVAL:
                success_rate = stats[url]["success"] / stats[url]["total"]
                blocked = stats[url]["blocked"]
                total = stats[url]["total"]

                print(f"\n---- {url} ----")
                print(f"Success rate: {success_rate:.2%}")
                print(f"Success: {stats[url]['success']}")
                print(f"Blocked: {blocked}")
                print(f"Total: {total}")
                print("--------------------------\n")

                # 清零，开始下一个统计周期
                stats[url] = {"success": 0, "blocked": 0, "total": 0}


def main():
    print("Starting benchmark workers...")

    # 启动 URL 请求线程
    for url in URLS:
        t = threading.Thread(target=worker, args=(url,), daemon=True)
        t.start()

    # 启动统计线程
    print_stats()


if __name__ == "__main__":
    main()
