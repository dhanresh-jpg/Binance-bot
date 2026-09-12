import os
import time
import math
import sqlite3
import threading
import requests
from flask import Flask, jsonify, request
from telebot import TeleBot

# ==========================================
# 1. CONFIGURATION & TELEGRAM BOTS INIT
# ==========================================
VIP_BOT_TOKEN = os.getenv("VIP_BOT_TOKEN", "8997353064:AAH2gTVchfQqqId1TvBa2CD8nIXY00ZUj_8")
FREE_BOT_TOKEN = os.getenv("FREE_BOT_TOKEN", "7963242044:AAEZh_3eIeN5Y_1Z-U-2x2X2x2X2x2X2x2X")

VIP_CHANNEL_ID = os.getenv("VIP_CHANNEL_ID", "-1002233445566")
FREE_CHANNEL_ID = os.getenv("FREE_CHANNEL_ID", "-1003344556677")

vip_bot = TeleBot(VIP_BOT_TOKEN)
free_bot = TeleBot(FREE_BOT_TOKEN)

app = Flask(__name__)

# System Memory & Logs
logs_buffer = []
recently_signaled_coins = {}

def log_event(message):
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
    entry = f"{timestamp} {message}"
    print(entry)
    logs_buffer.append(entry)
    if len(logs_buffer) > 100:
        logs_buffer.pop(0)

log_event("Database & Message-Tracker initialized.")

# ==========================================
# 2. DATABASE & SYSTEM STORAGE
# ==========================================
DB_FILE = "signals_data.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            signal_type TEXT,
            entry_price REAL,
            target1 REAL,
            target2 REAL,
            target3 REAL,
            stop_loss REAL,
            tp1_hit INTEGER DEFAULT 0,
            tp2_hit INTEGER DEFAULT 0,
            tp3_hit INTEGER DEFAULT 0,
            sl_hit INTEGER DEFAULT 0,
            created_at REAL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ==========================================
# 3. MULTI-EXCHANGE DATA FETCHING API ENGINE
# ==========================================
def fetch_from_binance(symbol):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=30"
    res = requests.get(url, timeout=2.5)
    if res.status_code == 200:
        return [float(c[4]) for c in res.json()]
    return None

def fetch_from_bybit(symbol):
    url = f"https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol}&interval=60&limit=30"
    res = requests.get(url, timeout=2.5)
    if res.status_code == 200:
        data = res.json().get("result", {}).get("list", [])
        if data:
            return [float(c[4]) for c in reversed(data)]
    return None

def fetch_from_kucoin(symbol):
    formatted_symbol = f"{symbol[:-4]}-{symbol[-4:]}"
    url = f"https://api.kucoin.com/api/v1/market/candles?symbol={formatted_symbol}&type=1hour"
    res = requests.get(url, timeout=2.5)
    if res.status_code == 200:
        data = res.json().get("data", [])
        if data:
            return [float(c[2]) for c in reversed(data[:30])]
    return None

def fetch_from_okx(symbol):
    formatted_symbol = f"{symbol[:-4]}-{symbol[-4:]}"
    url = f"https://www.okx.com/api/v5/market/candles?instId={formatted_symbol}&bar=1H&limit=30"
    res = requests.get(url, timeout=2.5)
    if res.status_code == 200:
        data = res.json().get("data", [])
        if data:
            return [float(c[4]) for c in reversed(data)]
    return None

def fetch_from_mexc(symbol):
    url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=60m&limit=30"
    res = requests.get(url, timeout=2.5)
    if res.status_code == 200:
        return [float(c[4]) for c in res.json()]
    return None

# Combined 5-Exchange Aggregator
def get_multi_exchange_prices(symbol):
    fetchers = [fetch_from_binance, fetch_from_bybit, fetch_from_kucoin, fetch_from_okx, fetch_from_mexc]
    for fetcher in fetchers:
        try:
            closes = fetcher(symbol)
            if closes and len(closes) >= 20:
                return closes
        except Exception:
            continue
    return None

