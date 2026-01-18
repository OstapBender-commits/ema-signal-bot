import requests
import time
import os
import pandas as pd
import numpy as np
from datetime import datetime, UTC
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# ================= WEB SERVER FOR RENDER =================
PORT = int(os.environ.get("PORT", 10000))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

def run_server():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print("HTTP server started on port", PORT)
    server.serve_forever()

# ================= SETTINGS =================
TOKEN = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# ================= TELEGRAM =================
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram error:", e)

# ================= BASIC FUNCTIONS =================
def klines(pair, interval="15", limit=200):
    print("load klines:", pair, interval)

    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "linear",
        "symbol": pair,
        "interval": interval,
        "limit": limit
    }

    try:
        r = requests.get(url, params=params, timeout=10).json()

        if r.get("retCode") != 0:
            print("kline error", r)
            return None

        rows = r["result"]["list"][::-1]

        closes = [float(x[4]) for x in rows]

        return pd.DataFrame({"c": closes})

    except Exception as e:
        print("kline exception", e)
        return None


def ema(s, p):
    return s.ewm(span=p).mean()

def rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0)
    l = -d.clip(upper=0)
    rs = g.rolling(p).mean() / l.rolling(p).mean()
    return 100 - 100 / (1 + rs)

# ================= RESEARCH =================
def research():
    print("========== RESEARCH START ==========")

    pairs = ["BTCUSDT"]   # начнём только с BTC для гарантии
    results = []

    for pair in pairs:
        print("Check pair:", pair)

        df = klines(pair, "15", 200)
        if df is None:
            print("no data for", pair)
            continue

        c = df["c"]
        e50 = ema(c, 50)
        e200 = ema(c, 200)
        r = rsi(c)

        for i in range(len(df)):
            price = c.iloc[i]

            if pd.isna(e50.iloc[i]):
                continue

            in_zone = 40 < r.iloc[i] < 60
            touch = abs(price - e50.iloc[i]) / price < 0.0015

            if in_zone and touch:
                results.append({
                    "pair": pair,
                    "price": float(price),
                    "rsi": float(r.iloc[i]),
                    "ema50": float(e50.iloc[i])
                })

    print("FOUND:", len(results))

    text = "RESULTS:\n"

    for s in results[-5:]:
        line = f"{s['pair']} price={round(s['price'],2)} RSI={round(s['rsi'],1)}"
        print(line)
        text += line + "\n"

    send(text)

    print("========== RESEARCH END ==========")


# ================= START =================
if __name__ == "__main__":
    print("BOOT OK")

    research()

    # держим сервис живым
    threading.Thread(target=run_server, daemon=True).start()
    time.sleep(600)
