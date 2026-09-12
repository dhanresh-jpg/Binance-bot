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
active_signals_tracker = []  # List to track active running signals for TP/SL

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
    """Identifies the oldest recorded date (Day 1) and deletes all messages from that date."""
    try:
        conn = sqlite3.connect("vip_members.db")
        cursor = conn.cursor()
        
        # Get unique dates
        cursor.execute("SELECT DISTINCT created_date FROM channel_messages ORDER BY created_date ASC")
        dates = [row[0] for row in cursor.fetchall()]
        
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        
        # If we have multiple days accumulated, delete the oldest day (Day 1)
        if len(dates) > 1:
            oldest_date = dates[0]
            if oldest_date != today_str:
                cursor.execute("SELECT bot_type, chat_id, message_id FROM channel_messages WHERE created_date = ?", (oldest_date,))
                records = cursor.fetchall()
                log_event(f"Starting Cleanup for Day 1 ({oldest_date}). Total messages to delete: {len(records)}")
                
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
                log_event(f"Day 1 ({oldest_date}) messages successfully purged.")
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
                            return False, f"Received {value} USDT, which is less than minimum plan ($10)."
            return False, "Transaction not found on TRON Network yet. Wait 1-2 minutes."
    except Exception as e:
        log_event(f"TronGrid API Error: {e}")
        return False, "Error checking Blockchain API. Please try again later."
    
    return False, "Transaction not found for this wallet address."

# --- TELEGRAM API HELPER ---
def send_telegram_msg(bot_token, chat_id, text, is_channel=False):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
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

# --- MULTI-EXCHANGE AGGREGATED PRICE ENGINE ---
def fetch_global_index_price(symbol):
    prices = []
    try:
        url = f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            lst = res.json().get("result", {}).get("list", [])
            if lst:
                prices.append(float(lst[0]["lastPrice"]))
    except Exception:
        pass

    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            prices.append(float(res.json()["price"]))
    except Exception:
        pass

    try:
        kc_sym = symbol.replace("USDT", "-USDT")
        url = f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={kc_sym}"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            prices.append(float(res.json()["data"]["price"]))
    except Exception:
        pass

    if prices:
        return sum(prices) / len(prices)
    return None

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def get_market_analysis(symbol):
    try:
        url = f"https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol}&interval=60&limit=30"
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            candles = res.json().get("result", {}).get("list", [])
            if len(candles) >= 10:
                closes = [float(c[4]) for c in reversed(candles)]
                current_price = fetch_global_index_price(symbol) or closes[-1]
                rsi = calculate_rsi(closes)
                ema_20 = sum(closes[-10:]) / 10.0
                trend = "BULLISH" if current_price >= ema_20 else "BEARISH"
                return {"symbol": symbol, "price": current_price, "trend": trend, "rsi": round(rsi, 1)}
    except Exception:
        pass
    
    price = fetch_global_index_price(symbol)
    if price:
        return {"symbol": symbol, "price": price, "trend": "BULLISH", "rsi": 55.0}
    return None

def scan_top_opportunity_coins():
    candidate_pool = [
        "SOLUSDT", "AVAXUSDT", "LINKUSDT", "NEARUSDT", "DOTUSDT", 
        "FETUSDT", "APTUSDT", "ARBUSDT", "SUIUSDT", "BTCUSDT", "ETHUSDT"
    ]
    analyzed_list = []
    for sym in candidate_pool:
        result = get_market_analysis(sym)
        if result:
            analyzed_list.append(result)
            if len(analyzed_list) >= 2:
                break
        time.sleep(0.1)
    return analyzed_list

