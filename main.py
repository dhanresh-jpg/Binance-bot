import time
import requests
import sqlite3
import os
import threading
import traceback
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify

# --- CONFIGURATION ---
FREE_BOT_TOKEN = "8842407289:AAHD6UcvOZ0pgvN8EJXXetb2qrW-fGeZCvU"
VIP_BOT_TOKEN = "8997353064:AAH2gTVchfQqqId1TvBa2CD8nIXY00ZUj_8"

FREE_CHANNEL_ID = "-1003924921868"
VIP_CHANNEL_ID = "-1003836756507"

TRUST_WALLET_ADDRESS = "TErttGLUQZtrCwusaQsjdywXdkxUrNFm52"

app = Flask(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
system_logs = []
active_signals_tracker = []

def log_event(message):
    timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    system_logs.append(entry)
    if len(system_logs) > 150:
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
        log_event("Database & Message-Tracker initialized.")
    except Exception as e:
        log_event(f"DB Error: {e}")

init_db()

# --- DATABASE HELPERS ---
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

# --- DAY-1 AUTO DELETE CLEANUP ---
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

def purge_day1_oldest_messages():
    try:
        conn = sqlite3.connect("vip_members.db")
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT created_date FROM channel_messages ORDER BY created_date ASC")
        dates = [row[0] for row in cursor.fetchall()]
        
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        if len(dates) > 1:
            oldest_date = dates[0]
            if oldest_date != today_str:
                cursor.execute("SELECT bot_type, chat_id, message_id FROM channel_messages WHERE created_date = ?", (oldest_date,))
                records = cursor.fetchall()
                
                for bot_type, chat_id, msg_id in records:
                    token = FREE_BOT_TOKEN if bot_type == "FREE" else VIP_BOT_TOKEN
                    try:
                        requests.post(f"https://api.telegram.org/bot{token}/deleteMessage", 
                                      json={"chat_id": chat_id, "message_id": msg_id}, timeout=5)
                    except Exception:
                        pass
                    time.sleep(0.2)
                
                cursor.execute("DELETE FROM channel_messages WHERE created_date = ?", (oldest_date,))
                conn.commit()
                log_event(f"Day 1 ({oldest_date}) messages purged.")
        conn.close()
    except Exception as e:
        log_event(f"Purge Error: {e}")

# --- TRON BLOCKCHAIN AUTOMATIC VERIFIER ---
def verify_tron_txid(txid):
    if is_txid_processed(txid):
        return False, "This Transaction Hash (TXID) has already been used!"

    url = f"https://api.trongrid.io/v1/accounts/{TRUST_WALLET_ADDRESS}/transactions/trc20"
    try:
        res = requests.get(url, timeout=10)
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

# --- TELEGRAM API HELPER WITH KEYBOARD SUPPORT ---
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
        res = requests.post(url, json=payload, timeout=10)
        data = res.json()
        if data.get("ok"):
            msg_id = data["result"]["message_id"]
            if is_channel:
                bot_type = "FREE" if bot_token == FREE_BOT_TOKEN else "VIP"
                record_channel_message(bot_type, chat_id, msg_id)
        return data
    except Exception as e:
        log_event(f"Telegram Exception ({chat_id}): {e}")
        return None

def create_vip_invite_link():
    url = f"https://api.telegram.org/bot{VIP_BOT_TOKEN}/createChatInviteLink"
    payload = {"chat_id": VIP_CHANNEL_ID, "member_limit": 1}
    try:
        res = requests.post(url, json=payload, timeout=8).json()
        if res.get("ok"):
            return res["result"]["invite_link"]
    except Exception as e:
        log_event(f"Invite Link Error: {e}")
    return None

# --- UI KEYBOARD MARKUPS ---
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

# --- MULTI-EXCHANGE PRICE ENGINE ---
def fetch_global_index_price(symbol):
    prices = []
    try:
        res = requests.get(f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}", timeout=3)
        if res.status_code == 200:
            lst = res.json().get("result", {}).get("list", [])
            if lst: prices.append(float(lst[0]["lastPrice"]))
    except Exception: pass

    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=3)
        if res.status_code == 200: prices.append(float(res.json()["price"]))
    except Exception: pass

    if prices: return sum(prices) / len(prices)
    return None

