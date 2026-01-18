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

# ==========================================================
#                MULTI SOURCE KLINES
# ==========================================================
def klines(pair="BTCUSDT", interval="15", limit=800):
    """
    Источники только аналитические:
    1) CryptoCompare
    2) CoinGecko
    3) Tiingo
    """

    symbol = pair.replace("USDT", "")

    # ----- 1. CRYPTOCOMPARE -----
    try:
        print("Try CryptoCompare...")

        url = "https://min-api.cryptocompare.com/data/v2/histominute"

        params = {
            "fsym": symbol,
            "tsym": "USDT",
            "limit": limit,
            "aggregate": int(interval)
        }

        r = requests.get(url, params=params, timeout=10).json()

        if r.get("Response") == "Success":
            closes = [x["close"] for x in r["Data"]["Data"]]
            print("CryptoCompare OK")
            return pd.DataFrame({"c": closes})

        print("CryptoCompare empty")

    except Exception as e:
        print("CryptoCompare fail:", e)

    # ----- 2. COINGECKO -----
    try:
        print("Try CoinGecko...")

        url = f"https://api.coingecko.com/api/v3/coins/{symbol.lower()}/ohlc"

        params = {
            "vs_currency": "usd",
            "days": 7
        }

        r = requests.get(url, params=params, timeout=10).json()

        if isinstance(r, list) and len(r) > 0:
            closes = [x[4] for x in r]   # формат [t,o,h,l,c]
            print("CoinGecko OK")
            return pd.DataFrame({"c": closes})

        print("CoinGecko empty")

    except Exception as e:
        print("CoinGecko fail:", e)

    # ----- 3. TIINGO -----
    try:
        print("Try Tiingo...")

        url = f"https://api.tiingo.com/tiingo/crypto/prices"

        params = {
            "tickers": f"{symbol.lower()}usd",
            "resampleFreq": f"{interval}min",
            "startDate": "2024-01-01"
        }

        r = requests.get(url, params=params, timeout=10).json()

        if isinstance(r, list) and r:
            closes = [x["close"] for x in r[0]["priceData"]]
            print("Tiingo OK")
            return pd.DataFrame({"c": closes})

        print("Tiingo empty")

    except Exception as e:
        print("Tiingo fail:", e)

    print("NO SOURCE AVAILABLE")
    return None


# ==========================================================
#                INDICATORS
# ==========================================================
def ema(s, p):
    return s.ewm(span=p).mean()

def rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0)
    l = -d.clip(upper=0)
    rs = g.rolling(p).mean() / l.rolling(p).mean()
    return 100 - 100 / (1 + rs)


# ==========================================================
#            RESEARCH WITH MULTI ZONES
# ==========================================================
def research():
    print("========== RESEARCH START ==========")

    df = klines("BTCUSDT", "15", 800)

    if df is None:
        send("❌ NO DATA FROM ANY SOURCE")
        return

    c = df["c"]
    e50 = ema(c, 50)
    r = rsi(c)

    zones = [0.0015, 0.0020, 0.0025, 0.0030]

    stats = {z: 0 for z in zones}
    min_dist = 999

    for i in range(len(df)):
        price = c.iloc[i]

        if pd.isna(e50.iloc[i]):
            continue

        dist = abs(price - e50.iloc[i]) / price
        min_dist = min(min_dist, dist)

        if not (40 < r.iloc[i] < 60):
            continue

        for z in zones:
            if dist < z:
                stats[z] += 1

    text = "📊 TEST BTCUSDT\n\n"

    for z in zones:
        text += f"Zone {round(z*100,2)}% → {stats[z]} setups\n"

    text += f"\nMin distance to EMA: {round(min_dist*100,3)}%\n"

    print(text)
    send(text)

    print("========== RESEARCH END ==========")


# ==========================================================
#                        START
# ==========================================================
if __name__ == "__main__":
    print("BOOT OK")

    research()

    # держим сервис живым, чтобы увидеть логи
    threading.Thread(target=run_server, daemon=True).start()
    time.sleep(600)
