import requests
import time
import os
from datetime import datetime, UTC
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

PORT = int(os.environ.get("PORT", 10000))

# ===== WEB SERVER FOR RENDER =====
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

def run_server():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print("HTTP server started")
    server.serve_forever()

# ===== TELEGRAM =====
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram error:", e)

# ==========================================================
# 1. BYBIT
# ==========================================================
def test_bybit():
    try:
        t0 = time.time()

        url = "https://api.bybit.com/v5/market/tickers"
        r = requests.get(url, params={"category": "linear"}, timeout=10).json()

        dt = round(time.time() - t0, 2)

        if "result" not in r:
            return f"❌ BYBIT: bad format {str(r)[:100]}"

        btc = None
        for x in r["result"]["list"]:
            if x["symbol"] == "BTCUSDT":
                btc = x
                break

        if not btc:
            return "❌ BYBIT: BTCUSDT not found"

        return f"""✅ BYBIT OK ({dt}s)
price: {btc['lastPrice']}
bid: {btc['bid1Price']}
ask: {btc['ask1Price']}"""

    except Exception as e:
        return f"❌ BYBIT ERROR: {e}"

# ==========================================================
# 2. BINANCE
# ==========================================================
def test_binance():
    try:
        t0 = time.time()

        url = "https://api.binance.com/api/v3/ticker/price"
        r = requests.get(url, params={"symbol": "BTCUSDT"}, timeout=10).json()

        dt = round(time.time() - t0, 2)

        if "price" not in r:
            return f"❌ BINANCE: {str(r)[:100]}"

        return f"""✅ BINANCE OK ({dt}s)
price: {r['price']}"""

    except Exception as e:
        return f"❌ BINANCE ERROR: {e}"

# ==========================================================
# 3. CRYPTOCOMPARE
# ==========================================================
def test_cryptocompare():
    try:
        t0 = time.time()

        url = "https://min-api.cryptocompare.com/data/price"
        r = requests.get(url, params={"fsym": "BTC", "tsyms": "USDT"}, timeout=10).json()

        dt = round(time.time() - t0, 2)

        if "USDT" not in r:
            return f"❌ CRYPTOCOMPARE: {str(r)[:100]}"

        return f"""✅ CRYPTOCOMPARE OK ({dt}s)
price: {r['USDT']}"""

    except Exception as e:
        return f"❌ CRYPTOCOMPARE ERROR: {e}"

# ==========================================================
# 4. COINGECKO
# ==========================================================
def test_coingecko():
    try:
        t0 = time.time()

        url = "https://api.coingecko.com/api/v3/simple/price"
        r = requests.get(url, params={"ids": "bitcoin", "vs_currencies": "usd"}, timeout=10).json()

        dt = round(time.time() - t0, 2)

        if "bitcoin" not in r:
            return f"❌ COINGECKO: {str(r)[:100]}"

        return f"""✅ COINGECKO OK ({dt}s)
price: {r['bitcoin']['usd']}"""

    except Exception as e:
        return f"❌ COINGECKO ERROR: {e}"

# ==========================================================
# MAIN TEST
# ==========================================================
def full_test():
    send("🔎 START MARKET DATA TEST")

    report = []

    report.append(test_bybit())
    report.append(test_binance())
    report.append(test_cryptocompare())
    report.append(test_coingecko())

    text = "📊 DATA SOURCE CHECK\n\n" + "\n\n".join(report)

    text += f"\n\nTime: {datetime.now(UTC)}"

    send(text)

# ==========================================================
# START
# ==========================================================
if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()

    # запускаем тест каждые 5 минут
    while True:
        full_test()
        time.sleep(300)
