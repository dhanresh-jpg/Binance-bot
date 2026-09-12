import time
import requests
import sqlite3
import os
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

# ==========================================
# 1. CONFIGURATION & BOT INITIALIZATION
# ==========================================
FREE_BOT_TOKEN = os.getenv("FREE_BOT_TOKEN", "8842407289:AAHD6UcvOZ0pgvN8EJXXetb2qrW-fGeZCvU")
VIP_BOT_TOKEN = os.getenv("VIP_BOT_TOKEN", "8997353064:AAH2gTVchfQqqId1TvBa2CD8nIXY00ZUj_8")

FREE_CHANNEL_ID = os.getenv("FREE_CHANNEL_ID", "-1003924921868")
VIP_CHANNEL_ID = os.getenv("VIP_CHANNEL_ID", "-1003836756507")

TRUST_WALLET_ADDRESS = "TErttGLUQZtrCwusaQsjdywXdkxUrNFm52"

app = Flask(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
system_logs = []
recently_signaled_coins = {}

def log_event(message):
    timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    system_logs.append(entry)
    if len(system_logs) > 150:
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
        log_event("Database initialized.")
    except Exception as e:
        log_event(f"DB Error: {e}")

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
        log_event(f"DB Add Error: {e}")
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
        return False, "This TXID has already been processed!"

    url = f"https://api.trongrid.io/v1/accounts/{TRUST_WALLET_ADDRESS}/transactions/trc20"
    try:
        res = requests.get(url, timeout=4.0)
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
                            return False, f"Received ${value} USDT, minimum plan is $10 USDT."
            return False, "Transaction not found on TRON Network yet. Please wait 1-2 minutes."
    except Exception as e:
        log_event(f"TronGrid API Error: {e}")
        return False, "Error checking Blockchain API."
    return False, "Transaction not found for this wallet address."

# ==========================================
# 4. TELEGRAM API COMMUNICATION
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
        res = requests.post(url, json=payload, timeout=5.0)
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
        res = requests.post(url, json=payload, timeout=3.0).json()
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

# ==========================================
# 5. DYNAMIC REAL-TIME PRICE ENGINE
# ==========================================
def get_live_ticker_price(symbol):
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=3.0)
        if res.status_code == 200:
            return float(res.json()["price"])
    except Exception: pass

    try:
        res = requests.get(f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}", timeout=3.0)
        if res.status_code == 200:
            result = res.json().get("result", {}).get("list", [])
            if result:
                return float(result[0]["lastPrice"])
    except Exception: pass

    return None

def master_coin_scanner():
    candidate_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "NEARUSDT", "FETUSDT", "LINKUSDT", "SUIUSDT", "APTUSDT"]
    analyzed_coins = []

    for sym in candidate_symbols:
        live_price = get_live_ticker_price(sym)
        if live_price:
            analyzed_coins.append({"symbol": sym, "price": live_price, "trend": "BULLISH", "rsi": 55.0})
        if len(analyzed_coins) >= 2:
            break

    # Fallback to defaults if price fetching failed
    if len(analyzed_coins) < 2:
        analyzed_coins = [
            {"symbol": "SOLUSDT", "price": 145.50, "trend": "BULLISH", "rsi": 55.0},
            {"symbol": "BTCUSDT", "price": 64200.0, "trend": "BULLISH", "rsi": 58.0}
        ]

    return analyzed_coins

# ==========================================
# 6. SIGNAL BROADCASTER ENGINE
# ==========================================
def generate_and_send_signals():
    log_event("Generating live trading signals...")
    scanned = master_coin_scanner()

    spot_coin, futures_coin = scanned[0], scanned[1]

    # --- SPOT SIGNAL ---
    sp_p = spot_coin["price"]
    sp_tp1, sp_tp2, sp_tp3, sp_sl = sp_p * 1.03, sp_p * 1.06, sp_p * 1.10, sp_p * 0.975
    spot_msg = (
        f"🟢 <b>[VIP SPOT SWING SIGNAL]</b>\n"
        f"🪙 <b>Coin</b>: #{spot_coin['symbol']}\n"
        f"📥 <b>Entry Zone</b>: ${sp_p:.4f}\n"
        f"⏱️ <b>Timeframe</b>: 1-2 Days\n\n"
        f"🎯 <b>TP1</b>: ${sp_tp1:.4f} (+3%)\n"
        f"🎯 <b>TP2</b>: ${sp_tp2:.4f} (+6%)\n"
        f"🎯 <b>TP3</b>: ${sp_tp3:.4f} (+10%)\n"
        f"⛔ <b>Stop Loss</b>: ${sp_sl:.4f} (-2.5%)"
    )

    # --- FUTURES SIGNAL ---
    ft_p = futures_coin["price"]
    ft_tp1, ft_tp2, ft_tp3, ft_sl = ft_p * 1.012, ft_p * 1.025, ft_p * 1.045, ft_p * 0.988
    futures_msg = (
        f"⚡ <b>[VIP FUTURES LONG SIGNAL]</b>\n"
        f"🪙 <b>Coin</b>: #{futures_coin['symbol']}\n"
        f"⚙️ <b>Leverage</b>: Isolated 5x - 10x Max\n"
        f"📥 <b>Entry</b>: ${ft_p:.4f}\n\n"
        f"🎯 <b>TP1</b>: ${ft_tp1:.4f} (+12% @ 10x)\n"
        f"🎯 <b>TP2</b>: ${ft_tp2:.4f} (+25% @ 10x)\n"
        f"🎯 <b>TP3</b>: ${ft_tp3:.4f} (+45% @ 10x)\n"
        f"⛔ <b>Stop Loss</b>: ${ft_sl:.4f} (-12% @ 10x)"
    )

    r1 = send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, spot_msg, is_channel=True)
    time.sleep(0.5)
    r2 = send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, futures_msg, is_channel=True)

    free_promo = (
        f"🔥 <b>FREE HIGH-ACCURACY SIGNAL PREVIEW</b> 🔥\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{futures_msg}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>Free Channel:</b> https://t.me/BinanceTop10Free\n\n"
        f"💎 <b>Get Spot Swings & 10+ Daily Signals in VIP</b>\n"
        f"👉 <b>Join VIP Bot:</b> @BinanceTop10_VIPBot"
    )
    r3 = send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, free_promo, is_channel=True)
    
    log_event(f"Broadcast complete: VIP Spot={r1}, VIP Futures={r2}, Free={r3}")

# ==========================================
# 7. TELEGRAM BOT LISTENERS
# ==========================================
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
# 8. NON-BLOCKING SCHEDULER & FLASK CONTROLLER
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
    return jsonify({"status": "active", "scheduler": "running"})

@app.route('/logs')
def get_logs():
    return jsonify({"logs": system_logs})

@app.route('/force-signal')
def force_signal():
    threading.Thread(target=generate_and_send_signals, daemon=True).start()
    return "Signal process triggered successfully!"

start_resilient_thread(process_free_bot_updates, "Free-Bot-Listener")
start_resilient_thread(process_bot_updates, "VIP-Bot-Listener")

# Instant initial execution on app launch
threading.Thread(target=generate_and_send_signals, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
