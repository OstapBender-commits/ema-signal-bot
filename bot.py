import requests
import time
import os
import pandas as pd
import numpy as np
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

SYMBOLS = [
    "BTC","ETH","BNB","SOL","XRP",
    "ADA","DOGE","AVAX","LINK","DOT"
]

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

# ===== METRICS =====
def coin_metrics(df):
    c = df["c"]
    v = df["v"]

    # импульсы
    g15 = c.pct_change(4) * 100
    g60 = c.pct_change(13) * 100

    # откаты после локальных пиков
    peak = c.cummax()
    draw = (peak - c) / peak * 100

    # RSI
    d = c.diff()
    g = d.clip(lower=0)
    l = -d.clip(upper=0)
    rs = g.rolling(14).mean() / l.rolling(14).mean()
    rsi = 100 - 100/(1+rs)

    return {
        "g15_mean": round(g15.mean(),2),
        "g15_p90": round(np.percentile(g15.dropna(),90),2),

        "g60_mean": round(g60.mean(),2),
        "g60_p90": round(np.percentile(g60.dropna(),90),2),

        "max_pump": round(g60.max(),2),

        "vol_x": round((v.iloc[-1]/(v.mean()+1e-9)),2),

        "typical_dd": round(draw.mean(),2),

        "rsi_peak": round(rsi.tail(50).max(),1)
    }

# ===== 5-HOUR REPORT =====
def stats_report():
    while True:
        text = "📊 5H MARKET REPORT\n\n"

        for s in SYMBOLS:
            df = klines(s)
            if df is None:
                text += f"{s}: no data\n\n"
                continue

            m = coin_metrics(df)

            text += f"""🔹 {s}/USDT
15m avg: {m['g15_mean']}%
15m p90: {m['g15_p90']}%

1h avg: {m['g60_mean']}%
1h p90: {m['g60_p90']}%

max 1h: {m['max_pump']}%
vol x: {m['vol_x']}

typ dd: {m['typical_dd']}%
RSI peak: {m['rsi_peak']}

"""

        text += f"Time: {datetime.now(UTC)}"
        send(text)

        # ---- каждые 5 часов ----
        time.sleep(5 * 3600)

# ===== MAIN =====
def bot_loop():
    send("🟢 BOT START — STAT MODE")

    threading.Thread(target=stats_report, daemon=True).start()

    while True:
        time.sleep(60)

if __name__=="__main__":
    threading.Thread(target=run_server,daemon=True).start()
    bot_loop()
