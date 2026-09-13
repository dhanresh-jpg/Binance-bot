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
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
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
        res = requests.get(url, headers=HEADERS, timeout=3.0)
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
# 4. LIVE PRICE & TECHNICAL ANALYSIS ENGINE
# ==========================================
def get_live_ticker_price(symbol):
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", headers=HEADERS, timeout=2.0)
        if res.status_code == 200:
            return float(res.json()["price"])
    except Exception:
        pass

    try:
        res = requests.get(f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}", headers=HEADERS, timeout=2.0)
        if res.status_code == 200:
            result_list = res.json().get("result", {}).get("list", [])
            if result_list and "lastPrice" in result_list[0]:
                return float(result_list[0]["lastPrice"])
    except Exception:
        pass
    return None

def fetch_klines(symbol, interval="1h", limit=30):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=2.5)
        if res.status_code == 200:
            data = res.json()
            closes = [float(candle[4]) for candle in data]
            highs = [float(candle[2]) for candle in data]
            lows = [float(candle[3]) for candle in data]
            return np.array(closes), np.array(highs), np.array(lows)
    except Exception:
        pass
    return None, None, None

def calculate_rsi(prices, period=14):
    deltas = np.diff(prices)
    seed = deltas[:period+1]
    up = seed[seed >= 0].sum()/period
    down = -seed[seed < 0].sum()/period
    rs = up/down if down != 0 else 0
    rsi = np.zeros_like(prices)
    rsi[:period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        upval = delta if delta > 0 else 0.0
        downval = -delta if delta < 0 else 0.0

        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        rs = up/down if down != 0 else 0
        rsi[i] = 100.0 - (100.0 / (1.0 + rs))

    return rsi[-1]

def calculate_ema(prices, span):
    alpha = 2 / (span + 1)
    ema = np.zeros_like(prices)
    ema[0] = prices[0]
    for i in range(1, len(prices)):
        ema[i] = alpha * prices[i] + (1 - alpha) * ema[i-1]
    return ema[-1]

def analyze_market_setup(symbol):
    closes, highs, lows = fetch_klines(symbol, interval="1h", limit=30)
    if closes is None or len(closes) < 15:
        return None, 0

    live_price = get_live_ticker_price(symbol)
    if live_price is None:
        live_price = closes[-1]

    rsi = calculate_rsi(closes, 14)
    ema20 = calculate_ema(closes, 20)
    recent_high = np.max(highs[-8:-1])

    score = 10 
    if live_price >= recent_high * 0.98: score += 40
    if live_price >= ema20: score += 30
    if 38 <= rsi <= 80: score += 20

    atr = np.mean(highs[-10:] - lows[-10:])
    setup = {
        "symbol": symbol,
        "price": live_price,
        "rsi": round(rsi, 2),
        "atr": atr,
        "score": score,
        "signal_type": "FUTURES" if rsi > 52 else "SPOT"
    }
    return setup, score

# ==========================================
# 5. CONTINUOUS SCANNER & SIGNAL DISPATCH
# ==========================================
def scan_and_dispatch(force_mode=False):
    global free_signals_today, last_reset_day
    log_event(f"🔍 Running Real-Time Scan (Force Mode: {force_mode})...")

    current_day = datetime.now(IST).day
    if current_day != last_reset_day:
        free_signals_today = 0
        last_reset_day = current_day

    watchlist = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
        "NEARUSDT", "FETUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT", "APTUSDT",
        "ADAUSDT", "DOTUSDT", "PEPEUSDT", "WIFUSDT", "SHIBUSDT", "LTCUSDT",
        "OPUSDT", "ARBUSDT", "INJUSDT", "TIAUSDT", "NEARUSDT"
    ]

    now_time = time.time()
    all_evaluated = []

    for sym in watchlist:
        if not force_mode and sym in sent_cooldown and (now_time - sent_cooldown[sym]) < 3600:
            continue

        setup, score = analyze_market_setup(sym)
        if setup:
            all_evaluated.append(setup)

    all_evaluated.sort(key=lambda x: x["score"], reverse=True)

    sent_count = 0
    if all_evaluated:
        target_setups = []
        if force_mode:
            target_setups = all_evaluated[:1] # Always send top coin on force scan
        else:
            target_setups = [s for s in all_evaluated if s["score"] >= 40][:1]

        for setup in target_setups:
            dispatch_single_signal(setup)
            sent_cooldown[setup["symbol"]] = now_time
            sent_count += 1
            time.sleep(2)

    if sent_count == 0:
        log_event("Scan completed: Waiting for market condition match.")

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
            f"📈 <b>Analysis</b>: EMA Support + Resistance Momentum\n"
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

    log_event(f"🎯 Live Breakout Signal Dispatched for #{sym} | VIP: {r_vip} | Free Count ({free_signals_today}/6): {r_free}")

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
    return jsonify({"status": "active", "system": "Real-Time Scoring TA Engine Running"})

@app.route('/logs')
def get_logs():
    return jsonify({"logs": system_logs})

@app.route('/force-signal')
def force_signal():
    threading.Thread(target=scan_and_dispatch, args=(True,), daemon=True).start()
    return "Force scan triggered! Check /logs in 10 seconds."

threading.Thread(target=process_free_bot_updates, daemon=True).start()
threading.Thread(target=process_bot_updates, daemon=True).start()
threading.Thread(target=continuous_market_scanner, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
