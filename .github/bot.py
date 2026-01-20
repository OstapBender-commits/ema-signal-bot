import os
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask
import threading

# ===== Переменные из Render =====
LOGIN = os.getenv("Login")
PASSWORD = os.getenv("Password")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

HOST = "http://194.67.82.80/SEDA/en_GB/"

# ===== Имитация веб-сервера для Render =====
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running"

def run_web():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

# ===== Функция логина в 1С =====
def login_1c(session: requests.Session):
    data = {
        "username": LOGIN,
        "password": PASSWORD
    }

    r = session.post(HOST + "login", data=data)
    return r.status_code == 200


# ===== Получение остатков реагентов =====
def get_reagents():
    session = requests.Session()

    if not login_1c(session):
        return "❌ Ошибка входа в 1С"

    r = session.get(HOST + "reagents_stock")
    soup = BeautifulSoup(r.text, "html.parser")

    table = soup.find("table")

    result = "🧪 *Остатки реагентов:*\n\n"

    if not table:
        return "Не удалось найти таблицу остатков"

    for row in table.find_all("tr")[1:]:
        cols = [c.text.strip() for c in row.find_all("td")]
        if len(cols) >= 2:
            result += f"• {cols[0]} — {cols[1]}\n"

    return result


# ===== Команды Telegram =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот остатков реагентов.\n"
        "Используй /stock для выгрузки."
    )


async def stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_reagents()
    await update.message.reply_text(msg, parse_mode="Markdown")


def main():
    threading.Thread(target=run_web).start()

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stock", stock))

    application.run_polling()


if __name__ == "__main__":
    main()