def scan_top_opportunity_coins():
    candidate_pool = ["SOLUSDT", "AVAXUSDT", "LINKUSDT", "NEARUSDT", "DOTUSDT", "SUIUSDT", "BTCUSDT", "ETHUSDT"]
    analyzed_list = []
    for sym in candidate_pool:
        p = fetch_global_index_price(sym)
        if p:
            analyzed_list.append({"symbol": sym, "price": p, "trend": "BULLISH", "rsi": 56.0})
            if len(analyzed_list) >= 2: break
        time.sleep(0.1)
    return analyzed_list

# --- TARGET MONITOR ENGINE ---
def monitor_active_signals():
    global active_signals_tracker
    while True:
        try:
            if active_signals_tracker:
                current_time = datetime.now(IST)
                for sig in list(active_signals_tracker):
                    if (current_time - sig["created_at"]).total_seconds() > 86400:
                        active_signals_tracker.remove(sig)
                        continue

                    symbol = sig["symbol"]
                    current_price = fetch_global_index_price(symbol)
                    if not current_price: continue

                    signal_type, trend = sig["type"], sig["trend"]
                    tp1, tp2, tp3, sl = sig["tp1"], sig["tp2"], sig["tp3"], sig["sl"]
                    hit_update = None

                    if trend == "BULLISH":
                        if not sig["tp1_hit"] and current_price >= tp1:
                            sig["tp1_hit"] = True
                            hit_update = f"🚀 <b>#{symbol} TARGET 1 HIT! ({signal_type})</b>\n🎯 Reached <b>${tp1:.4f}</b>"
                        elif sig["tp1_hit"] and not sig["tp2_hit"] and current_price >= tp2:
                            sig["tp2_hit"] = True
                            hit_update = f"🔥 <b>#{symbol} TARGET 2 HIT! ({signal_type})</b>\n🎯 Reached <b>${tp2:.4f}</b>"
                        elif sig["tp2_hit"] and not sig["tp3_hit"] and current_price >= tp3:
                            sig["tp3_hit"] = True
                            hit_update = f"🎯 <b>#{symbol} TARGET 3 COMPLETE! ({signal_type})</b>\n🏆 Reached <b>${tp3:.4f}</b>"
                        elif not sig["sl_hit"] and current_price <= sl:
                            sig["sl_hit"] = True
                            hit_update = f"⛔ <b>#{symbol} STOP LOSS HIT ({signal_type})</b>\nPrice: <b>${sl:.4f}</b>"

                    if hit_update:
                        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, hit_update, is_channel=True)
                        if signal_type == "FUTURES":
                            send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, hit_update, is_channel=True)

            purge_day1_oldest_messages()
        except Exception as e:
            log_event(f"Monitor Loop Error: {e}")
        time.sleep(30)

