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

RISK_EMA = 2.5      # ~0.5% от 500$
RISK_PUMP = 1.5     # ~0.3%

MAX_EMA = 3
MAX_PUMP = 3

REQUEST_DELAY = 1.0

stats = {
    "day": "",
    "ema": 0,
    "pump": 0
}

cached_pairs = []
last_pairs_update = 0

# ================= TELEGRAM =================
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram error:", e)

# ================= SELF PING (ANTI SLEEP) =================
PING_URL = "https://ema-signal-bot-mp9f.onrender.com/"
PING_INTERVAL = 300        # 5 минут
PING_FAIL_ALERT = 3        # после 3 падений — уведомление

def self_ping():
    fails = 0

    # ждём 30 сек чтобы бот точно стартовал
    time.sleep(30)

    while True:
        try:
            r = requests.get(PING_URL, timeout=10)
            if r.status_code == 200:
                print("self-ping ok")
                fails = 0
            else:
                fails += 1
                print("self-ping bad status:", r.status_code)

        except Exception as e:
            fails += 1
            print("self-ping error:", e)

        if fails >= PING_FAIL_ALERT:
            send("⚠ SELF-PING PROBLEM: сервис может засыпать!")
            fails = 0

        time.sleep(PING_INTERVAL)

# ================= LIQUIDITY FILTER (STRICT) =================
def liquidity_ok(pair, size_usd=500):
    try:
        t = requests.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "linear", "symbol": pair},
            timeout=10
        ).json()["result"]["list"][0]

        bid = float(t["bid1Price"])
        ask = float(t["ask1Price"])
        vol24 = float(t["turnover24h"])

        # 1. Объём
        if vol24 < 1_500_000:
            return False, "volume<1.5m"

        mid = (bid + ask) / 2
        spread = (ask - bid) / mid

        # 2. Спред
        if spread > 0.0010:     # 0.10%
            return False, "spread>0.10%"

        # 3. Минутная ликвидность
        k1 = klines(pair, "1", 5)
        if k1 is None:
            return False, "no_1m_data"

        vol1m_usd = k1["v"].iloc[-1] * mid

        if vol1m_usd < 25_000:
            return False, "1m_liq<25k"

        # 4. Оценка проскальзывания
        impact = (size_usd / max(vol1m_usd, 1)) * 0.5
        slippage_est = spread/2 + impact

        if slippage_est > 0.0012:   # 0.12%
            return False, "slip>0.12%"

        return True, "ok"

    except Exception as e:
        return False, "error"

# ================= MARKET DATA =================
def get_all_futures():
    global cached_pairs, last_pairs_update

    if time.time() - last_pairs_update < 600 and cached_pairs:
        return cached_pairs

    try:
        url = "https://api.bybit.com/v5/market/tickers?category=linear"
        r = requests.get(url, timeout=10).json()

        pairs = []
        for x in r["result"]["list"]:
            symbol = x["symbol"]

            if not symbol.endswith("USDT"):
                continue

            pairs.append(symbol)

        cached_pairs = pairs
        last_pairs_update = time.time()

        print("Pairs loaded:", len(pairs))
        return pairs

    except Exception as e:
        print("Pairs error:", e)
        return cached_pairs

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

# ================= INDICATORS =================
def ema(s, p):
    return s.ewm(span=p).mean()

def rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0)
    l = -d.clip(upper=0)
    rs = g.rolling(p).mean() / l.rolling(p).mean()
    return 100 - 100 / (1 + rs)

# ================= EMA STRATEGY =================
def check_ema(pair):
    if stats["ema"] >= MAX_EMA:
        return

    ok, reason = liquidity_ok(pair)
    if not ok:
        print(pair, "EMA filtered:", reason)
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

# ================= PUMP STRATEGY =================
def check_pump(pair):
    if stats["pump"] >= MAX_PUMP:
        return

    ok, reason = liquidity_ok(pair)
    if not ok:
        print(pair, "PUMP filtered:", reason)
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

TP1: {tp1}
TP2: {tp2}

Риск: {RISK_PUMP}$

Сегодня пампов: {stats['pump']+1}/{MAX_PUMP}"""

    send(msg)
    stats["pump"] += 1

# ================= MAIN LOOP =================
def bot_loop():
    send("🟡 BOT STARTED — STRICT LIQ + SELF-PING")

    while True:
        now = datetime.now(UTC)
        today = now.strftime("%Y-%m-%d")

        if stats["day"] != today:
            stats["day"] = today
            stats["ema"] = 0
            stats["pump"] = 0

        pairs = get_all_futures()

        for p in pairs:
            check_ema(p)
            check_pump(p)
            time.sleep(REQUEST_DELAY)

        time.sleep(30)

# ================= RESEARCH MODE =================
def research_all_pairs_top10():
    print("=== RESEARCH MODE: TOP-10 LAST EMA SIGNALS ===")

    pairs = get_all_futures()
    results = []

    for pair in pairs:
        ok, reason = liquidity_ok(pair)
        if not ok:
            continue

        df = klines(pair, "15", 200)
        if df is None:
            continue

        c = df["c"]
        e50 = ema(c, 50)
        e200 = ema(c, 200)
        r = rsi(c)

        for i in range(len(df)):
            price = c.iloc[i]

            if pd.isna(e50.iloc[i]) or pd.isna(e200.iloc[i]):
                continue

            trend_up = price > e50.iloc[i] and price > e200.iloc[i]
            trend_dn = price < e50.iloc[i] and price < e200.iloc[i]

            in_zone = 40 < r.iloc[i] < 60
            touch = abs(price - e50.iloc[i]) / price < 0.0015

            if in_zone and touch and (trend_up or trend_dn):
                ts = df.index[i] if "t" not in df else df["t"].iloc[i]

                results.append({
                    "pair": pair,
                    "side": "LONG" if trend_up else "SHORT",
                    "price": float(price),
                    "rsi": float(r.iloc[i]),
                    "ema50": float(e50.iloc[i]),
                    "ema200": float(e200.iloc[i]),
                    "time": ts
                })

    # сортируем по времени (новые вверху)
    results = results[-10:]

    print("\n===== TOP 10 SIGNALS =====\n")

    for s in results:
        print(
            s["pair"],
            s["side"],
            "price:", round(s["price"], 2),
            "RSI:", round(s["rsi"], 2),
            "EMA50:", round(s["ema50"], 2),
            "EMA200:", round(s["ema200"], 2),
            "time:", s["time"]
        )

    print("\n=== END RESEARCH ===")

# ================= START =================
if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    threading.Thread(target=self_ping, daemon=True).start()
    bot_loop()