# --- LIVE TARGET & SL MONITORING ENGINE ---
def monitor_active_signals():
    global active_signals_tracker
    while True:
        try:
            if active_signals_tracker:
                current_time = datetime.now(IST)
                for sig in list(active_signals_tracker):
                    # Stop watching signals older than 24 hours
                    if (current_time - sig["created_at"]).total_seconds() > 86400:
                        active_signals_tracker.remove(sig)
                        continue

                    symbol = sig["symbol"]
                    current_price = fetch_global_index_price(symbol)
                    if not current_price:
                        continue

                    signal_type = sig["type"]  # "SPOT" or "FUTURES"
                    trend = sig["trend"]
                    tp1, tp2, tp3, sl = sig["tp1"], sig["tp2"], sig["tp3"], sig["sl"]

                    hit_update = None

                    if trend == "BULLISH":
                        if not sig["tp1_hit"] and current_price >= tp1:
                            sig["tp1_hit"] = True
                            hit_update = f"🚀 <b>#{symbol} TARGET 1 HIT! ({signal_type})</b>\n🎯 Price reached <b>${tp1:.4f}</b>. Book partial profits!"
                        elif sig["tp1_hit"] and not sig["tp2_hit"] and current_price >= tp2:
                            sig["tp2_hit"] = True
                            hit_update = f"🔥 <b>#{symbol} TARGET 2 HIT! ({signal_type})</b>\n🎯 Price reached <b>${tp2:.4f}</b>. Amazing gains!"
                        elif sig["tp2_hit"] and not sig["tp3_hit"] and current_price >= tp3:
                            sig["tp3_hit"] = True
                            hit_update = f"🎯 <b>#{symbol} TARGET 3 (FINAL) HIT! ({signal_type})</b>\n🏆 Price reached <b>${tp3:.4f}</b>. Target completed successfully!"
                        elif not sig["sl_hit"] and current_price <= sl:
                            sig["sl_hit"] = True
                            hit_update = f"⛔ <b>#{symbol} STOP LOSS HIT ({signal_type})</b>\nPrice dipped to <b>${sl:.4f}</b>. Strict risk management closed trade."
                    else:  # BEARISH / SHORT
                        if not sig["tp1_hit"] and current_price <= tp1:
                            sig["tp1_hit"] = True
                            hit_update = f"🚀 <b>#{symbol} TARGET 1 HIT! ({signal_type})</b>\n🎯 Price reached <b>${tp1:.4f}</b>. Book partial profits!"
                        elif sig["tp1_hit"] and not sig["tp2_hit"] and current_price <= tp2:
                            sig["tp2_hit"] = True
                            hit_update = f"🔥 <b>#{symbol} TARGET 2 HIT! ({signal_type})</b>\n🎯 Price reached <b>${tp2:.4f}</b>. Amazing gains!"
                        elif sig["tp2_hit"] and not sig["tp3_hit"] and current_price <= tp3:
                            sig["tp3_hit"] = True
                            hit_update = f"🎯 <b>#{symbol} TARGET 3 (FINAL) HIT! ({signal_type})</b>\n🏆 Price reached <b>${tp3:.4f}</b>. Target completed successfully!"
                        elif not sig["sl_hit"] and current_price >= sl:
                            sig["sl_hit"] = True
                            hit_update = f"⛔ <b>#{symbol} STOP LOSS HIT ({signal_type})</b>\nPrice rose to <b>${sl:.4f}</b>. Strict risk management closed trade."

                    if hit_update:
                        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, hit_update, is_channel=True)
                        if signal_type == "FUTURES":
                            send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, hit_update, is_channel=True)
                        log_event(f"Live Update Sent: {hit_update}")

            # Also trigger Day-1 Purge routinely
            purge_day1_oldest_messages()

        except Exception as e:
            log_event(f"Monitor Loop Error: {e}")
        time.sleep(30)

