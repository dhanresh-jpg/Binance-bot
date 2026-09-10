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
            return result
    except:
        pass
    return []

def execute_signal_cycle():
    coins = fetch_crypto_data()
    if not coins:
        return

    for index, coin in enumerate(coins):
        symbol = coin["symbol"]
        price = coin["current_price"]
        volume = float(coin["total_volume"]) / 1_000_000
        change = float(coin["price_change_percentage_24h"])

        spot = (
            f"🟢 *[SPOT SIGNAL] {symbol}*\n\n"
            f"📥 *Entry Range*: ${price:.4f}\n"
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
            f"📥 *Entry*: ${price:.4f}\n\n"
            f"🎯 *Target 1*: ${round(price * 1.015, 4)} (+15% @ 10x)\n"
            f"🎯 *Target 2*: ${round(price * 1.03, 4)} (+30% @ 10x)\n"
            f"🎯 *Target 3*: ${round(price * 1.05, 4)} (+50% @ 10x)\n"
            f"⛔ *Stop Loss*: ${round(price * 0.985, 4)} (-15% @ 10x)\n\n"
            f"📊 *Analysis*: High Volume Breakout Pattern"
        )

        # Send to VIP
        send_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, spot)
        time.sleep(1)
        send_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, futures)
        time.sleep(1)

        # Send to Free (First 2 coins only)
        if index < 2:
            free_msg = (
                f"🚀 *FREE PREVIEW SIGNAL* 🚀\n\n"
                f"{spot}\n\n"
                f"🔥 *JOIN VIP FOR ALL SIGNALS*: @BinanceTop10_VIPBot"
            )
            res = send_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, free_msg)
            
            # Diagnostic: If Free Bot fails, print exact reason to VIP Channel
            if not res or not res.get("ok"):
                err = res.get("description", "Unknown Error") if res else "No Response"
                send_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, f"⚠️ *Free Channel Delivery Failure*: `{err}`")
            time.sleep(1)

def run_loop():
    time.sleep(3)
    while True:
        execute_signal_cycle()
        time.sleep(3600)

threading.Thread(target=run_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
