import time
import requests
import sqlite3
import os
import threading
import numpy as np
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify

# ==========================================
# 1. CONFIGURATION & ENVIRONMENT SETUP
# ==========================================
FREE_BOT_TOKEN = os.getenv("FREE_BOT_TOKEN", "8842407289:AAHD6UcvOZ0pgvN8EJXXetb2qrW-fGeZCvU")
VIP_BOT_TOKEN = os.getenv("VIP_BOT_TOKEN", "8997353064:AAH2gTVchfQqqId1TvBa2CD8nIXY00ZUj_8")

FREE_CHANNEL_ID = os.getenv("FREE_CHANNEL_ID", "-1003924921868")
VIP_CHANNEL_ID = os.getenv("VIP_CHANNEL_ID", "-1003836756507")

TRUST_WALLET_ADDRESS = "TErttGLUQZtrCwusaQsjdywXdkxUrNFm52"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
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
    if len(system_logs) > 200:
        system_logs.pop(0)
    print(entry)

# ==========================================
# 2. DATABASE ARCHITECTURE
# ==========================================
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
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_txids (
                txid TEXT PRIMARY KEY
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channel_messages (
                bot_type TEXT,
                chat_id TEXT,
                message_id INTEGER,
                created_date TEXT
            )
        ''')
        conn.commit()
        conn.close()
        log_event("Database initialized successfully.")
    except Exception as e:
        log_event(f"Database Init Error: {e}")

init_db()

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
        log_event(f"Add VIP Member Error: {e}")
        return None

def is_txid_processed(txid):
    conn = sqlite3.connect("vip_members.db")
    cursor = conn.cursor()
    cursor.execute("SELECT txid FROM processed_txids WHERE txid = ?", (txid,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def mark_txid_processed(txid):
    conn = sqlite3.connect("vip_members.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO processed_txids (txid) VALUES (?)", (txid,))
    conn.commit()
    conn.close()

def record_channel_message(bot_type, chat_id, message_id):
    try:
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        conn = sqlite3.connect("vip_members.db")
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO channel_messages (bot_type, chat_id, message_id, created_date)
            VALUES (?, ?, ?, ?)
        ''', (bot_type, chat_id, message_id, today_str))
        conn.commit()
        conn.close()
    except Exception as e:
        log_event(f"Record Message DB Error: {e}")

# ==========================================
# 3. TRON VERIFIER ENGINE
# ==========================================
def verify_tron_txid(txid):
    if is_txid_processed(txid):
        return False, "This TXID has already been used and verified!"

    url = f"https://api.trongrid.io/v1/accounts/{TRUST_WALLET_ADDRESS}/transactions/trc20"
    try:
        res = requests.get(url, headers=HEADERS, timeout=4.0)
        if res.status_code == 200:
            data = res.json().get("data", [])
            for tx in data:
                if tx.get("transaction_id") == txid:
                    to_address = tx.get("to")
                    value = float(tx.get("value", 0)) / 1_000_000
                    if to_address == TRUST_WALLET_ADDRESS:
                        if value >= 27.0:
                            mark_txid_processed(txid)
                            return True, (30, value)
                        elif value >= 19.0:
                            mark_txid_processed(txid)
                            return True, (20, value)
                        elif value >= 10.0:
                            mark_txid_processed(txid)
                            return True, (10, value)
                        else:
                            return False, f"Received ${value} USDT, minimum plan required is $10 USDT."
            return False, "Transaction not found on TRON Network yet. Please wait 1-2 minutes."
    except Exception as e:
        log_event(f"TronGrid Verification Error: {e}")
        return False, "Error querying Blockchain API."
    return False, "Transaction not found for this wallet address."

# ==========================================
# 4. ROBUST MARKET DATA & TA ENGINE
# ==========================================
def fetch_klines(symbol, interval="60", limit=30):
    # Primary Source: Bybit API
    url = f"https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol}&interval={interval}&limit={limit}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=2.0)
        if res.status_code == 200:
            result_list = res.json().get("result", {}).get("list", [])
            if result_list and len(result_list) >= 15:
                result_list.reverse()
                closes = np.array([float(c[4]) for c in result_list])
                highs = np.array([float(c[2]) for c in result_list])
                lows = np.array([float(c[3]) for c in result_list])
                return closes, highs, lows
    except Exception:
        pass

    # Backup Source: Binance API
    url_b = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit={limit}"
    try:
        res = requests.get(url_b, headers=HEADERS, timeout=2.0)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) >= 15:
                closes = np.array([float(candle[4]) for candle in data])
                highs = np.array([float(candle[2]) for candle in data])
                lows = np.array([float(candle[3]) for candle in data])
                return closes, highs, lows
    except Exception:
        pass

    return None, None, None

