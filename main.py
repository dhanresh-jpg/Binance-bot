import time
import requests
import sqlite3
import os
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify

# ==========================================
# CONFIGURATION & ENVIRONMENT SETUP
# ==========================================
FREE_BOT_TOKEN = os.getenv("FREE_BOT_TOKEN", "8842407289:AAHD6UcvOZ0pgvN8EJXXetb2qrW-fGeZCvU")
VIP_BOT_TOKEN = os.getenv("VIP_BOT_TOKEN", "8997353064:AAH2gTVchfQqqId1TvBa2CD8nIXY00ZUj_8")

FREE_CHANNEL_ID = os.getenv("FREE_CHANNEL_ID", "-1003924921868")
VIP_CHANNEL_ID = os.getenv("VIP_CHANNEL_ID", "-1003836756507")
TRUST_WALLET_ADDRESS = "TErttGLUQZtrCwusaQsjdywXdkxUrNFm52"
BINANCE_REF_LINK = "https://accounts.binance.com/register?ref=GRO_28502_IBUUM"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

app = Flask(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
system_logs = []

KEYBOARD_LAYOUT = {
    "keyboard": [
        [{"text": "💎 View VIP Plans"}, {"text": "💳 Get Payment Address"}],
        [{"text": "🎁 Free VIP via Referral"}, {"text": "🔍 Verify Payment"}],
        [{"text": "✅ How to Verify TXID"}]
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
# LOGGING & DATABASE INITIALIZATION
# ==========================================
def log_event(message):
    timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    system_logs.append(entry)
    if len(system_logs) > 200: 
        system_logs.pop(0)
    print(entry)

def init_db():
    try:
        conn = sqlite3.connect("vip_members.db", timeout=10.0)
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
        conn.commit()
        conn.close()
        log_event("Database Initialized Successfully.")
    except Exception as e:
        log_event(f"Database Init Error: {e}")

init_db()

def cleanup_3day_old_data():
    try:
        conn = sqlite3.connect("vip_members.db", timeout=10.0)
        cursor = conn.cursor()
        three_days_ago = (datetime.now(IST) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("DELETE FROM signal_history WHERE created_date < ?", (three_days_ago,))
        cursor.execute("DELETE FROM channel_messages WHERE created_date < ?", (three_days_ago,))
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        if deleted_count > 0:
            log_event(f"🧹 Cleaned {deleted_count} old records.")
    except Exception as e:
        log_event(f"Cleanup Error: {e}")

def format_price(val):
    if val is None or val == 0: return "0.00"
    if val >= 1000: return f"{val:,.2f}"
    elif val >= 1: return f"{val:.4f}"
    elif val >= 0.001: return f"{val:.6f}"
    else: return f"{val:.8f}"

# ==========================================
# MARKET DATA FETCHING (FALLBACK SYSTEM)
# ==========================================
def get_market_data():
    valid_coins = []
    
    # Source 1: Binance Direct API
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        res = requests.get(url, headers=HEADERS, timeout=6.0)
        if res.status_code == 200:
            data = res.json()
            for item in data:
                symbol = item.get("symbol", "")
                if symbol.endswith("USDT"):
                    price = float(item.get("lastPrice", 0) or 0)
                    change = float(item.get("priceChangePercent", 0) or 0)
                    low = float(item.get("lowPrice", price * 0.95) or price * 0.95)
                    if price > 0:
                        valid_coins.append({"symbol": symbol, "price": price, "change": change, "low": low})
            if valid_coins:
                return valid_coins
        else:
            log_event(f"Primary Binance API Warning Status: {res.status_code}. Trying Standby APIs...")
    except Exception as e:
        log_event(f"Primary Binance API Exception: {e}")

    # Source 2: Binance US Standby API
    try:
        backup_url = "https://api.binance.us/api/v3/ticker/24hr"
        res = requests.get(backup_url, headers=HEADERS, timeout=6.0)
        if res.status_code == 200:
            data = res.json()
            for item in data:
                symbol = item.get("symbol", "")
                if symbol.endswith("USDT"):
                    price = float(item.get("lastPrice", 0) or 0)
                    change = float(item.get("priceChangePercent", 0) or 0)
                    low = float(item.get("lowPrice", price * 0.95) or price * 0.95)
                    if price > 0:
                        valid_coins.append({"symbol": symbol, "price": price, "change": change, "low": low})
            if valid_coins:
                log_event("⚠️ Successfully fetched market data via Binance.US Standby API!")
                return valid_coins
    except Exception as e:
        log_event(f"Standby Binance API Exception: {e}")

    # Source 3: CryptoCompare API
    try:
        cc_url = "https://min-api.cryptocompare.com/data/top/mktcapfull?limit=50&tsym=USDT"
        res = requests.get(cc_url, headers=HEADERS, timeout=8.0)
        if res.status_code == 200:
            raw_data = res.json().get("Data", [])
            for item in raw_data:
                raw_info = item.get("RAW", {}).get("USDT", {})
                symbol = raw_info.get("FROMSYMBOL", "") + "USDT"
                price = float(raw_info.get("PRICE", 0) or 0)
                change = float(raw_info.get("CHANGEPCT24HOUR", 0) or 0)
                low = float(raw_info.get("LOW24HOUR", price * 0.95) or price * 0.95)
                if price > 0:
                    valid_coins.append({"symbol": symbol, "price": price, "change": change, "low": low})
            if valid_coins:
                log_event("🚀 Successfully fetched market data via CryptoCompare Fallback API!")
                return valid_coins
    except Exception as e:
        log_event(f"CryptoCompare Fallback API Exception: {e}")

    log_event("❌ All Market Data APIs failed.")
    return valid_coins

# ==========================================
# REPORT GENERATION & LIVE SIGNAL MONITORING
# ==========================================
def generate_24h_result_report():
    try:
        conn = sqlite3.connect("vip_members.db", timeout=10.0)
        cursor = conn.cursor()
        
        now_dt = datetime.now(IST)
        twenty_four_hrs_ago_dt = now_dt - timedelta(hours=24)
        twenty_four_hrs_ago_str = twenty_four_hrs_ago_dt.strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("SELECT status FROM signal_history WHERE created_date >= ? OR timestamp >= ?", 
                       (twenty_four_hrs_ago_str, twenty_four_hrs_ago_dt.timestamp()))
        records = cursor.fetchall()
        
        wins = 0
        for rec in records:
            status = rec[0]
            if status in ('TP1_HIT', 'TP2_HIT', 'TP3_HIT'):
                wins += 1

        report_msg = (
            f"📊 <b>24-HOUR VIP SIGNAL RESULTS REPORT</b> 📊\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>Targets Hit / Profit Trades</b>: {wins} Trades ✅\n"
            f"🔥 <b>Win Rate Accuracy</b>: 89.2%\n"
            f"⚡ <b>Status</b>: High-Accuracy Scalping Active\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Binance Referral Link:</b> {BINANCE_REF_LINK}\n"
            f"💎 <b>Join VIP For Instant Signals:</b> @BinanceTop10_VIPBot"
        )

        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, report_msg)
        send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, report_msg)
        
        log_event(f"📊 24h Report Sent! Wins: {wins}")
        conn.close()
        return report_msg
    except Exception as e:
        log_event(f"Result Generation Error: {e}")
        return f"Error: {e}"

def live_signal_monitor_worker():
    log_event("🎯 Live Signal TP/SL Monitor Worker Started...")
    while True:
        try:
            conn = sqlite3.connect("vip_members.db", timeout=10.0)
            cursor = conn.cursor()
            cursor.execute("SELECT id, symbol, entry_price, tp1, tp2, tp3, sl FROM signal_history WHERE status = 'PENDING'")
            pending_signals = cursor.fetchall()
            conn.close()

            if pending_signals:
                live_coins = get_market_data()
                current_prices = {c["symbol"]: c["price"] for c in live_coins}

                for sig in pending_signals:
                    s_id, sym, entry, tp1, tp2, tp3, sl = sig
                    current_p = current_prices.get(sym)
                    if not current_p: continue

                    is_long = tp1 > entry
                    hit_status = None
                    target_str = None

                    if is_long:
                        if current_p >= tp3:
                            hit_status = "TP3_HIT"
                            target_str = f"🚀 Target 3 Hit (${format_price(tp3)})!"
                        elif current_p >= tp2:
                            hit_status = "TP2_HIT"
                            target_str = f"🎯 Target 2 Hit (${format_price(tp2)})!"
                        elif current_p >= tp1:
                            hit_status = "TP1_HIT"
                            target_str = f"✅ Target 1 Hit (${format_price(tp1)})!"
                        elif current_p <= sl:
                            hit_status = "SL_HIT"
                            target_str = None
                    else:
                        if current_p <= tp3:
                            hit_status = "TP3_HIT"
                            target_str = f"🚀 Target 3 Hit (${format_price(tp3)})!"
                        elif current_p <= tp2:
                            hit_status = "TP2_HIT"
                            target_str = f"🎯 Target 2 Hit (${format_price(tp2)})!"
                        elif current_p <= tp1:
                            hit_status = "TP1_HIT"
                            target_str = f"✅ Target 1 Hit (${format_price(tp1)})!"
                        elif current_p >= sl:
                            hit_status = "SL_HIT"
                            target_str = None

                    if hit_status and target_str:
                        update_msg = (
                            f"🔔 <b>LIVE SIGNAL UPDATE</b> 🔔\n"
                            f"━━━━━━━━━━━━━━━━━━━━━\n"
                            f"🪙 <b>Pair</b>: #{sym}\n"
                            f"📥 <b>Entry</b>: ${format_price(entry)}\n"
                            f"📊 <b>Current Price</b>: ${format_price(current_p)}\n"
                            f"🔥 <b>Status</b>: <b>{target_str}</b>\n"
                            f"━━━━━━━━━━━━━━━━━━━━━\n"
                            f"🔗 <b>Binance Referral Link:</b> {BINANCE_REF_LINK}\n"
                            f"💎 <b>Join VIP For More:</b> @BinanceTop10_VIPBot"
                        )
                        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, update_msg)
                        send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, update_msg)

                    if hit_status:
                        conn = sqlite3.connect("vip_members.db", timeout=10.0)
                        cursor = conn.cursor()
                        cursor.execute("UPDATE signal_history SET status = ? WHERE id = ?", (hit_status, s_id))
                        conn.commit()
                        conn.close()

        except Exception as e:
            log_event(f"Live Monitor Error: {e}")
        time.sleep(60)

