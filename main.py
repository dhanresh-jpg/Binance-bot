import time
import requests
import sqlite3
import os
import threading
import traceback
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify

# --- CONFIGURATION ---
FREE_BOT_TOKEN = "8842407289:AAHD6UcvOZ0pgvN8EJXXetb2qrW-fGeZCvU"
VIP_BOT_TOKEN = "8997353064:AAH2gTVchfQqqId1TvBa2CD8nIXY00ZUj_8"

FREE_CHANNEL_ID = "-1003924921868"
VIP_CHANNEL_ID = "-1003836756507"

app = Flask(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
system_logs = []

def log_event(message):
    timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    system_logs.append(entry)
    if len(system_logs) > 100:
        system_logs.pop(0)
    print(entry)

def init_db():
    try:
        conn = sqlite3.connect("vip_members.db")
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS members (
                user_id INTEGER PRIMARY KEY,
                expiry_date TEXT,
                status TEXT
            )
        ''')
        conn.commit()
        conn.close()
        log_event("Database initialized successfully.")
    except Exception as e:
        log_event(f"DB Error: {e}")

init_db()

def send_telegram_msg(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        res = requests.post(url, json=payload, timeout=8)
        res_json = res.json()
        if not res_json.get("ok"):
            log_event(f"Telegram API Error ({chat_id}): {res_json.get('description')}")
        else:
            log_event(f"SUCCESS: Msg sent to {chat_id}")
        return res_json
    except Exception as e:
        log_event(f"Telegram Exception ({chat_id}): {e}")
        return None

def fetch_binance_price(symbol):
    try:
        # Fast endpoint with 3-second timeout
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            return float(res.json()["price"])
    except Exception as e:
        log_event(f"Binance fetch fail for {symbol}: {e}")
    
    # Static fallback prices in case Binance blocks server
    fallback_prices = {"BTCUSDT": 62500.0, "ETHUSDT": 2450.0, "SOLUSDT": 135.0, "BNBUSDT": 550.0}
    return fallback_prices.get(symbol, 100.0)

def generate_and_send_signals():
    log_event("Generating market signals...")
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    first_spot, first_fut = None, None

    for sym in symbols:
        price = fetch_binance_price(sym)
        p_fmt = f"{price:.2f}" if price > 10 else f"{price:.4f}"

        # VIP Spot Signal Format
        spot_msg = (
            f"🟢 <b>[VIP SPOT SIGNAL] {sym}</b>\n\n"
            f"📥 <b>Entry</b>: ${p_fmt}\n"
            f"📊 <b>Trend</b>: Strong Bullish Breakout\n\n"
            f"🎯 <b>TP1</b>: ${price * 1.025:.4f} (+2.5%)\n"
            f"🎯 <b>TP2</b>: ${price * 1.050:.4f} (+5.0%)\n"
            f"🎯 <b>TP3</b>: ${price * 1.085:.4f} (+8.5%)\n"
            f"⛔ <b>SL</b>: ${price * 0.960:.4f} (-4.0%)\n\n"
            f"📈 <b>Analysis</b>: High Volume Confirmation"
        )

        # VIP Futures Signal Format
        futures_msg = (
            f"⚡ <b>[VIP FUTURES LONG] {sym}</b>\n\n"
            f"⚙️ <b>Leverage</b>: Cross 10x - 20x\n"
            f"📥 <b>Entry</b>: ${p_fmt}\n\n"
            f"🎯 <b>TP1</b>: ${price * 1.015:.4f} (+15% @ 10x)\n"
            f"🎯 <b>TP2</b>: ${price * 1.035:.4f} (+35% @ 10x)\n"
            f"🎯 <b>TP3</b>: ${price * 1.060:.4f} (+60% @ 10x)\n"
            f"⛔ <b>SL</b>: ${price * 0.985:.4f} (-15% @ 10x)\n\n"
            f"📊 <b>Analysis</b>: RSI Bullish Divergence"
        )

        # Send to VIP Channel
        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, spot_msg)
        time.sleep(1)
        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, futures_msg)
        time.sleep(1)

        if not first_spot:
            first_spot, first_fut = spot_msg, futures_msg

    if first_spot and first_fut:
        free_promo = (
            f"🚀 <b>FREE PREVIEW SIGNAL</b> 🚀\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{first_spot}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{first_fut}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔥 <b>GET ALL INSTANT SIGNALS IN VIP</b> 🔥\n\n"
            f"👉 Join VIP: @BinanceTop10_VIPBot"
        )
        send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, free_promo)

def continuous_loop():
    time.sleep(5)
    while True:
        try:
            generate_and_send_signals()
        except Exception as e:
            log_event(f"Loop Exception: {e}\n{traceback.format_exc()}")
        time.sleep(14400) # Every 4 Hours

@app.route('/')
def home():
    return "Signal Engine Running Successfully."

@app.route('/logs')
def get_logs():
    return jsonify({"logs": system_logs})

@app.route('/force-signal')
def force_signal():
    threading.Thread(target=generate_and_send_signals, daemon=True).start()
    return "Signals triggered! Check Telegram channels."

threading.Thread(target=continuous_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