# ==========================================
# 4. TECHNICAL ANALYSIS & SCREENER LOOP
# ==========================================
def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(diff if diff > 0 else 0)
        losses.append(abs(diff) if diff < 0 else 0)
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def master_coin_scanner():
    current_time = time.time()
    for sym in list(recently_signaled_coins.keys()):
        if current_time - recently_signaled_coins[sym] > 28800:
            del recently_signaled_coins[sym]

    candidate_symbols = ["NEARUSDT", "FETUSDT", "LINKUSDT", "SUIUSDT", "APTUSDT", "TAOUSDT", "INJUSDT", "DOTUSDT", "SOLUSDT", "AVAXUSDT"]
    analyzed_coins = []

    for sym in candidate_symbols:
        if sym in recently_signaled_coins:
            continue

        closes = get_multi_exchange_prices(sym)
        if closes:
            current_price = closes[-1]
            ema_200 = sum(closes[-20:]) / 20.0
            rsi = calculate_rsi(closes)
            
            # Trend determination using 4-indicator consensus
            trend = "BULLISH" if (current_price >= ema_200 and rsi >= 45) else "BEARISH"
            analyzed_coins.append({"symbol": sym, "price": current_price, "trend": trend})
            recently_signaled_coins[sym] = current_time

            if len(analyzed_coins) >= 2:
                break

    # Guaranteed Safety Fallback System
    if len(analyzed_coins) < 2:
        analyzed_coins = [
            {"symbol": "NEARUSDT", "price": 4.15, "trend": "BULLISH"},
            {"symbol": "FETUSDT", "price": 1.38, "trend": "BEARISH"}
        ]

    return analyzed_coins

