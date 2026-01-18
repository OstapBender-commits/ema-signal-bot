import requests
import time
import os
import pandas as pd
from datetime import datetime, UTC
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("PORT", 10000))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

def run_server():
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

TOKEN = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# ===== AUDIT STORAGE =====
audit = {
    "ticks": 0,
    "touch_true": 0,
    "rsi_true": 0,
    "trend_true": 0,
    "signals_sent": 0,
    "rejected_by_mode": 0,
}

# ===== TELEGRAM =====
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except:
        pass

# ===== DATA =====
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

# ===== INDICATORS =====
def ema(s,p): return s.ewm(span=p).mean()

def rsi(s,p=14):
    d=s.diff(); g=d.clip(lower=0); l=-d.clip(upper=0)
    rs=g.rolling(p).mean()/l.rolling(p).mean()
    return 100-100/(1+rs)

def base_volatility(df,look=20):
    return float(df["c"].pct_change().abs().rolling(look).mean().iloc[-1])

def adaptive_threshold(df,mode):
    vol=base_volatility(df)
    k=0.8 if mode=="NEUTRAL" else (0.75 if mode=="UP" else 0.9)
    th=max(0.0015,min(0.0042,vol*k))
    return round(th,5)

# ===== PROFILE =====
def build_profile(df):
    mask=(df["t"]>="2026-01-13 17:30")&(df["t"]<="2026-01-14 02:00")
    d=df[mask]
    if len(d)<20: return None

    return {
        "up":{"hour":(d["c"].pct_change(4).max())*100},
        "down":{"hour":abs((d["c"].pct_change(4).min())*100)}
    }

def current_impulse(df):
    d=df.tail(20)
    return {
        "hour_gain":(d["c"].pct_change(4).max())*100,
        "hour_drop":abs((d["c"].pct_change(4).min())*100)
    }

def similarity(now,profile):
    su=sd=0
    if now["hour_gain"]>=profile["up"]["hour"]*0.7: su+=1
    if now["hour_drop"]>=profile["down"]["hour"]*0.7: sd+=1
    return su,sd

# ===== AUDIT SNAPSHOT =====
def debug_snapshot(df,mode,th,checks):
    msg=f"""
🧪 SNAPSHOT #{audit['ticks']}

Prices: {df['c'].tail(3).tolist()}

Vol base: {round(base_volatility(df),6)}
Threshold: {th}

RSI: {round(rsi(df['c']).iloc[-1],2)}
EMA50: {round(ema(df['c'],50).iloc[-1],2)}
EMA200: {round(ema(df['c'],200).iloc[-1],2)}

Mode: {mode}

Conditions:
touch={checks['touch']}
rsi={checks['rsi']}
trend={checks['trend']}
"""
    send(msg)

# ===== STRATEGY WITH AUDIT =====
def check_ema(df,mode):
    audit["ticks"]+=1

    c=df["c"]
    e50=ema(c,50); e200=ema(c,200); r=rsi(c)

    price=c.iloc[-1]
    th=adaptive_threshold(df,mode)

    touch=abs(price-e50.iloc[-1])/price < th
    rsi_ok=40<r.iloc[-1]<60

    trend_up=price>e50.iloc[-1] and price>e200.iloc[-1]
    trend_dn=price<e50.iloc[-1] and price<e200.iloc[-1]
    trend=trend_up or trend_dn

    # --- audit counters ---
    if touch: audit["touch_true"]+=1
    if rsi_ok: audit["rsi_true"]+=1
    if trend: audit["trend_true"]+=1

    checks={"touch":touch,"rsi":rsi_ok,"trend":trend}

    debug_snapshot(df,mode,th,checks)

    # --- decision ---
    if not (touch and rsi_ok and trend):
        return

    side="LONG" if trend_up else "SHORT"

    # filter by mode
    if mode=="UP" and side!="LONG":
        audit["rejected_by_mode"]+=1
        return

    if mode=="DOWN" and side!="SHORT":
        audit["rejected_by_mode"]+=1
        return

    audit["signals_sent"]+=1

    send(f"""🎯 SIGNAL {side}

price: {price}
threshold: {th}
mode: {mode}""")

# ===== HOURLY AUDIT REPORT =====
def audit_report():
    while True:
        time.sleep(3600)

        msg=f"""
📊 AUDIT REPORT

ticks: {audit['ticks']}

touch true: {audit['touch_true']}
rsi true: {audit['rsi_true']}
trend true: {audit['trend_true']}

signals sent: {audit['signals_sent']}
rejected by mode: {audit['rejected_by_mode']}
"""
        send(msg)

# ===== MAIN =====
def bot_loop():
    send("🟢 BOT START — AUDIT MODE")

    threading.Thread(target=audit_report,daemon=True).start()

    warned=False

    while True:
        df=klines()
        if df is None:
            time.sleep(60)
            continue

        profile=build_profile(df)

        if not profile:
            if not warned:
                send("ℹ профиль не найден — режим NEUTRAL")
                warned=True
            mode="NEUTRAL"
        else:
            now=current_impulse(df)
            su,sd=similarity(now,profile)
            mode="UP" if su>sd else "DOWN" if sd>su else "NEUTRAL"

        check_ema(df,mode)

        time.sleep(60)

if __name__=="__main__":
    threading.Thread(target=run_server,daemon=True).start()
    bot_loop()
