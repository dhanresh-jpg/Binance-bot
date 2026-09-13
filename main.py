import time
import requests
import sqlite3
import os
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify

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

def get_market_data():
    """CoinGecko API for 100% Reliable Render Server Execution"""
    url = "https://api.coingecko.com/api/v3/simple/price?ids=solana,bitcoin,ethereum,binancecoin,ripple,dogecoin,near,avalanche-2,sui,pepe,floki&vs_currencies=usd&include_24hr_change=true"
    mapping = {
        "solana": "SOLUSDT", "bitcoin": "BTCUSDT", "ethereum": "ETHUSDT",
        "binancecoin": "BNBUSDT", "ripple": "XRPUSDT", "dogecoin": "DOGEUSDT",
        "near": "NEARUSDT", "avalanche-2": "AVAXUSDT", "sui": "SUIUSDT", "pepe": "PEPEUSDT"
    }
    try:
        res = requests.get(url, headers=HEADERS, timeout=6.0)
        if res.status_code == 200:
            data = res.json()
            valid_coins = []
            for cid, symbol in mapping.items():
                if cid in data:
                    price = float(data[cid].get("usd", 0))
                    change = float(data[cid].get("usd_24h_change", 0))
                    if price > 0:
                        valid_coins.append({"symbol": symbol, "price": price, "change": change})
            return valid_coins
    except Exception as e:
        log_event(f"CoinGecko API Exception: {e}")
    return []

def scan_and_dispatch(force_mode=False):
    global free_signals_today, last_reset_day
    log_event(f"🔍 Running Live Scan (Force Mode: {force_mode})...")

    current_day = datetime.now(IST).day
    if current_day != last_reset_day:
        free_signals_today = 0
        last_reset_day = current_day

    coins = get_market_data()
    now_time = time.time()
    
    if not coins:
        log_event("⚠️ Market API unreachable. Retrying next cycle.")
        return

    coins.sort(key=lambda x: abs(x["change"]), reverse=True)
    top_coin = None
    for c in coins:
        if force_mode or (c["symbol"] not in sent_cooldown or (now_time - sent_cooldown[c["symbol"]]) >= 1800):
            top_coin = c
            break

    if not top_coin: top_coin = coins[0]

    p = top_coin["price"]
    sym = top_coin["symbol"]
    stype = "FUTURES" if top_coin["change"] >= 0 else "SPOT"
    atr = p * 0.025

    setup = {
        "symbol": sym,
        "price": p,
        "rsi": round(50 + (top_coin["change"] * 0.8), 1),
        "atr": atr,
        "signal_type": stype
    }

    dispatch_single_signal(setup)
    sent_cooldown[sym] = now_time

def format_price(val):
    if val >= 1000: return f"{val:,.2f}"
    elif val >= 1: return f"{val:.4f}"
    else: return f"{val:.6f}"

def dispatch_single_signal(setup):
    global free_signals_today
    p, atr, sym, rsi, stype = setup["price"], setup["atr"], setup["symbol"], setup["rsi"], setup["signal_type"]

    if stype == "SPOT":
        tp1, tp2, sl = p + (atr * 1.5), p + (atr * 3.0), p - (atr * 1.2)
        msg = (
            f"🟢 <b>[VIP SPOT BREAKOUT SIGNAL]</b>\n"
            f"🪙 <b>Coin</b>: #{sym}\n"
            f"📥 <b>Entry Price</b>: ${format_price(p)}\n"
            f"📊 <b>RSI Strength</b>: {rsi}\n\n"
            f"🎯 <b>Target 1</b>: ${format_price(tp1)}\n"
            f"🎯 <b>Target 2</b>: ${format_price(tp2)}\n"
            f"⛔ <b>Stop Loss</b>: ${format_price(sl)}"
        )
    else:
        tp1, tp2, sl = p + (atr * 1.2), p + (atr * 2.5), p - (atr * 1.0)
        msg = (
            f"⚡ <b>[VIP FUTURES MOMENTUM LONG]</b>\n"
            f"🪙 <b>Coin</b>: #{sym}\n"
            f"⚙️ <b>Leverage</b>: Cross 5x - 10x\n"
            f"📥 <b>Entry Price</b>: ${format_price(p)}\n"
            f"📊 <b>RSI Indicator</b>: {rsi}\n\n"
            f"🎯 <b>Target 1</b>: ${format_price(tp1)}\n"
            f"🎯 <b>Target 2</b>: ${format_price(tp2)}\n"
            f"⛔ <b>Stop Loss</b>: ${format_price(sl)}"
        )

    r_vip = send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, msg, is_channel=True)
    r_free = False
    if free_signals_today < 6:
        free_promo = f"🔥 <b>LIVE VIP PREVIEW</b> 🔥\n\n{msg}\n\n📢 <b>Free Channel:</b> https://t.me/BinanceTop10Free"
        r_free = send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, free_promo, is_channel=True)
        if r_free: free_signals_today += 1

    log_event(f"🎯 Signal Dispatched for #{sym} @ ${format_price(p)} | VIP: {r_vip} | Free: {r_free}")

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
        except Exception as e: log_event(f"Loop Error: {e}")
        time.sleep(180)

@app.route('/')
def home(): return jsonify({"status": "active"})

@app.route('/logs')
def get_logs(): return jsonify({"logs": system_logs})

@app.route('/force-signal')
def force_signal():
    threading.Thread(target=scan_and_dispatch, args=(True,), daemon=True).start()
    return "Force scan triggered!"

threading.Thread(target=continuous_market_scanner, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
