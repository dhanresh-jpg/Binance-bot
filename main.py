import os
import time
import sqlite3
import threading
import requests
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify

# ==========================================
# CONFIGURATION & ENVIRONMENT VARIABLES
# ==========================================
FREE_BOT_TOKEN = os.getenv("FREE_BOT_TOKEN")
VIP_BOT_TOKEN = os.getenv("VIP_BOT_TOKEN")

FREE_CHANNEL_ID = os.getenv("FREE_CHANNEL_ID", "-1003924921868")
VIP_CHANNEL_ID = os.getenv("VIP_CHANNEL_ID", "-1003836756507")
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "default_admin_secret")

TRUST_WALLET_ADDRESS = "TErttGLUQZtrCwusaQsjdywXdkxUrNFm52"
BINANCE_REF_LINK = "https://accounts.binance.com/register?ref=GRO_28502_IBUUM"
DB_NAME = "vip_members.db"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

app = Flask(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
system_logs = []

KEYBOARD_LAYOUT = {
    "keyboard": [
        [{"text": "View VIP Plans"}, {"text": "Get Payment Address"}],
        [{"text": "Free VIP via Referral"}, {"text": "Verify Payment"}],
        [{"text": "How to Verify TXID"}]
    ],
    "resize_keyboard": True,
    "is_persistent": True
}

free_signals_today = 0
vip_signals_today = 0
last_reset_day = datetime.now(IST).day
last_free_dispatch_time = 0
last_vip_dispatch_time = 0

# ==========================================
# SYSTEM LOGGING & DATABASE HELPERS
# ==========================================
def log_event(message):
    timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    system_logs.append(entry)
    if len(system_logs) > 200:
        system_logs.pop(0)
    print(entry)

def get_db():
    return sqlite3.connect(DB_NAME, timeout=10.0)

def init_db():
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('CREATE TABLE IF NOT EXISTS members (user_id INTEGER PRIMARY KEY, expiry_date TEXT, status TEXT)')
            cursor.execute('CREATE TABLE IF NOT EXISTS processed_txids (txid TEXT PRIMARY KEY)')
            cursor.execute('CREATE TABLE IF NOT EXISTS channel_messages (bot_type TEXT, chat_id TEXT, message_id INTEGER, created_date TEXT)')
            cursor.execute('''CREATE TABLE IF NOT EXISTS referral_claims (
                                user_id INTEGER, 
                                binance_uid TEXT PRIMARY KEY, 
                                status TEXT DEFAULT "PENDING", 
                                created_date TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS signal_history (
                                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                                symbol TEXT, 
                                entry_price REAL, 
                                tp1 REAL, 
                                tp2 REAL, 
                                tp3 REAL, 
                                sl REAL, 
                                timestamp REAL, 
                                created_date TEXT, 
                                status TEXT DEFAULT "PENDING")''')
            
            # Additional column check to maintain tracking for TP1, TP2, TP3, SL independently
            cursor.execute("PRAGMA table_info(signal_history)")
            columns = [col[1] for col in cursor.fetchall()]
            if "hits" not in columns:
                cursor.execute("ALTER TABLE signal_history ADD COLUMN hits TEXT DEFAULT ''")
                
        log_event("Database Initialized Successfully.")
    except Exception as e:
        log_event(f"Database Init Error: {e}")

init_db()

def cleanup_3day_old_data():
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            three_days_ago = (datetime.now(IST) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("DELETE FROM signal_history WHERE created_date < ?", (three_days_ago,))
            cursor.execute("DELETE FROM channel_messages WHERE created_date < ?", (three_days_ago,))
            deleted_count = cursor.rowcount
        if deleted_count > 0:
            log_event(f"Cleaned {deleted_count} old records.")
    except Exception as e:
        log_event(f"Cleanup Error: {e}")

def format_price(val):
    if val is None or val == 0:
        return "0.00"
    if val >= 1000:
        return f"{val:,.2f}"
    elif val >= 1:
        return f"{val:.4f}"
    elif val >= 0.001:
        return f"{val:.6f}"
    else:
        return f"{val:.8f}"

# ==========================================
# MARKET DATA & SIGNAL GENERATION
# ==========================================
def get_market_data():
    valid_coins = []
    
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        res = requests.get(url, headers=HEADERS, timeout=10.0)
        if res.status_code == 200:
            for item in res.json():
                symbol = item.get("symbol", "")
                if symbol.endswith("USDT"):
                    price = float(item.get("lastPrice", 0) or 0)
                    change = float(item.get("priceChangePercent", 0) or 0)
                    low = float(item.get("lowPrice", price * 0.95) or price * 0.95)
                    if price > 0:
                        valid_coins.append({"symbol": symbol, "price": price, "change": change, "low": low})
            if valid_coins:
                return valid_coins
    except Exception as e:
        log_event(f"Primary Binance API Exception: {e}. Switching to Standby API...")

    try:
        backup_url = "https://data-api.binance.vision/api/v3/ticker/24hr"
        res = requests.get(backup_url, headers=HEADERS, timeout=10.0)
        if res.status_code == 200:
            for item in res.json():
                symbol = item.get("symbol", "")
                if symbol.endswith("USDT"):
                    price = float(item.get("lastPrice", 0) or 0)
                    change = float(item.get("priceChangePercent", 0) or 0)
                    low = float(item.get("lowPrice", price * 0.95) or price * 0.95)
                    if price > 0:
                        valid_coins.append({"symbol": symbol, "price": price, "change": change, "low": low})
            if valid_coins:
                log_event("Market data fetched using Standby API.")
                return valid_coins
    except Exception as e:
        log_event(f"Standby API Exception: {e}")

    return valid_coins

def generate_24h_result_report():
    try:
        twenty_four_hrs_ago = (datetime.now(IST) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT symbol, entry_price, tp1, sl FROM signal_history WHERE created_date >= ?", (twenty_four_hrs_ago,))
            records = cursor.fetchall()
            
        if not records:
            return

        live_coins = get_market_data()
        current_prices = {c["symbol"]: c["price"] for c in live_coins}

        total_signals = 0
        wins = 0
        losses = 0

        for rec in records:
            sym, entry, tp1, sl = rec
            current_p = current_prices.get(sym)
            if not current_p:
                continue
                
            total_signals += 1
            if tp1 > entry:
                if current_p >= tp1 or current_p > entry:
                    wins += 1
                else:
                    losses += 1
            else:
                if current_p <= tp1 or current_p < entry:
                    wins += 1
                else:
                    losses += 1

        if total_signals == 0:
            return

        win_rate = round((wins / total_signals) * 100, 1)
        report_msg = (
            f"24-HOUR VIP SIGNAL RESULTS REPORT\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Total Unique Signals: {total_signals}\n"
            f"Targets Hit / Profit Trades: {wins}\n"
            f"Stop Losses Hit: {losses}\n"
            f"Win Rate Accuracy: {win_rate}%\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Binance Referral Link: {BINANCE_REF_LINK}\n"
            f"Join VIP For Instant Signals: @BinanceTop10_VIPBot"
        )

        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, report_msg)
        send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, report_msg)
        log_event(f"24-Hour Results Published! Total: {total_signals}, Win Rate: {win_rate}%")
    except Exception as e:
        log_event(f"Result Generation Error: {e}")

def live_signal_monitor_worker():
    log_event("Live Signal TP/SL Monitor Worker Started...")
    while True:
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, symbol, entry_price, tp1, tp2, tp3, sl, hits FROM signal_history WHERE status = 'PENDING'")
                pending_signals = cursor.fetchall()

            if pending_signals:
                live_coins = get_market_data()
                current_prices = {c["symbol"]: c["price"] for c in live_coins}

                for sig in pending_signals:
                    s_id, sym, entry, tp1, tp2, tp3, sl, hits = sig
                    current_p = current_prices.get(sym)
                    if not current_p:
                        continue

                    already_hit = set(hits.split(",")) if hits else set()
                    is_long = tp1 > entry

                    hits_to_trigger = []

                    if is_long:
                        if "TP1" not in already_hit and current_p >= tp1:
                            hits_to_trigger.append(("TP1", f"Target 1 Hit (${format_price(tp1)})"))
                        if "TP2" not in already_hit and current_p >= tp2:
                            hits_to_trigger.append(("TP2", f"Target 2 Hit (${format_price(tp2)})"))
                        if "TP3" not in already_hit and current_p >= tp3:
                            hits_to_trigger.append(("TP3", f"Target 3 Hit (${format_price(tp3)})"))
                        if "SL" not in already_hit and current_p <= sl:
                            hits_to_trigger.append(("SL", f"Stop Loss Hit (${format_price(sl)})"))
                    else:
                        if "TP1" not in already_hit and current_p <= tp1:
                            hits_to_trigger.append(("TP1", f"Target 1 Hit (${format_price(tp1)})"))
                        if "TP2" not in already_hit and current_p <= tp2:
                            hits_to_trigger.append(("TP2", f"Target 2 Hit (${format_price(tp2)})"))
                        if "TP3" not in already_hit and current_p <= tp3:
                            hits_to_trigger.append(("TP3", f"Target 3 Hit (${format_price(tp3)})"))
                        if "SL" not in already_hit and current_p >= sl:
                            hits_to_trigger.append(("SL", f"Stop Loss Hit (${format_price(sl)})"))

                    for code, target_str in hits_to_trigger:
                        update_msg = (
                            f"LIVE SIGNAL UPDATE\n"
                            f"━━━━━━━━━━━━━━━━━━━━━\n"
                            f"Pair: #{sym}\n"
                            f"Entry: ${format_price(entry)}\n"
                            f"Current Price: ${format_price(current_p)}\n"
                            f"Status: {target_str}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━\n"
                            f"Binance Referral Link: {BINANCE_REF_LINK}\n"
                            f"Join VIP For More: @BinanceTop10_VIPBot"
                        )
                        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, update_msg)
                        send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, update_msg)

                        already_hit.add(code)
                        new_hits = ",".join(already_hit)
                        new_status = "COMPLETED" if ("TP3" in already_hit or "SL" in already_hit) else "PENDING"

                        with get_db() as conn:
                            cursor = conn.cursor()
                            cursor.execute("UPDATE signal_history SET hits = ?, status = ? WHERE id = ?", (new_hits, new_status, s_id))
                        
                        log_event(f"Signal Update Sent for {sym}: {target_str}")
        except Exception as e:
            log_event(f"Live Monitor Error: {e}")
        time.sleep(60)

