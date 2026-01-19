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

# ===== PRIORITY MODEL =====
PRIORITY = ["BTC", "ETH"]
BASE = ["BNB","SOL","XRP","ADA","DOGE","AVAX","LINK","DOT"]

stats = {"day": "", "main": 0, "alt": 0}

# ===== TELEGRAM =====
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except:
        pass

# ===== DATA =====
def klines(symbol, limit=2000):
    try:
        url = "https://min-api.cryptocompare.com/data/v2/histominute"
        p = {"fsym":symbol,"tsym":"USDT","limit":limit,"aggregate":15}
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

# ===== HELPERS =====
def ema(s,p): return s.ewm(span=p).mean()

def rsi(s,p=14):
    d=s.diff(); g=d.clip(lower=0); l=-d.clip(upper=0)
    rs=g.rolling(p).mean()/l.rolling(p).mean()
    return 100-100/(1+rs)

def base_volatility(df,look=20):
    return float(df["c"].pct_change().abs().rolling(look).mean().iloc[-1])

def adaptive_threshold(df):
    vol=base_volatility(df)
    th=max(0.0015,min(0.0042,vol*0.8))
    return round(th,5)

# ===== EXECUTION =====
def execution_filter(df):
    v=df["v"]
    vol_ok=v.iloc[-1] > v.mean()*0.8

    move=abs(df["c"].pct_change().iloc[-1])
    price_ok=move < 0.0012

    enough_vol=base_volatility(df) > 0.0009
    return vol_ok and price_ok and enough_vol

def trade_levels(df,side):
    c=df["c"]
    high=df["c"].rolling(5).max().iloc[-1]
    low=df["c"].rolling(5).min().iloc[-1]

    price=c.iloc[-1]

    if side=="LONG":
        stop=low*0.999; R=abs(price-stop)
        tp1=price+R; tp2=price+R*1.8
    else:
        stop=high*1.001; R=abs(stop-price)
        tp1=price-R; tp2=price-R*1.8

    return round(stop,5),round(tp1,5),round(tp2,5)

# =====================================================
#            EMA CLASSIC
# =====================================================
def check_ema(symbol, df):
    is_main = symbol in PRIORITY

    if is_main and stats["main"]>=3: return
    if not is_main and stats["alt"]>=2: return

    c=df["c"]; price=c.iloc[-1]

    e50=ema(c,50); e200=ema(c,200)
    r=rsi(c)

    th=adaptive_threshold(df)

    dist=abs(price-e50.iloc[-1])/price
    touch=dist < th
    rsi_ok=40<r.iloc[-1]<60

    trend_up=price>e50.iloc[-1] and price>e200.iloc[-1]
    trend_dn=price<e50.iloc[-1] and price<e200.iloc[-1]

    if not (touch and rsi_ok and (trend_up or trend_dn)):
        return

    side="LONG" if trend_up else "SHORT"

    if not execution_filter(df):
        return

    stop,tp1,tp2=trade_levels(df,side)
    RR=round(abs(tp1-price)/abs(price-stop),2)

    if is_main: stats["main"]+=1
    else: stats["alt"]+=1

    send(f"""🎯 EMA {side} — {symbol}/USDT — MARKET

Price: {price}

STOP: {stop}
TP1: {tp1}
TP2: {tp2}

RR: 1:{RR}

dist={round(dist*100,3)}% < {round(th*100,3)}%
RSI={round(r.iloc[-1],1)}""")

# =====================================================
#        PUMP → DUMP DETECTOR
# =====================================================
watchlist = {}

def check_pump_dump(symbol, df):
    c=df["c"]; v=df["v"]
    price=c.iloc[-1]

    # --- DETECT PUMP ---
    g15=(c.iloc[-1]-c.iloc[-4])/c.iloc[-4]*100
    g60=(c.iloc[-1]-c.iloc[-13])/c.iloc[-13]*100
    vol_x=v.iloc[-1]/(v.mean()+1e-9)

    if symbol not in watchlist:
        if g15>8 and g60>12 and vol_x>3:
            watchlist[symbol]={
                "peak":price,
                "stage":"pumped",
                "time":time.time()
            }
        return

    w=watchlist[symbol]

    # обновляем пик
    if price>w["peak"]:
        w["peak"]=price

    # --- WAIT FOR CRACK ---
    r=rsi(c).iloc[-1]

    drop=(w["peak"]-price)/w["peak"]*100
    red=c.iloc[-1]<c.iloc[-2]

    if w["stage"]=="pumped":
        # условия слома
        if drop>3 and r<68 and red:
            stop=round(w["peak"]*1.02,5)
            tp1=round(price*0.96,5)
            tp2=round(price*0.93,5)

            send(f"""🚨 PUMP-DUMP SHORT — {symbol}/USDT

Price: {price}
Peak: {round(w['peak'],5)}

STOP: {stop}
TP1: {tp1}
TP2: {tp2}

drop: {round(drop,2)}%
RSI: {round(r,1)}""")

            del watchlist[symbol]

    # забываем старые истории
    if time.time()-w["time"]>3600*6:
        del watchlist[symbol]

# =====================================================
#            MAIN LOOP
# =====================================================
def bot_loop():
    send("🟢 BOT START — PRIORITY + PUMP-DUMP")

    warned=False

    while True:
        today=datetime.now(UTC).strftime("%Y-%m-%d")
        if stats["day"]!=today:
            stats.update({"day":today,"main":0,"alt":0})

        symbols = PRIORITY + BASE

        for s in symbols:
            df=klines(s)
            if df is None: 
                continue

            if not warned:
                send("ℹ профиль не найден — режим NEUTRAL")
                warned=True

            check_ema(s,df)
            check_pump_dump(s,df)

            time.sleep(2)

        time.sleep(60)

if __name__=="__main__":
    threading.Thread(target=run_server,daemon=True).start()
    bot_loop()
