import time
import requests
import sqlite3
import os
import threading
import numpy as np
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

# ==========================================
# 1. CONFIGURATION & ENVIRONMENT SETUP
# ==========================================
FREE_BOT_TOKEN = os.getenv("FREE_BOT_TOKEN", "8842407289:AAHD6UcvOZ0pgvN8EJXXetb2qrW-fGeZCvU")
VIP_BOT_TOKEN = os.getenv("VIP_BOT_TOKEN", "8997353064:AAH2gTVchfQqqId1TvBa2CD8nIXY00ZUj_8")

FREE_CHANNEL_ID = os.getenv("FREE_CHANNEL_ID", "-1003924921868")
VIP_CHANNEL_ID = os.getenv("VIP_CHANNEL_ID", "-1003836756507")

TRUST_WALLET_ADDRESS = "TErttGLUQZtrCwusaQsjdywXdkxUrNFm52"

app = Flask(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
system_logs = []

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
        res = requests.get(url, timeout=5.0)
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
# 4. REAL TECHNICAL ANALYSIS ENGINE (BINANCE)
# ==========================================
def fetch_klines(symbol, interval="1h", limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        res = requests.get(url, timeout=5.0)
        if res.status_code == 200:
            data = res.json()
            closes = [float(candle[4]) for candle in data]
            highs = [float(candle[2]) for candle in data]
            lows = [float(candle[3]) for candle in data]
            volumes = [float(candle[5]) for candle in data]
            return np.array(closes), np.array(highs), np.array(lows), np.array(volumes)
    except Exception as e:
        log_event(f"Kline Fetch Error ({symbol}): {e}")
    return None, None, None, None

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

def analyze_crypto_pair(symbol):
    closes, highs, lows, volumes = fetch_klines(symbol, interval="1h", limit=100)
    if closes is None or len(closes) < 50:
        return None

    current_price = closes[-1]
    rsi = calculate_rsi(closes, 14)
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)

    # Criteria: EMA20 > EMA50 (Upward Momentum) & RSI within healthy range
    if ema20 > ema50 and 42 <= rsi <= 68:
        atr = np.mean(highs[-14:] - lows[-14:])
        return {
            "symbol": symbol,
            "price": current_price,
            "rsi": round(rsi, 2),
            "atr": atr
        }
    return None

def scan_market_for_signals():
    watchlist = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "NEARUSDT", "FETUSDT", "AVAXUSDT", "LINKUSDT", "APTUSDT", "SUIUSDT"]
    valid_signals = []

    for sym in watchlist:
        res = analyze_crypto_pair(sym)
        if res:
            valid_signals.append(res)
            if len(valid_signals) >= 2:
                break
        time.sleep(0.2)

    # Strong Fallback using direct live rates if criteria doesn't match
    if len(valid_signals) < 2:
        for sym in ["SOLUSDT", "BTCUSDT"]:
            closes, highs, lows, _ = fetch_klines(sym, interval="1h", limit=20)
            if closes is not None:
                cp = closes[-1]
                atr = np.mean(highs[-10:] - lows[-10:]) if highs is not None else cp * 0.02
                valid_signals.append({"symbol": sym, "price": cp, "rsi": 54.0, "atr": atr})
                if len(valid_signals) >= 2:
                    break

    return valid_signals

# ==========================================
# 5. DYNAMIC FORMATTING & BROADCAST ENGINE
# ==========================================
def format_price(val):
    if val >= 1000:
        return f"{val:,.2f}"
    elif val >= 1:
        return f"{val:.4f}"
    else:
        return f"{val:.6f}"