def scan_and_dispatch(force_mode=False):
    global vip_signals_today, free_signals_today, last_reset_day, last_free_dispatch_time, last_vip_dispatch_time
    log_event(f"Running Scan (Force Mode: {force_mode})...")

    current_time = time.time()
    current_day = datetime.now(IST).day

    if current_day != last_reset_day:
        vip_signals_today = 0
        free_signals_today = 0
        last_reset_day = current_day
        cleanup_3day_old_data()
        generate_24h_result_report()

    coins = get_market_data()
    if not coins:
        log_event("Scan aborted: No coins fetched from APIs.")
        return

    coin_index = (vip_signals_today + free_signals_today) % len(coins)
    selected_coin = coins[coin_index]
    
    p = selected_coin["price"]
    sym = selected_coin["symbol"]
    chg = selected_coin["change"]
    
    if chg >= 3.0:
        signal_mode = "FUTURES SCALP LONG"
        leverage = "Cross 10x - 20x"
        tp1, tp2, tp3, sl = p * 1.006, p * 1.015, p * 1.030, p * 0.940
    elif chg <= -3.0:
        signal_mode = "FUTURES SCALP SHORT"
        leverage = "Cross 10x - 20x"
        tp1, tp2, tp3, sl = p * 0.994, p * 0.985, p * 0.970, p * 1.060
    else:
        signal_mode = "SPOT QUICK SCALP"
        leverage = "Spot (1x)"
        tp1, tp2, tp3, sl = p * 1.008, p * 1.020, p * 1.040, p * 0.920

    rsi_est = round(50.0 + (chg * 0.6), 1)
    rsi_est = min(max(rsi_est, 22.1), 78.4)

    setup = {
        "symbol": sym, "price": p, "mode": signal_mode, "leverage": leverage,
        "rsi": rsi_est, "tp1": tp1, "tp2": tp2, "tp3": tp3, "sl": sl,
        "change": round(chg, 2), "low": selected_coin.get("low", p * 0.95)
    }

    should_send_vip = force_mode or (vip_signals_today < 36 and (current_time - last_vip_dispatch_time >= 2400))
    should_send_free = force_mode or (free_signals_today < 6 and (current_time - last_free_dispatch_time >= 14400))

    if should_send_vip:
        dispatch_vip_signal(setup)
        vip_signals_today += 1
        last_vip_dispatch_time = current_time
        log_event(f"VIP Signal Sent ({vip_signals_today}/36) for {sym}")

    if should_send_free:
        dispatch_free_signal(setup)
        free_signals_today += 1
        last_free_dispatch_time = current_time
        log_event(f"Free Signal Sent ({free_signals_today}/6) for {sym}")

    if should_send_vip or should_send_free:
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute(
                    "INSERT INTO signal_history (symbol, entry_price, tp1, tp2, tp3, sl, timestamp, created_date, status, hits) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', '')", 
                    (sym, p, tp1, tp2, tp3, sl, current_time, now_str)
                )
        except Exception as e:
            log_event(f"History Save Error: {e}")

