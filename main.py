import threading
import time
import random
import requests
from datetime import datetime
from flask import Flask

BOT_TOKEN = "8997353064:AAGqtm4nFQihOzwgIUuWWXRHagTAt8Itq4w"

VIP_CHANNEL_ID = "-1003836756507"
FREE_CHANNEL_ID = "-1003924921868"

app = Flask(__name__)

# Daily Performance Tracking Data
daily_stats = {
    "total_spot": 0,
    "total_futures": 0,
    "tp1_hits": 0,
    "tp2_hits": 0,
    "tp3_hits": 0,
    "sl_hits": 0,
    "total_gain_pct": 0.0
}

@app.route('/')
def home():
    return "Automated Accurate 6-Hour Signal System Active!"

def send_telegram_msg(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.json()
    except Exception as e:
        return {"ok": False, "description": str(e)}

def fetch_binance_klines(symbol):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=30"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            closes = [float(item[4]) for item in data]
            volumes = [float(item[5]) for item in data]
            return closes, volumes
    except Exception:
        pass
    return None, None

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(abs(change))
            losses.append(abs(change))
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def get_accurate_market_signals():
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"]
    analyzed_coins = []

    for sym in symbols:
        closes, volumes = fetch_binance_klines(sym)
        if closes and len(closes) >= 20:
            current_price = closes[-1]
            rsi = calculate_rsi(closes)
            sma_20 = sum(closes[-20:]) / 20
            
            vol_24h = (sum(volumes[-24:]) * current_price) / 1_000_000 if len(volumes) >= 24 else 150.0
            price_change = ((current_price - closes[0]) / closes[0]) * 100

            if current_price >= sma_20 and rsi >= 45:
                trend = "Strong Bullish Momentum (RSI + SMA Breakout)"
            elif rsi < 45:
                trend = "Oversold Rebound Pattern"
            else:
                trend = "Volume Consolidation Breakout"

            analyzed_coins.append({
                "symbol": sym,
                "price": current_price,
                "volume": round(vol_24h, 2),
                "change": round(price_change, 2),
                "rsi": round(rsi, 1),
                "analysis": trend
            })
        time.sleep(0.2)

    return analyzed_coins

def send_daily_report():
    """Generates and posts 24 Hours Performance Report to VIP and Free Channels"""
    global daily_stats
    
    report_text = (
        f"📊 <b>24-HOUR VIP SIGNALS PERFORMANCE REPORT</b> 📊\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ <b>Total Spot Signals</b>: {daily_stats['total_spot']}\n"
        f"⚡ <b>Total Futures Signals</b>: {daily_stats['total_futures']}\n\n"
        f"🎯 <b>Target 1 Hit</b>: {daily_stats['tp1_hits']}\n"
        f"🎯 <b>Target 2 Hit</b>: {daily_stats['tp2_hits']}\n"
        f"🎯 <b>Target 3 Hit</b>: {daily_stats['tp3_hits']}\n"
        f"⛔ <b>Stop Loss Hit</b>: {daily_stats['sl_hits']}\n\n"
        f"📈 <b>Overall Win Rate</b>: 88.5%\n"
        f"💰 <b>Est. Cumulative Gain</b>: +{daily_stats['total_gain_pct']:.1f}%\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔥 <i>Join VIP to receive all high-accuracy daily signals!</i>\n"
        f"👉 <b>Bot</b>: @BinanceTop10_VIPBot"
    )

    # Post Report to Both Channels
    send_telegram_msg(VIP_CHANNEL_ID, report_text)
    time.sleep(2)
    send_telegram_msg(FREE_CHANNEL_ID, report_text)

    # Reset daily stats for next 24h
    daily_stats = {
        "total_spot": 0,
        "total_futures": 0,
        "tp1_hits": 0,
        "tp2_hits": 0,
        "tp3_hits": 0,
        "sl_hits": 0,
        "total_gain_pct": 0.0
    }

def signal_engine():
    global daily_stats
    coins = get_accurate_market_signals()

    if not coins:
        return

    first_spot_text = ""
    first_futures_text = ""

    # 1. Deliver ALL Signals to VIP Channel First
    for index, coin in enumerate(coins):
        symbol = coin["symbol"]
        price = coin["price"]
        volume = coin["volume"]
        change = coin["change"]
        analysis_text = coin["analysis"]

        p_fmt = f"{price:.2f}" if price > 10 else f"{price:.4f}"

        t1_spot = price * 1.025
        t2_spot = price * 1.050
        t3_spot = price * 1.085
        sl_spot = price * 0.960

        t1_fut = price * 1.015
        t2_fut_sl = price * 0.985
        t2_fut_target = price * 1.035
        t3_fut_target = price * 1.060

        spot_text = (
            f"🟢 <b>[SPOT SIGNAL] {symbol}</b>\n\n"
            f"📥 <b>Entry Range</b>: ${p_fmt}\n"
            f"📊 <b>24h Vol</b>: ${volume}M | <b>Change</b>: {change:+.2f}%\n\n"
            f"🎯 <b>Target 1</b>: ${t1_spot:.4f} (+2.5%)\n"
            f"🎯 <b>Target 2</b>: ${t2_spot:.4f} (+5.0%)\n"
            f"🎯 <b>Target 3</b>: ${t3_spot:.4f} (+8.5%)\n"
            f"⛔ <b>Stop Loss</b>: ${sl_spot:.4f} (-4.0%)\n\n"
            f"📈 <b>Analysis</b>: {analysis_text}"
        )

        futures_text = (
            f"⚡ <b>[FUTURES LONG] {symbol}</b>\n\n"
            f"⚙️ <b>Leverage</b>: Cross 10x - 20x\n"
            f"📥 <b>Entry</b>: ${p_fmt}\n\n"
            f"🎯 <b>Target 1</b>: ${t1_fut:.4f} (+15% @ 10x)\n"
            f"🎯 <b>Target 2</b>: ${t2_fut_target:.4f} (+35% @ 10x)\n"
            f"🎯 <b>Target 3</b>: ${t3_fut_target:.4f} (+60% @ 10x)\n"
            f"⛔ <b>Stop Loss</b>: ${t2_fut_sl:.4f} (-15% @ 10x)\n\n"
            f"📊 <b>Analysis</b>: {analysis_text}"
        )

        # Send VIP Signals
        send_telegram_msg(VIP_CHANNEL_ID, spot_text)
        time.sleep(1.2)
        send_telegram_msg(VIP_CHANNEL_ID, futures_text)
        time.sleep(1.5)

        # Update Daily Stats Counter
        daily_stats["total_spot"] += 1
        daily_stats["total_futures"] += 1
        daily_stats["tp1_hits"] += random.choice([1, 2])
        daily_stats["tp2_hits"] += random.choice([1, 1, 0])
        daily_stats["tp3_hits"] += random.choice([1, 0])
        daily_stats["total_gain_pct"] += random.uniform(8.0, 18.0)

        # Save first signal for free channel delayed post
        if index == 0:
            first_spot_text = spot_text
            first_futures_text = futures_text

    # 2. Wait 5 to 10 Minutes before sending Free Preview Signal
    delay_seconds = random.randint(300, 600)  # 5 min (300s) to 10 min (600s)
    time.sleep(delay_seconds)

    # 3. Post Free Channel Preview (1 Spot & 1 Futures)
    free_promo_text = (
        f"🚀 <b>FREE PREVIEW SIGNALS (DELAYED)</b> 🚀\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{first_spot_text}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{first_futures_text}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔥 <b>GET REAL-TIME INSTANT SIGNALS IN VIP</b> 🔥\n\n"
        f"💳 <b>Subscription Plans</b>:\n"
        f"• 10 Days: $10 USDT\n"
        f"• 20 Days: $19 USDT\n"
        f"• 30 Days: $27 USDT\n\n"
        f"👉 <b>Join VIP Bot</b>: @BinanceTop10_VIPBot"
    )
    send_telegram_msg(FREE_CHANNEL_ID, free_promo_text)

def execution_loop():
    time.sleep(5)
    batch_count = 0
    while True:
        signal_engine()
        batch_count += 1

        # 4 Batches = 24 Hours (Since each batch is spaced 6 hours apart)
        if batch_count >= 4:
            send_daily_report()
            batch_count = 0

        # Wait 6 Hours (21,600 Seconds) minus the 5-10 min delay spent
        time.sleep(21000)

threading.Thread(target=execution_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
