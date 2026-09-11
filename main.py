import time
import random
import requests
import sqlite3
import os
import threading
import traceback
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify

# --- CONFIGURATION ---
BOT_TOKEN = "8997353064:AAH3g9MlS-tjPOxpihquJVMcopWRnn_SMEQ"
VIP_CHANNEL_ID = "-1003836756507"
FREE_CHANNEL_ID = "-1003924921868"
TRUST_WALLET_ADDRESS = "TErttGLUQZtrCwusaQsjdywXdkxUrNFm52"

app = Flask(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

system_logs = []

def log_event(message):
    timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    system_logs.append(entry)
    if len(system_logs) > 50:
        system_logs.pop(0)
    print(entry)

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
        log_event("Database initialized.")
    except Exception as e:
        log_event(f"DB Init Error: {e}")

init_db()

# --- TELEGRAM API HELPERS ---
def send_telegram_msg(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
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
            log_event(f"Telegram API Error ({chat_id}): {res_json.get('description')}")
        else:
            log_event(f"SUCCESS: Posted to {chat_id}")
        return res_json
    except Exception as e:
        log_event(f"Telegram Exception ({chat_id}): {e}")
        return None

# --- MARKET DATA & SIGNALS ---
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
            gains.append(abs(change))
            losses.append(abs(change))
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def get_accurate_market_signals():
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    analyzed_coins = []

    for sym in symbols:
        closes, volumes = fetch_binance_klines(sym)
        if closes and len(closes) >= 20:
            current_price = closes[-1]
            rsi = calculate_rsi(closes)
            sma_20 = sum(closes[-20:]) / 20
            vol_24h = (sum(volumes[-24:]) * current_price) / 1_000_000 if len(volumes) >= 24 else 150.0
            price_change = ((current_price - closes[0]) / closes[0]) * 100

            if current_price >= sma_20 and rsi >= 45:
                trend = "Strong Bullish Momentum (RSI + SMA Breakout)"
            elif rsi < 45:
                trend = "Oversold Rebound Pattern"
            else:
                trend = "Volume Consolidation Breakout"

            analyzed_coins.append({
                "symbol": sym, "price": current_price, "volume": round(vol_24h, 2),
                "change": round(price_change, 2), "rsi": round(rsi, 1), "analysis": trend
            })
        time.sleep(0.1)

    return analyzed_coins

def process_and_send_signals():
    log_event("Processing signals...")
    coins = get_accurate_market_signals()
    if not coins:
        log_event("Failed to fetch Binance data.")
        return False

    first_spot_text, first_futures_text = "", ""

    for index, coin in enumerate(coins):
        symbol, price, volume, change, analysis_text = coin["symbol"], coin["price"], coin["volume"], coin["change"], coin["analysis"]
        p_fmt = f"{price:.2f}" if price > 10 else f"{price:.4f}"

        t1_spot, t2_spot, t3_spot, sl_spot = price * 1.025, price * 1.050, price * 1.085, price * 0.960
        t1_fut, t2_fut_sl, t2_fut_target, t3_fut_target = price * 1.015, price * 0.985, price * 1.035, price * 1.060

        spot_text = (
            f"🟢 <b>[SPOT SIGNAL] {symbol}</b>\n\n"
            f"📥 <b>Entry Range</b>: ${p_fmt}\n"
            f"📊 <b>24h Vol</b>: ${volume}M | <b>Change</b>: {change:+.2f}%\n\n"
            f"🎯 <b>Target 1</b>: ${t1_spot:.4f} (+2.5%)\n"
            f"🎯 <b>Target 2</b>: ${t2_spot:.4f} (+5.0%)\n"
            f"🎯 <b>Target 3</b>: ${t3_spot:.4f} (+8.5%)\n"
            f"⛔ <b>Stop Loss</b>: ${sl_spot:.4f} (-4.0%)\n\n"
            f"📈 <b>Analysis</b>: {analysis_text}"
        )

        futures_text = (
            f"⚡ <b>[FUTURES LONG] {symbol}</b>\n\n"
            f"⚙️ <b>Leverage</b>: Cross 10x - 20x\n"
            f"📥 <b>Entry</b>: ${p_fmt}\n\n"
            f"🎯 <b>Target 1</b>: ${t1_fut:.4f} (+15% @ 10x)\n"
            f"🎯 <b>Target 2</b>: ${t2_fut_target:.4f} (+35% @ 10x)\n"
            f"🎯 <b>Target 3</b>: ${t3_fut_target:.4f} (+60% @ 10x)\n"
            f"⛔ <b>Stop Loss</b>: ${t2_fut_sl:.4f} (-15% @ 10x)\n\n"
            f"📊 <b>Analysis</b>: {analysis_text}"
        )

        send_telegram_msg(VIP_CHANNEL_ID, spot_text)
        time.sleep(1)
        send_telegram_msg(VIP_CHANNEL_ID, futures_text)
        time.sleep(1)

        if index == 0:
            first_spot_text, first_futures_text = spot_text, futures_text

    free_promo_text = (
        f"🚀 <b>FREE PREVIEW SIGNALS (DELAYED)</b> 🚀\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{first_spot_text}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{first_futures_text}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔥 <b>GET REAL-TIME INSTANT SIGNALS IN VIP</b> 🔥\n\n"
        f"👉 <b>Join VIP Bot</b>: @BinanceTop10_VIPBot"
    )
    send_telegram_msg(FREE_CHANNEL_ID, free_promo_text)
    return True

def continuous_signal_loop():
    time.sleep(3)
    while True:
        try:
            process_and_send_signals()
        except Exception as e:
            log_event(f"Error in Loop: {e}\n{traceback.format_exc()}")
        
        # 4 Hours Interval (14400 seconds)
        time.sleep(14400)

@app.route('/')
def home():
    return "VIP Bot Operational!"

@app.route('/logs')
def view_logs():
    return jsonify({"logs": system_logs})

@app.route('/force-signal')
def force_signal():
    threading.Thread(target=process_and_send_signals, daemon=True).start()
    return "Instant Signal Processing Triggered! Check Telegram."

# Start background worker on launch
threading.Thread(target=continuous_signal_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