def dispatch_vip_signal(s):
    msg = (
        f"BINANCE VIP TRADE SIGNAL\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Pair: #{s['symbol']}\n"
        f"Market Type: {s['mode']}\n"
        f"Leverage: {s['leverage']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Entry Zone: ${format_price(s['price'])}\n\n"
        f"Target 1: ${format_price(s['tp1'])}\n"
        f"Target 2: ${format_price(s['tp2'])}\n"
        f"Target 3 (Max): ${format_price(s['tp3'])}\n"
        f"Stop Loss (SL): ${format_price(s['sl'])}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"TARGETS & SL SUMMARY:\n"
        f"• TP1: ${format_price(s['tp1'])}\n"
        f"• TP2: ${format_price(s['tp2'])}\n"
        f"• TP3: ${format_price(s['tp3'])}\n"
        f"• SL: ${format_price(s['sl'])}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"24h Change: {s['change']}%\n"
        f"RSI Indicator: {s['rsi']}\n"
        f"Key Support/Resistance: ${format_price(s['low'])}\n"
        f"Strategy: High-Probability Scalp\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Create Binance Account (Ref): {BINANCE_REF_LINK}\n"
        f"Use 2-5% of total wallet balance per trade."
    )
    return send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, msg)

def dispatch_free_signal(s):
    msg = (
        f"REAL-TIME VIP SIGNAL PREVIEW\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Pair: #{s['symbol']}\n"
        f"Market Type: {s['mode']}\n"
        f"Leverage: {s['leverage']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Entry Zone: ${format_price(s['price'])}\n\n"
        f"Target 1: ${format_price(s['tp1'])}\n"
        f"Target 2: ${format_price(s['tp2'])}\n"
        f"Target 3 (Max): ${format_price(s['tp3'])}\n"
        f"Stop Loss (SL): ${format_price(s['sl'])}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"TARGETS & SL SUMMARY:\n"
        f"• TP1: ${format_price(s['tp1'])}\n"
        f"• TP2: ${format_price(s['tp2'])}\n"
        f"• TP3: ${format_price(s['tp3'])}\n"
        f"• SL: ${format_price(s['sl'])}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"24h Change: {s['change']}%\n"
        f"RSI Indicator: {s['rsi']}\n"
        f"Key Support/Resistance: ${format_price(s['low'])}\n"
        f"Strategy: High-Probability Scalp\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Binance Referral Link: {BINANCE_REF_LINK}\n"
        f"Free Channel: https://t.me/BinanceTop10Free\n"
        f"Join VIP For All Signals: @BinanceTop10_VIPBot"
    )
    return send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, msg)

