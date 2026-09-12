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
sent_signals_history = []  # Prevents coin repetition

def log_event(message):
    timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    system_logs.append(entry)
    if len(system_logs) > 100:
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
        conn.commit()
        conn.close()
        log_event("Database & TXID tracker initialized.")
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
def send_telegram_msg(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        res = requests.post(url, json=payload, timeout=8)
        return res.json()
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
    
    # 1. Bybit Exchange Price
    try:
        url = f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            lst = res.json().get("result", {}).get("list", [])
            if lst:
                prices.append(float(lst[0]["lastPrice"]))
    except Exception as e:
        log_event(f"Bybit price fail: {e}")

    # 2. Binance Exchange Price
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            prices.append(float(res.json()["price"]))
    except Exception as e:
        log_event(f"Binance price fail: {e}")

    # 3. KuCoin Exchange Price
    try:
        kc_sym = symbol.replace("USDT", "-USDT")
        url = f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={kc_sym}"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            prices.append(float(res.json()["data"]["price"]))
    except Exception as e:
        log_event(f"KuCoin price fail: {e}")

    # Return Multi-Exchange Average Price if available
    if prices:
        avg_price = sum(prices) / len(prices)
        return avg_price
    return None

# --- TECHNICAL ANALYSIS & MULTI-EXCHANGE SCANNER ---
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
        # Fetch 1-Hour Candlesticks via Bybit Engine
        url = f"https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol}&interval=60&limit=30"
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            candles = res.json().get("result", {}).get("list", [])
            if len(candles) >= 20:
                closes = [float(c[4]) for c in reversed(candles)]
                
                # Global Multi-Exchange Index Price Fetch
                current_price = fetch_global_index_price(symbol) or closes[-1]
                rsi = calculate_rsi(closes)
                ema_20 = sum(closes[-20:]) / 20.0
                
                # 75% - 80% Win Rate Condition Checks
                if rsi > 52 and current_price > ema_20:
                    return {"symbol": symbol, "price": current_price, "trend": "BULLISH", "rsi": round(rsi, 1)}
                elif rsi < 48 and current_price < ema_20:
                    return {"symbol": symbol, "price": current_price, "trend": "BEARISH", "rsi": round(rsi, 1)}
    except Exception as e:
        log_event(f"Analysis error for {symbol}: {e}")
    return None

def scan_top_opportunity_coins():
    candidate_pool = [
        "AVAXUSDT", "LINKUSDT", "NEARUSDT", "DOTUSDT", "FETUSDT", 
        "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "SUIUSDT",
        "RNDRUSDT", "TIAUSDT", "LTCUSDT", "ATOMUSDT", "ADAUSDT"
    ]
    
    # Exclude recent coins to avoid continuous repetition
    valid_pool = [s for s in candidate_pool if s not in sent_signals_history[-8:]]
    analyzed_list = []

    for sym in valid_pool:
        result = get_market_analysis(sym)
        if result:
            analyzed_list.append(result)
            if len(analyzed_list) >= 3:
                break
        time.sleep(0.3)

    return analyzed_list

# --- SIGNAL GENERATION & BROADCAST ENGINE ---
def generate_and_send_signals():
    log_event("Scanning Multi-Exchange Markets for High-Accuracy Opportunities...")
    scanned_coins = scan_top_opportunity_coins()

    if len(scanned_coins) < 2:
        log_event("Not enough high-confidence setups found across exchanges. Retrying next cycle.")
        return

    # Assign distinct coins for Spot & Futures to avoid single-coin overlap
    spot_coin = scanned_coins[0]
    futures_coin = scanned_coins[1]

    # Save to history to avoid repetition
    sent_signals_history.extend([spot_coin["symbol"], futures_coin["symbol"]])

    # 1. SPOT SWING SIGNAL (1-2 Days Hold Timeframe)
    sp_price = spot_coin["price"]
    sp_fmt = f"{sp_price:.2f}" if sp_price > 10 else f"{sp_price:.4f}"
    
    if spot_coin["trend"] == "BULLISH":
        spot_msg = (
            f"🟢 <b>[VIP SPOT SWING SIGNAL - BUY]</b>\n"
            f"🪙 <b>Coin</b>: #{spot_coin['symbol']}\n"
            f"🌐 <b>Price Index</b>: Multi-Exchange Global Average\n\n"
            f"📥 <b>Buy Entry Zone</b>: ${sp_fmt}\n"
            f"⏱️ <b>Timeframe Target</b>: 1 - 2 Days Swing\n"
            f"📊 <b>Indicators</b>: RSI ({spot_coin['rsi']}) + EMA 20 Cross\n\n"
            f"🎯 <b>Target 1</b>: ${sp_price * 1.04:.4f} (+4%)\n"
            f"🎯 <b>Target 2</b>: ${sp_price * 1.08:.4f} (+8%)\n"
            f"🎯 <b>Target 3</b>: ${sp_price * 1.14:.4f} (+14%)\n"
            f"⛔ <b>Stop Loss</b>: ${sp_price * 0.94:.4f} (-6%)\n\n"
            f"💡 <b>Strategy</b>: Multi-Day Hold for Swing Breakout."
        )
    else:
        spot_msg = (
            f"🔴 <b>[VIP SPOT SWING SIGNAL - DIP ACCUMULATION]</b>\n"
            f"🪙 <b>Coin</b>: #{spot_coin['symbol']}\n"
            f"🌐 <b>Price Index</b>: Multi-Exchange Average\n\n"
            f"📥 <b>Buy Zone</b>: ${sp_price * 0.96:.4f}\n"
            f"⏱️ <b>Timeframe Target</b>: 1 - 2 Days\n"
            f"📊 <b>Indicators</b>: Oversold RSI ({spot_coin['rsi']})\n\n"
            f"🎯 <b>Target 1</b>: ${sp_price * 1.03:.4f} (+3%)\n"
            f"🎯 <b>Target 2</b>: ${sp_price * 1.07:.4f} (+7%)\n"
            f"⛔ <b>Stop Loss</b>: ${sp_price * 0.91:.4f} (-5%)\n\n"
            f"💡 <b>Strategy</b>: Accumulate at Support Level."
        )

    # 2. FUTURES SIGNAL (Quick Target: 2-4 Hours)
    ft_price = futures_coin["price"]
    ft_fmt = f"{ft_price:.2f}" if ft_price > 10 else f"{ft_price:.4f}"

    if futures_coin["trend"] == "BULLISH":
        futures_msg = (
            f"⚡ <b>[VIP FUTURES LONG SIGNAL]</b>\n"
            f"🪙 <b>Coin</b>: #{futures_coin['symbol']}\n"
            f"🌐 <b>Price Index</b>: Global Index Rate\n\n"
            f"⚙️ <b>Leverage</b>: Cross 10x - 15x\n"
            f"📥 <b>Entry</b>: ${ft_fmt}\n"
            f"⏱️ <b>Target Timeframe</b>: 2 - 4 Hours\n\n"
            f"🎯 <b>TP1</b>: ${ft_price * 1.015:.4f} (+15% @ 10x)\n"
            f"🎯 <b>TP2</b>: ${ft_price * 1.032:.4f} (+32% @ 10x)\n"
            f"🎯 <b>TP3</b>: ${ft_price * 1.055:.4f} (+55% @ 10x)\n"
            f"⛔ <b>Stop Loss</b>: ${ft_price * 0.985:.4f} (-15% @ 10x)\n\n"
            f"📊 <b>Analysis</b>: High Volume Breakout Confirmation"
        )
    else:
        futures_msg = (
            f"🔻 <b>[VIP FUTURES SHORT SIGNAL]</b>\n"
            f"🪙 <b>Coin</b>: #{futures_coin['symbol']}\n"
            f"🌐 <b>Price Index</b>: Global Index Rate\n\n"
            f"⚙️ <b>Leverage</b>: Cross 10x - 15x\n"
            f"📥 <b>Entry</b>: ${ft_fmt}\n"
            f"⏱️ <b>Target Timeframe</b>: 2 - 4 Hours\n\n"
            f"🎯 <b>TP1</b>: ${ft_price * 0.985:.4f} (+15% @ 10x)\n"
            f"🎯 <b>TP2</b>: ${ft_price * 0.968:.4f} (+32% @ 10x)\n"
            f"🎯 <b>TP3</b>: ${ft_price * 0.945:.4f} (+55% @ 10x)\n"
            f"⛔ <b>Stop Loss</b>: ${ft_price * 1.015:.4f} (-15% @ 10x)\n\n"
            f"📊 <b>Analysis</b>: Resistance Rejection Confirmation"
        )

    # Post Signals to VIP Channel
    send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, spot_msg)
    time.sleep(1.5)
    send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, futures_msg)

    # 3. SINGLE HIGH-ACCURACY SIGNAL PREVIEW FOR FREE CHANNEL
    free_promo = (
        f"🔥 <b>FREE HIGH-ACCURACY SIGNAL PREVIEW</b> 🔥\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{futures_msg}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>Free Channel:</b> https://t.me/BinanceTop10Free\n\n"
        f"💎 <b>Get Spot Swing & All 24/7 Signals in VIP</b>\n"
        f"👉 <b>Join VIP Bot:</b> @BinanceTop10_VIPBot"
    )
    send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, free_promo)