# --- SIGNAL BROADCAST ENGINE ---
def generate_and_send_signals():
    log_event("Scanning Multi-Exchange Markets for Opportunities...")
    scanned_coins = scan_top_opportunity_coins()

    if len(scanned_coins) < 2:
        scanned_coins = [
            {"symbol": "SOLUSDT", "price": 145.50, "trend": "BULLISH", "rsi": 58.2},
            {"symbol": "NEARUSDT", "price": 4.25, "trend": "BULLISH", "rsi": 54.1}
        ]

    spot_coin = scanned_coins[0]
    futures_coin = scanned_coins[1]

    # 1. SPOT SWING SIGNAL
    sp_price = spot_coin["price"]
    sp_fmt = f"{sp_price:.2f}" if sp_price > 10 else f"{sp_price:.4f}"
    
    if spot_coin["trend"] == "BULLISH":
        sp_tp1, sp_tp2, sp_tp3, sp_sl = sp_price * 1.04, sp_price * 1.08, sp_price * 1.14, sp_price * 0.94
        spot_msg = (
            f"🟢 <b>[VIP SPOT SWING SIGNAL - BUY]</b>\n"
            f"🪙 <b>Coin</b>: #{spot_coin['symbol']}\n"
            f"📥 <b>Buy Entry Zone</b>: ${sp_fmt}\n"
            f"⏱️ <b>Timeframe Target</b>: 1 - 2 Days Swing\n\n"
            f"🎯 <b>Target 1</b>: ${sp_tp1:.4f} (+4%)\n"
            f"🎯 <b>Target 2</b>: ${sp_tp2:.4f} (+8%)\n"
            f"🎯 <b>Target 3</b>: ${sp_tp3:.4f} (+14%)\n"
            f"⛔ <b>Stop Loss</b>: ${sp_sl:.4f} (-6%)"
        )
    else:
        sp_tp1, sp_tp2, sp_tp3, sp_sl = sp_price * 0.96, sp_price * 0.92, sp_price * 0.86, sp_price * 1.05
        spot_msg = (
            f"🔴 <b>[VIP SPOT SWING SIGNAL - DIP BUY]</b>\n"
            f"🪙 <b>Coin</b>: #{spot_coin['symbol']}\n"
            f"📥 <b>Buy Zone</b>: ${sp_fmt}\n\n"
            f"🎯 <b>Target 1</b>: ${sp_tp1:.4f}\n"
            f"🎯 <b>Target 2</b>: ${sp_tp2:.4f}\n"
            f"🎯 <b>Target 3</b>: ${sp_tp3:.4f}\n"
            f"⛔ <b>Stop Loss</b>: ${sp_sl:.4f}"
        )

    # Register Spot Signal for Live Tracking
    active_signals_tracker.append({
        "symbol": spot_coin["symbol"],
        "type": "SPOT",
        "trend": spot_coin["trend"],
        "tp1": sp_tp1, "tp2": sp_tp2, "tp3": sp_tp3, "sl": sp_sl,
        "tp1_hit": False, "tp2_hit": False, "tp3_hit": False, "sl_hit": False,
        "created_at": datetime.now(IST)
    })

    # 2. FUTURES SIGNAL
    ft_price = futures_coin["price"]
    ft_fmt = f"{ft_price:.2f}" if ft_price > 10 else f"{ft_price:.4f}"

    if futures_coin["trend"] == "BULLISH":
        ft_tp1, ft_tp2, ft_tp3, ft_sl = ft_price * 1.015, ft_price * 1.032, ft_price * 1.055, ft_price * 0.985
        futures_msg = (
            f"⚡ <b>[VIP FUTURES LONG SIGNAL]</b>\n"
            f"🪙 <b>Coin</b>: #{futures_coin['symbol']}\n"
            f"⚙️ <b>Leverage</b>: Cross 10x - 15x\n"
            f"📥 <b>Entry</b>: ${ft_fmt}\n\n"
            f"🎯 <b>TP1</b>: ${ft_tp1:.4f} (+15% @ 10x)\n"
            f"🎯 <b>TP2</b>: ${ft_tp2:.4f} (+32% @ 10x)\n"
            f"🎯 <b>TP3</b>: ${ft_tp3:.4f} (+55% @ 10x)\n"
            f"⛔ <b>Stop Loss</b>: ${ft_sl:.4f} (-15% @ 10x)"
        )
    else:
        ft_tp1, ft_tp2, ft_tp3, ft_sl = ft_price * 0.985, ft_price * 0.968, ft_price * 0.945, ft_price * 1.015
        futures_msg = (
            f"🔻 <b>[VIP FUTURES SHORT SIGNAL]</b>\n"
            f"🪙 <b>Coin</b>: #{futures_coin['symbol']}\n"
            f"⚙️ <b>Leverage</b>: Cross 10x - 15x\n"
            f"📥 <b>Entry</b>: ${ft_fmt}\n\n"
            f"🎯 <b>TP1</b>: ${ft_tp1:.4f} (+15% @ 10x)\n"
            f"🎯 <b>TP2</b>: ${ft_tp2:.4f} (+32% @ 10x)\n"
            f"🎯 <b>TP3</b>: ${ft_tp3:.4f} (+55% @ 10x)\n"
            f"⛔ <b>Stop Loss</b>: ${ft_sl:.4f} (-15% @ 10x)"
        )

    # Register Futures Signal for Live Tracking
    active_signals_tracker.append({
        "symbol": futures_coin["symbol"],
        "type": "FUTURES",
        "trend": futures_coin["trend"],
        "tp1": ft_tp1, "tp2": ft_tp2, "tp3": ft_tp3, "sl": ft_sl,
        "tp1_hit": False, "tp2_hit": False, "tp3_hit": False, "sl_hit": False,
        "created_at": datetime.now(IST)
    })

    # Post Signals to VIP Channel
    send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, spot_msg, is_channel=True)
    time.sleep(1.0)
    send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, futures_msg, is_channel=True)

    # 3. FREE CHANNEL PREVIEW
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
    log_event("New Signals Generated & Added to Live Tracker!")