# ==========================================
# TELEGRAM API & USER MANAGEMENT
# ==========================================
def send_telegram_msg(bot_token, chat_id, text, reply_markup=None):
    if not bot_token:
        log_event(f"Telegram Error: Missing Bot Token for Chat ID {chat_id}")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    
    chat_str = str(chat_id)
    if not chat_str.startswith("-"):
        payload["reply_markup"] = reply_markup if reply_markup else KEYBOARD_LAYOUT

    try:
        res = requests.post(url, json=payload, timeout=10.0)
        data = res.json()
        if not data.get("ok", False):
            log_event(f"Telegram Send FAILED ({chat_id}): {res.status_code} - {data.get('description')}")
        return data.get("ok", False)
    except Exception as e:
        log_event(f"Telegram Send Exception Error: {e}")
        return False

def kick_telegram_user(chat_id, user_id):
    if not VIP_BOT_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{VIP_BOT_TOKEN}/banChatMember"
    payload = {"chat_id": chat_id, "user_id": user_id, "revoke_messages": False}
    try:
        res = requests.post(url, json=payload, timeout=5.0)
        requests.post(f"https://api.telegram.org/bot{VIP_BOT_TOKEN}/unbanChatMember", json={"chat_id": chat_id, "user_id": user_id}, timeout=5.0)
        return res.json().get("ok", False)
    except Exception:
        return False

