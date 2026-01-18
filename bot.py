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

RISK_EMA = 2.5
RISK_PUMP = 1.5

MAX_EMA = 3
MAX_PUMP = 3

REQUEST_DELAY = 1.0

stats = {"day": "", "ema": 0, "pump": 0}

# ================= TELEGRAM =================
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram error:", e)

# ================= DATA SOURCE (аналитические) =================
def klines(limit=2000):
    """Данные только из нейтрального источника"""
    try:
        url = "https://min-api.cryptocompare.com/data/v2/histominute"
        params = {"fsym": "BTC", "tsym": "USDT", "limit": limit, "aggregate": 15}

        r = requests.get(url, params=params, timeout=10).json()

        if r.get("Response") != "Success":
            return None

        df = pd.DataFrame(r["Data"]["Data"])
        df["t"] = pd.to_datetime(df["time"], unit="s", utc=True)

        return df[["t", "close", "volumeto"]].rename(
            columns={"close": "c", "volumeto": "v"}
        )

    except:
        return None

# ================= INDICATORS =================
def ema(s, p):
    return s.ewm(span=p).mean()

def rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0)
    l = -d.clip(upper=0)
    rs = g.rolling(p).mean() / l.rolling(p).mean()
    return 100 - 100 / (1 + rs)

# ================= JANUARY PROFILE =================
def build_impulse_profile(df):
    mask = (df["t"] >= "2026-01-13") & (df["t"] <= "2026-01-15 23:59")
    d = df[mask]

    if len(d) < 50:
        return None

    start = d["c"].iloc[0]
    peak = d["c"].max()
    low = d["c"].min()

    # UP metrics
    hour_up = (d["c"].pct_change(4).max()) * 100
    day_up = (peak / start - 1) * 100

    # DOWN metrics
    hour_down = abs((d["c"].pct_change(4).min()) * 100)
    day_down = abs((low / start - 1) * 100)

    vol_x = d["v"].mean() / df["v"].mean()

    e50 = ema(df["c"], 50)
    dist = (abs(d["c"] - e50) / d["c"]).mean() * 100

    return {
        "up": {"hour": round(hour_up, 2), "day": round(day_up, 2), "ema_dist": round(dist, 2)},
        "down": {"hour": round(hour_down, 2), "day": round(day_down, 2), "ema_dist": round(dist, 2)},
        "vol_x": round(vol_x, 2),
    }

def current_impulse(df):
    d = df.tail(20)

    hour_gain = (d["c"].pct_change(4).max()) * 100
    hour_drop = abs((d["c"].pct_change(4).min()) * 100)

    vol_x = d["v"].mean() / df["v"].mean()
    e50 = ema(df["c"], 50)
    dist = (abs(d["c"] - e50) / d["c"]).mean() * 100

    return {
        "hour_gain": round(hour_gain, 2),
        "hour_drop": round(hour_drop, 2),
        "vol_x": round(vol_x, 2),
        "ema_dist": round(dist, 2),
    }

def similarity(now, profile):
    score_up = 0
    score_down = 0

    if now["hour_gain"] >= profile["up"]["hour"] * 0.7:
        score_up += 1
    if now["ema_dist"] >= profile["up"]["ema_dist"] * 0.7:
        score_up += 1

    if now["hour_drop"] >= profile["down"]["hour"] * 0.7:
        score_down += 1
    if now["ema_dist"] >= profile["down"]["ema_dist"] * 0.7:
        score_down += 1

    return score_up / 2, score_down / 2

# ================= STRATEGIES =================
def check_ema(df, mode):
    if stats["ema"] >= MAX_EMA:
        return

    c = df["c"]
    e50 = ema(c, 50)
    e200 = ema(c, 200)
    r = rsi(c)

    price = c.iloc[-1]

    trend_up = price > e50.iloc[-1] and price > e200.iloc[-1]
    trend_dn = price < e50.iloc[-1] and price < e200.iloc[-1]

    # фильтр по режиму января
    if mode == "UP" and not trend_up:
        return
    if mode == "DOWN" and not trend_dn:
        return

    in_zone = 40 < r.iloc[-1] < 60
    touch = abs(price - e50.iloc[-1]) / price < 0.0025

    if in_zone and touch:
        side = "LONG" if trend_up else "SHORT"

        msg = f"""🎯 EMA {side}

Цена: {price}
RSI: {round(r.iloc[-1],1)}

Режим рынка: {mode}
Сегодня EMA: {stats['ema']+1}/{MAX_EMA}"""

        send(msg)
        stats["ema"] += 1

def check_pump(df, mode):
    if stats["pump"] >= MAX_PUMP:
        return

    c = df["c"]
    v = df["v"]

    growth15 = (c.iloc[-1] - c.iloc[-4]) / c.iloc[-4] * 100
    vol_x = v.iloc[-1] / (v.mean() + 0.0001)

    if growth15 > 10 and vol_x > 3 and mode == "DOWN":
        msg = f"""🚨 PUMP SHORT (режим {mode})

Импульс: +{round(growth15,1)}%
Объём: x{round(vol_x,1)}"""

        send(msg)
        stats["pump"] += 1

# ================= MAIN =================
def bot_loop():
    df = klines()
    if df is None:
        send("нет данных для анализа")
        return

    profile = build_impulse_profile(df)
    if not profile:
        send("мало данных за 13–15 янв 2026")
        return

    now = current_impulse(df)
    sim_up, sim_down = similarity(now, profile)

    mode = "NEUTRAL"
    if sim_up > 0.7:
        mode = "UP"
    if sim_down > 0.7:
        mode = "DOWN"

    send(f"Режим рынка: {mode}\nПохожесть UP:{sim_up} DOWN:{sim_down}")

    while True:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if stats["day"] != today:
            stats.update({"day": today, "ema": 0, "pump": 0})

        df = klines()
        if df is not None:
            check_ema(df, mode)
            check_pump(df, mode)

        time.sleep(60)

# ================= START =================
if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    bot_loop()