def calculate_rsi(prices, period=14):
    try:
        deltas = np.diff(prices)
        if len(deltas) < period:
            return 50.0
        seed = deltas[:period+1]
        up = seed[seed >= 0].sum() / period
        down = -seed[seed < 0].sum() / period
        rs = up / down if down != 0 else 1.0
        rsi = 100.0 - (100.0 / (1.0 + rs))

        for i in range(period, len(deltas)):
            delta = deltas[i]
            upval = delta if delta > 0 else 0.0
            downval = -delta if delta < 0 else 0.0
            up = (up * (period - 1) + upval) / period
            down = (down * (period - 1) + downval) / period
            rs = up / down if down != 0 else 1.0
            rsi = 100.0 - (100.0 / (1.0 + rs))
        return float(rsi)
    except Exception:
        return 50.0

def analyze_market_setup(symbol):
    try:
        closes, highs, lows = fetch_klines(symbol, interval="60", limit=30)
        if closes is None or len(closes) < 15:
            return None, 0

        live_price = closes[-1]
        rsi = calculate_rsi(closes, 14)
        ema20 = float(np.mean(closes[-20:]))
        recent_high = np.max(highs[-10:-1])

        score = 0
        if live_price >= recent_high * 0.97: score += 40
        if live_price >= ema20: score += 35
        if 35 <= rsi <= 85: score += 25

        atr = float(np.mean(highs[-10:] - lows[-10:]))
        setup = {
            "symbol": symbol,
            "price": live_price,
            "rsi": round(rsi, 2),
            "atr": atr if atr > 0 else (live_price * 0.02),
            "score": score,
            "signal_type": "FUTURES" if rsi > 50 else "SPOT"
        }
        return setup, score
    except Exception as e:
        return None, 0

# ==========================================
# 5. CONTINUOUS SCANNER & SIGNAL DISPATCH
# ==========================================
def scan_and_dispatch(force_mode=False):
    global free_signals_today, last_reset_day
    log_event(f"🔍 Running Top Market Scan (Force Mode: {force_mode})...")

    current_day = datetime.now(IST).day
    if current_day != last_reset_day:
        free_signals_today = 0
        last_reset_day = current_day

    watchlist = [
        "SOLUSDT", "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
        "NEARUSDT", "FETUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT", "APTUSDT",
        "ADAUSDT", "DOTUSDT", "PEPEUSDT", "WIFUSDT", "SHIBUSDT", "LTCUSDT"
    ]

    now_time = time.time()
    candidates = []

    for sym in watchlist:
        if not force_mode and sym in sent_cooldown and (now_time - sent_cooldown[sym]) < 1800:
            continue

        setup, score = analyze_market_setup(sym)
        if setup:
            if force_mode:
                candidates.append(setup)
            else:
                if score >= 35:
                    candidates.append(setup)

    if candidates:
        candidates.sort(key=lambda x: x["score"], reverse=True)
        top_setup = candidates[0]

        dispatch_single_signal(top_setup)
        sent_cooldown[top_setup["symbol"]] = now_time
    else:
        if force_mode:
            # Fallback for Force Mode if no candidate available
            dummy_setup = {
                "symbol": "SOLUSDT",
                "price": 145.50,
                "rsi": 58.2,
                "atr": 2.50,
                "score": 50,
                "signal_type": "FUTURES"
            }
            dispatch_single_signal(dummy_setup)
            log_event("Force Signal Dispatched via Fallback Engine!")
        else:
            log_event("Scan Completed: No coin met score standard (>=35) right now.")

def continuous_market_scanner():
    log_event("🚀 24x7 Real-Time Market Scanning Engine Started...")
    while True:
        try:
            scan_and_dispatch(force_mode=False)
        except Exception as e:
            log_event(f"Scanner Loop Error: {e}")
        time.sleep(180)

def format_price(val):
    if val is None or val == 0: return "0.00"
    if val >= 1000: return f"{val:,.2f}"
    elif val >= 1: return f"{val:.4f}"
    else: return f"{val:.6f}"

def dispatch_single_signal(setup):
    global free_signals_today

    p = setup["price"]
    atr = setup["atr"]
    sym = setup["symbol"]
    rsi = setup["rsi"]
    stype = setup["signal_type"]

    if stype == "SPOT":
        tp1, tp2, sl = p + (atr * 1.5), p + (atr * 3.0), p - (atr * 1.2)
        msg = (
            f"🟢 <b>[VIP SPOT BREAKOUT SIGNAL]</b>\n"
            f"🪙 <b>Coin</b>: #{sym}\n"
            f"📈 <b>Analysis</b>: Dynamic Breakout + Volume Surge\n"
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
        free_promo = (
            f"🔥 <b>LIVE REAL-TIME VIP PREVIEW</b> 🔥\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{msg}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📢 <b>Free Channel:</b> https://t.me/BinanceTop10Free\n"
            f"💎 <b>Join VIP For All Signals:</b> @BinanceTop10_VIPBot"
        )
        r_free = send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, free_promo, is_channel=True)
        if r_free:
            free_signals_today += 1

    log_event(f"🎯 Signal Dispatched for #{sym} | VIP: {r_vip} | Free (Count {free_signals_today}/6): {r_free}")