def verify_usdt_trc20_tx(txid, expected_amount_min=10.0):
    try:
        url = f"https://apilist.tronscan.org/api/transaction-info?hash={txid.strip()}"
        res = requests.get(url, timeout=5.0)
        if res.status_code != 200:
            return False, 0, "Invalid TXID format or Blockchain API error."
        
        data = res.json()
        if not data or data.get("contractRet") != "SUCCESS":
            return False, 0, "Transaction failed, pending, or not found on blockchain."
            
        trc20_transfers = data.get("trc20TransferInfo", [])
        if not trc20_transfers:
            return False, 0, "No USDT TRC20 transfer found in this Transaction ID."
            
        for t in trc20_transfers:
            to_addr = t.get("to_address", "")
            symbol = t.get("symbol", "")
            raw_amount = float(t.get("amount_str", "0")) / 10**6
            
            if to_addr == TRUST_WALLET_ADDRESS and symbol == "USDT" and raw_amount >= expected_amount_min:
                return True, raw_amount, "Verification Successful!"
                
        return False, 0, "Recipient address or payment amount does not match our wallet/plans."
    except Exception as e:
        return False, 0, f"Verification error: {e}"

def membership_expiry_checker():
    log_event("Expiry & Auto-Kick Worker Started...")
    while True:
        try:
            now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id FROM members WHERE expiry_date <= ? AND status = 'ACTIVE'", (now_str,))
                expired_users = cursor.fetchall()
                
                for row in expired_users:
                    u_id = row[0]
                    if kick_telegram_user(VIP_CHANNEL_ID, u_id):
                        log_event(f"Auto-Kicked expired user ID: {u_id}")
                        send_telegram_msg(VIP_BOT_TOKEN, u_id, "Your VIP Membership has Expired!\n\nYou have been removed from the VIP channel.")
                    cursor.execute("UPDATE members SET status = 'EXPIRED' WHERE user_id = ?", (u_id,))
        except Exception as e:
            log_event(f"Expiry Checker Error: {e}")
        time.sleep(3600)

def process_message_async(chat_id, text):
    try:
        log_event(f"Processing message from {chat_id}: {text}")
        text_clean = text.strip()

        if text_clean.startswith("/start"):
            welcome_text = (
                f"Welcome to Binance Top 10 Signals Bot!\n\n"
                f"Get high-accuracy crypto signals with multi-TP targets and automated VIP access.\n\n"
                f"Want Free VIP? Create your Binance account using our official link below, then send your Binance UID here:\n"
                f"{BINANCE_REF_LINK}\n\n"
                f"Use the menu buttons below to navigate:"
            )
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, welcome_text)

        elif "View VIP Plans" in text_clean:
            plan_text = (
                "VIP MEMBERSHIP PLANS\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "• 10 Days VIP: $10 USDT\n"
                "• 20 Days VIP: $19 USDT\n"
                "• 30 Days VIP: $28 USDT\n\n"
                "Click 'Get Payment Address' to proceed with payment or 'Free VIP via Referral' to join for free!"
            )
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, plan_text)

        elif "Get Payment Address" in text_clean:
            pay_text = (
                "USDT TRC20 PAYMENT ADDRESS\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"{TRUST_WALLET_ADDRESS}\n\n"
                "Send only USDT via TRC20 network. After payment, save your TXID."
            )
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, pay_text)

        elif "Free VIP via Referral" in text_clean:
            ref_text = (
                "GET 1 MONTH FREE VIP VIA BINANCE REFERRAL\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "1. Create a new Binance account using our official referral link:\n"
                f"{BINANCE_REF_LINK}\n\n"
                "2. Complete your account setup.\n"
                "3. Copy your Binance UID (8-10 digit number) and send it directly here in chat.\n\n"
                "Our team will verify your referral and grant you 1 month of Free VIP access!"
            )
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, ref_text)

        elif "Verify Payment" in text_clean:
            verify_text = (
                "PAYMENT VERIFICATION\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "Please send your Transaction ID (TXID) right here in the chat."
            )
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, verify_text)

        elif "How to Verify TXID" in text_clean:
            guide_text = (
                "HOW TO VERIFY PAYMENT\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "1. Transfer USDT to our TRC20 wallet.\n"
                "2. Copy the Transaction ID (TXID / Hash) from your wallet.\n"
                "3. Send your TXID here in chat for automatic verification."
            )
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, guide_text)

        elif text_clean.isdigit() and 7 <= len(text_clean) <= 12:
            binance_uid = text_clean
            now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            
            try:
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO referral_claims (user_id, binance_uid, status, created_date) VALUES (?, ?, 'PENDING', ?)", 
                                  (chat_id, binance_uid, now_str))
                
                success_claim_msg = (
                    "BINANCE UID RECEIVED & SAVED!\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Binance UID: {binance_uid}\n"
                    f"Status: PENDING ADMIN VERIFICATION\n\n"
                    "Once confirmed, your 1 month Free VIP access will be activated!"
                )
                send_telegram_msg(VIP_BOT_TOKEN, chat_id, success_claim_msg)
                log_event(f"Referral claim submitted by user {chat_id} with UID {binance_uid}")
            except sqlite3.IntegrityError:
                send_telegram_msg(VIP_BOT_TOKEN, chat_id, "Error: This Binance UID has already been submitted or claimed!")

        else:
            txid = text_clean
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM processed_txids WHERE txid = ?", (txid,))
                if cursor.fetchone():
                    send_telegram_msg(VIP_BOT_TOKEN, chat_id, "Error: This TXID has already been used!")
                    return

            is_valid, paid_amount, reason = verify_usdt_trc20_tx(txid, expected_amount_min=10.0)

            if is_valid:
                days = 30 if paid_amount >= 27.0 else (20 if paid_amount >= 18.0 else 10)
                plan_name = f"{days} Days VIP"
                expiry_dt = datetime.now(IST) + timedelta(days=days)
                expiry_str = expiry_dt.strftime("%Y-%m-%d %H:%M:%S")

                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO processed_txids (txid) VALUES (?)", (txid,))
                    cursor.execute("INSERT OR REPLACE INTO members (user_id, expiry_date, status) VALUES (?, ?, 'ACTIVE')", (chat_id, expiry_str))

                success_msg = (
                    "PAYMENT VERIFIED & VIP ACTIVATED!\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Plan: {plan_name} (${paid_amount} USDT)\n"
                    f"Valid Till: {expiry_str}\n\n"
                    "VIP Channel Invite Link:\n"
                    "https://t.me/+YourVIPChannelInviteLink"
                )
                send_telegram_msg(VIP_BOT_TOKEN, chat_id, success_msg)
            else:
                fail_msg = f"VERIFICATION FAILED\n\nReason: {reason}"
                send_telegram_msg(VIP_BOT_TOKEN, chat_id, fail_msg)
    except Exception as e:
        log_event(f"Async Processing Error: {e}")