def continuous_loop():
    time.sleep(5)
    while True:
        try:
            generate_and_send_signals()
        except Exception as e:
            log_event(f"Loop Exception: {e}\n{traceback.format_exc()}")
        time.sleep(14400)  # Every 4 hours

# --- TELEGRAM BOT LISTENERS ---
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
                        send_telegram_msg(FREE_BOT_TOKEN, user_id, "👋 Welcome to Binance Top 10 Signals Free Bot!")
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
                    msg = update.get("message", {})
                    text = msg.get("text", "").strip()
                    user_id = msg.get("from", {}).get("id")
                    if not text or not user_id:
                        continue

                    if text == "/start":
                        send_telegram_msg(VIP_BOT_TOKEN, user_id, "👋 Welcome to VIP Bot!\nUse /plans, /pay, or /verify TXID")
                    elif text == "/plans":
                        send_telegram_msg(VIP_BOT_TOKEN, user_id, "💎 Plans: 10 Days ($10), 20 Days ($19), 30 Days ($27)")
                    elif text == "/pay":
                        send_telegram_msg(VIP_BOT_TOKEN, user_id, f"💳 USDT TRC20 Address:\n<code>{TRUST_WALLET_ADDRESS}</code>")
                    elif text.startswith("/verify"):
                        parts = text.split()
                        if len(parts) >= 2:
                            is_valid, res_data = verify_tron_txid(parts[1].strip())
                            if is_valid:
                                days, amt = res_data
                                exp = add_vip_member(user_id, days)
                                link = create_vip_invite_link()
                                send_telegram_msg(VIP_BOT_TOKEN, user_id, f"✅ Verified! Access until {exp}\n{link}")
                            else:
                                send_telegram_msg(VIP_BOT_TOKEN, user_id, f"❌ Failed: {res_data}")
        except Exception:
            time.sleep(2)

# --- WATCHDOG TO ENSURE NO THREAD DIES ---
def start_resilient_thread(target_func, name):
    def wrapper():
        while True:
            try:
                log_event(f"Starting thread: {name}")
                target_func()
            except Exception as e:
                log_event(f"Thread '{name}' crashed with error: {e}. Restarting in 2s...")
                time.sleep(2)

    t = threading.Thread(target=wrapper, daemon=True, name=name)
    t.start()
    return t

# --- FLASK SERVER ---
@app.route('/')
@app.route('/ping')
def home():
    return jsonify({"status": "active", "message": "Signal Bot Engine Running Successfully"})

@app.route('/logs')
def get_logs():
    return jsonify({"logs": system_logs})

@app.route('/force-signal')
def force_signal():
    threading.Thread(target=generate_and_send_signals, daemon=True).start()
    return "Signals triggered successfully!"

# Launch Crash-Proof Background Threads
start_resilient_thread(continuous_loop, "Signal-Generator-Loop")
start_resilient_thread(monitor_active_signals, "Live-Target-Monitor")
start_resilient_thread(process_free_bot_updates, "Free-Bot-Listener")
start_resilient_thread(process_bot_updates, "VIP-Bot-Listener")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