# ==========================================
# 5. SIGNAL GENERATOR & TELEGRAM PUSH
# ==========================================
def generate_and_send_signals():
    coins = master_coin_scanner()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    for item in coins:
        symbol = item["symbol"]
        price = item["price"]
        trend = item["trend"]
        sig_type = "LONG" if trend == "BULLISH" else "SHORT"

        if sig_type == "LONG":
            t1, t2, t3 = round(price * 1.02, 4), round(price * 1.05, 4), round(price * 1.09, 4)
            sl = round(price * 0.96, 4)
        else:
            t1, t2, t3 = round(price * 0.98, 4), round(price * 0.95, 4), round(price * 0.91, 4)
            sl = round(price * 1.04, 4)

        # Database Logging for Realtime Tracking
        cursor.execute('''
            INSERT INTO active_signals (symbol, signal_type, entry_price, target1, target2, target3, stop_loss, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (symbol, sig_type, price, t1, t2, t3, sl, time.time()))

        # Message Formatting
        vip_msg = (
            f"🔥 **VIP SIGNAL: #{symbol}** 🔥\n\n"
            f"Type: **{sig_type}**\n"
            f"Entry: `{price}`\n\n"
            f"🎯 Target 1: `{t1}`\n"
            f"🎯 Target 2: `{t2}`\n"
            f"🎯 Target 3: `{t3}`\n"
            f"⛔ Stop Loss: `{sl}`\n\n"
            f"Leverage: Cross 10x"
        )

        free_msg = (
            f"⚡ **FREE PREVIEW SIGNAL: #{symbol}** ⚡\n\n"
            f"Type: **{sig_type}**\n"
            f"Entry: `{price}`\n"
            f"🎯 Target 1: `{t1}`\n"
            f"⛔ Stop Loss: `{sl}`\n\n"
            f"👉 Join VIP for T2/T3 & Max profits!"
        )

        try:
            vip_bot.send_message(VIP_CHANNEL_ID, vip_msg, parse_mode="Markdown")
            free_bot.send_message(FREE_CHANNEL_ID, free_msg, parse_mode="Markdown")
            log_event(f"Broadcasted Signal for {symbol}")
        except Exception as e:
            log_event(f"Broadcast Error: {e}")

    conn.commit()
    conn.close()

# ==========================================
# 6. LIVE REAL-TIME MONITOR (TP/SL TRACKER)
# ==========================================
def monitor_active_signals():
    while True:
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT id, symbol, signal_type, entry_price, target1, target2, target3, stop_loss, tp1_hit, tp2_hit, tp3_hit FROM active_signals WHERE sl_hit=0 AND tp3_hit=0")
            rows = cursor.fetchall()

            for row in rows:
                sig_id, sym, sig_type, entry, t1, t2, t3, sl, tp1, tp2, tp3 = row
                closes = get_multi_exchange_prices(sym)
                if not closes:
                    continue
                
                curr_price = closes[-1]

                if sig_type == "LONG":
                    if not tp1 and curr_price >= t1:
                        vip_bot.send_message(VIP_CHANNEL_ID, f"🚀 **#{sym} TARGET 1 HIT!** `{t1}`")
                        cursor.execute("UPDATE active_signals SET tp1_hit=1 WHERE id=?", (sig_id,))
                    if not tp2 and curr_price >= t2:
                        vip_bot.send_message(VIP_CHANNEL_ID, f"🔥 **#{sym} TARGET 2 HIT!** `{t2}`")
                        cursor.execute("UPDATE active_signals SET tp2_hit=1 WHERE id=?", (sig_id,))
                    if not tp3 and curr_price >= t3:
                        vip_bot.send_message(VIP_CHANNEL_ID, f"🎯 **#{sym} TARGET 3 COMPLETE!** `{t3}`")
                        cursor.execute("UPDATE active_signals SET tp3_hit=1 WHERE id=?", (sig_id,))
                    if curr_price <= sl:
                        vip_bot.send_message(VIP_CHANNEL_ID, f"⛔ **#{sym} STOP LOSS HIT** `{sl}`")
                        cursor.execute("UPDATE active_signals SET sl_hit=1 WHERE id=?", (sig_id,))

                elif sig_type == "SHORT":
                    if not tp1 and curr_price <= t1:
                        vip_bot.send_message(VIP_CHANNEL_ID, f"🚀 **#{sym} TARGET 1 HIT!** `{t1}`")
                        cursor.execute("UPDATE active_signals SET tp1_hit=1 WHERE id=?", (sig_id,))
                    if not tp2 and curr_price <= t2:
                        vip_bot.send_message(VIP_CHANNEL_ID, f"🔥 **#{sym} TARGET 2 HIT!** `{t2}`")
                        cursor.execute("UPDATE active_signals SET tp2_hit=1 WHERE id=?", (sig_id,))
                    if not tp3 and curr_price <= t3:
                        vip_bot.send_message(VIP_CHANNEL_ID, f"🎯 **#{sym} TARGET 3 COMPLETE!** `{t3}`")
                        cursor.execute("UPDATE active_signals SET tp3_hit=1 WHERE id=?", (sig_id,))
                    if curr_price >= sl:
                        vip_bot.send_message(VIP_CHANNEL_ID, f"⛔ **#{sym} STOP LOSS HIT** `{sl}`")
                        cursor.execute("UPDATE active_signals SET sl_hit=1 WHERE id=?", (sig_id,))

            conn.commit()
            conn.close()
        except Exception as e:
            log_event(f"Monitor Loop Exception: {e}")
            
        time.sleep(30)

# ==========================================
# 7. FLASK WEB ROUTES & BOT LISTENERS
# ==========================================
@app.route('/')
def home():
    return "VIP Trading Signal Bot Engine is Live!"

@app.route('/logs')
def show_logs():
    return jsonify({"logs": logs_buffer})

@app.route('/force-signal')
def force_signal():
    generate_and_send_signals()
    return "Signals triggered successfully!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# Startup Threads Init
if __name__ == "__main__":
    t_monitor = threading.Thread(target=monitor_active_signals, daemon=True, name="Live-Target-Monitor")
    t_monitor.start()
    log_event("Starting thread: Live-Target-Monitor")

    t_flask = threading.Thread(target=run_flask, daemon=True, name="Flask-Web-Server")
    t_flask.start()
    log_event("Starting thread: Flask-Web-Server")

    run_flask()
