import requests
import time
import os
import pandas as pd
import numpy as np
from datetime import datetime, UTC
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("PORT", 10000))

# ===== KEEP ALIVE =====
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

def run_server():
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


# ===== НАСТРОЙКИ =====
TOKEN = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

SYMBOLS = [
    "BTC","ETH","BNB","SOL","XRP",
    "ADA","DOGE","AVAX","LINK","DOT"
]

# память сигналов, чтобы не спамить
LAST_ALERT = {}
STATS = {
    "signals": 0,
    "long": 0,
    "short": 0
}

# ===== ОТПРАВКА В TG =====
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={
            "chat_id": CHAT_ID,
            "text": msg
        }, timeout=10)
    except:
        pass


# ===== ЗАГРУЗКА ДАННЫХ =====
def klines(symbol, limit=2000):
    try:
        url = "https://min-api.cryptocompare.com/data/v2/histominute"

        # 15-минутные бары как у тебя
        p = {
            "fsym": symbol,
            "tsym": "USDT",
            "limit": limit,
            "aggregate": 15
        }

        r = requests.get(url, params=p, timeout=10).json()

        if r.get("Response") != "Success":
            return None

        df = pd.DataFrame(r["Data"]["Data"])
        df["t"] = pd.to_datetime(df["time"], unit="s", utc=True)

        return df[["t","close","volumeto"]].rename(
            columns={"close":"c","volumeto":"v"}
        )
    except:
        return None


# ===== МЕТРИКИ (твой код) =====
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


# ==========================================================
# =============== НАШ ПАТТЕРН ИЗ ИССЛЕДОВАНИЯ ==============
# ==========================================================

def detect_pattern(df):
    if len(df) < 6:
        return None

    c = df["c"]
    v = df["v"]

    # ===== ПАРАМЕТРЫ ИЗ КАЛИБРОВКИ =====
    MIN_GROWTH = 0.25      # %
    MIN_VOLX   = 1.5

    growth = (c.iloc[-1] - c.iloc[-3]) / c.iloc[-3] * 100
    vol_mult = v.iloc[-1] / (v.iloc[-20:].mean() + 1e-9)

    trend = (c.iloc[-3] < c.iloc[-2] < c.iloc[-1])

    # --- коэффициент похожести ---
    score = 0

    if trend:
        score += 40

    if growth >= MIN_GROWTH:
        score += 30
    if growth >= MIN_GROWTH * 1.6:
        score += 10

    if vol_mult >= MIN_VOLX:
        score += 30
    if vol_mult >= MIN_VOLX * 1.4:
        score += 10

    signal = None

    # ===== LONG (наиболее валидно по тесту) =====
    if score >= 70:
        signal = {
            "type": "LONG",
            "score": score,
            "growth": round(growth, 2),
            "vol_x": round(vol_mult, 2),

            # цели из реальной статистики BTC
            "tp1": 0.35,
            "tp2": 0.60,
            "sl": -0.22
        }

    # ===== SHORT ПО ПЕРЕГРЕВУ =====
    g60 = (c.iloc[-1] - c.iloc[-5]) / c.iloc[-5] * 100

    if g60 > 1.0 and vol_mult < 0.8:
        signal = {
            "type": "SHORT",
            "score": score,
            "growth": round(g60, 2),
            "vol_x": round(vol_mult, 2),

            "tp": -0.6,
            "sl": 0.25
        }

    return signal
    
# ===== ПРОВЕРКА И АЛЕРТЫ =====
def scan_signals():
    while True:

        for s in SYMBOLS:
            df = klines(s, 300)

            if df is None:
                continue

            sig = detect_pattern(df)

            if not sig:
                continue

            # антиспам — не чаще раза в 60 мин на монету
            last = LAST_ALERT.get(s, 0)
            if time.time() - last < 3600:
                continue

            LAST_ALERT[s] = time.time()
            STATS["signals"] += 1

            if sig["type"] == "LONG":
                STATS["long"] += 1

                msg = f"""
🟢 LONG SETUP {s}/USDT

Похожесть: {sig['score']}%
Рост: {sig['growth']}%
Объём x: {sig['vol_x']}

Идея:
SL −0.22%
TP1 +0.35%
TP2 +0.60%
"""

            else:
                STATS["short"] += 1

                msg = f"""
🔴 RISK OF DUMP {s}/USDT

Перегрев: +{sig['growth']}%
Объём x: {sig['vol_x']}

Идея:
SHORT на сломе
SL +0.25%
TP −0.4…−0.8%
"""

            send(msg)

        time.sleep(60 * 5)   # каждые 5 минут


# ===== ТВОЙ ОТЧЁТ 5H (оставлен) =====
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

bars: {bars}
coverage: ~{days} days

15m avg: {m['g15_mean']}%
15m p90: {m['g15_p90']}%

1h avg: {m['g60_mean']}%
1h p90: {m['g60_p90']}%

max 1h: {m['max_pump']}%
vol x: {m['vol_x']}

RSI peak: {m['rsi_peak']}

"""

            time.sleep(1.2)

        # добавим статистику сигналов
        text += f"""

Signals: {STATS['signals']}
Long: {STATS['long']}
Short: {STATS['short']}

Time: {datetime.now(UTC)}
"""

        send(text)

        time.sleep(5 * 3600)


# ===== ЗАПУСК =====
def bot_loop():
    send("🟢 BOT START — PATTERN + DEPTH")

    threading.Thread(target=stats_report, daemon=True).start()
    threading.Thread(target=scan_signals, daemon=True).start()

    while True:
        time.sleep(60)


if __name__=="__main__":
    threading.Thread(target=run_server,daemon=True).start()
    bot_loop()
