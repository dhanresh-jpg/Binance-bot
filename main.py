import threading
import time
from flask import Flask
import requests

VIP_BOT_TOKEN = "8997353064:AAGqtm4nFQihOzwgIUuWWXRHagTAt8Itq4w"
FREE_BOT_TOKEN = "8842407289:AAEBSOVQz1NRFmdZFFYsd7TPhoA5TKSJMfk"

VIP_CHANNEL_ID = "-1003836756507"
FREE_CHANNEL_ID = "-1003924921868"

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Service is Alive and Running!"

def send_msg(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def fetch_crypto_data():
    # Primary API: Binance Official Public API (Bypasses CoinGecko rate limit)
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            usdt_pairs = [d for d in data if d['symbol'].endswith('USDT') and not d['symbol'].startswith('USD')]
            sorted_pairs = sorted(usdt_pairs, key=lambda x: float(x['quoteVolume']), reverse=True)[:10]
            
            result = []
            for item in sorted_pairs:
                result.append({
                    "symbol": item["symbol"],
                    "current_price": float(item["lastPrice"]),
                    "total_volume": float(item["quoteVolume"]),
                    "price_change_percentage_24h": float(item["priceChangePercent"])
                })
            return result
    except Exception:
        pass

    # Fallback API: CoinGecko
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {"vs_currency": "usd", "order": "volume_desc", "per_page": 10, "page": 1}
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, params=params, headers=headers, timeout=10)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass

    return []

def execute_signal_cycle():
    coins = fetch_crypto_data()
    
    if not coins or not isinstance(coins, list):
        send_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, "⚠️ *Data Engine Alert*: Fetch Failed. Retrying in 1 min...")
        return

    for index, coin in enumerate(coins):
        symbol = coin["symbol"].upper()
        if not symbol.endswith("USDT"):
            symbol += "USDT"
            
        price = coin["current_price"]
        volume = float(coin["total_volume"]) / 1_000_000
        change = float(coin.get("price_change_percentage_24h", 0.0))

        spot = (
            f"🟢 *[SPOT SIGNAL] {symbol}*\n\n"
            f"📥 *Entry Range*: ${price}\n"
            f"📊 *24h Vol*: ${volume:.2f}M | *Change*: {change:+.2f}%\n\n"
            f"🎯 *Target 1*: ${round(price * 1.02, 4)} (+2.0%)\n"
            f"🎯 *Target 2*: ${round(price * 1.045, 4)} (+4.5%)\n"
            f"🎯 *Target 3*: ${round(price * 1.08, 4)} (+8.0%)\n"
            f"⛔ *Stop Loss*: ${round(price * 0.965, 4)} (-3.5%)\n\n"
            f"📈 *Analysis*: Top Volume Momentum"
        )
        
        futures = (
            f"⚡ *[FUTURES LONG] {symbol}*\n\n"
            f"⚙️ *Leverage*: Cross 10x - 20x\n"
            f"📥 *Entry*: ${price}\n\n"
            f"🎯 *Target 1*: ${round(price * 1.015, 4)} (+15% @ 10x)\n"
            f"🎯 *Target 2*: ${round(price * 1.03, 4)} (+30% @ 10x)\n"
            f"🎯 *Target 3*: ${round(price * 1.05, 4)} (+50% @ 10x)\n"
            f"⛔ *Stop Loss*: ${round(price * 0.985, 4)} (-15% @ 10x)\n\n"
            f"📊 *Analysis*: High Volume Breakout Pattern"
        )

        # VIP Channels Receives All Signals
        send_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, spot)
        time.sleep(1)
        send_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, futures)
        time.sleep(1.5)

        # Free Channel Receives First 2 Coins Only
        if index < 2:
            promo = (
                f"🚀 *FREE PREVIEW SIGNAL* 🚀\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{spot}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔥 *UNLOCK ALL 10 SPOT & FUTURES SIGNALS* 🔥\n\n"
                f"💳 *Subscription Plans*:\n"
                f"• 10 Days: $10 USDT\n"
                f"• 20 Days: $19 USDT\n"
                f"• 30 Days: $27 USDT\n\n"
                f"👉 *Join VIP Bot*: @BinanceTop10_VIPBot"
            )
            send_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, promo)
            time.sleep(1.5)

def run_loop():
    time.sleep(5)
    while True:
        execute_signal_cycle()
        time.sleep(3600)

threading.Thread(target=run_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
