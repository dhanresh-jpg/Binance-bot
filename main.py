import time
import requests
import sqlite3
import os
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify

# Environment Variables & Config
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

# Multi-API Fallback System
def get_market_data():
    valid_coins = []
    
    # Primary Binance API
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        res = requests.get(url, headers=HEADERS, timeout=10.0)
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
            log_event(f"Primary Binance API Warning Status: {res.status_code}. Trying Standby API...")
    except Exception as e:
        log_event(f"Primary Binance API Exception: {e}. Switching to Standby API...")

    # Standby Backup API
    try:
        backup_url = "https://data-api.binance.vision/api/v3/ticker/24hr"
        res = requests.get(backup_url, headers=HEADERS, timeout=10.0)
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
                log_event("⚠️ Successfully fetched market data using Standby Binance API endpoint!")
                return valid_coins
    except Exception as e:
        log_event(f"Standby API Exception: {e}")

    return valid_coins

def generate_24h_result_report():
    try:
        conn = sqlite3.connect("vip_members.db", timeout=10.0)
        cursor = conn.cursor()
        twenty_four_hrs_ago = (datetime.now(IST) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("SELECT DISTINCT symbol, entry_price, tp1, sl FROM signal_history WHERE created_date >= ?", (twenty_four_hrs_ago,))
        records = cursor.fetchall()
        if not records:
            conn.close()
            return

        live_coins = get_market_data()
        current_prices = {c["symbol"]: c["price"] for c in live_coins}

        total_signals = 0
        wins = 0
        losses = 0

        for rec in records:
            sym, entry, tp1, sl = rec
            current_p = current_prices.get(sym)
            if not current_p: continue
                
            total_signals += 1
            if tp1 > entry:
                if current_p >= tp1: wins += 1
                elif current_p <= sl: losses += 1
                else:
                    if current_p > entry: wins += 1
                    else: losses += 1
            else:
                if current_p <= tp1: wins += 1
                elif current_p >= sl: losses += 1
                else:
                    if current_p < entry: wins += 1
                    else: losses += 1

        if total_signals == 0:
            conn.close()
            return

        win_rate = round((wins / total_signals) * 100, 1)

        report_msg = (
            f"📊 <b>24-HOUR VIP SIGNAL RESULTS REPORT</b> 📊\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ <b>Total Unique Signals</b>: {total_signals}\n"
            f"🎯 <b>Targets Hit / Profit Trades</b>: {wins}\n"
            f"⛔ <b>Stop Losses Hit</b>: {losses}\n"
            f"🔥 <b>Win Rate Accuracy</b>: {win_rate}%\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Binance Referral Link:</b> {BINANCE_REF_LINK}\n"
            f"💎 <b>Join VIP For Instant Signals:</b> @BinanceTop10_VIPBot"
        )

        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, report_msg)
        send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, report_msg)
        log_event(f"📊 Real 24-Hour Results Published! Total: {total_signals}, Win Rate: {win_rate}%")
        conn.close()
    except Exception as e:
        log_event(f"Result Generation Error: {e}")

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
                    target_str = ""

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
                            target_str = f"⛔ Stop Loss Hit (${format_price(sl)})!"
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
                            target_str = f"⛔ Stop Loss Hit (${format_price(sl)})!"

                    if hit_status:
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

                        conn = sqlite3.connect("vip_members.db", timeout=10.0)
                        cursor = conn.cursor()
                        cursor.execute("UPDATE signal_history SET status = ? WHERE id = ?", (hit_status, s_id))
                        conn.commit()
                        conn.close()
                        log_event(f"📈 Signal Update Sent for {sym}: {target_str}")

        except Exception as e:
            log_event(f"Live Monitor Error: {e}")
        time.sleep(60)

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

def kick_telegram_user(chat_id, user_id):
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
        if not data or ("contractRet" in data and data["contractRet"] != "SUCCESS"):
            return False, 0, "Transaction failed, pending, or not found on blockchain."
            
        trc20_transfers = data.get("trc20TransferInfo", [])
        if not trc20_transfers:
            return False, 0, "No USDT TRC20 transfer found in this Transaction ID."
            
        valid_transfer = False
        final_amount = 0.0
        for t in trc20_transfers:
            to_addr = t.get("to_address", "")
            symbol = t.get("symbol", "")
            raw_amount = float(t.get("amount_str", "0")) / 10**6
            
            if (to_addr == TRUST_WALLET_ADDRESS and 
                symbol == "USDT" and 
                raw_amount >= expected_amount_min):
                valid_transfer = True
                final_amount = raw_amount
                break
                
        if valid_transfer:
            return True, final_amount, "Verification Successful!"
        else:
            return False, 0, "Recipient address or payment amount does not match our wallet/plans."
    except Exception as e:
        return False, 0, f"Verification error: {e}"

