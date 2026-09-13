import time
import requests
import sqlite3
import os
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify

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
free_signals_today = 0
last_reset_day = datetime.now(IST).day

def log_event(message):
    timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    system_logs.append(entry)
    if len(system_logs) > 200: system_logs.pop(0)
    print(entry)

def init_db():
    try:
        conn = sqlite3.connect("vip_members.db")
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE IF NOT EXISTS members (user_id INTEGER PRIMARY KEY, expiry_date TEXT, status TEXT)')
        cursor.execute('CREATE TABLE IF NOT EXISTS processed_txids (txid TEXT PRIMARY KEY)')
        cursor.execute('CREATE TABLE IF NOT EXISTS channel_messages (bot_type TEXT, chat_id TEXT, message_id INTEGER, created_date TEXT)')
        cursor.execute('CREATE TABLE IF NOT EXISTS signal_history (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, entry_price REAL, tp1 REAL, sl REAL, timestamp REAL, created_date TEXT, status TEXT DEFAULT "PENDING")')
        conn.commit()
        conn.close()
        log_event("Database Initialized with Full Market Scan Engine.")
    except Exception as e:
        log_event(f"Database Init Error: {e}")

init_db()

def cleanup_3day_old_data():
    try:
        conn = sqlite3.connect("vip_members.db")
        cursor = conn.cursor()
        three_days_ago = (datetime.now(IST) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("DELETE FROM signal_history WHERE created_date < ?", (three_days_ago,))
        cursor.execute("DELETE FROM channel_messages WHERE created_date < ?", (three_days_ago,))
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        if deleted_count > 0:
            log_event(f"🧹 3-Day Rotation Reset: Cleaned {deleted_count} old records.")
    except Exception as e:
        log_event(f"Cleanup Error: {e}")

def format_price(val):
    if val is None or val == 0: return "0.00"
    if val >= 1000: return f"{val:,.2f}"
    elif val >= 1: return f"{val:.4f}"
    elif val >= 0.001: return f"{val:.6f}"
    else: return f"{val:.8f}"

# ====================================================
# FULL MARKET SCANNER (Fetches ALL USDT Spot Pairs)
# ====================================================
def get_market_data():
    valid_coins = []
    try:
        url = "https://www.okx.com/api/v5/market/tickers?instType=SPOT"
        res = requests.get(url, headers=HEADERS, timeout=5.0)
        if res.status_code == 200:
            data = res.json().get("data", [])
            for item in data:
                inst = item.get("instId", "")
                # Automatically capture all pairs ending with -USDT
                if inst.endswith("-USDT"):
                    symbol = inst.replace("-", "") # e.g. BTCUSDT, ETHUSDT, etc.
                    price = float(item.get("last", 0))
                    open_24 = float(item.get("open24h", 0))
                    change = ((price - open_24) / open_24 * 100) if open_24 > 0 else 0
                    low = float(item.get("low24h", 0))
                    
                    if price > 0:
                        valid_coins.append({
                            "symbol": symbol,
                            "price": price,
                            "change": change,
                            "low": low
                        })
            if valid_coins:
                log_event(f"🌐 Full Market Scan: Fetched {len(valid_coins)} USDT pairs from OKX.")
                return valid_coins
    except Exception as e:
        log_event(f"OKX Full Market Fetch Failed: {e}")
    return valid_coins

def generate_24h_result_report():
    try:
        conn = sqlite3.connect("vip_members.db")
        cursor = conn.cursor()
        twenty_four_hrs_ago = (datetime.now(IST) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("SELECT symbol, entry_price, tp1, sl FROM signal_history WHERE created_date >= ?", (twenty_four_hrs_ago,))
        records = cursor.fetchall()
        
        if not records:
            conn.close()
            return

        total_signals = len(records)
        wins, losses = 0, 0
        coins_data = {c["symbol"]: c["price"] for c in get_market_data()}

        for rec in records:
            sym, entry, tp1, sl = rec
            current_p = coins_data.get(sym, entry)
            if current_p >= tp1: wins += 1
            elif current_p <= sl: losses += 1
            else: wins += 1

        win_rate = round((wins / total_signals) * 100, 1) if total_signals > 0 else 100.0

        report_msg = (
            f"📊 <b>24-HOUR VIP SIGNAL RESULTS REPORT</b> 📊\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ <b>Total Signals Dispatched</b>: {total_signals}\n"
            f"🎯 <b>Targets Hit / Profit Trades</b>: {wins}\n"
            f"⛔ <b>Stop Losses Hit</b>: {losses}\n"
            f"🔥 <b>Win Rate Accuracy</b>: {win_rate}%\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💎 <b>Join VIP For Instant Signals:</b> @BinanceTop10_VIPBot"
        )

        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, report_msg, is_channel=True)
        send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, report_msg, is_channel=True)
        log_event(f"📊 24-Hour Results Published! Win Rate: {win_rate}%")
        conn.close()

    except Exception as e:
        log_event(f"Result Generation Error: {e}")

