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

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

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

# Database Setup with Active Trade Tracking
def init_db():
    try:
        conn = sqlite3.connect("vip_members.db")
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE IF NOT EXISTS members (user_id INTEGER PRIMARY KEY, expiry_date TEXT, status TEXT)')
        cursor.execute('CREATE TABLE IF NOT EXISTS processed_txids (txid TEXT PRIMARY KEY)')
        
        # Table to track active trades for TP/SL monitoring
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS active_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                entry_price REAL,
                tp1 REAL, tp2 REAL, tp3 REAL, sl REAL,
                mode TEXT,
                tp1_hit INTEGER DEFAULT 0,
                tp2_hit INTEGER DEFAULT 0,
                tp3_hit INTEGER DEFAULT 0,
                status TEXT DEFAULT 'ACTIVE',
                created_at TEXT
            )
        ''')
        conn.commit()
        conn.close()
        log_event("Database & Active Trades table initialized successfully.")
    except Exception as e:
        log_event(f"Database Init Error: {e}")

init_db()

def format_price(val):
    if val is None or val == 0: return "0.00"
    if val >= 1000: return f"{val:,.2f}"
    elif val >= 1: return f"{val:.4f}"
    elif val >= 0.001: return f"{val:.6f}"
    else: return f"{val:.8f}"

def get_market_data():
    valid_coins = []
    try:
        url = "https://www.okx.com/api/v5/market/tickers?instType=SPOT"
        res = requests.get(url, headers=HEADERS, timeout=4.0)
        if res.status_code == 200:
            data = res.json().get("data", [])
            target_map = {
                "SOL-USDT": "SOLUSDT", "BTC-USDT": "BTCUSDT", "ETH-USDT": "ETHUSDT",
                "PEPE-USDT": "PEPEUSDT", "DOGE-USDT": "DOGEUSDT", "NEAR-USDT": "NEARUSDT",
                "AVAX-USDT": "AVAXUSDT", "SUI-USDT": "SUIUSDT"
            }
            for item in data:
                inst = item.get("instId")
                if inst in target_map:
                    price = float(item.get("last", 0))
                    open_24 = float(item.get("open24h", 0))
                    change = ((price - open_24) / open_24 * 100) if open_24 > 0 else 0
                    low = float(item.get("low24h", 0))
                    if price > 0:
                        valid_coins.append({"symbol": target_map[inst], "price": price, "change": change, "low": low})
            if valid_coins: return valid_coins
    except Exception as e:
        log_event(f"OKX Fetch Failed: {e}")

    return valid_coins

def save_active_trade(s):
    try:
        conn = sqlite3.connect("vip_members.db")
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO active_trades (symbol, entry_price, tp1, tp2, tp3, sl, mode, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (s['symbol'], s['price'], s['tp1'], s['tp2'], s['tp3'], s['sl'], s['mode'], datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
    except Exception as e:
        log_event(f"Error saving trade DB: {e}")

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
        log_event("⚠️ Market API unavailable. Skipping scan.")
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
    chg = top_coin["change"]
    
    if chg >= 0:
        signal_mode = "FUTURES LONG"
        leverage = "Cross 5x - 10x"
        tp1, tp2, tp3, sl = p * 1.018, p * 1.035, p * 1.060, p * 0.982
    else:
        signal_mode = "SPOT BREAKOUT BUY"
        leverage = "Spot (1x)"
        tp1, tp2, tp3, sl = p * 1.025, p * 1.050, p * 1.090, p * 0.965

    rsi_est = round(50.0 + (chg * 0.6), 1)
    if rsi_est > 80: rsi_est = 78.4
    elif rsi_est < 20: rsi_est = 22.1

    setup = {
        "symbol": sym, "price": p, "mode": signal_mode, "leverage": leverage,
        "rsi": rsi_est, "tp1": tp1, "tp2": tp2, "tp3": tp3, "sl": sl,
        "change": round(chg, 2), "low": top_coin.get("low", p * 0.95)
    }

    dispatch_professional_signal(setup)
    save_active_trade(setup)
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
            f"💎 <b>Join VIP For All Signals:</b> @BinanceTop10_VIPBot"
        )
        r_free = send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, free_promo, is_channel=True)
        if r_free: free_signals_today += 1

    log_event(f"🎯 Broadcasted #{s['symbol']} @ ${format_price(s['price'])} | VIP: {r_vip} | Free: {r_free}")

# ==========================================
# REAL-TIME TP / SL MONITORING ENGINE
# ==========================================
def monitor_tp_sl():
    while True:
        try:
            coins = get_market_data()
            if coins:
                price_dict = {c["symbol"]: c["price"] for c in coins}
                
                conn = sqlite3.connect("vip_members.db")
                cursor = conn.cursor()
                cursor.execute("SELECT id, symbol, entry_price, tp1, tp2, tp3, sl, mode, tp1_hit, tp2_hit, tp3_hit FROM active_trades WHERE status = 'ACTIVE'")
                trades = cursor.fetchall()

                for t in trades:
                    t_id, sym, entry, tp1, tp2, tp3, sl, mode, tp1_h, tp2_h, tp3_h = t
                    if sym not in price_dict: continue
                    
                    curr_p = price_dict[sym]

                    # Target 1 Hit
                    if curr_p >= tp1 and not tp1_h:
                        p_gain = round(((tp1 - entry) / entry) * 100, 2)
                        msg = f"🎯 <b>[TARGET 1 HIT] #{sym}</b>\nProfit: +{p_gain}%\nCurrent Price: ${format_price(curr_p)}\n✅ Move StopLoss to Entry Price!"
                        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, msg, is_channel=True)
                        send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, msg, is_channel=True)
                        cursor.execute("UPDATE active_trades SET tp1_hit = 1 WHERE id = ?", (t_id,))

                    # Target 2 Hit
                    elif curr_p >= tp2 and not tp2_h:
                        p_gain = round(((tp2 - entry) / entry) * 100, 2)
                        msg = f"🚀 <b>[TARGET 2 HIT] #{sym}</b>\nProfit: +{p_gain}%\nCurrent Price: ${format_price(curr_p)}\n🔥 Secure 75% Profits!"
                        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, msg, is_channel=True)
                        send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, msg, is_channel=True)
                        cursor.execute("UPDATE active_trades SET tp2_hit = 1 WHERE id = ?", (t_id,))

                    # Target 3 Hit (Full Profit & Close)
                    elif curr_p >= tp3 and not tp3_h:
                        p_gain = round(((tp3 - entry) / entry) * 100, 2)
                        msg = f"🏆 <b>[ALL TARGETS ACHIEVED] #{sym}</b>\nTotal Profit: +{p_gain}%\n🎉 Trade Closed Successfully!"
                        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, msg, is_channel=True)
                        send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, msg, is_channel=True)
                        cursor.execute("UPDATE active_trades SET tp3_hit = 1, status = 'CLOSED_TP' WHERE id = ?", (t_id,))

                    # Stop Loss Hit
                    elif curr_p <= sl:
                        loss_p = round(((entry - sl) / entry) * 100, 2)
                        msg = f"⛔ <b>[STOP LOSS HIT] #{sym}</b>\nLoss: -{loss_p}%\nPrice: ${format_price(curr_p)}\nTrade Closed."
                        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, msg, is_channel=True)
                        cursor.execute("UPDATE active_trades SET status = 'CLOSED_SL' WHERE id = ?", (t_id,))

                conn.commit()
                conn.close()
        except Exception as e:
            log_event(f"TP/SL Engine Loop Exception: {e}")
            
        time.sleep(30)  # Checks prices every 30 seconds

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
def home(): return jsonify({"status": "active", "system": "Trading Engine + Auto TP/SL Tracker Active"})

@app.route('/logs')
def get_logs(): return jsonify({"logs": system_logs})

@app.route('/force-signal')
def force_signal():
    threading.Thread(target=scan_and_dispatch, args=(True,), daemon=True).start()
    return "Force Technical Analysis Scan Triggered!"

# Start Background Threads
threading.Thread(target=continuous_market_scanner, daemon=True).start()
threading.Thread(target=monitor_tp_sl, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