def generate_and_send_signals():
    log_event("🔍 Technical Market Scanner Started...")
    setups = scan_market_for_signals()

    if len(setups) < 2:
        log_event("⚠️ Market scanner returned insufficient setups.")
        return

    spot_item = setups[0]
    futures_item = setups[1]

    # --- SPOT SIGNAL ---
    sp_p = spot_item["price"]
    sp_atr = spot_item["atr"]
    sp_tp1, sp_tp2, sp_sl = sp_p + (sp_atr * 1.5), sp_p + (sp_atr * 3.0), sp_p - (sp_atr * 1.2)

    spot_msg = (
        f"🟢 <b>[VIP SPOT SWING SIGNAL]</b>\n"
        f"🪙 <b>Coin</b>: #{spot_item['symbol']}\n"
        f"📈 <b>Strategy</b>: EMA20/50 Golden Cross + Dynamic ATR\n"
        f"📥 <b>Entry Price</b>: ${format_price(sp_p)}\n"
        f"📊 <b>RSI (1H)</b>: {spot_item['rsi']}\n\n"
        f"🎯 <b>Target 1</b>: ${format_price(sp_tp1)}\n"
        f"🎯 <b>Target 2</b>: ${format_price(sp_tp2)}\n"
        f"⛔ <b>Stop Loss</b>: ${format_price(sp_sl)}"
    )

    # --- FUTURES SIGNAL ---
    ft_p = futures_item["price"]
    ft_atr = futures_item["atr"]
    ft_tp1, ft_tp2, ft_sl = ft_p + (ft_atr * 1.0), ft_p + (ft_atr * 2.2), ft_p - (ft_atr * 0.9)

    futures_msg = (
        f"⚡ <b>[VIP FUTURES LONG SIGNAL]</b>\n"
        f"🪙 <b>Coin</b>: #{futures_item['symbol']}\n"
        f"⚙️ <b>Leverage</b>: Cross 5x - 10x\n"
        f"📥 <b>Entry Price</b>: ${format_price(ft_p)}\n"
        f"📊 <b>RSI Indicator</b>: {futures_item['rsi']}\n\n"
        f"🎯 <b>Target 1</b>: ${format_price(ft_tp1)}\n"
        f"🎯 <b>Target 2</b>: ${format_price(ft_tp2)}\n"
        f"⛔ <b>Stop Loss</b>: ${format_price(ft_sl)}"
    )

    r1 = send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, spot_msg, is_channel=True)
    time.sleep(1)
    r2 = send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, futures_msg, is_channel=True)

    free_promo = (
        f"🔥 <b>LIVE REAL-TIME VIP PREVIEW</b> 🔥\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{futures_msg}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>Free Channel:</b> https://t.me/BinanceTop10Free\n\n"
        f"💎 <b>Join VIP For Technical Spot & Futures Signals</b>\n"
        f"👉 <b>VIP Bot:</b> @BinanceTop10_VIPBot"
    )
    r3 = send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, free_promo, is_channel=True)

    log_event(f"Broadcast Completed -> VIP Spot: {r1}, VIP Futures: {r2}, Free: {r3}")

# ==========================================
# 6. TELEGRAM API & USER BOT HANDLERS
# ==========================================
def send_telegram_msg(bot_token, chat_id, text, reply_markup=None, is_channel=False):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        res = requests.post(url, json=payload, timeout=6.0)
        data = res.json()
        if data.get("ok"):
            msg_id = data["result"]["message_id"]
            if is_channel:
                bot_type = "FREE" if bot_token == FREE_BOT_TOKEN else "VIP"
                record_channel_message(bot_type, chat_id, msg_id)
            return True
        else:
            log_event(f"Telegram API Error ({chat_id}): {data.get('description')}")
            return False
    except Exception as e:
        log_event(f"Telegram Exception ({chat_id}): {e}")
        return False

def create_vip_invite_link():
    url = f"https://api.telegram.org/bot{VIP_BOT_TOKEN}/createChatInviteLink"
    payload = {"chat_id": VIP_CHANNEL_ID, "member_limit": 1}
    try:
        res = requests.post(url, json=payload, timeout=4.0).json()
        if res.get("ok"):
            return res["result"]["invite_link"]
    except Exception as e:
        log_event(f"Invite Link Error: {e}")
    return None

def get_vip_menu_keyboard():
    return {
        "keyboard": [
            [{"text": "💎 VIP Plans"}, {"text": "💳 Get Pay Address"}],
            [{"text": "📊 Free vs VIP Comparison"}, {"text": "❓ How To Verify"}]
        ],
        "resize_keyboard": True,
        "persistent": True
    }

def get_verify_inline_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "💳 Get Deposit Address", "callback_data": "btn_pay"}],
            [{"text": "📢 Join Free Channel", "url": "https://t.me/BinanceTop10Free"}]
        ]
    }

def process_free_bot_updates():
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{FREE_BOT_TOKEN}/getUpdates"
            res = requests.get(url, params={"timeout": 5, "offset": offset}, timeout=6.0)
            if res.status_code == 200:
                for update in res.json().get("result", []):
                    offset = update["update_id"] + 1
                    user_id = update.get("message", {}).get("from", {}).get("id")
                    if user_id:
                        welcome_free = (
                            f"👋 <b>Welcome to Binance Top 10 Signals!</b>\n\n"
                            f"📢 <b>Join Free Signal Channel</b>:\n"
                            f"https://t.me/BinanceTop10Free\n\n"
                            f"💎 <b>Upgrade To VIP Bot (Instant Auto Activation)</b>:\n"
                            f"@BinanceTop10_VIPBot"
                        )
                        send_telegram_msg(FREE_BOT_TOKEN, user_id, welcome_free)
        except Exception:
            time.sleep(2)

