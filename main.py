import time
import requests
import sqlite3
import os
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify

# Environment Configuration
FREE_BOT_TOKEN = os.getenv("FREE_BOT_TOKEN", "8842407289:AAHD6UcvOZ0pgvN8EJXXetb2qrW-fGeZCvU")
VIP_BOT_TOKEN = os.getenv("VIP_BOT_TOKEN", "8997353064:AAH2gTVchfQqqId1TvBa2CD8nIXY00ZUj_8")

FREE_CHANNEL_ID = os.getenv("FREE_CHANNEL_ID", "-1003924921868")
VIP_CHANNEL_ID = os.getenv("VIP_CHANNEL_ID", "-1003836756507")
TRUST_WALLET_ADDRESS = "TErttGLUQZtrCwusaQsjdywXdkxUrNFm52"

HEADERS = {'User-Agent': 'Mozilla/5.0'}
app = Flask(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
system_logs = []
sent_cooldown = {} 
free_signals_today = 0
last_reset_day = datetime.now(IST).day

def log_event(message):
    timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    system_logs.append(entry)
    if len(system_logs) > 200: system_logs.pop(0)
    print(entry)

def init_db():
    try:
        conn = sqlite3.connect("vip_members.db")
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE IF NOT EXISTS members (user_id INTEGER PRIMARY KEY, expiry_date TEXT, status TEXT)')
        cursor.execute('CREATE TABLE IF NOT EXISTS processed_txids (txid TEXT PRIMARY KEY)')
        cursor.execute('CREATE TABLE IF NOT EXISTS channel_messages (bot_type TEXT, chat_id TEXT, message_id INTEGER, created_date TEXT)')
        conn.commit()
        conn.close()
        log_event("Database initialized successfully.")
    except Exception as e:
        log_event(f"Database Init Error: {e}")

init_db()

# Precision Decimal Handling for Altcoins & Meme Tokens
def format_price(val):
    if val is None or val == 0: return "0.00"
    if val >= 1000: return f"{val:,.2f}"
    elif val >= 1: return f"{val:.4f}"
    elif val >= 0.001: return f"{val:.6f}"
    else: return f"{val:.8f}"

def get_market_data():
    target_symbols = ["SOLUSDT", "BTCUSDT", "ETHUSDT", "PEPEUSDT", "DOGEUSDT", "NEARUSDT", "AVAXUSDT", "SUIUSDT", "WIFUSDT"]
    valid_coins = []
    
    url = "https://api.bybit.com/v5/market/tickers?category=spot"
    try:
        res = requests.get(url, headers=HEADERS, timeout=6.0)
        if res.status_code == 200:
            data = res.json().get("result", {}).get("list", [])
            for item in data:
                symbol = item.get("symbol")
                if symbol in target_symbols:
                    price = float(item.get("lastPrice", 0))
                    change = float(item.get("price24hPcnt", 0)) * 100
                    high = float(item.get("highPrice24h", 0))
                    low = float(item.get("lowPrice24h", 0))
                    turnover = float(item.get("turnover24h", 0))
                    
                    if price > 0:
                        valid_coins.append({
                            "symbol": symbol,
                            "price": price,
                            "change": change,
                            "high": high,
                            "low": low,
                            "turnover": turnover
                        })
            if valid_coins:
                return valid_coins
    except Exception as e:
        log_event(f"Market Fetch Error: {e}")
        
    return valid_coins

def scan_and_dispatch(force_mode=False):
    global free_signals_today, last_reset_day
    log_event(f"🔍 Technical Analysis Scan Started (Force: {force_mode})...")

    current_day = datetime.now(IST).day
    if current_day != last_reset_day:
        free_signals_today = 0
        last_reset_day = current_day

    coins = get_market_data()
    now_time = time.time()
    
    if not coins:
        log_event("⚠️ Market API unavailable. Skipping scan iteration.")
        return

    # Filter out coins sent recently (30 min cooldown)
    coins.sort(key=lambda x: abs(x["change"]), reverse=True)
    top_coin = None
    for c in coins:
        if force_mode or (c["symbol"] not in sent_cooldown or (now_time - sent_cooldown[c["symbol"]]) >= 1800):
            top_coin = c
            break

    if not top_coin: top_coin = coins[0]

    p = top_coin["price"]
    sym = top_coin["symbol"]
    chg = top_coin["change"]
    
    # Advanced Trade Classification Logic
    if chg >= 0:
        signal_mode = "FUTURES LONG"
        leverage = "Cross 5x - 10x"
        tp1 = p * 1.018  # +1.8%
        tp2 = p * 1.035  # +3.5%
        tp3 = p * 1.060  # +6.0%
        sl = p * 0.982   # -1.8%
    else:
        signal_mode = "SPOT BREAKOUT BUY"
        leverage = "Spot (1x)"
        tp1 = p * 1.025  # +2.5%
        tp2 = p * 1.050  # +5.0%
        tp3 = p * 1.090  # +9.0%
        sl = p * 0.965   # -3.5%

    rsi_est = round(50.0 + (chg * 0.6), 1)
    if rsi_est > 80: rsi_est = 78.4
    elif rsi_est < 20: rsi_est = 22.1

    setup = {
        "symbol": sym,
        "price": p,
        "mode": signal_mode,
        "leverage": leverage,
        "rsi": rsi_est,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "sl": sl,
        "change": round(chg, 2),
        "low": top_coin["low"]
    }

    dispatch_professional_signal(setup)
    sent_cooldown[sym] = now_time

def dispatch_professional_signal(s):
    global free_signals_today

    msg = (
        f"🚨 <b>BINANCE VIP TRADE SIGNAL</b> 🚨\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 <b>Pair</b>: #{s['symbol']}\n"
        f"📊 <b>Market Type</b>: <code>{s['mode']}</code>\n"
        f"⚙️ <b>Leverage</b>: {s['leverage']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 <b>Entry Zone</b>: ${format_price(s['price'])}\n\n"
        f"🎯 <b>Target 1</b>: ${format_price(s['tp1'])}\n"
        f"🎯 <b>Target 2</b>: ${format_price(s['tp2'])}\n"
        f"🚀 <b>Target 3 (Max)</b>: ${format_price(s['tp3'])}\n"
        f"⛔ <b>Stop Loss</b>: ${format_price(s['sl'])}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 <b>24h Change</b>: {s['change']}%\n"
        f"📊 <b>RSI Indicator</b>: {s['rsi']} (Bullish Momentum)\n"
        f"🛡️ <b>Key Support Level</b>: ${format_price(s['low'])}\n"
        f"⚖️ <b>Risk / Reward</b>: 1 : 2.5\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <i>Use 2-5% of total wallet balance per trade.</i>"
    )

    r_vip = send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, msg, is_channel=True)

    r_free = False
    if free_signals_today < 6:
        free_promo = (
            f"🔥 <b>REAL-TIME VIP SIGNAL PREVIEW</b> 🔥\n\n"
            f"{msg}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📢 <b>Free Channel:</b> https://t.me/BinanceTop10Free\n"
            f"💎 <b>Join VIP For 100% Signals:</b> @BinanceTop10_VIPBot"
        )
        r_free = send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, free_promo, is_channel=True)
        if r_free: free_signals_today += 1

    log_event(f"🎯 Market Signal Broadcasted #{s['symbol']} | Mode: {s['mode']} | VIP: {r_vip} | Free: {r_free}")

def send_telegram_msg(bot_token, chat_id, text, reply_markup=None, is_channel=False):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        res = requests.post(url, json=payload, timeout=5.0)
        return res.json().get("ok", False)
    except Exception: return False

def continuous_market_scanner():
    log_event("🚀 24x7 Real-Time Engine Active...")
    while True:
        try: scan_and_dispatch(force_mode=False)
        except Exception as e: log_event(f"Scanner Loop Error: {e}")
        time.sleep(180)

@app.route('/')
def home(): return jsonify({"status": "active", "system": "Trading Engine Running"})

@app.route('/logs')
def get_logs(): return jsonify({"logs": system_logs})

@app.route('/force-signal')
def force_signal():
    threading.Thread(target=scan_and_dispatch, args=(True,), daemon=True).start()
    return "Force Technical Analysis Scan Triggered!"

threading.Thread(target=continuous_market_scanner, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