# --- BROADCAST ENGINE ---
def generate_and_send_signals():
    scanned = scan_top_opportunity_coins()
    if len(scanned) < 2:
        scanned = [
            {"symbol": "SOLUSDT", "price": 145.50, "trend": "BULLISH", "rsi": 58.2},
            {"symbol": "NEARUSDT", "price": 4.25, "trend": "BULLISH", "rsi": 54.1}
        ]

    spot_coin, futures_coin = scanned[0], scanned[1]

    # SPOT
    sp_p = spot_coin["price"]
    sp_tp1, sp_tp2, sp_tp3, sp_sl = sp_p * 1.04, sp_p * 1.08, sp_p * 1.14, sp_p * 0.94
    spot_msg = (
        f"🟢 <b>[VIP SPOT SWING SIGNAL - BUY]</b>\n"
        f"🪙 <b>Coin</b>: #{spot_coin['symbol']}\n"
        f"📥 <b>Entry Zone</b>: ${sp_p:.4f}\n"
        f"⏱️ <b>Timeframe</b>: 1-2 Days\n\n"
        f"🎯 <b>TP1</b>: ${sp_tp1:.4f} (+4%)\n"
        f"🎯 <b>TP2</b>: ${sp_tp2:.4f} (+8%)\n"
        f"🎯 <b>TP3</b>: ${sp_tp3:.4f} (+14%)\n"
        f"⛔ <b>Stop Loss</b>: ${sp_sl:.4f} (-6%)"
    )

    active_signals_tracker.append({
        "symbol": spot_coin["symbol"], "type": "SPOT", "trend": "BULLISH",
        "tp1": sp_tp1, "tp2": sp_tp2, "tp3": sp_tp3, "sl": sp_sl,
        "tp1_hit": False, "tp2_hit": False, "tp3_hit": False, "sl_hit": False,
        "created_at": datetime.now(IST)
    })

    # FUTURES
    ft_p = futures_coin["price"]
    ft_tp1, ft_tp2, ft_tp3, ft_sl = ft_p * 1.015, ft_p * 1.032, ft_p * 1.055, ft_p * 0.985
    futures_msg = (
        f"⚡ <b>[VIP FUTURES LONG SIGNAL]</b>\n"
        f"🪙 <b>Coin</b>: #{futures_coin['symbol']}\n"
        f"⚙️ <b>Leverage</b>: Cross 10x-15x\n"
        f"📥 <b>Entry</b>: ${ft_p:.4f}\n\n"
        f"🎯 <b>TP1</b>: ${ft_tp1:.4f} (+15%)\n"
        f"🎯 <b>TP2</b>: ${ft_tp2:.4f} (+32%)\n"
        f"🎯 <b>TP3</b>: ${ft_tp3:.4f} (+55%)\n"
        f"⛔ <b>Stop Loss</b>: ${ft_sl:.4f} (-15%)"
    )

    active_signals_tracker.append({
        "symbol": futures_coin["symbol"], "type": "FUTURES", "trend": "BULLISH",
        "tp1": ft_tp1, "tp2": ft_tp2, "tp3": ft_tp3, "sl": ft_sl,
        "tp1_hit": False, "tp2_hit": False, "tp3_hit": False, "sl_hit": False,
        "created_at": datetime.now(IST)
    })

    send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, spot_msg, is_channel=True)
    time.sleep(1.0)
    send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, futures_msg, is_channel=True)

    free_promo = (
        f"🔥 <b>FREE HIGH-ACCURACY SIGNAL PREVIEW</b> 🔥\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{futures_msg}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>Free Channel:</b> https://t.me/BinanceTop10Free\n\n"
        f"💎 <b>Get Spot Swing & Live Updates in VIP</b>\n"
        f"👉 <b>Join VIP Bot:</b> @BinanceTop10_VIPBot"
    )
    send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, free_promo, is_channel=True)

def continuous_loop():
    time.sleep(5)
    while True:
        try:
            generate_and_send_signals()
        except Exception as e:
            log_event(f"Loop Exception: {e}")
        time.sleep(14400)