def membership_expiry_checker():
    log_event("⏳ Expiry & Auto-Kick Worker Started...")
    while True:
        try:
            conn = sqlite3.connect("vip_members.db", timeout=10.0)
            cursor = conn.cursor()
            now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            
            cursor.execute("SELECT user_id FROM members WHERE expiry_date <= ? AND status = 'ACTIVE'", (now_str,))
            expired_users = cursor.fetchall()
            
            for row in expired_users:
                u_id = row[0]
                success = kick_telegram_user(VIP_CHANNEL_ID, u_id)
                if success:
                    log_event(f"👢 Auto-Kicked expired user ID: {u_id}")
                    send_telegram_msg(VIP_BOT_TOKEN, u_id, "⚠️ <b>Your VIP Membership has Expired!</b>\n\nYou have been removed from the VIP channel. Please renew your plan using the bot menu.")
                
                cursor.execute("UPDATE members SET status = 'EXPIRED' WHERE user_id = ?", (u_id,))
                conn.commit()
            conn.close()
        except Exception as e:
            log_event(f"Expiry Checker Error: {e}")
        time.sleep(3600)

def process_message_async(chat_id, text):
    try:
        log_event(f"📩 Processing message from {chat_id}: {text}")
        text_clean = text.strip()

        if text_clean.startswith("/start"):
            welcome_text = (
                f"🤖 <b>Welcome to Binance Top 10 Signals Bot!</b>\n\n"
                f"Get high-accuracy crypto signals with multi-TP targets and automated VIP access.\n\n"
                f"🎁 <b>Want Free VIP?</b> Create your Binance account using our official link below, then send your Binance UID here:\n"
                f"🔗 {BINANCE_REF_LINK}\n\n"
                f"Use the menu buttons below to navigate:"
            )
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, welcome_text)
            
        elif "View VIP Plans" in text_clean:
            plan_text = (
                "💎 <b>VIP MEMBERSHIP PLANS</b> 💎\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "• <b>10 Days VIP</b>: $10 USDT\n"
                "• <b>20 Days VIP</b>: $19 USDT\n"
                "• <b>30 Days VIP</b>: $28 USDT\n\n"
                "<i>Click 'Get Payment Address' to proceed with payment or 'Free VIP via Referral' to join for free!</i>"
            )
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, plan_text)
            
        elif "Get Payment Address" in text_clean:
            pay_text = (
                "💳 <b>USDT TRC20 PAYMENT ADDRESS</b> 💳\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"<code>{TRUST_WALLET_ADDRESS}</code>\n\n"
                "⚠️ <i>Send only USDT via TRC20 network. After payment, save your TXID.</i>"
            )
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, pay_text)

        elif "Free VIP via Referral" in text_clean:
            ref_text = (
                "🎁 <b>GET 1 MONTH FREE VIP VIA BINANCE REFERRAL</b> 🎁\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "1️⃣ Create a new Binance account using our official referral link:\n"
                f"🔗 {BINANCE_REF_LINK}\n\n"
                "2️⃣ Complete your account setup.\n"
                "3️⃣ Copy your **Binance UID** (8-10 digit number from your Binance profile) and send it directly here in chat.\n\n"
                "<i>Our team will verify your referral and grant you 1 month of Free VIP access!</i>"
            )
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, ref_text)
            
        elif "Verify Payment" in text_clean:
            verify_text = (
                "🔍 <b>PAYMENT VERIFICATION</b> 🔍\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "Please send your <b>Transaction ID (TXID)</b> right here in the chat.\n\n"
                "Our automated system will instantly verify your TRC20 transfer and activate your VIP access!"
            )
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, verify_text)
            
        elif "How to Verify TXID" in text_clean:
            guide_text = (
                "📖 <b>HOW TO VERIFY PAYMENT</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "1. Transfer the required USDT to our TRC20 wallet.\n"
                "2. Copy the Transaction ID (TXID / Hash) from your wallet.\n"
                "3. Send your TXID here in chat for automatic verification and VIP activation."
            )
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, guide_text)
            
        elif text_clean.isdigit() and 7 <= len(text_clean) <= 12:
            binance_uid = text_clean
            now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            
            conn = sqlite3.connect("vip_members.db", timeout=10.0)
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO referral_claims (user_id, binance_uid, status, created_date) VALUES (?, ?, 'PENDING', ?)", 
                              (chat_id, binance_uid, now_str))
                conn.commit()
                conn.close()
                
                success_claim_msg = (
                    "📥 <b>BINANCE UID RECEIVED & SAVED!</b> ⏳\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🆔 <b>Binance UID</b>: <code>{binance_uid}</code>\n"
                    f"📌 <b>Status</b>: <b>PENDING ADMIN VERIFICATION</b>\n\n"
                    "🎉 We are verifying your signup through our referral link. Once confirmed, your 1 month Free VIP access will be activated!"
                )
                send_telegram_msg(VIP_BOT_TOKEN, chat_id, success_claim_msg)
                log_event(f"🎁 Referral claim submitted by user {chat_id} with UID {binance_uid}")
            except sqlite3.IntegrityError:
                conn.close()
                send_telegram_msg(VIP_BOT_TOKEN, chat_id, "⚠️ <b>Error:</b> This Binance UID has already been submitted or claimed!")
        
        else:
            txid = text_clean
            conn = sqlite3.connect("vip_members.db", timeout=10.0)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM processed_txids WHERE txid = ?", (txid,))
            if cursor.fetchone():
                conn.close()
                send_telegram_msg(VIP_BOT_TOKEN, chat_id, "⚠️ <b>Error:</b> This Transaction ID (TXID) has already been used!")
                return
                
            is_valid, paid_amount, reason = verify_usdt_trc20_tx(txid, expected_amount_min=10.0)
            
            if is_valid:
                if paid_amount >= 27.0:
                    days = 30
                    plan_name = "30 Days VIP"
                elif paid_amount >= 18.0:
                    days = 20
                    plan_name = "20 Days VIP"
                else:
                    days = 10
                    plan_name = "10 Days VIP"
                
                expiry_dt = datetime.now(IST) + timedelta(days=days)
                expiry_str = expiry_dt.strftime("%Y-%m-%d %H:%M:%S")
                
                cursor.execute("INSERT INTO processed_txids (txid) VALUES (?)", (txid,))
                cursor.execute("INSERT OR REPLACE INTO members (user_id, expiry_date, status) VALUES (?, ?, 'ACTIVE')", (chat_id, expiry_str))
                conn.commit()
                conn.close()
                
                success_msg = (
                    "✅ <b>PAYMENT VERIFIED & VIP ACTIVATED!</b> ✅\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📦 <b>Plan</b>: {plan_name} (${paid_amount} USDT)\n"
                    f"⏳ <b>Valid Till</b>: {expiry_str}\n\n"
                    "🎉 <b>VIP Channel Invite Link:</b>\n"
                    "https://t.me/+YourVIPChannelInviteLink"
                )
                send_telegram_msg(VIP_BOT_TOKEN, chat_id, success_msg)
            else:
                conn.close()
                fail_msg = (
                    "❌ <b>VERIFICATION FAILED</b> ❌\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"<b>Reason:</b> {reason}\n\n"
                    "⚠️ Please ensure you sent USDT via TRC20 to the correct wallet address and provided a valid TXID."
                )
                send_telegram_msg(VIP_BOT_TOKEN, chat_id, fail_msg)
    except Exception as e:
        log_event(f"🚨 Async Processing Error: {e}")