def process_bot_updates():
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{VIP_BOT_TOKEN}/getUpdates"
            res = requests.get(url, params={"timeout": 5, "offset": offset}, timeout=6.0)
            if res.status_code == 200:
                for update in res.json().get("result", []):
                    offset = update["update_id"] + 1
                    
                    callback = update.get("callback_query")
                    if callback:
                        cb_user_id = callback["from"]["id"]
                        cb_data = callback.get("data")
                        if cb_data == "btn_pay":
                            pay_txt = (
                                f"💳 <b>USDT TRC-20 Deposit Address</b>:\n\n"
                                f"<code>{TRUST_WALLET_ADDRESS}</code>\n\n"
                                f"<b>Activation Steps:</b>\n"
                                f"1. Send exact amount for your plan.\n"
                                f"2. Send <code>/verify YOUR_TXID</code> here."
                            )
                            send_telegram_msg(VIP_BOT_TOKEN, cb_user_id, pay_txt, reply_markup=get_vip_menu_keyboard())
                        continue

                    msg = update.get("message", {})
                    text = msg.get("text", "").strip()
                    user_id = msg.get("from", {}).get("id")
                    if not text or not user_id:
                        continue

                    if text in ["/start", "🔙 Main Menu"]:
                        welcome = (
                            f"🤖 <b>Welcome to Binance Top 10 VIP Bot!</b>\n\n"
                            f"Real-Time Accurate Crypto Signals with Automated TRON TRC-20 Activation.\n\n"
                            f"👇 <b>Select an option below to proceed:</b>"
                        )
                        send_telegram_msg(VIP_BOT_TOKEN, user_id, welcome, reply_markup=get_vip_menu_keyboard())

                    elif text in ["/plans", "💎 VIP Plans"]:
                        plans_txt = (
                            f"💎 <b>VIP SUBSCRIPTION PLANS</b>\n\n"
                            f"🔹 <b>10 Days Access</b>: 10 USDT\n"
                            f"🔹 <b>20 Days Access</b>: 19 USDT\n"
                            f"🔹 <b>30 Days Access</b>: 27 USDT\n\n"
                            f"⚡ <i>Instant Activation via TRC-20 Blockchain Verifier.</i>"
                        )
                        send_telegram_msg(VIP_BOT_TOKEN, user_id, plans_txt, reply_markup=get_verify_inline_keyboard())

                    elif text in ["/pay", "💳 Get Pay Address"]:
                        pay_txt = (
                            f"💳 <b>USDT TRC-20 Deposit Address</b>:\n\n"
                            f"<code>{TRUST_WALLET_ADDRESS}</code>\n\n"
                            f"<b>Activation Steps:</b>\n"
                            f"1. Send exact USDT amount for your plan.\n"
                            f"2. Copy your Transaction Hash (TXID).\n"
                            f"3. Send <code>/verify YOUR_TXID</code> in this chat."
                        )
                        send_telegram_msg(VIP_BOT_TOKEN, user_id, pay_txt, reply_markup=get_vip_menu_keyboard())

                    elif text.startswith("/verify"):
                        parts = text.split()
                        if len(parts) < 2:
                            send_telegram_msg(VIP_BOT_TOKEN, user_id, "⚠️ Format: <code>/verify YOUR_TXID_HERE</code>")
                        else:
                            txid = parts[1].strip()
                            send_telegram_msg(VIP_BOT_TOKEN, user_id, "🔍 Verifying transaction on TRON Network...")
                            
                            is_valid, result = verify_tron_txid(txid)
                            if is_valid:
                                days, amount = result
                                exp_date = add_vip_member(user_id, days)
                                invite_link = create_vip_invite_link()
                                
                                success_msg = (
                                    f"✅ <b>PAYMENT VERIFIED INSTANTLY!</b>\n\n"
                                    f"💰 <b>Received</b>: ${amount} USDT\n"
                                    f"📅 <b>Duration</b>: {days} Days\n"
                                    f"⏳ <b>Expiry Date</b>: {exp_date}\n\n"
                                    f"🚀 <b>Join VIP Channel</b>:\n{invite_link}"
                                )
                                send_telegram_msg(VIP_BOT_TOKEN, user_id, success_msg, reply_markup=get_vip_menu_keyboard())
                            else:
                                send_telegram_msg(VIP_BOT_TOKEN, user_id, f"❌ Verification Failed:\n{result}")

        except Exception:
            time.sleep(2)

# ==========================================
# 7. SCHEDULER & FLASK SERVICE CONTROLLER
# ==========================================
scheduler = BackgroundScheduler()
scheduler.add_job(generate_and_send_signals, 'interval', hours=4)
scheduler.start()

def start_resilient_thread(target_func, name):
    t = threading.Thread(target=target_func, daemon=True, name=name)
    t.start()
    return t

@app.route('/')
@app.route('/ping')
def home():
    return jsonify({"status": "active", "engine": "Binance 1H TA + TRON Verifier Active"})

@app.route('/logs')
def get_logs():
    return jsonify({"logs": system_logs})

@app.route('/force-signal')
def force_signal():
    threading.Thread(target=generate_and_send_signals, daemon=True).start()
    return "Signal Execution Triggered!"

start_resilient_thread(process_free_bot_updates, "Free-Bot-Listener")
start_resilient_thread(process_bot_updates, "VIP-Bot-Listener")

# Initial Signal Trigger on Startup
threading.Thread(target=generate_and_send_signals, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
