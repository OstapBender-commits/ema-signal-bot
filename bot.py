import requests
import time
import os
import pandas as pd
import numpy as np
from datetime import datetime, UTC
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# ======================================================
# ================== KEEP ALIVE SERVER =================
# ======================================================

PORT = int(os.environ.get("PORT", 10000))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

def run_server():
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

def self_ping():
    url = f"http://127.0.0.1:{PORT}"
    while True:
        try:
            requests.get(url, timeout=5)
        except:
            pass
        time.sleep(120)

# ======================================================
# ===================== TELEGRAM =======================
# ======================================================

TOKEN = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

if not TOKEN or not CHAT_ID:
    raise Exception("TOKEN / CHAT_ID not set")

def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except:
        pass

def heartbeat():
    while True:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendChatAction",
                data={"chat_id": CHAT_ID, "action": "typing"},
                timeout=5
            )
        except:
            pass
        time.sleep(180)

# ======================================================
# ===================== SETTINGS =======================
# ======================================================

SYMBOLS = [
    "BTC","ETH","BNB","SOL","XRP",
    "ADA","DOGE","AVAX","LINK","DOT"
]

DEPOSIT = 500
RISK_USD = 10

LAST_ALERT = {}
STATS = {"signals":0,"long":0,"short":0}

os.makedirs("data", exist_ok=True)

# ======================================================
# ===================== DATA ===========================
# ======================================================

def klines(symbol, limit=300):
    try:
        url = "https://min-api.cryptocompare.com/data/v2/histominute"
        params = {
            "fsym": symbol,
            "tsym": "USDT",
            "limit": limit,
            "aggregate": 15
        }
        r = requests.get(url, params=params, timeout=10).json()
        if r.get("Response") != "Success":
            return None

        df = pd.DataFrame(r["Data"]["Data"])
        df["t"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df[["t","close","volumeto"]].rename(
            columns={"close":"c","volumeto":"v"}
        )

        log_quotes(symbol, df)

        return df
    except:
        return None

def log_quotes(symbol, df):
    fname = f"data/{symbol}_quotes.csv"
    df.tail(1).to_csv(
        fname,
        mode="a",
        header=not os.path.exists(fname),
        index=False
    )

# ======================================================
# ===================== PATTERN ========================
# ======================================================

def detect_pattern(df):
    if len(df) < 6:
        return None

    c = df["c"]
    v = df["v"]

    growth = (c.iloc[-1] - c.iloc[-3]) / c.iloc[-3] * 100
    volx = v.iloc[-1] / (v.iloc[-20:].mean() + 1e-9)
    trend = c.iloc[-3] < c.iloc[-2] < c.iloc[-1]

    score = 0
    if trend: score += 40
    if growth >= 0.40: score += 30
    if growth >= 0.65: score += 10
    if volx >= 1.8: score += 30
    if volx >= 2.3: score += 10

    # ===== LONG =====
    if score >= 80:
        sl_pct = 0.22
        pos_size = RISK_USD / (sl_pct / 100)

        return {
            "type":"LONG",
            "score":score,
            "growth":round(growth,2),
            "volx":round(volx,2),
            "size":round(pos_size,1)
        }

    # ===== SHORT =====
    g60 = (c.iloc[-1] - c.iloc[-5]) / c.iloc[-5] * 100
    if g60 >= 1.2 and volx < 0.8:
        sl_pct = 0.25
        pos_size = RISK_USD / (sl_pct / 100)

        return {
            "type":"SHORT",
            "score":score,
            "growth":round(g60,2),
            "volx":round(volx,2),
            "size":round(pos_size,1)
        }

    return None

# ======================================================
# ===================== SIGNAL SCAN ====================
# ======================================================

def scan_signals():
    while True:
        for s in SYMBOLS:
            df = klines(s)
            if df is None:
                continue

            sig = detect_pattern(df)
            if not sig:
                continue

            last = LAST_ALERT.get(s,0)
            if time.time() - last < 3600:
                continue

            LAST_ALERT[s] = time.time()
            STATS["signals"] += 1

            if sig["type"]=="LONG":
                STATS["long"] += 1
                msg = f"""🟢 STRONG LONG {s}/USDT

Score: {sig['score']}%
Рост: {sig['growth']}%
Объём x: {sig['volx']}

💼 Позиция:
Объём: {sig['size']} USDT
Риск: 10$

SL −0.22%
TP1 +0.35%
TP2 +0.60%
"""
            else:
                STATS["short"] += 1
                msg = f"""🔴 STRONG SHORT {s}/USDT

Памп: +{sig['growth']}%
Объём x: {sig['volx']}

💼 Позиция:
Объём: {sig['size']} USDT
Риск: 10$

SL +0.25%
TP −0.5…−0.8%
"""

            send(msg)

        time.sleep(300)

# ======================================================
# ===================== DAILY REPORT ===================
# ======================================================

def stats_report():
    while True:
        text = "📊 DAILY MARKET REPORT\n\n"

        for s in SYMBOLS:
            df = klines(s, 300)
            if df is None:
                continue

            c = df["c"]
            g60 = c.pct_change(13)*100

            text += f"""🔹 {s}
Max 1h: {round(g60.max(),2)}%
"""

            time.sleep(1)

        text += f"""
Signals: {STATS['signals']}
Long: {STATS['long']}
Short: {STATS['short']}
Time: {datetime.now(UTC)}
"""

        send(text)

        for _ in range(1440):
            time.sleep(60)

# ======================================================
# ===================== MAIN ===========================
# ======================================================

def bot_loop():
    send("🟢 BOT START — STRONG MOVE ENGINE")

    threading.Thread(target=scan_signals, daemon=True).start()
    threading.Thread(target=stats_report, daemon=True).start()
    threading.Thread(target=heartbeat, daemon=True).start()
    threading.Thread(target=self_ping, daemon=True).start()

    while True:
        time.sleep(60)

if __name__=="__main__":
    threading.Thread(target=run_server, daemon=True).start()
    bot_loop()