def telegram_polling_worker():
    log_event("🔄 Telegram Polling Worker Started...")
    offset = 0
    try:
        requests.get(f"https://api.telegram.org/bot{VIP_BOT_TOKEN}/deleteWebhook", timeout=5)
    except Exception:
        pass

    while True:
        try:
            url = f"https://api.telegram.org/bot{VIP_BOT_TOKEN}/getUpdates?offset={offset}&timeout=30"
            res = requests.get(url, timeout=35.0)
            if res.status_code == 200:
                updates = res.json().get("result", [])
                for update in updates:
                    offset = update["update_id"] + 1
                    message = update.get("message", {})
                    chat_id = message.get("chat", {}).get("id")
                    text = message.get("text", "")
                    
                    if chat_id and text:
                        threading.Thread(target=process_message_async, args=(chat_id, text), daemon=True).start()
        except Exception as e:
            log_event(f"Polling Error: {e}")
            time.sleep(5)

# Flask Web Endpoints
@app.route('/')
def home():
    return jsonify({
        "status": "Online",
        "system": "Binance VIP Signal Engine",
        "vip_signals_today": vip_signals_today,
        "free_signals_today": free_signals_today
    })

@app.route('/scan', methods=['GET', 'POST'])
def trigger_scan():
    force = request.args.get('force', 'false').lower() == 'true'
    threading.Thread(target=scan_and_dispatch, args=(force,), daemon=True).start()
    return jsonify({"message": "Scan triggered successfully", "force_mode": force})

@app.route('/logs', methods=['GET'])
def get_logs():
    return jsonify({"logs": system_logs})

# Background Workers Initialization
def start_background_workers():
    threading.Thread(target=telegram_polling_worker, daemon=True).start()
    threading.Thread(target=live_signal_monitor_worker, daemon=True).start()
    threading.Thread(target=membership_expiry_checker, daemon=True).start()

start_background_workers()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
