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
    return "Bot Engine Live!"

def send_msg(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def fetch_crypto_data():
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get("https://api.coincap.io/v2/assets?limit=10", headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json().get('data', [])
            result = []
            for coin in data:
                result.append({
                    "symbol": coin["symbol"].upper() + "USDT",
                    "current_price": float(coin["priceUsd"]),
                    "total_volume": float(coin["volumeUsd24Hr"]),
                    "price_change_percentage_24h": float(coin["changePercent24Hr"])
                })
            if result:
                return result
    except Exception:
        pass
    return []

def execute_signal_cycle():
    coins = fetch_crypto_data()
    if not coins:
        return

    for index, coin in enumerate(coins):
        symbol = str(coin["symbol"])
        price = round(float(coin["current_price"]), 4)
        volume = round(float(coin["total_volume"]) / 1_000_000, 2)
        change = round(float(coin["price_change_percentage_24h"]), 2)

        t1 = round(price * 1.02, 4)
        t2 = round(price * 1.045, 4)
        t3 = round(price * 1.08, 4)
        sl = round(price * 0.965, 4)

        spot = (
            f"🟢 *[SPOT SIGNAL] {symbol}*\n\n"
            f"📥 *Entry Range*: ${price}\n"
            f"📊 *24h Vol*: ${volume}M | *Change*: {change}%\n\n"
            f"🎯 *Target 1*: ${t1} (+2.0%)\n"
            f"🎯 *Target 2*: ${t2} (+4.5%)\n"
            f"🎯 *Target 3*: ${t3} (+8.0%)\n"
            f"⛔ *Stop Loss*: ${sl} (-3.5%)\n\n"
            f"📈 *Analysis*: Top Volume Momentum"
        )

        ft1 = round(price * 1.015, 4)
        ft2 = round(price * 1.03, 4)
        ft3 = round(price * 1.05, 4)
        fsl = round(price * 0.985, 4)

        futures = (
            f"⚡ *[FUTURES LONG] {symbol}*\n\n"
            f"⚙️ *Leverage*: Cross 10x - 20x\n"
            f"📥 *Entry*: ${price}\n\n"
            f"🎯 *Target 1*: ${ft1} (+15% @ 10x)\n"
            f"🎯 *Target 2*: ${ft2} (+30% @ 10x)\n"
            f"🎯 *Target 3*: ${ft3} (+50% @ 10x)\n"
            f"⛔ *Stop Loss*: ${fsl} (-15% @ 10x)\n\n"
            f"📊 *Analysis*: High Volume Breakout Pattern"
        )

        # VIP Messages
        send_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, spot)
        time.sleep(1)
        send_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, futures)
        time.sleep(1.5)

        # Free Messages (First 2 Coins Only)
        if index < 2:
            free_text = (
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
            send_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, free_text)
            time.sleep(1.5)

def run_loop():
    time.sleep(3)
    execute_signal_cycle()
    while True:
        time.sleep(3600)
        execute_signal_cycle()

threading.Thread(target=run_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
