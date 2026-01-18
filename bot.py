import requests
import time
import os
import pandas as pd
import numpy as np
from datetime import datetime

TOKEN = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
RISK = 2.5
MAX_PER_DAY = 3
REQUEST_DELAY = 1.2

stats = {
    "day": "",
    "count": 0,
    "log": []
}

# ---------- Telegram ----------
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram send error:", e)

# ---------- Bybit candles ----------
def klines(pair):
    # Bybit требует формат BTCUSDT -> BTCUSDT (ок, совпадает)
    url = "https://api.bybit.com/v5/market/kline"

    params = {
        "category": "linear",
        "symbol": pair,
        "interval": "15",
        "limit": 120
    }

    try:
        r = requests.get(url, params=params, timeout=10).json()

        if r.get("retCode") != 0:
            print("Bybit error:", r)
            time.sleep(5)
            return None

        rows = r["result"]["list"]

        # Bybit отдаёт в обратном порядке → разворачиваем
        rows = rows[::-1]

        closes = [float(x[4]) for x in rows]

        df = pd.DataFrame({"c": closes})

        return df

    except Exception as e:
        print("Klines exception:", e)
        time.sleep(5)
        return None

# ---------- Индикаторы ----------
def ema(s, p):
    return s.ewm(span=p).mean()

def rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0)
    l = -d.clip(upper=0)
    rs = g.rolling(p).mean() / l.rolling(p).mean()
    return 100 - 100 / (1 + rs)

# ---------- Уровни ----------
def calc_levels(price, side):
    if side == "LONG":
        stop = price * 0.994
        tp1 = price * 1.012
        tp2 = price * 1.024
    else:
        stop = price * 1.006
        tp1 = price * 0.988
        tp2 = price * 0.976

    return round(stop, 2), round(tp1, 2), round(tp2, 2)

# ---------- Отчёт ----------
def daily_report():
    if not stats["log"]:
        return "📊 За вчера сигналов не было."

    text = "📊 Отчёт за день\n\n"
    for l in stats["log"]:
        text += f"{l}\n"

    text += f"\nВсего сигналов: {stats['count']}"
    return text

# ---------- СТАРТ ----------
send("🟡 EMA Signal Bot STARTED (Bybit data)")

# ---------- ОСНОВНОЙ ЦИКЛ ----------
while True:
    now = datetime.utcnow()
    today = now.strftime("%Y-%m-%d")

    if stats["day"] != today:
        if stats["day"] != "":
            send(daily_report())

        stats = {"day": today, "count": 0, "log": []}

    for p in PAIRS:

        if stats["count"] >= MAX_PER_DAY:
            continue

        df = klines(p)
        if df is None:
            continue

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

            side = None
            if trend_up:
                side = "LONG"
            elif trend_dn:
                side = "SHORT"

            if not side:
                continue

            stop, tp1, tp2 = calc_levels(price, side)
            pos = round(RISK / 0.006, 1)

            msg = f"""{'🟢' if side=='LONG' else '🔴'} {p} {side}
Цена: {price}
RSI: {round(r.iloc[-1],1)}

Риск: {RISK}$
Позиция: {pos}$

Рекомендации:
Стоп: {stop}
Тейк1: {tp1}
Тейк2: {tp2}

Сегодня сигналов: {stats['count']+1}/{MAX_PER_DAY}

Проверь вручную:
• EMA50/200
• откат к EMA50
• цвет свечи"""

            send(msg)

            stats["count"] += 1
            stats["log"].append(f"{p} {side} @ {price}")

            if stats["count"] >= MAX_PER_DAY:
                send("⛔ Дневной лимит 3 сигнала достигнут. Ждём завтра.")

        time.sleep(REQUEST_DELAY)

    time.sleep(30)
