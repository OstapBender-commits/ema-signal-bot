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
                text += f"❌ {s}: no data\n\n"
                continue

            # ===== НОВЫЙ БЛОК ГЛУБИНЫ =====
            bars = len(df)
            first = df["t"].iloc[0]
            last  = df["t"].iloc[-1]

            days = round((last - first).total_seconds() / 86400, 1)
            # ==============================

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

# ===== MAIN =====
def bot_loop():
    send("🟢 BOT START — STAT MODE")

    threading.Thread(target=stats_report, daemon=True).start()

    while True:
        time.sleep(60)

if __name__=="__main__":
    threading.Thread(target=run_server,daemon=True).start()
    def range_check():
    PERIOD_START = "2026-01-13 00:00:00"
    PERIOD_END   = "2026-01-15 23:59:59"

    report = "🔎 RANGE CHECK 13–15 Jan 2026\n\n"

    for symbol in SYMBOLS:
        df = klines(symbol)

        if df is None:
            report += f"❌ {symbol}: API вернул None\n\n"
            continue

        first = df["t"].iloc[0]
        last  = df["t"].iloc[-1]

        part = df[
            (df["t"] >= PERIOD_START) &
            (df["t"] <= PERIOD_END)
        ]

        report += f"""🔹 {symbol}/USDT
Всего баров: {len(df)}
Диапазон в ответе:
  from: {first}
  to:   {last}

В периоде 13–15 янв:
  bars: {len(part)}

"""

        # если есть данные — покажем 3 первые цены
        if len(part) > 0:
            sample = part["c"].head(3).tolist()
            report += f"sample prices: {sample}\n\n"

        time.sleep(1.5)

    send(report)


# ===== ЗАПУСК ТЕСТА =====
if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()

    send("🧪 START RANGE TEST")
    range_check()