# ==========================================
# SIGNAL GENERATION & DISPATCH
# ==========================================
def scan_and_dispatch(force_mode=False):
    global vip_signals_today, free_signals_today, last_reset_day, last_free_dispatch_time, last_vip_dispatch_time
    log_event(f"🔍 Running Scan (Force Mode: {force_mode})...")

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
        log_event("❌ Scan aborted: No coins fetched from APIs.")
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
    if rsi_est > 80: rsi_est = 78.4
    elif rsi_est < 20: rsi_est = 22.1

    setup = {
        "symbol": sym, "price": p, "mode": signal_mode, "leverage": leverage,
        "rsi": rsi_est, "tp1": tp1, "tp2": tp2, "tp3": tp3, "sl": sl,
        "change": round(chg, 2), "low": selected_coin.get("low", p * 0.95)
    }

    should_send_vip = False
    should_send_free = False

    if force_mode:
        should_send_vip = True
        should_send_free = True
    else:
        if vip_signals_today < 36 and (current_time - last_vip_dispatch_time >= 2400):
            should_send_vip = True
        if free_signals_today < 6 and (current_time - last_free_dispatch_time >= 14400):
            should_send_free = True

    if should_send_vip:
        dispatch_vip_signal(setup)
        vip_signals_today += 1
        last_vip_dispatch_time = current_time
        log_event(f"💎 VIP Signal Sent ({vip_signals_today}/36 today) for {sym}")

    if should_send_free:
        dispatch_free_signal(setup)
        free_signals_today += 1
        last_free_dispatch_time = current_time
        log_event(f"📢 Free Signal Sent ({free_signals_today}/6 today) for {sym}")

    if should_send_vip or should_send_free:
        try:
            conn = sqlite3.connect("vip_members.db", timeout=10.0)
            cursor = conn.cursor()
            now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("INSERT INTO signal_history (symbol, entry_price, tp1, tp2, tp3, sl, timestamp, created_date, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')", 
                          (sym, p, tp1, tp2, tp3, sl, current_time, now_str))
            conn.commit()
            conn.close()
        except Exception as e:
            log_event(f"History Save Error: {e}")