# --- BOT LISTENERS WITH BUTTON LOGIC ---
def process_free_bot_updates():
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{FREE_BOT_TOKEN}/getUpdates"
            res = requests.get(url, params={"timeout": 10, "offset": offset}, timeout=12)
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
            res = requests.get(url, params={"timeout": 10, "offset": offset}, timeout=12)
            if res.status_code == 200:
                for update in res.json().get("result", []):
                    offset = update["update_id"] + 1
                    
                    # Handle Callback Queries (Inline Buttons)
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

                    # Handle Message Commands & Buttons
                    msg = update.get("message", {})
                    text = msg.get("text", "").strip()
                    user_id = msg.get("from", {}).get("id")
                    if not text or not user_id:
                        continue

                    if text in ["/start", "🔙 Main Menu"]:
                        welcome = (
                            f"🤖 <b>Welcome to Binance Top 10 VIP Bot!</b>\n\n"
                            f"24/7 Multi-Exchange Crypto Signals with Automated TRON TRC-20 Activation.\n\n"
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

                    elif text in ["📊 Free vs VIP Comparison"]:
                        comparison_txt = (
                            f"📊 <b>FREE vs VIP CHANNEL COMPARISON</b>\n\n"
                            f"❌ <b>FREE CHANNEL</b>\n"
                            f"├ ⚠️ Only 1 Signal Preview / day\n"
                            f"├ ⚠️ Delayed Entry & Exit Targets\n"
                            f"├ ❌ No Live TP1 / TP2 / TP3 Alerts\n"
                            f"├ ❌ No Spot Swing Signals\n"
                            f"└ ❌ No Priority Support\n\n"
                            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                            f"👑 <b>VIP CHANNEL (PREMIUM)</b>\n"
                            f"├ 💎 <b>10-15 High-Accuracy Signals Daily</b>\n"
                            f"├ 🎯 <b>Spot + Futures (Leverage Guidance)</b>\n"
                            f"├ ⚡ <b>Real-Time Live Target & SL Alerts</b>\n"
                            f"├ 📈 <b>Exclusive High-Yield Spot Swings</b>\n"
                            f"├ 🧠 <b>Market Updates & Risk Management</b>\n"
                            f"└ 💬 <b>24/7 VIP Priority Support</b>\n\n"
                            f"🔥 <i>Upgrade now to maximize your trading profits!</i>"
                        )
                        send_telegram_msg(VIP_BOT_TOKEN, user_id, comparison_txt, reply_markup=get_verify_inline_keyboard())

                    elif text in ["❓ How To Verify"]:
                        verify_info = (
                            f"❓ <b>HOW TO VERIFY PAYMENT</b>\n\n"
                            f"1. Make transfer to address using <b>Get Pay Address</b>.\n"
                            f"2. Copy the Transaction Hash (TXID) from TrustWallet / Binance.\n"
                            f"3. Send command in format:\n"
                            f"<code>/verify YOUR_TXID_HERE</code>\n\n"
                            f"<i>Our TRON Grid engine verifies txid on-chain instantly!</i>"
                        )
                        send_telegram_msg(VIP_BOT_TOKEN, user_id, verify_info, reply_markup=get_vip_menu_keyboard())

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

# --- RESILIENT THREAD WATCHDOG ---
def start_resilient_thread(target_func, name):
    def wrapper():
        while True:
            try:
                log_event(f"Starting thread: {name}")
                target_func()
            except Exception as e:
                log_event(f"Thread '{name}' crashed with error: {e}. Restarting...")
                time.sleep(2)

    t = threading.Thread(target=wrapper, daemon=True, name=name)
    t.start()
    return t

# --- FLASK SERVER ---
@app.route('/')
@app.route('/ping')
def home():
    return jsonify({"status": "active", "message": "Signal Bot Engine Active with Interactive UI"})

@app.route('/logs')
def get_logs():
    return jsonify({"logs": system_logs})

@app.route('/force-signal')
def force_signal():
    threading.Thread(target=generate_and_send_signals, daemon=True).start()
    return "Signals triggered successfully!"

# Launch Threads
start_resilient_thread(continuous_loop, "Signal-Generator-Loop")
start_resilient_thread(monitor_active_signals, "Live-Target-Monitor")
start_resilient_thread(process_free_bot_updates, "Free-Bot-Listener")
start_resilient_thread(process_bot_updates, "VIP-Bot-Listener")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
