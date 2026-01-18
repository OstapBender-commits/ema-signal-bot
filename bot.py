import requests
import time
import os
import pandas as pd
import numpy as np
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
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()

# =============== SETTINGS ===============
TOKEN = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

MAX_EMA = 3
MAX_PUMP = 3

stats = {"day": "", "ema": 0, "pump": 0}

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
        params = {"fsym": "BTC", "tsym": "USDT", "limit": limit, "aggregate": 15}

        r = requests.get(url, params=params, timeout=10).json()
        if r.get("Response") != "Success":
            return None

        df = pd.DataFrame(r["Data"]["Data"])
        df["t"] = pd.to_datetime(df["time"], unit="s", utc=True)

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

def base_volatility(df, look=20):
    """Базовая волатильность диапазона"""
    vol = df["c"].pct_change().abs().rolling(look).mean().iloc[-1]
    return float(vol)

def regime_coeff(mode, hour):
    """Разные коэффициенты под режим и время"""
    # ночь менее ликвидна
    night = 1.15 if hour in range(22,24) or hour in range(0,6) else 1.0

    if mode == "UP":
        return 0.75 * night
    if mode == "DOWN":
        return 0.90 * night

    return 0.80 * night

def calibrate_3days(df):
    """Автоподбор по последним 3 дням"""
    last = df[df["t"] > df["t"].max() - pd.Timedelta(days=3)]
    if len(last) < 50:
        return 1.0

    vols = last["c"].pct_change().abs()
    q = vols.quantile(0.75)   # верхний квартиль
    med = vols.median()

    # если рынок стал заметно волатильнее
    if q > med * 1.4:
        return 1.1
    if q < med * 0.7:
        return 0.9

    return 1.0

def adaptive_threshold(df, mode):
    vol = base_volatility(df)

    hour = datetime.now(UTC).hour
    k = regime_coeff(mode, hour)

    cal = calibrate_3days(df)

    th = vol * k * cal

    # разумные границы
    th = max(0.0015, min(0.0042, th))

    return round(th, 5)

# =============== JAN PROFILE (optional) ===============
def build_profile(df):
    mask = (df["t"] >= "2026-01-13 17:30") & \
           (df["t"] <= "2026-01-14 02:00")

    d = df[mask]
    if len(d) < 20:
        return None

    hour_up = (d["c"].pct_change(4).max())*100
    hour_down = abs((d["c"].pct_change(4).min())*100)

    e50 = ema(df["c"],50)
    dist = (abs(d["c"]-e50)/d["c"]).mean()*100

    return {
        "up":{"hour":hour_up,"ema_dist":dist},
        "down":{"hour":hour_down,"ema_dist":dist}
    }

def current_impulse(df):
    d=df.tail(20)
    return {
        "hour_gain":(d["c"].pct_change(4).max())*100,
        "hour_drop":abs((d["c"].pct_change(4).min())*100),
        "ema_dist":(abs(d["c"]-ema(df["c"],50))/d["c"]).mean()*100
    }

def similarity(now, profile):
    su=sd=0
    if now["hour_gain"]>=profile["up"]["hour"]*0.7: su+=1
    if now["ema_dist"]>=profile["up"]["ema_dist"]*0.7: su+=1

    if now["hour_drop"]>=profile["down"]["hour"]*0.7: sd+=1
    if now["ema_dist"]>=profile["down"]["ema_dist"]*0.7: sd+=1

    return su/2, sd/2

# =============== STRATEGIES ===============
def check_ema(df, mode):
    if stats["ema"]>=MAX_EMA:
        return

    c=df["c"]
    e50=ema(c,50)
    e200=ema(c,200)
    r=rsi(c)

    price=c.iloc[-1]

    trend_up=price>e50.iloc[-1] and price>e200.iloc[-1]
    trend_dn=price<e50.iloc[-1] and price<e200.iloc[-1]

    if mode=="UP" and not trend_up: return
    if mode=="DOWN" and not trend_dn: return

    th=adaptive_threshold(df,mode)

    touch=abs(price-e50.iloc[-1])/price < th
    in_zone=40<r.iloc[-1]<60

    if touch and in_zone:
        side="LONG" if trend_up else "SHORT"

        send(f"""🎯 EMA {side}

Цена: {price}
RSI: {round(r.iloc[-1],1)}

Порог: {round(th*100,3)}%
Режим: {mode}

Сегодня: {stats['ema']+1}/{MAX_EMA}""")

        stats["ema"]+=1

def check_pump(df, mode):
    if stats["pump"]>=MAX_PUMP:
        return

    c=df["c"]; v=df["v"]

    growth=(c.iloc[-1]-c.iloc[-4])/c.iloc[-4]*100
    vol_x=v.iloc[-1]/(v.mean()+1e-9)

    # для шортов только в режиме DOWN
    if growth>10 and vol_x>3 and mode=="DOWN":
        send(f"""🚨 PUMP SHORT

Импульс: +{round(growth,1)}%
Объём: x{round(vol_x,1)}
Режим: {mode}""")

        stats["pump"]+=1

# =============== MAIN LOOP ===============
def bot_loop():
    send("🟢 BOT START (adaptive mode)")

    warned=False

    while True:
        df=klines()
        if df is None:
            time.sleep(60)
            continue

        profile=build_profile(df)

        if not profile:
            if not warned:
                send("ℹ Профиль янв не найден — работаем адаптивно")
                warned=True
            mode="NEUTRAL"
        else:
            now=current_impulse(df)
            su,sd=similarity(now,profile)

            mode="NEUTRAL"
            if su>0.7: mode="UP"
            if sd>0.7: mode="DOWN"

        today=datetime.now(UTC).strftime("%Y-%m-%d")
        if stats["day"]!=today:
            stats.update({"day":today,"ema":0,"pump":0})

        check_ema(df,mode)
        check_pump(df,mode)

        time.sleep(60)

# =============== START ===============
if __name__=="__main__":
    threading.Thread(target=run_server,daemon=True).start()
    bot_loop()