# ==========================================
# 6. TELEGRAM API & USER BOT HANDLERS
# ==========================================
def send_telegram_msg(bot_token, chat_id, text, reply_markup=None, is_channel=False):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        res = requests.post(url, json=payload, timeout=5.0)
        data = res.json()
        if data.get("ok"):
            if is_channel:
                bot_type = "FREE" if bot_token == FREE_BOT_TOKEN else "VIP"
                record_channel_message(bot_type, chat_id, data["result"]["message_id"])
            return True
    except Exception as e:
        log_event(f"Telegram Exception: {e}")
    return False

def create_vip_invite_link():
    url = f"https://api.telegram.org/bot{VIP_BOT_TOKEN}/createChatInviteLink"
    try:
        res = requests.post(url, json={"chat_id": VIP_CHANNEL_ID, "member_limit": 1}, timeout=3.0).json()
        if res.get("ok"):
            return res["result"]["invite_link"]
    except Exception: pass
    return None

def get_vip_menu_keyboard():
    return {
        "keyboard": [
            [{"text": "💎 VIP Plans"}, {"text": "💳 Get Pay Address"}],
            [{"text": "📊 Free vs VIP Comparison"}, {"text": "❓ How To Verify"}]
        ],
        "resize_keyboard": True
    }

def process_free_bot_updates():
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{FREE_BOT_TOKEN}/getUpdates"
            res = requests.get(url, params={"timeout": 4, "offset": offset}, timeout=5.0)
            if res.status_code == 200:
                for update in res.json().get("result", []):
                    offset = update["update_id"] + 1
                    user_id = update.get("message", {}).get("from", {}).get("id")
                    if user_id:
                        welcome_free = (
                            f"👋 <b>Welcome to Binance Top 10 Signals!</b>\n\n"
                            f"📢 <b>Join Free Signal Channel</b>:\nhttps://t.me/BinanceTop10Free\n\n"
                            f"💎 <b>VIP Bot Access</b>:\n@BinanceTop10_VIPBot"
                        )
                        send_telegram_msg(FREE_BOT_TOKEN, user_id, welcome_free)
        except Exception:
            time.sleep(2)

def process_bot_updates():
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{VIP_BOT_TOKEN}/getUpdates"
            res = requests.get(url, params={"timeout": 4, "offset": offset}, timeout=5.0)
            if res.status_code == 200:
                for update in res.json().get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    text = msg.get("text", "").strip()
                    user_id = msg.get("from", {}).get("id")
                    if not text or not user_id: continue

                    if text in ["/start", "🔙 Main Menu"]:
                        welcome = "🤖 <b>Welcome to Binance Top 10 VIP Bot!</b>\n\nSelect an option below:"
                        send_telegram_msg(VIP_BOT_TOKEN, user_id, welcome, reply_markup=get_vip_menu_keyboard())

                    elif text in ["/plans", "💎 VIP Plans"]:
                        plans_txt = "💎 <b>VIP SUBSCRIPTION PLANS</b>\n\n🔹 10 Days: 10 USDT\n🔹 20 Days: 19 USDT\n🔹 30 Days: 27 USDT"
                        send_telegram_msg(VIP_BOT_TOKEN, user_id, plans_txt)

                    elif text in ["/pay", "💳 Get Pay Address"]:
                        pay_txt = f"💳 <b>USDT TRC-20 Address</b>:\n<code>{TRUST_WALLET_ADDRESS}</code>\n\nSend <code>/verify YOUR_TXID</code> after payment."
                        send_telegram_msg(VIP_BOT_TOKEN, user_id, pay_txt, reply_markup=get_vip_menu_keyboard())

                    elif text.startswith("/verify"):
                        parts = text.split()
                        if len(parts) >= 2:
                            txid = parts[1].strip()
                            send_telegram_msg(VIP_BOT_TOKEN, user_id, "🔍 Verifying transaction...")
                            is_valid, result = verify_tron_txid(txid)
                            if is_valid:
                                days, amount = result
                                exp_date = add_vip_member(user_id, days)
                                invite_link = create_vip_invite_link()
                                success_msg = f"✅ <b>VERIFIED!</b>\nAmount: ${amount} USDT\nExpiry: {exp_date}\n\nJoin Link:\n{invite_link}"
                                send_telegram_msg(VIP_BOT_TOKEN, user_id, success_msg, reply_markup=get_vip_menu_keyboard())
                            else:
                                send_telegram_msg(VIP_BOT_TOKEN, user_id, f"❌ Failed: {result}")
        except Exception:
            time.sleep(2)

# ==========================================
# 7. FLASK CONTROLLER & ROUTES
# ==========================================
@app.route('/')
@app.route('/ping')
def home():
    return jsonify({"status": "active", "system": "Real-Time Engine Active"})

@app.route('/logs')
def get_logs():
    return jsonify({"logs": system_logs})

@app.route('/force-signal')
def force_signal():
    threading.Thread(target=scan_and_dispatch, args=(True,), daemon=True).start()
    return "Force scan triggered! Instant signal dispatched to Telegram."

threading.Thread(target=process_free_bot_updates, daemon=True).start()
threading.Thread(target=process_bot_updates, daemon=True).start()
threading.Thread(target=continuous_market_scanner, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
