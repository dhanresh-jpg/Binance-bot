import time
import requests
import sqlite3
import os
import threading
import traceback
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, request

# --- CONFIGURATION ---
FREE_BOT_TOKEN = "8842407289:AAHD6UcvOZ0pgvN8EJXXetb2qrW-fGeZCvU"
VIP_BOT_TOKEN = "8997353064:AAH2gTVchfQqqId1TvBa2CD8nIXY00ZUj_8"

FREE_CHANNEL_ID = "-1003924921868"
VIP_CHANNEL_ID = "-1003836756507"

TRUST_WALLET_ADDRESS = "TErttGLUQZtrCwusaQsjdywXdkxUrNFm52"

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

PLANS = {
    "plan_10": {"days": 10, "price": 10.0, "name": "10 Days VIP"},
    "plan_20": {"days": 20, "price": 19.0, "name": "20 Days VIP"},
    "plan_30": {"days": 30, "price": 27.0, "name": "30 Days VIP"}
}

# --- DATABASE SETUP ---
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

# --- TELEGRAM SENDER HELPER ---
def send_telegram_msg(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        res_json = res.json()
        if not res_json.get("ok"):
            log_event(f"Telegram Error ({chat_id}): {res_json.get('description')}")
        else:
            log_event(f"SUCCESS: Msg sent to {chat_id}")
        return res_json
    except Exception as e:
        log_event(f"Telegram Exception ({chat_id}): {e}")
        return None

# --- MARKET DATA & CALCULATIONS ---
def fetch_binance_klines(symbol):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=30"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            closes = [float(item[4]) for item in data]
            volumes = [float(item[5]) for item in data]
            return closes, volumes
    except Exception as e:
        log_event(f"Binance Error ({symbol}): {e}")
    return None, None

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def generate_and_send_signals():
    log_event("Generating market signals...")
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    first_spot, first_fut = None, None

    for sym in symbols:
        closes, volumes = fetch_binance_klines(sym)
        if not closes or len(closes) < 20:
            continue

        price = closes[-1]
        rsi = calculate_rsi(closes)
        sma_20 = sum(closes[-20:]) / 20
        vol_24h = (sum(volumes[-24:]) * price) / 1_000_000 if len(volumes) >= 24 else 150.0
        change = ((price - closes[0]) / closes[0]) * 100

        if price >= sma_20 and rsi >= 45:
            analysis = "Bullish Momentum (SMA Breakout)"
        elif rsi < 45:
            analysis = "Oversold Rebound Pattern"
        else:
            analysis = "Consolidation Phase"

        p_fmt = f"{price:.2f}" if price > 10 else f"{price:.4f}"

        # VIP Spot Text
        spot_msg = (
            f"🟢 <b>[VIP SPOT SIGNAL] {sym}</b>\n\n"
            f"📥 <b>Entry</b>: ${p_fmt}\n"
            f"📊 <b>24h Vol</b>: ${vol_24h:.2f}M | <b>Chg</b>: {change:+.2f}%\n\n"
            f"🎯 <b>TP1</b>: ${price * 1.025:.4f} (+2.5%)\n"
            f"🎯 <b>TP2</b>: ${price * 1.050:.4f} (+5.0%)\n"
            f"🎯 <b>TP3</b>: ${price * 1.085:.4f} (+8.5%)\n"
            f"⛔ <b>SL</b>: ${price * 0.960:.4f} (-4.0%)\n\n"
            f"📈 <b>Analysis</b>: {analysis}"
        )

        # VIP Futures Text
        futures_msg = (
            f"⚡ <b>[VIP FUTURES LONG] {sym}</b>\n\n"
            f"⚙️ <b>Leverage</b>: Cross 10x - 20x\n"
            f"📥 <b>Entry</b>: ${p_fmt}\n\n"
            f"🎯 <b>TP1</b>: ${price * 1.015:.4f} (+15% @ 10x)\n"
            f"🎯 <b>TP2</b>: ${price * 1.035:.4f} (+35% @ 10x)\n"
            f"🎯 <b>TP3</b>: ${price * 1.060:.4f} (+60% @ 10x)\n"
            f"⛔ <b>SL</b>: ${price * 0.985:.4f} (-15% @ 10x)\n\n"
            f"📊 <b>Analysis</b>: {analysis}"
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

# --- FLASK ENDPOINTS ---
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

# Start background worker
threading.Thread(target=continuous_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
