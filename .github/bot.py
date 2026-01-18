import requests, time, os
import pandas as pd
import numpy as np

TOKEN = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

PAIRS = ["BTCUSDT","ETHUSDT","SOLUSDT"]
RISK = 2.5

def send(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def klines(pair):
    url = "https://api.binance.com/api/v3/klines"
    p = {"symbol": pair, "interval":"15m", "limit":120}
    r = requests.get(url, params=p).json()

    df = pd.DataFrame(r)
    df = df.iloc[:,0:6]
    df.columns = ["t","o","h","l","c","v"]
    df["c"] = df["c"].astype(float)
    return df

def ema(s, p):
    return s.ewm(span=p).mean()

def rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0)
    l = -d.clip(upper=0)
    rs = g.rolling(p).mean()/l.rolling(p).mean()
    return 100 - 100/(1+rs)

send("🟡 EMA Signal Bot STARTED")

sent = {}
day_count = 0
last_day = ""

while True:
    now_day = time.strftime("%Y-%m-%d")

    if now_day != last_day:
        day_count = 0
        last_day = now_day

    for p in PAIRS:
        if day_count >= 3:
            continue

        df = klines(p)
        c = df["c"]

        e50 = ema(c,50)
        e200 = ema(c,200)
        r = rsi(c)

        price = c.iloc[-1]

        trend_up = price > e50.iloc[-1] and price > e200.iloc[-1]
        trend_dn = price < e50.iloc[-1] and price < e200.iloc[-1]

        in_zone = 40 < r.iloc[-1] < 60
        touch = abs(price - e50.iloc[-1])/price < 0.0015

        key = p + now_day

        if in_zone and touch and key not in sent:

            pos = round(RISK/0.006,1)

            if trend_up:
                msg = f"""🟢 {p} LONG
Цена: {price}
RSI: {round(r.iloc[-1],1)}

Риск: {RISK}$
Позиция: {pos}$

Проверь:
• выше EMA50/200
• откат к EMA50
• зелёная свеча

Не более 3 сделок в день"""
                send(msg)
                sent[key]=1
                day_count+=1

            elif trend_dn:
                msg = f"""🔴 {p} SHORT
Цена: {price}
RSI: {round(r.iloc[-1],1)}

Риск: {RISK}$
Позиция: {pos}$

Проверь:
• ниже EMA50/200
• откат к EMA50
• красная свеча

Не более 3 сделок в день"""
                send(msg)
                sent[key]=1
                day_count+=1

    time.sleep(30)
