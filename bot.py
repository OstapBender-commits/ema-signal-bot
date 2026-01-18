import requests
import time
import os
import pandas as pd
from datetime import datetime, UTC
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# =============== WEB SERVER ===============
PORT = int(os.environ.get("PORT", 10000))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

def run_server():
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

# =============== SETTINGS ===============
TOKEN = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

MAX_EMA = 3

stats = {"day": "", "ema": 0}

# =============== TELEGRAM ===============
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except:
        pass

# =============== DATA (CryptoCompare) ===============
def klines(limit=2000):
    try:
        url = "https://min-api.cryptocompare.com/data/v2/histominute"
        p = {"fsym":"BTC","tsym":"USDT","limit":limit,"aggregate":15}
        r = requests.get(url, params=p, timeout=10).json()

        if r.get("Response")!="Success":
            return None

        df=pd.DataFrame(r["Data"]["Data"])
        df["t"]=pd.to_datetime(df["time"],unit="s",utc=True)

        return df[["t","close","volumeto"]].rename(
            columns={"close":"c","volumeto":"v"}
        )
    except:
        return None

# =============== INDICATORS ===============
def ema(s,p): 
    return s.ewm(span=p).mean()

def rsi(s,p=14):
    d=s.diff()
    g=d.clip(lower=0)
    l=-d.clip(upper=0)
    rs=g.rolling(p).mean()/l.rolling(p).mean()
    return 100-100/(1+rs)

# =============== ADAPTIVE THRESHOLD ===============
def base_volatility(df,look=20):
    return float(df["c"].pct_change().abs().rolling(look).mean().iloc[-1])

def adaptive_threshold(df,mode):
    vol=base_volatility(df)
    k=0.8 if mode=="NEUTRAL" else (0.75 if mode=="UP" else 0.9)
    th=max(0.0015,min(0.0042,vol*k))
    return round(th,5)

# =============== EXECUTION LOGIC ===============

def execution_filter(df):
    # 1) объём не слишком низкий
    v = df["v"]
    vol_ok = v.iloc[-1] > v.mean()*0.8

    # 2) цена не убежала от момента сигнала
    move = abs(df["c"].pct_change().iloc[-1])
    price_ok = move < 0.0012   # 0.12%

    return vol_ok and price_ok

def trade_levels(df, side):
    c = df["c"]

    # экстремумы последних 5 свечей
    high = df["c"].rolling(5).max().iloc[-1]
    low  = df["c"].rolling(5).min().iloc[-1]

    price = c.iloc[-1]

    if side == "LONG":
        stop = low * 0.999          # -0.1% буфер
        R = abs(price - stop)
        tp1 = price + R
        tp2 = price + R * 1.8

    else:
        stop = high * 1.001         # +0.1% буфер
        R = abs(stop - price)
        tp1 = price - R
        tp2 = price - R * 1.8

    return round(stop,2), round(tp1,2), round(tp2,2)

# =============== STRATEGY ===============

def check_ema(df,mode):
    if stats["ema"] >= MAX_EMA:
        return

    c=df["c"]
    e50=ema(c,50)
    e200=ema(c,200)
    r=rsi(c)

    price=c.iloc[-1]

    trend_up=price>e50.iloc[-1] and price>e200.iloc[-1]
    trend_dn=price<e50.iloc[-1] and price<e200.iloc[-1]

    if mode=="UP" and not trend_up: 
        return
    if mode=="DOWN" and not trend_dn: 
        return

    th=adaptive_threshold(df,mode)

    touch=abs(price-e50.iloc[-1])/price < th
    rsi_ok=40<r.iloc[-1]<60

    if not (touch and rsi_ok):
        return

    side="LONG" if trend_up else "SHORT"

    # ---- защита MARKET входа ----
    if not execution_filter(df):
        send("⛔ Сетап отклонён: плохой момент входа (объём/уход цены)")
        return

    stop,tp1,tp2 = trade_levels(df,side)

    RR = round(abs(tp1-price)/abs(price-stop),2)

    send(f"""🎯 EMA {side} — MARKET

Цена входа: {price}

STOP: {stop}
TP1: {tp1}
TP2: {tp2}

RR: 1 : {RR}

Порог: {round(th*100,3)}%
RSI: {round(r.iloc[-1],1)}

Сегодня: {stats['ema']+1}/{MAX_EMA}""")

    stats["ema"]+=1

# =============== MAIN ===============
def bot_loop():
    send("🟢 BOT START — MARKET VERSION")

    warned=False

    while True:
        df=klines()
        if df is None:
            time.sleep(60)
            continue

        # без январского профиля — работаем адаптивно
        if not warned:
            send("ℹ Профиль янв не найден — работаем адаптивно")
            warned=True

        mode="NEUTRAL"

        today=datetime.now(UTC).strftime("%Y-%m-%d")
        if stats["day"]!=today:
            stats.update({"day":today,"ema":0})

        check_ema(df,mode)

        time.sleep(60)

# =============== START ===============
if __name__=="__main__":
    threading.Thread(target=run_server,daemon=True).start()
    bot_loop()
