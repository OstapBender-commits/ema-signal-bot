import requests
import time
import os
import pandas as pd
import numpy as np
from datetime import datetime, UTC
import threading

# --- маленький веб-сервер ---
from http.server import BaseHTTPRequestHandler, HTTPServer

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

# --- настройки ---
TOKEN = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

EMA_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

RISK_EMA = 2.5      # 0.5%
RISK_PUMP = 1.5     # 0.3%

MAX_EMA = 3
MAX_PUMP = 3

REQUEST_DELAY = 1.0

stats = {
    "day": "",
    "ema": 0,
    "pump": 0,
    "log": []
}

# ---------- Telegram ----------
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram error:", e)

# ---------- BYBIT ----------
def get_all_futures():
    try:
        url = "https://api.bybit.com/v5/market/tickers?category=linear"
        r = requests.get(url, timeout=10).json()
        return [x["symbol"] for x in r["result"]["list"] if x["symbol"].endswith("USDT")]
    except:
        return []

def klines(pair, interval="15", limit=120):
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
            return None

        rows = r["result"]["list"][::-1]

        closes = [float(x[4]) for x in rows]
        highs  = [float(x[2]) for x in rows]
        lows   = [float(x[3]) for x in rows]
        vol    = [float(x[5]) for x in rows]

        return pd.DataFrame({"c": closes, "h": highs, "l": lows, "v": vol})

    except:
        return None

# ---------- индикаторы ----------
def ema(s, p):
    return s.ewm(span=p).mean()

def rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0)
    l = -d.clip(upper=0)
    rs = g.rolling(p).mean() / l.rolling(p).mean()
    return 100 - 100 / (1 + rs)

# ---------- EMA ----------
def check_ema(pair):
    if stats["ema"] >= MAX_EMA:
        return

    df = klines(pair)
    if df is None:
        return

    c = df["c"]
    e50 = ema(c, 50)
    e200 = ema(c, 200)
    r = rsi(c)

    price = c.iloc[-1]

    trend_up = price > e50.iloc[-1] and price > e200.iloc[-1]
    trend_dn = price < e50.iloc[-1] and price < e200.iloc[-1]

    in_zone = 40 < r.iloc[-1] < 60
    touch = abs(price - e50.iloc[-1]) / price < 0.0015

    if in_zone and touch:
        side = "LONG" if trend_up else "SHORT" if trend_dn else None
        if not side:
            return

        pos = round(RISK_EMA / 0.006, 1)

        msg = f"""{'🟢' if side=='LONG' else '🔴'} EMA {pair} {side}
Цена: {price}
RSI: {round(r.iloc[-1],1)}

Риск: {RISK_EMA}$
Позиция: {pos}$

Сегодня EMA: {stats['ema']+1}/{MAX_EMA}"""

        send(msg)
        stats["ema"] += 1

# ---------- PUMP ----------
def check_pump(pair):
    if stats["pump"] >= MAX_PUMP:
        return

    df = klines(pair, "5", 200)
    if df is None:
        return

    c = df["c"]
    v = df["v"]

    growth15 = (c.iloc[-1] - c.iloc[-4]) / c.iloc[-4] * 100
    growth60 = (c.iloc[-1] - c.iloc[-13]) / c.iloc[-13] * 100

    vol_x = v.iloc[-1] / (v.mean() + 0.0001)

    if not (growth15 > 10 and growth60 > 15 and vol_x > 3):
        return

    last = c.iloc[-1]
    high = c.iloc[-20:].max()

    drawdown = (high - last) / high * 100
    r = rsi(c)

    safe = drawdown > 3 and r.iloc[-1] < 75

    if not safe:
        return

    stop = round(high * 1.02, 6)
    tp1 = round(last * 0.96, 6)
    tp2 = round(last * 0.93, 6)

    pos = round(RISK_PUMP / 0.01, 1)

    msg = f"""🚨 PUMP SHORT — {pair}

Импульс 15m: +{round(growth15,1)}%
Импульс 1h: +{round(growth60,1)}%
Объём: x{round(vol_x,1)}

Вход: {last}
Стоп: {stop}

Тейки:
TP1: {tp1}
TP2: {tp2}

Риск: {RISK_PUMP}$

Сегодня пампов: {stats['pump']+1}/{MAX_PUMP}"""

    send(msg)
    stats["pump"] += 1

# ---------- MAIN LOGIC ----------
def bot_loop():
    send("🟡 BOT STARTED (WEB MODE)")

    while True:
        now = datetime.now(UTC)
        today = now.strftime("%Y-%m-%d")

        if stats["day"] != today:
            stats["day"] = today
            stats["ema"] = 0
            stats["pump"] = 0

        # EMA
        for p in EMA_PAIRS:
            check_ema(p)
            time.sleep(REQUEST_DELAY)

        # PUMPS
        for p in get_all_futures():
            check_pump(p)
            time.sleep(REQUEST_DELAY)

        time.sleep(30)

# ---------- START ----------
if __name__ == "__main__":
    # веб-сервер в отдельном потоке
    threading.Thread(target=run_server, daemon=True).start()

    # основная логика
    bot_loop()
