import asyncio
import statistics
from collections import deque, defaultdict
from datetime import datetime

from binance import AsyncClient, BinanceSocketManager
from telegram import Bot

# ===== ТВОИ КОНСТАНТЫ ИЗ ПРОЕКТА =====
from config import TOKEN, CHAT_ID


# ===== HTTP ДЛЯ RENDER =====
from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.get("/")
async def root():
    return {"status": "alive", "time": str(datetime.utcnow())}


# ===== НАСТРОЙКИ ТОРГОВЛИ =====
SYMBOLS = [
    "BTCUSDT","ETHUSDT","SOLUSDT",
    "BNBUSDT","XRPUSDT","DOGEUSDT"
]

NEWCOMERS = set()

PARAMS = {
    "min_growth": 0.25,
    "volume_mult": 1.8,
    "max_upper_shadow": 0.3,
    "min_similarity": 70
}

# ===== ХРАНИЛИЩА =====
trades = defaultdict(lambda: deque(maxlen=2000))
candles = defaultdict(lambda: deque(maxlen=200))
stats = defaultdict(list)

bot = Bot(TOKEN)

# ===== УТИЛИТЫ =====
def pct(a, b):
    return (b - a) / a * 100


def build_candle(ticks):
    o = ticks[0]["p"]
    c = ticks[-1]["p"]
    h = max(t["p"] for t in ticks)
    l = min(t["p"] for t in ticks)
    vol = sum(t["q"] for t in ticks)

    body = abs(c - o)
    upper = h - max(o, c)

    return {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "vol": vol,
        "upper_shadow": upper / (body + 1e-9)
    }


# ===== ПОХОЖЕСТЬ НА ПАТТЕРН =====
def similarity(symbol):
    cs = list(candles[symbol])[-3:]
    if len(cs) < 3:
        return 0

    shape = sum(1 for c in cs if c["close"] > c["open"]) * 10

    avg = statistics.mean(c["vol"] for c in list(candles[symbol])[-30:])
    vol_score = min(30, int(cs[-1]["vol"] / avg * 15))

    shadow = sum(
        1 for c in cs if c["upper_shadow"] < PARAMS["max_upper_shadow"]
    ) * 10

    growth = pct(cs[0]["open"], cs[-1]["close"])
    growth_score = min(
        30, int(growth / PARAMS["min_growth"] * 15)
    )

    return shape + vol_score + shadow + growth_score


# ===== ПЕРЕГРЕВ ДЛЯ ШОРТА =====
def overheat(symbol):
    cs = list(candles[symbol])[-10:]
    if len(cs) < 10:
        return False

    growth = pct(cs[0]["open"], cs[-1]["close"])
    if growth < 1:
        return False

    vols = [c["vol"] for c in cs]
    return vols[-1] < statistics.mean(vols)


# ===== АЛЕРТЫ =====
async def alert_long(symbol, sim, candle):
    msg = f"""
🟢 LONG {symbol}

Похожесть: {sim}%
Рост: {pct(candle['open'], candle['close']):.2f}%
Объём: {candle['vol']:.2f}

SL: −0.22%
TP1: +0.35%
TP2: +0.60%
"""
    await bot.send_message(CHAT_ID, msg)


async def alert_short(symbol, candle):
    msg = f"""
🔴 SHORT IDEA {symbol}

Перегрев после пампа
Цена: {candle['close']}

SL: +0.25%
TP: −0.4…−0.8%
"""
    await bot.send_message(CHAT_ID, msg)


# ===== СОКЕТ ТРЕЙДОВ =====
async def trade_socket(symbol, bm):
    ts = bm.trade_socket(symbol)

    async with ts as tscm:
        while True:
            res = await tscm.recv()

            trades[symbol].append({
                "p": float(res["p"]),
                "q": float(res["q"]),
                "T": res["T"]
            })

            if len(trades[symbol]) > 20:
                candle = build_candle(list(trades[symbol]))
                candles[symbol].append(candle)

                sim = similarity(symbol)

                if sim >= PARAMS["min_similarity"]:
                    await alert_long(symbol, sim, candle)

                if overheat(symbol):
                    await alert_short(symbol, candle)


# ===== ПОИСК НОВЫХ МОНЕТ =====
async def scan_newcomers(client):
    try:
        tickers = await client.get_ticker()
        for t in tickers:
            s = t["symbol"]
            if not s.endswith("USDT"):
                continue

            change = float(t["priceChangePercent"])

            if change > 20 and s not in SYMBOLS:
                SYMBOLS.append(s)
                NEWCOMERS.add(s)

                await bot.send_message(
                    CHAT_ID,
                    f"🆕 Новый горячий токен: {s} +{change}%"
                )
    except Exception as e:
        print("scan error", e)


# ===== KEEP ALIVE ДЛЯ RENDER =====
async def keep_alive():
    while True:
        try:
            await bot.send_chat_action(
                CHAT_ID, action="typing"
            )
        except:
            pass

        await asyncio.sleep(300)   # 5 минут


# ===== ГЛАВНЫЙ ЦИКЛ =====
async def trading_loop():
    client = await AsyncClient.create()
    bm = BinanceSocketManager(client)

    for s in SYMBOLS:
        asyncio.create_task(
            trade_socket(s.lower(), bm)
        )

    while True:
        await scan_newcomers(client)
        await asyncio.sleep(600)


# ===== ЗАПУСК =====
async def main():
    asyncio.create_task(trading_loop())
    asyncio.create_task(keep_alive())

    # веб для Render
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=10000,
        log_level="info"
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