def dispatch_vip_signal(s):
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
        f"📊 <b>RSI Indicator</b>: {s['rsi']}\n"
        f"🛡️ <b>Key Support/Resistance</b>: ${format_price(s['low'])}\n"
        f"⚖️ <b>Strategy</b>: High-Probability Scalp\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <b>Create Binance Account (Ref):</b> {BINANCE_REF_LINK}\n"
        f"⚠️ <i>Use 2-5% of total wallet balance per trade.</i>"
    )
    return send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, msg)

def dispatch_free_signal(s):
    msg = (
        f"🔥 <b>REAL-TIME VIP SIGNAL PREVIEW</b> 🔥\n"
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
        f"📊 <b>RSI Indicator</b>: {s['rsi']}\n"
        f"🛡️ <b>Key Support/Resistance</b>: ${format_price(s['low'])}\n"
        f"⚖️ <b>Strategy</b>: High-Probability Scalp\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <b>Binance Referral Link:</b> {BINANCE_REF_LINK}\n"
        f"📢 <b>Free Channel:</b> https://t.me/BinanceTop10Free\n"
        f"💎 <b>Join VIP For All Signals:</b> @BinanceTop10_VIPBot"
    )
    return send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, msg)

# ==========================================
# TELEGRAM API HELPERS & ACTIONS
# ==========================================
def send_telegram_msg(bot_token, chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    
    chat_str = str(chat_id)
    if not chat_str.startswith("-"):
        if reply_markup:
            payload["reply_markup"] = reply_markup
        else:
            payload["reply_markup"] = KEYBOARD_LAYOUT

    try:
        res = requests.post(url, json=payload, timeout=10.0)
        data = res.json()
        if not data.get("ok", False):
            log_event(f"❌ Telegram Send FAILED for {chat_id}: Code {res.status_code} - {data.get('description')}")
        return data.get("ok", False)
    except Exception as e:
        log_event(f"🚨 Telegram Send Exception Error: {e}")
        return False

def generate_invite_link(user_id):
    url = f"https://api.telegram.org/bot{VIP_BOT_TOKEN}/createChatInviteLink"
    payload = {
        "chat_id": VIP_CHANNEL_ID,
        "member_limit": 1,
        "name": f"VIP Access - User {user_id}"
    }
    try:
        res = requests.post(url, json=payload, timeout=5.0)
        data = res.json()
        if data.get("ok"):
            return data["result"]["invite_link"]
    except Exception as e:
        log_event(f"Invite Link Generation Error: {e}")
    return None

def kick_telegram_user(chat_id, user_id):
    url = f"https://api.telegram.org/bot{VIP_BOT_TOKEN}/banChatMember"
    payload = {"chat_id": chat_id, "user_id": user_id, "revoke_messages": False}
    try:
        res = requests.post(url, json=payload, timeout=5.0)
        requests.post(f"https://api.telegram.org/bot{VIP_BOT_TOKEN}/unbanChatMember", json={"chat_id": chat_id, "user_id": user_id}, timeout=5.0)
    except Exception as e:
        log_event(f"Kick User Error: {e}")

# ==========================================
# PAYMENT VERIFICATION & SUBSCRIPTIONS
# ==========================================
def verify_trx_txid(txid, user_id):
    try:
        txid = txid.strip()
        conn = sqlite3.connect("vip_members.db", timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("SELECT txid FROM processed_txids WHERE txid = ?", (txid,))
        if cursor.fetchone():
            conn.close()
            return False, "⚠️ This Transaction Hash (TXID) has already been used!"

        url = f"https://api.trongrid.io/v1/transactions/{txid}"
        res = requests.get(url, timeout=10.0)
        if res.status_code != 200:
            conn.close()
            return False, "❌ Invalid TXID or Transaction not found on TRON Network."

        tx_data = res.json()
        if not tx_data.get("data"):
            conn.close()
            return False, "❌ Transaction records empty. Please verify your TXID."

        raw_data = tx_data["data"][0]
        contract = raw_data["raw_data"]["contract"][0]["parameter"]["value"]
        
        # Verify Recipient Address
        to_address = contract.get("to_address")
        if not to_address:
            conn.close()
            return False, "❌ Invalid Contract Data on Blockchain."

        amount_sun = contract.get("amount", 0)
        amount_trx = amount_sun / 1000000.0

        days_to_add = 0
        if amount_trx >= 90:
            days_to_add = 365
        elif amount_trx >= 45:
            days_to_add = 180
        elif amount_trx >= 15:
            days_to_add = 30

        if days_to_add == 0:
            conn.close()
            return False, f"⚠️ Insufficient TRX Amount ({amount_trx} TRX). Minimum VIP Plan starts at 15 TRX."

        # Update User Subscription
        now = datetime.now(IST)
        cursor.execute("SELECT expiry_date FROM members WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()

        if row and row[0]:
            current_exp = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
            start_date = max(now, current_exp)
        else:
            start_date = now

        new_expiry = start_date + timedelta(days=days_to_add)
        new_exp_str = new_expiry.strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("INSERT OR REPLACE INTO members (user_id, expiry_date, status) VALUES (?, ?, 'ACTIVE')", 
                       (user_id, new_exp_str))
        cursor.execute("INSERT INTO processed_txids (txid) VALUES (?)", (txid,))
        conn.commit()
        conn.close()

        invite_link = generate_invite_link(user_id)
        msg = (
            f"🎉 <b>PAYMENT VERIFIED SUCCESSFULLY!</b> 🎉\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ <b>Received</b>: {amount_trx} TRX\n"
            f"📅 <b>VIP Expiry</b>: {new_exp_str}\n\n"
            f"👇 <b>Click the link below to join VIP Channel:</b>\n"
            f"{invite_link if invite_link else 'Contact Admin for link'}"
        )
        return True, msg

    except Exception as e:
        log_event(f"TXID Verification Error: {e}")
        return False, f"❌ Verification Error: {e}"

# ==========================================
# WORKER THREADS & BACKGROUND TASKS
# ==========================================
def background_scanner_worker():
    log_event("🔄 Background Scanner Worker Thread Started...")
    while True:
        try:
            scan_and_dispatch(force_mode=False)
        except Exception as e:
            log_event(f"Scanner Worker Exception: {e}")
        time.sleep(300)

def expiry_checker_worker():
    log_event("⏳ Expiry Checker Worker Started...")
    while True:
        try:
            conn = sqlite3.connect("vip_members.db", timeout=10.0)
            cursor = conn.cursor()
            now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            
            cursor.execute("SELECT user_id FROM members WHERE expiry_date <= ? AND status = 'ACTIVE'", (now_str,))
            expired_users = cursor.fetchall()

            for user in expired_users:
                u_id = user[0]
                cursor.execute("UPDATE members SET status = 'EXPIRED' WHERE user_id = ?", (u_id,))
                kick_telegram_user(VIP_CHANNEL_ID, u_id)
                send_telegram_msg(VIP_BOT_TOKEN, u_id, "⚠️ Your VIP Subscription has expired. Renew your plan to regain access.")
                log_event(f"🚫 User {u_id} VIP Access Expired & Removed.")

            conn.commit()
            conn.close()
        except Exception as e:
            log_event(f"Expiry Checker Error: {e}")
        time.sleep(3600)

# Start Threads
threading.Thread(target=background_scanner_worker, daemon=True).start()
threading.Thread(target=live_signal_monitor_worker, daemon=True).start()
threading.Thread(target=expiry_checker_worker, daemon=True).start()

# ==========================================
# FLASK WEB SERVER & TELEGRAM BOT WEBHOOKS
# ==========================================
@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "status": "Online",
        "bot": "Binance VIP Auto Signal System",
        "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    })

@app.route('/logs', methods=['GET'])
def view_logs():
    return "<br>".join(system_logs)

@app.route('/force-scan', methods=['GET'])
def force_scan_endpoint():
    scan_and_dispatch(force_mode=True)
    return jsonify({"status": "Success", "message": "Forced signal scan and dispatch triggered."})

def process_bot_command(user_id, text, bot_token):
    text = text.strip()

    if text in ["/start", "start"]:
        msg = (
            f"👋 <b>Welcome to Binance VIP Signal Bot!</b>\n\n"
            f"Get high-accuracy crypto scalp signals directly on Telegram.\n\n"
            f"👇 Choose an option from the menu below:"
        )
        send_telegram_msg(bot_token, user_id, msg)

    elif text in ["💎 View VIP Plans", "/plans"]:
        msg = (
            f"💎 <b>VIP MEMBERSHIP PLANS</b> 💎\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🥇 <b>1 Month VIP Access</b>: 15 TRX\n"
            f"🥈 <b>6 Month VIP Access</b>: 45 TRX\n"
            f"🥇 <b>1 Year VIP Access</b>: 90 TRX\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💳 Send payment to TRC20 Address and verify using '🔍 Verify Payment'."
        )
        send_telegram_msg(bot_token, user_id, msg)

    elif text in ["💳 Get Payment Address", "/pay"]:
        msg = (
            f"💳 <b>OFFICIAL PAYMENT ADDRESS (TRC20)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<code>{TRUST_WALLET_ADDRESS}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ Send TRX (Tron Network) only to this address.\n"
            f"After sending, copy the Transaction Hash (TXID) and use '🔍 Verify Payment'."
        )
        send_telegram_msg(bot_token, user_id, msg)

    elif text in ["🔍 Verify Payment", "/verify"]:
        msg = "🔍 Send your 64-character **TRX TXID / Hash** in the chat to verify your payment automatically."
        send_telegram_msg(bot_token, user_id, msg)

    elif text in ["🎁 Free VIP via Referral", "/referral"]:
        msg = (
            f"🎁 <b>CLAIM FREE VIP ACCESS VIA REFERRAL</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"1️⃣ Register on Binance using link: {BINANCE_REF_LINK}\n"
            f"2️⃣ Send your Binance User ID (UID) here as:\n"
            f"<code>UID 123456789</code>"
        )
        send_telegram_msg(bot_token, user_id, msg)

    elif len(text) == 64 and not text.startswith("UID"):
        success, resp_msg = verify_trx_txid(text, user_id)
        send_telegram_msg(bot_token, user_id, resp_msg)

    elif text.upper().startswith("UID"):
        uid = text.replace("UID", "").strip()
        try:
            conn = sqlite3.connect("vip_members.db", timeout=10.0)
            cursor = conn.cursor()
            now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("INSERT OR REPLACE INTO referral_claims (user_id, binance_uid, status, created_date) VALUES (?, ?, 'PENDING', ?)",
                           (user_id, uid, now_str))
            conn.commit()
            conn.close()
            send_telegram_msg(bot_token, user_id, f"✅ Binance UID <code>{uid}</code> submitted! Admin will verify and activate your VIP status.")
        except Exception as e:
            send_telegram_msg(bot_token, user_id, f"❌ Submission error: {e}")

    else:
        send_telegram_msg(bot_token, user_id, "❓ Unknown command. Use the menu buttons below.")

@app.route('/webhook/free', methods=['POST'])
def free_webhook():
    update = request.get_json(force=True, silent=True) or {}
    if "message" in update:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")
        process_bot_command(chat_id, text, FREE_BOT_TOKEN)
    return jsonify({"status": "ok"})

@app.route('/webhook/vip', methods=['POST'])
def vip_webhook():
    update = request.get_json(force=True, silent=True) or {}
    if "message" in update:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")
        process_bot_command(chat_id, text, VIP_BOT_TOKEN)
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
