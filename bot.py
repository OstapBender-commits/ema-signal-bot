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

def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except:
        pass


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


def coin_metrics(df):
    c = df["c"]
    v = df["v"]

    g15 = c.pct_change(4) * 100
    g60 = c.pct_change(13) * 100

    peak = c.cummax()
    draw = (peak - c) / peak * 100

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


def stats_report():
    while True:
        text = "📊 5H MARKET REPORT\n\n"

        for s in SYMBOLS:
            df = klines(s)

            if df is None:
                text += f"❌ {s}: no data\n\n"
                continue

            bars = len(df)
            first = df["t"].iloc[0]
            last  = df["t"].iloc[-1]

            days = round((last - first).total_seconds() / 86400, 1)

            m = coin_metrics(df)

            text += f"""🔹 {s}/USDT

🕐 DEPTH INFO
bars: {bars}
from: {first}
to:   {last}
coverage: ~{days} days

15m avg: {m['g15_mean']}%
15m p90: {m['g15_p90']}%

1h avg: {m['g60_mean']}%
1h p90: {m['g60_p90']}%

max 1h: {m['max_pump']}%
vol x: {m['vol_x']}

typ dd: {m['typical_dd']}%
RSI peak: {m['rsi_peak']}

"""

            time.sleep(1.2)

        text += f"Time: {datetime.now(UTC)}"
        send(text)

        time.sleep(5 * 3600)


def bot_loop():
    send("🟢 BOT START — DEPTH MONITOR")

    threading.Thread(target=stats_report, daemon=True).start()

    while True:
        time.sleep(60)


if __name__=="__main__":
    threading.Thread(target=run_server,daemon=True).start()
    bot_loop()