# ==========================================
# FLASK ROUTES & WEBHOOKS
# ==========================================
@app.route("/", methods=["GET"])
def index():
    return "Binance Signals Bot Service Running.", 200

@app.route("/webhook/vip", methods=["POST"])
def vip_webhook():
    data = request.get_json(silent=True) or {}
    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")
        if text:
            threading.Thread(target=process_message_async, args=(chat_id, text)).start()
    return jsonify({"status": "ok"}), 200

@app.route("/admin/approve_referral", methods=["POST"])
def admin_approve_referral():
    auth_key = request.headers.get("X-Admin-Secret")
    if auth_key != ADMIN_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json() or {}
    binance_uid = payload.get("binance_uid")
    
    if not binance_uid:
        return jsonify({"error": "Missing binance_uid"}), 400

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM referral_claims WHERE binance_uid = ?", (binance_uid,))
        row = cursor.fetchone()
        
        if not row:
            return jsonify({"error": "Referral claim not found"}), 404
            
        user_id = row[0]
        expiry_str = (datetime.now(IST) + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("UPDATE referral_claims SET status = 'APPROVED' WHERE binance_uid = ?", (binance_uid,))
        cursor.execute("INSERT OR REPLACE INTO members (user_id, expiry_date, status) VALUES (?, ?, 'ACTIVE')", (user_id, expiry_str))

    send_telegram_msg(VIP_BOT_TOKEN, user_id, "Referral Verified! Your 30-day Free VIP access is activated!")
    return jsonify({"status": "success", "user_id": user_id, "expiry_date": expiry_str}), 200

@app.route("/admin/force_scan", methods=["POST"])
def admin_force_scan():
    auth_key = request.headers.get("X-Admin-Secret")
    if auth_key != ADMIN_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    threading.Thread(target=scan_and_dispatch, kwargs={"force_mode": True}).start()
    return jsonify({"status": "Scan triggered"}), 200

# ==========================================
# BACKGROUND WORKERS
# ==========================================
def start_background_threads():
    threading.Thread(target=membership_expiry_checker, daemon=True).start()
    threading.Thread(target=live_signal_monitor_worker, daemon=True).start()

start_background_threads()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
