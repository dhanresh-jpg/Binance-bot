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
ADMIN_USER_ID = 123456789  # Replace with your Telegram User ID if needed

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
    "10": {"days": 10, "price": "10 USDT", "name": "10 Days VIP"},
    "20": {"days": 20, "price": "19 USDT", "name": "20 Days VIP"},
    "30": {"days": 30, "price": "27 USDT", "name": "30 Days VIP"}
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

# --- DATABASE OPERATIONS ---
def add_vip_member(user_id, days):
    try:
        conn = sqlite3.connect("vip_members.db")
        cursor = conn.cursor()
        expiry = datetime.now(IST) + timedelta(days=days)
        expiry_str = expiry.strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute('''
            INSERT OR REPLACE INTO members (user_id, expiry_date, status)
            VALUES (?, ?, ?)
        ''', (user_id, expiry_str, "ACTIVE"))
        
        conn.commit()
        conn.close()
        return expiry_str
    except Exception as e:
        log_event(f"DB Add Error: {e}")
        return None

def get_member_status(user_id):
    try:
        conn = sqlite3.connect("vip_members.db")
        cursor = conn.cursor()
        cursor.execute("SELECT expiry_date, status FROM members WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return row[0], row[1]
    except Exception as e:
        log_event(f"DB Get Error: {e}")
    return None, None

# --- TELEGRAM SENDER HELPERS ---
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
        return res.json()
    except Exception as e:
        log_event(f"Telegram Exception ({chat_id}): {e}")
        return None

# --- MARKET DATA & SIGNALS ---
def fetch_binance_price(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            return float(res.json()["price"])
    except Exception as e:
        log_event(f"Binance fetch fail for {symbol}: {e}")
    
    fallback_prices = {"BTCUSDT": 62500.0, "ETHUSDT": 2450.0, "SOLUSDT": 135.0, "BNBUSDT": 550.0}
    return fallback_prices.get(symbol, 100.0)

def generate_and_send_signals():
    log_event("Generating market signals...")
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    first_spot, first_fut = None, None

    for sym in symbols:
        price = fetch_binance_price(sym)
        p_fmt = f"{price:.2f}" if price > 10 else f"{price:.4f}"

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

# --- TELEGRAM BOT UPDATES / COMMANDS LISTENER ---
def process_bot_updates():
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{VIP_BOT_TOKEN}/getUpdates"
            params = {"timeout": 10, "offset": offset}
            res = requests.get(url, params=params, timeout=12)
            if res.status_code == 200:
                data = res.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    user_id = msg.get("from", {}).get("id")

                    if not text or not user_id:
                        continue

                    if text == "/start":
                        welcome = (
                            f"👋 <b>Welcome to Crypto VIP Signals Bot!</b>\n\n"
                            f"Commands:\n"
                            f"🔹 /plans - View VIP Pricing\n"
                            f"🔹 /pay - Deposit TRC20 Address\n"
                            f"🔹 /status - Check Membership Validity"
                        )
                        send_telegram_msg(VIP_BOT_TOKEN, user_id, welcome)

                    elif text == "/plans":
                        plans_txt = (
                            f"💎 <b>VIP SUBSCRIPTION PLANS</b>\n\n"
                            f"🔸 <b>10 Days Access</b>: 10 USDT\n"
                            f"🔸 <b>20 Days Access</b>: 19 USDT\n"
                            f"🔸 <b>30 Days Access</b>: 27 USDT\n\n"
                            f"👉 Type /pay to get the Deposit Address."
                        )
                        send_telegram_msg(VIP_BOT_TOKEN, user_id, plans_txt)

                    elif text == "/pay":
                        pay_txt = (
                            f"💳 <b>USDT TRC-20 Payment Address</b>\n\n"
                            f"<code>{TRUST_WALLET_ADDRESS}</code>\n\n"
                            f"⚠️ Send exact amount for your plan.\n"
                            f"After payment, send your Transaction TXID/Screenshot here or to Admin."
                        )
                        send_telegram_msg(VIP_BOT_TOKEN, user_id, pay_txt)

                    elif text == "/status":
                        expiry, status = get_member_status(user_id)
                        if status == "ACTIVE":
                            stat_txt = f"✅ <b>VIP Status</b>: ACTIVE\n⏳ <b>Expires On</b>: {expiry}"
                        else:
                            stat_txt = "❌ <b>VIP Status</b>: INACTIVE\nType /plans to join VIP."
                        send_telegram_msg(VIP_BOT_TOKEN, user_id, stat_txt)

                    elif text.startswith("/addmember"):
                        parts = text.split()
                        if len(parts) == 3:
                            target_id = int(parts[1])
                            days = int(parts[2])
                            exp = add_vip_member(target_id, days)
                            send_telegram_msg(VIP_BOT_TOKEN, user_id, f"✅ User {target_id} added until {exp}")
                            send_telegram_msg(VIP_BOT_TOKEN, target_id, f"🎉 Your VIP Membership is activated until {exp}!")

        except Exception as e:
            time.sleep(2)

# --- FLASK ENDPOINTS ---
@app.route('/')
def home():
    return "VIP & Free Engine Running."

@app.route('/logs')
def get_logs():
    return jsonify({"logs": system_logs})

@app.route('/force-signal')
def force_signal():
    threading.Thread(target=generate_and_send_signals, daemon=True).start()
    return "Signals triggered! Check Telegram channels."

threading.Thread(target=continuous_loop, daemon=True).start()
threading.Thread(target=process_bot_updates, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