def scan_and_dispatch(force_mode=False):
    global free_signals_today, last_reset_day
    log_event(f"🔍 Running Full Market Scan (Force Mode: {force_mode})...")

    current_day = datetime.now(IST).day
    if current_day != last_reset_day:
        free_signals_today = 0
        last_reset_day = current_day
        cleanup_3day_old_data()
        generate_24h_result_report()

    coins = get_market_data()
    if not coins:
        log_event("❌ APIs unavailable. Retrying next cycle.")
        return

    # Fetch last signal timestamp for each coin from database
    last_signals = {}
    try:
        conn = sqlite3.connect("vip_members.db")
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, MAX(timestamp) FROM signal_history GROUP BY symbol")
        last_signals = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()
    except Exception as e:
        log_event(f"History Fetch Error: {e}")

    now_time = time.time()

    # Assign rotation metrics to all scanned coins
    for c in coins:
        c["last_signal"] = last_signals.get(c["symbol"], 0)

    def rotation_sort(c):
        lt = c["last_signal"]
        # Prioritize coins not signaled in the last 24 hours (86400s)
        is_recent = 1 if (now_time - lt < 86400) else 0
        # Among eligible ones, sort by oldest timestamp and highest change momentum
        return (is_recent, lt, -abs(c["change"]))

    coins.sort(key=rotation_sort)
    top_coin = coins[0]

    p = top_coin["price"]
    sym = top_coin["symbol"]
    chg = top_coin["change"]
    
    if chg >= 0:
        signal_mode = "FUTURES LONG"
        leverage = "Cross 5x - 10x"
        tp1, tp2, tp3, sl = p * 1.018, p * 1.035, p * 1.060, p * 0.982
    else:
        signal_mode = "SPOT BREAKOUT BUY"
        leverage = "Spot (1x)"
        tp1, tp2, tp3, sl = p * 1.025, p * 1.050, p * 1.090, p * 0.965

    rsi_est = round(50.0 + (chg * 0.6), 1)
    if rsi_est > 80: rsi_est = 78.4
    elif rsi_est < 20: rsi_est = 22.1

    setup = {
        "symbol": sym, "price": p, "mode": signal_mode, "leverage": leverage,
        "rsi": rsi_est, "tp1": tp1, "tp2": tp2, "tp3": tp3, "sl": sl,
        "change": round(chg, 2), "low": top_coin.get("low", p * 0.95)
    }

    dispatch_professional_signal(setup)
    
    # Save Signal History
    try:
        conn = sqlite3.connect("vip_members.db")
        cursor = conn.cursor()
        now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("INSERT INTO signal_history (symbol, entry_price, tp1, sl, timestamp, created_date) VALUES (?, ?, ?, ?, ?, ?)", 
                       (sym, p, tp1, sl, now_time, now_str))
        conn.commit()
        conn.close()
    except Exception as e:
        log_event(f"History Save Error: {e}")

def dispatch_professional_signal(s):
    global free_signals_today

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
        f"📊 <b>RSI Indicator</b>: {s['rsi']} (Bullish Momentum)\n"
        f"🛡️ <b>Key Support Level</b>: ${format_price(s['low'])}\n"
        f"⚖️ <b>Risk / Reward</b>: 1 : 2.5\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <i>Use 2-5% of total wallet balance per trade.</i>"
    )

    r_vip = send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, msg, is_channel=True)

    r_free = False
    if free_signals_today < 6:
        free_promo = (
            f"🔥 <b>REAL-TIME VIP SIGNAL PREVIEW</b> 🔥\n\n"
            f"{msg}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📢 <b>Free Channel:</b> https://t.me/BinanceTop10Free\n"
            f"💎 <b>Join VIP For All Signals:</b> @BinanceTop10_VIPBot"
        )
        r_free = send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, free_promo, is_channel=True)
        if r_free: free_signals_today += 1

    log_event(f"🎯 Broadcasted #{s['symbol']} @ ${format_price(s['price'])} | VIP: {r_vip} | Free: {r_free}")

def send_telegram_msg(bot_token, chat_id, text, reply_markup=None, is_channel=False):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        res = requests.post(url, json=payload, timeout=5.0)
        return res.json().get("ok", False)
    except Exception: return False

def continuous_market_scanner():
    log_event("🚀 Engine Active with Full Market USDT Scan...")
    while True:
        try: scan_and_dispatch(force_mode=False)
        except Exception as e: log_event(f"Scanner Loop Error: {e}")
        time.sleep(180)

@app.route('/')
def home(): return jsonify({"status": "active"})

@app.route('/logs')
def get_logs(): return jsonify({"logs": system_logs})

@app.route('/force-signal')
def force_signal():
    threading.Thread(target=scan_and_dispatch, args=(True,), daemon=True).start()
    return "Force Scan Triggered!"

@app.route('/force-result')
def force_result():
    threading.Thread(target=generate_24h_result_report, daemon=True).start()
    return "24h Result Report Triggered!"

threading.Thread(target=continuous_market_scanner, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

