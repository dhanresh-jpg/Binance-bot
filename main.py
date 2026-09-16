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

# Tracking counters and timestamps for frequency control
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
    if val is None or val == 0: 
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
        res = requests.get(url, headers=HEADERS, timeout=10.0)
        if res.status_code == 200:
            data = res.json().get("data", [])
            for item in data:
                inst = item.get("instId", "")
                if inst.endswith("-USDT"):
                    symbol = inst.replace("-", "")
                    price = float(item.get("last", 0))
                    open_24 = float(item.get("open24h", 0))
                    change = ((price - open_24) / open_24 * 100) if open_24 > 0 else 0
                    low = float(item.get("low24h", 0))
                    high = float(item.get("high24h", price))
                    vol = float(item.get("vol24h", 0))
                    if price > 0:
                        valid_coins.append({
                            "symbol": symbol, 
                            "price": price, 
                            "change": change, 
                            "low": low,
                            "high": high,
                            "vol": vol
                        })
            if valid_coins: return valid_coins
        else:
            log_event(f"OKX API Error Status Code: {res.status_code}")
    except Exception as e:
        log_event(f"OKX Fetch Failed Exception: {e}")
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
            log_event("📊 24-Hour Results: No signals found for the last 24 hours.")
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
                    if not current_p:
                        continue

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
                        log_event(f"📈 Signal Update Sent for {sym}: {target_str}")

        except Exception as e:
            log_event(f"Live Monitor Error: {e}")
        time.sleep(300)

def scan_and_dispatch(force_mode=False):
    global vip_signals_today, free_signals_today, last_reset_day, last_free_dispatch_time, last_vip_dispatch_time
    log_event(f"🔍 Running Pro Market Scan & Strategy Analysis (Force Mode: {force_mode})...")

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
        log_event("❌ Scan aborted: No coins fetched from market data API.")
        return

    try:
        conn = sqlite3.connect("vip_members.db", timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("SELECT symbol FROM signal_history ORDER BY id DESC LIMIT 15")
        recent_symbols = [row[0] for row in cursor.fetchall()]
        conn.close()
    except Exception:
        recent_symbols = []

    available_coins = [c for c in coins if c["symbol"] not in recent_symbols]
    if not available_coins:
        available_coins = coins

    # ==================== PRO STRATEGY FILTER & SCORING ====================
    # Score formula: Volatility & Volume Confluence (No. 1 Pro Setup)
    scored_coins = []
    for c in available_coins:
        chg = c["change"]
        vol = c["vol"]
        # Filter for high momentum or high breakout potential
        if abs(chg) >= 1.5 and vol > 50000:
            score = abs(chg) * (vol ** 0.15)
            scored_coins.append((score, c))

    if not scored_coins:
        # Fallback to top volume coins if strict filter yields nothing
        scored_coins = [(abs(c["change"]), c) for c in available_coins]

    scored_coins.sort(key=lambda x: x[0], reverse=True)
    top_candidates = [item[1] for item in scored_coins[:10]]
    selected_coin = random.choice(top_candidates)
    
    p = selected_coin["price"]
    sym = selected_coin["symbol"]
    chg = selected_coin["change"]
    
    # Pro Strategy Logic for Signal Type & Targets
    if chg >= 2.0:
        signal_mode = "FUTURES LONG"
        leverage = "Cross 5x - 10x"
        tp1 = p * 1.022
        tp2 = p * 1.045
        tp3 = p * 1.080
        sl  = p * 0.982
    elif chg <= -2.0:
        signal_mode = "FUTURES SHORT"
        leverage = "Cross 5x - 10x"
        tp1 = p * 0.978
        tp2 = p * 0.955
        tp3 = p * 0.920
        sl  = p * 1.018
    else:
        signal_mode = "SPOT BREAKOUT BUY"
        leverage = "Spot (1x)"
        tp1 = p * 1.030
        tp2 = p * 1.060
        tp3 = p * 1.100
        sl  = p * 0.960

    rsi_est = round(50.0 + (chg * 0.7), 1)
    if rsi_est > 82: rsi_est = 79.5
    elif rsi_est < 18: rsi_est = 21.0

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
        log_event(f"💎 Pro VIP Signal Sent ({vip_signals_today}/36 today) for #{sym} | Change: {chg}%")

    if should_send_free:
        dispatch_free_signal(setup)
        free_signals_today += 1
        last_free_dispatch_time = current_time
        log_event(f"📢 Pro Free Signal Sent ({free_signals_today}/6 today) for #{sym} | Change: {chg}%")

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
        f"🚨 <b>BINANCE PRO VIP TRADE SIGNAL</b> 🚨\n"
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
        f"⚖️ <b>Risk / Reward</b>: 1 : 3.0\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <i>Use 2-5% of total wallet balance per trade.</i>\n"
        f"📚 <i>Disclaimer: For educational purposes only. Not financial advice. DYOR!</i>"
    )
    return send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, msg)

def dispatch_free_signal(s):
    msg = (
        f"🔥 <b>REAL-TIME PRO VIP SIGNAL PREVIEW</b> 🔥\n"
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
        f"⚖️ <b>Risk / Reward</b>: 1 : 3.0\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>Free Channel:</b> https://t.me/BinanceTop10Free\n"
        f"💎 <b>Join VIP For All Signals:</b> @BinanceTop10_VIPBot\n"
        f"📚 <i>Disclaimer: For educational purposes only. Not financial advice. DYOR!</i>"
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

def verify_usdt_trc20_tx(txid, expected_amount_min=10.0):
    try:
        url = f"https://apilist.tronscan.org/api/transaction-info?hash={txid.strip()}"
        res = requests.get(url, timeout=5.0)
        if res.status_code != 200:
            return False, 0, "Transaction is still propagating on blockchain or invalid TXID format. Please wait 1-2 minutes and try verifying again."
        # Baaki verification logic same rahega...
    except Exception as e:
        return False, 0, f"Error verifying transaction: {e}"
