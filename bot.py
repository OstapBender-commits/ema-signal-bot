import requests
import time
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, UTC
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# ================= WEB SERVER (Render keep-alive) =================
PORT = int(os.environ.get("PORT", 10000))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

def run_server():
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


# ================= SETTINGS =================
TOKEN = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

SYMBOLS = [
    "BTC","ETH","BNB","SOL","XRP",
    "ADA","DOGE","AVAX","LINK","DOT"
]

DB_FILE = "db.json"


# ================= TELEGRAM =================
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("tg error:", e)


# ================= LOCAL STORAGE =================
def load_db():
    if not os.path.exists(DB_FILE):
        return {}

    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f)


db = load_db()


# ================= SOURCE (CryptoCompare) =================
def fetch_latest(symbol):
    """
    Берём последние 100 свечей 15m
    """
    try:
        url = "https://min-api.cryptocompare.com/data/v2/histominute"

        p = {
            "fsym": symbol,
            "tsym": "USDT",
            "limit": 100,
            "aggregate": 15
        }

        r = requests.get(url, params=p, timeout=10).json()

        if r.get("Response") != "Success":
            return None

        rows = r["Data"]["Data"]

        out = []
        for x in rows:
            out.append({
                "t": int(x["time"]),
                "c": float(x["close"]),
                "v": float(x["volumeto"])
            })

        return out

    except Exception as e:
        print("fetch error", symbol, e)
        return None


# ================= MERGE TO LOCAL DB =================
def update_symbol(symbol):
    rows = fetch_latest(symbol)
    if not rows:
        return

    if symbol not in db:
        db[symbol] = {}

    for r in rows:
        db[symbol][str(r["t"])] = {
            "c": r["c"],
            "v": r["v"]
        }

    save_db(db)


# ================= METRICS FROM LOCAL DATA =================
def df_from_local(symbol):
    if symbol not in db:
        return None

    items = []
    for ts, v in db[symbol].items():
        items.append({
            "t": pd.to_datetime(int(ts), unit="s", utc=True),
            "c": v["c"],
            "v": v["v"]
        })

    df = pd.DataFrame(items).sort_values("t")
    return df


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
        "bars": len(df),

        "g15_mean": round(g15.mean(),2),
        "g15_p90": round(np.percentile(g15.dropna(),90),2),

        "g60_mean": round(g60.mean(),2),
        "g60_p90": round(np.percentile(g60.dropna(),90),2),

        "max_pump": round(g60.max(),2),

        "vol_x": round((v.iloc[-1]/(v.mean()+1e-9)),2),

        "typical_dd": round(draw.mean(),2),

        "rsi_peak": round(rsi.tail(50).max(),1)
    }


# ================= COLLECTOR =================
def collector_loop():
    send("🟢 COLLECTOR STARTED — LOCAL DB MODE")

    while True:
        for s in SYMBOLS:
            update_symbol(s)
            time.sleep(1.2)

        time.sleep(15 * 60)   # каждые 15 минут


# ================= REPORT =================
def stats_report():
    while True:
        text = "📊 5H LOCAL REPORT\n\n"

        for s in SYMBOLS:
            df = df_from_local(s)

            if df is None or len(df) < 20:
                text += f"❌ {s}: not enough local data\n\n"
                continue

            m = coin_metrics(df)

            first = df["t"].iloc[0]
            last  = df["t"].iloc[-1]

            days = round((last - first).total_seconds()/86400, 2)

            text += f"""🔹 {s}/USDT

🕐 LOCAL DB
bars: {m['bars']}
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

        text += f"Time: {datetime.now(UTC)}"
        send(text)

        time.sleep(5 * 3600)


# ================= START =================
def bot_loop():
    threading.Thread(target=collector_loop, daemon=True).start()
    threading.Thread(target=stats_report, daemon=True).start()

    while True:
        time.sleep(60)


if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    bot_loop()
