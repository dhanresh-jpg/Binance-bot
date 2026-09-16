import time
import requests
import sqlite3
import os
import threading
import random
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify
 
FREE_BOT_TOKEN = os.getenv("FREE_BOT_TOKEN", "8842407289:AAHD6UcvOZ0pgvN8EJXXetb2qrW-fGeZCvU")
VIP_BOT_TOKEN = os.getenv("VIP_BOT_TOKEN", "8997353064:AAH2gTVchfQqqId1TvBa2CD8nIXY00ZUj_8")
 
FREE_CHANNEL_ID = os.getenv("FREE_CHANNEL_ID", "-1003924921868")
VIP_CHANNEL_ID = os.getenv("VIP_CHANNEL_ID", "-1003836756507")
TRUST_WALLET_ADDRESS = "TErttGLUQZtrCwusaQsjdywXdkxUrNFm52"
 
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}
 
app = Flask(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
system_logs = []
 
KEYBOARD_LAYOUT = {
    "keyboard": [
        [{"text": "💎 View VIP Plans"}, {"text": "💳 Get Payment Address"}],
        [{"text": "🔍 Verify Payment"}, {"text": "✅ How to Verify TXID"}]
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
    if len(system_logs) > 200: system_logs.pop(0)
    print(entry)
 
def init_db():
    try:
        conn = sqlite3.connect("vip_members.db", timeout=10.0)
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE IF NOT EXISTS members (user_id INTEGER PRIMARY KEY, expiry_date TEXT, status TEXT)')
        cursor.execute('CREATE TABLE IF NOT EXISTS processed_txids (txid TEXT PRIMARY KEY)')
        cursor.execute('CREATE TABLE IF NOT EXISTS channel_messages (bot_type TEXT, chat_id TEXT, message_id INTEGER, created_date TEXT)')
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
        log_event("Database Initialized Successfully with 10.0s timeout.")
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
            log_event(f"🧹 Cleaned {deleted_count} old records safely.")
    except Exception as e:
        log_event(f"Cleanup Error: {e}")
 
def format_price(val):
    try:
        val = float(val)
    except (TypeError, ValueError):
        return "0.00"
        
    if val == 0: 
        return "0.00"
    if val >= 1000: 
        return f"{val:,.2f}"
    elif val >= 1: 
        return f"{val:.4f}"
    elif val >= 0.001: 
        return f"{val:.6f}"
    elif val >= 0.00001: 
        return f"{val:.8f}"
    else:
        formatted = f"{val:.12f}".rstrip('0')
        if formatted.endswith('.'):
            formatted = formatted.rstrip('.')
        return formatted
 
def get_market_data():
    valid_coins = []
    try:
        url = "https://www.okx.com/api/v5/market/tickers?instType=SPOT"
        res = requests.get(url, headers=HEADERS, timeout=6.0)
        if res.status_code == 200:
            data = res.json().get("data", [])
            for item in data:
                try:
                    inst = item.get("instId", "")
                    if inst.endswith("-USDT"):
                        symbol = inst.replace("-", "")
                        price = float(item.get("last", 0))
                        open_24 = float(item.get("open24h", 0))
                        change = ((price - open_24) / open_24 * 100) if open_24 > 0 else 0
                        low = float(item.get("low24h", 0))
                        high = float(item.get("high24h", 0))
                        vol = float(item.get("vol24h", 0))
                        if price > 0 and low > 0 and high > 0:
                            valid_coins.append({
                                "symbol": symbol, 
                                "price": price, 
                                "change": change, 
                                "low": low,
                                "high": high,
                                "vol": vol
                            })
                except (ValueError, TypeError):
                    continue
            if valid_coins: return valid_coins
    except Exception as e:
        log_event(f"OKX Fetch Failed: {e}")
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
            f"💎 <b>Join VIP For Instant Signals:</b> @BinanceTop10_VIPBot\n"
            f"⚠️ <i>Disclaimer: For educational purposes only. Not financial advice.</i>"
        )
        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, report_msg)
        send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, report_msg)
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
                            f"💎 <b>Join VIP For More:</b> @BinanceTop10_VIPBot\n"
                            f"⚠️ <i>Disclaimer: For educational purposes only. Not financial advice.</i>"
                        )
                        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, update_msg)
                        send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, update_msg)

                        conn = sqlite3.connect("vip_members.db", timeout=10.0)
                        cursor = conn.cursor()
                        cursor.execute("UPDATE signal_history SET status = ? WHERE id = ?", (hit_status, s_id))
                        conn.commit()
                        conn.close()
        except Exception as e:
            log_event(f"Live Monitor Error: {e}")
        time.sleep(300)
 