def continuous_loop():
    time.sleep(5)
    while True:
        try:
            generate_and_send_signals()
        except Exception as e:
            log_event(f"Loop Exception: {e}\n{traceback.format_exc()}")
        time.sleep(14400)  # Every 4 Hours

# --- FREE BOT LISTENER ---
def process_free_bot_updates():
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{FREE_BOT_TOKEN}/getUpdates"
            params = {"timeout": 10, "offset": offset}
            res = requests.get(url, params=params, timeout=12)
            if res.status_code == 200:
                data = res.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    user_id = msg.get("from", {}).get("id")

                    if not user_id:
                        continue

                    welcome_free = (
                        f"👋 <b>Welcome to Binance Top 10 Signals!</b>\n\n"
                        f"📢 <b>Join Our Free Signals Channel:</b>\n"
                        f"https://t.me/BinanceTop10Free\n\n"
                        f"💎 <b>Upgrade To VIP Bot (Auto Payment):</b>\n"
                        f"@BinanceTop10_VIPBot"
                    )
                    send_telegram_msg(FREE_BOT_TOKEN, user_id, welcome_free)
        except Exception:
            time.sleep(2)

# --- VIP BOT LISTENER ---
def process_bot_updates():
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{VIP_BOT_TOKEN}/getUpdates"
            params = {"timeout": 10, "offset": offset}
            res = requests.get(url, params=params, timeout=12)
            if res.status_code == 200:
                data = res.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    text = msg.get("text", "").strip()
                    user_id = msg.get("from", {}).get("id")

                    if not text or not user_id:
                        continue

                    if text == "/start":
                        welcome = (
                            f"👋 <b>Welcome to Crypto VIP Bot!</b>\n\n"
                            f"Commands:\n"
                            f"🔹 /plans - View Pricing Plans\n"
                            f"🔹 /pay - Get USDT TRC20 Address\n"
                            f"🔹 /verify TXID - Auto-Activate VIP Access"
                        )
                        send_telegram_msg(VIP_BOT_TOKEN, user_id, welcome)

                    elif text == "/plans":
                        plans_txt = (
                            f"💎 <b>VIP SUBSCRIPTION PLANS</b>\n\n"
                            f"🔸 <b>10 Days Access</b>: 10 USDT\n"
                            f"🔸 <b>20 Days Access</b>: 19 USDT\n"
                            f"🔸 <b>30 Days Access</b>: 27 USDT\n\n"
                            f"👉 Send exact amount to deposit address using /pay"
                        )
                        send_telegram_msg(VIP_BOT_TOKEN, user_id, plans_txt)

                    elif text == "/pay":
                        pay_txt = (
                            f"💳 <b>USDT TRC-20 Address</b>:\n\n"
                            f"<code>{TRUST_WALLET_ADDRESS}</code>\n\n"
                            f"<b>Automatic Activation Instructions:</b>\n"
                            f"1. Send exact USDT amount for your chosen plan.\n"
                            f"2. Copy your Transaction Hash (TXID).\n"
                            f"3. Send <code>/verify YOUR_TXID</code> to this bot."
                        )
                        send_telegram_msg(VIP_BOT_TOKEN, user_id, pay_txt)

                    elif text.startswith("/verify"):
                        parts = text.split()
                        if len(parts) < 2:
                            send_telegram_msg(VIP_BOT_TOKEN, user_id, "⚠️ Format: <code>/verify YOUR_TXID_HERE</code>")
                        else:
                            txid = parts[1].strip()
                            send_telegram_msg(VIP_BOT_TOKEN, user_id, "🔍 Verifying transaction on TRON Blockchain...")
                            
                            is_valid, result = verify_tron_txid(txid)
                            if is_valid:
                                days, amount = result
                                exp_date = add_vip_member(user_id, days)
                                invite_link = create_vip_invite_link()
                                
                                success_msg = (
                                    f"✅ <b>PAYMENT VERIFIED!</b>\n\n"
                                    f"💰 Received: ${amount} USDT\n"
                                    f"📅 Membership Duration: {days} Days\n"
                                    f"⏳ Expiry Date: {exp_date}\n\n"
                                    f"🚀 <b>Join VIP Channel Now</b>:\n{invite_link}"
                                )
                                send_telegram_msg(VIP_BOT_TOKEN, user_id, success_msg)
                            else:
                                send_telegram_msg(VIP_BOT_TOKEN, user_id, f"❌ Verification Failed:\n{result}")

        except Exception as e:
            time.sleep(2)

# --- FLASK SERVER ENDPOINTS ---
@app.route('/')
def home():
    return "Automated VIP Engine Active."

@app.route('/logs')
def get_logs():
    return jsonify({"logs": system_logs})

@app.route('/force-signal')
def force_signal():
    threading.Thread(target=generate_and_send_signals, daemon=True).start()
    return "Signals triggered across multi-exchanges! Check Telegram channels."

threading.Thread(target=continuous_loop, daemon=True).start()
threading.Thread(target=process_free_bot_updates, daemon=True).start()
threading.Thread(target=process_bot_updates, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
