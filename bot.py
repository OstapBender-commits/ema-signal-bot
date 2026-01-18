import requests
import time
import os
import statistics
from datetime import datetime, UTC
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

PORT = int(os.environ.get("PORT", 10000))

# ===== WEB SERVER =====
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

def run_server():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()

# ===== TELEGRAM =====
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except:
        pass

# ===== SOURCES =====
def get_gecko():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd"},
            timeout=5
        ).json()
        return float(r["bitcoin"]["usd"])
    except:
        return None


def get_cc():
    try:
        r = requests.get(
            "https://min-api.cryptocompare.com/data/price",
            params={"fsym": "BTC", "tsyms": "USDT"},
            timeout=5
        ).json()
        return float(r["USDT"])
    except:
        return None


# ===== TEST ENGINE =====
def run_test(minutes=30):
    send("🧪 START SOURCE COMPARISON (30 min)")

    gecko = []
    cc = []

    last_g = None
    last_c = None

    frozen_g = 0
    frozen_c = 0

    errors_g = 0
    errors_c = 0

    start = time.time()

    while time.time() - start < minutes * 60:
        g = get_gecko()
        c = get_cc()

        # ---- CoinGecko ----
        if g is None:
            errors_g += 1
        else:
            gecko.append(g)
            if g == last_g:
                frozen_g += 1
            last_g = g

        # ---- CryptoCompare ----
        if c is None:
            errors_c += 1
        else:
            cc.append(c)
            if c == last_c:
                frozen_c += 1
            last_c = c

        time.sleep(10)

    # ===== METRICS =====
    def stats(arr):
        if len(arr) < 2:
            return "no data"
        return {
            "updates": len(arr),
            "std": round(statistics.stdev(arr), 2),
            "range": round(max(arr) - min(arr), 2)
        }

    diff = []
    for i in range(min(len(gecko), len(cc))):
        diff.append(abs(gecko[i] - cc[i]))

    report = f"""
📊 COMPARISON RESULT

--- CoinGecko ---
samples: {len(gecko)}
frozen ticks: {frozen_g}
errors: {errors_g}
stats: {stats(gecko)}

--- CryptoCompare ---
samples: {len(cc)}
frozen ticks: {frozen_c}
errors: {errors_c}
stats: {stats(cc)}

--- Divergence ---
avg diff: {round(sum(diff)/len(diff),2) if diff else 'n/a'}
max diff: {round(max(diff),2) if diff else 'n/a'}

Time: {datetime.now(UTC)}
"""

    send(report)


# ===== START =====
if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    run_test(30)