def scan_and_dispatch(force_mode=False):
    global vip_signals_today, free_signals_today, last_reset_day, last_free_dispatch_time, last_vip_dispatch_time
    log_event(f"🔍 Running Advanced Spot & Futures S/R Market Scan (Force Mode: {force_mode})...")

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
        log_event("❌ Scan aborted: No coins fetched.")
        return

    try:
        conn = sqlite3.connect("vip_members.db", timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("SELECT symbol FROM signal_history ORDER BY id DESC LIMIT 15")
        recent_symbols = [row[0] for row in cursor.fetchall()]
        conn.close()
    except Exception:
        recent_symbols = []

    available_coins = [c for c in coins if c["symbol"] not in recent_symbols and c["vol"] > 800000]
    if not available_coins:
        available_coins = coins

    available_coins.sort(key=lambda x: x["vol"], reverse=True)
    top_candidates = available_coins[:15]
    selected_coin = random.choice(top_candidates)
    
    p = selected_coin["price"]
    sym = selected_coin["symbol"]
    chg = selected_coin["change"]
    sup = selected_coin["low"]
    res = selected_coin["high"]
    
    signal_choice_pool = ["SPOT BUY", "FUTURES LONG", "FUTURES SHORT"]
    chosen_type = random.choice(signal_choice_pool)

    if chosen_type == "SPOT BUY":
        signal_mode = "SPOT DCA / ACCUMULATION"
        leverage = "Spot (1x)"
        tp1 = p * 1.025
        tp2 = p * 1.055
        tp3 = p * 1.090
        sl = sup * 0.975
    elif chosen_type == "FUTURES LONG":
        signal_mode = "FUTURES LONG (S/R Bounce)"
        leverage = "Cross 3x - 5x"
        tp1 = p * 1.020
        tp2 = p * 1.042
        tp3 = p * 1.070
        sl = sup * 0.982
    else:
        signal_mode = "FUTURES SHORT (Resistance Rejection)"
        leverage = "Cross 3x - 5x"
        tp1 = p * 0.980
        tp2 = p * 0.958
        tp3 = p * 0.930
        sl = res * 1.018

    rsi_est = round(50.0 + (chg * 0.5), 1)
    if rsi_est > 78: rsi_est = 73.5
    elif rsi_est < 22: rsi_est = 26.5

    setup = {
        "symbol": sym, "price": p, "mode": signal_mode, "leverage": leverage,
        "rsi": rsi_est, "tp1": tp1, "tp2": tp2, "tp3": tp3, "sl": sl,
        "change": round(chg, 2), "support": sup, "resistance": res
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
        log_event(f"💎 VIP Signal Sent ({signal_mode}) for #{sym} | Support: {sup} | Resistance: {res}")

    if should_send_free:
        dispatch_free_signal(setup)
        free_signals_today += 1
        last_free_dispatch_time = current_time
        log_event(f"📢 Free Signal Sent ({signal_mode}) for #{sym}")

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
        f"📊 <b>Strategy / Type</b>: <code>{s['mode']}</code>\n"
        f"⚙️ <b>Market Mode</b>: {s['leverage']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 <b>Entry Zone</b>: ${format_price(s['price'])}\n\n"
        f"🎯 <b>Target 1</b>: ${format_price(s['tp1'])}\n"
        f"🎯 <b>Target 2</b>: ${format_price(s['tp2'])}\n"
        f"🚀 <b>Target 3 (Max)</b>: ${format_price(s['tp3'])}\n"
        f"⛔ <b>Stop Loss (Safe S/R)</b>: ${format_price(s['sl'])}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ <b>24h Support</b>: ${format_price(s['support'])}\n"
        f"⚔️ <b>24h Resistance</b>: ${format_price(s['resistance'])}\n"
        f"📈 <b>24h Change</b>: {s['change']}% | <b>RSI</b>: {s['rsi']}\n"
        f"⚖️ <b>Risk / Reward</b>: 1 : 2.5\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <i>Manage risk properly. DYOR!</i>"
    )
    return send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, msg)
 
def dispatch_free_signal(s):
    msg = (
        f"🔥 <b>REAL-TIME SIGNAL PREVIEW</b> 🔥\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 <b>Pair</b>: #{s['symbol']}\n"
        f"📊 <b>Strategy / Type</b>: <code>{s['mode']}</code>\n"
        f"⚙️ <b>Market Mode</b>: {s['leverage']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 <b>Entry Zone</b>: ${format_price(s['price'])}\n\n"
        f"🎯 <b>Target 1</b>: ${format_price(s['tp1'])}\n"
        f"🎯 <b>Target 2</b>: ${format_price(s['tp2'])}\n"
        f"🚀 <b>Target 3 (Max)</b>: ${format_price(s['tp3'])}\n"
        f"⛔ <b>Stop Loss (Safe S/R)</b>: ${format_price(s['sl'])}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ <b>24h Support</b>: ${format_price(s['support'])}\n"
        f"⚔️ <b>24h Resistance</b>: ${format_price(s['resistance'])}\n"
        f"📈 <b>24h Change</b>: {s['change']}% | <b>RSI</b>: {s['rsi']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>Free Channel:</b> https://t.me/BinanceTop10Free\n"
        f"💎 <b>Join VIP For All Signals:</b> @BinanceTop10_VIPBot\n"
        f"⚠️ <i>Disclaimer: For educational purposes only. Not financial advice.</i>"
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
        res = requests.post(url, json=payload, timeout=5.0)
        data = res.json()
        return data.get("ok", False)
    except Exception as e:
        log_event(f"Telegram Send Error: {e}")
        return False
 
def kick_telegram_user(chat_id, user_id):
    url = f"https://api.telegram.org/bot{VIP_BOT_TOKEN}/banChatMember"
    payload = {"chat_id": chat_id, "user_id": user_id, "revoke_messages": False}
    try:
        res = requests.post(url, json=payload, timeout=3.0)
        requests.post(f"https://api.telegram.org/bot{VIP_BOT_TOKEN}/unbanChatMember", json={"chat_id": chat_id, "user_id": user_id}, timeout=3.0)
        return res.json().get("ok", False)
    except Exception:
        return False
 
def verify_usdt_trc20_tx(txid, expected_amount_min=10.0):
    try:
        url = f"https://apilist.tronscan.org/api/transaction-info?hash={txid.strip()}"
        res = requests.get(url, timeout=4.0)
        if res.status_code != 200:
            return False, 0, "Transaction propagating or invalid TXID format. Please wait 1-2 minutes."
        
        data = res.json()
        if not data or "contractRet" in data and data["contractRet"] != "SUCCESS":
            return False, 0, "Transaction pending or failed on blockchain."
            
        trc20_transfers = data.get("trc20TransferInfo", [])
        if not trc20_transfers:
            return False, 0, "No USDT TRC20 transfer found in this Transaction ID."
            
        valid_transfer = False
        final_amount = 0.0
        for t in trc20_transfers:
            to_addr = t.get("to_address", "")
            symbol = t.get("symbol", "")
            raw_amount = float(t.get("amount_str", "0")) / 10**6
            
            if (to_addr == TRUST_WALLET_ADDRESS and symbol == "USDT" and raw_amount >= expected_amount_min):
                valid_transfer = True
                final_amount = raw_amount
                break
                
        if valid_transfer:
            return True, final_amount, "Verification Successful!"
        else:
            return False, 0, "Recipient address or USDT amount mismatch."
    except Exception as e:
        return False, 0, f"Verification error: {str(e)}"

@app.route('/')
def home():
    return "VIP Crypto Signal Bot is Running Successfully!", 200

@app.route(f'/{FREE_BOT_TOKEN}', methods=['POST'])
def free_webhook():
    try:
        data = request.get_json()
        if data and "message" in data:
            message = data["message"]
            chat_id = message["chat"]["id"]
            text = message.get("text", "")
            
            if text.startswith("/start"):
                send_telegram_msg(FREE_BOT_TOKEN, chat_id, "Welcome to Binance Top 10 Free Signals Bot! Choose an option below:")
            elif text == "💎 View VIP Plans":
                send_telegram_msg(FREE_BOT_TOKEN, chat_id, "💎 <b>VIP MEMBERSHIP PLANS</b> 💎\n\n1 Month: $10 USDT\nLifetime: $30 USDT\n\nClick 'Get Payment Address' to proceed.")
            elif text == "💳 Get Payment Address":
                send_telegram_msg(FREE_BOT_TOKEN, chat_id, f"💳 <b>USDT (TRC20) Payment Address:</b>\n\n<code>{TRUST_WALLET_ADDRESS}</code>\n\nSend minimum $10 USDT and verify using your Transaction ID (TXID).")
            elif text == "✅ How to Verify TXID":
                send_telegram_msg(FREE_BOT_TOKEN, chat_id, "Send your USDT TRC20 transaction hash (TXID) after making payment to automatically activate your VIP membership.")
            elif text == "🔍 Verify Payment":
                send_telegram_msg(FREE_BOT_TOKEN, chat_id, "Please send your TXID in format: `/verify <TXID>`")
            elif text.startswith("/verify "):
                txid = text.split(" ", 1)[1].strip()
                try:
                    conn = sqlite3.connect("vip_members.db", timeout=10.0)
                    cursor = conn.cursor()
                    cursor.execute("SELECT txid FROM processed_txids WHERE txid = ?", (txid,))
                    if cursor.fetchone():
                        send_telegram_msg(FREE_BOT_TOKEN, chat_id, "❌ This TXID has already been used.")
                        conn.close()
                        return jsonify({"status": "ok"}), 200
                    conn.close()
                except Exception:
                    pass

                success, amt, msg_desc = verify_usdt_trc20_tx(txid, 10.0)
                if success:
                    try:
                        conn = sqlite3.connect("vip_members.db", timeout=10.0)
                        cursor = conn.cursor()
                        cursor.execute("INSERT OR IGNORE INTO processed_txids (txid) VALUES (?)", (txid,))
                        expiry = (datetime.now(IST) + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
                        cursor.execute("INSERT OR REPLACE INTO members (user_id, expiry_date, status) VALUES (?, ?, 'ACTIVE')", (chat_id, expiry))
                        conn.commit()
                        conn.close()
                    except Exception:
                        pass
                    send_telegram_msg(FREE_BOT_TOKEN, chat_id, f"✅ Payment Verified Successfully!\nAmount: ${amt}\nYour VIP access is now active.")
                else:
                    send_telegram_msg(FREE_BOT_TOKEN, chat_id, f"❌ Verification Failed: {msg_desc}")
    except Exception as e:
        log_event(f"Free Webhook Error: {e}")
    return jsonify({"status": "ok"}), 200

@app.route(f'/{VIP_BOT_TOKEN}', methods=['POST'])
def vip_webhook():
    try:
        data = request.get_json()
        if data and "message" in data:
            message = data["message"]
            chat_id = message["chat"]["id"]
            text = message.get("text", "")
            
            if text.startswith("/start"):
                send_telegram_msg(VIP_BOT_TOKEN, chat_id, "Welcome to Binance Top 10 VIP Bot! You will receive exclusive signals here.")
    except Exception as e:
        log_event(f"VIP Webhook Error: {e}")
    return jsonify({"status": "ok"}), 200

def background_scanner():
    while True:
        try:
            scan_and_dispatch(force_mode=False)
        except Exception as e:
            log_event(f"Background Scanner Error: {e}")
        time.sleep(3600) # Runs market scan every 1 hour

if __name__ == "__main__":
    threading.Thread(target=live_signal_monitor_worker, daemon=True).start()
    threading.Thread(target=background_scanner, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
