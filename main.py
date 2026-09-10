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
    return "Bot Service is Alive!"

def send_msg(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def fetch_crypto_data():
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {"vs_currency": "usd", "order": "volume_desc", "per_page": 10, "page": 1}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, params=params, headers=headers, timeout=10)
        return res.json() if res.status_code == 200 else []
    except:
        return []

def execute_signal_cycle():
    # Instant System Status Check Signals
    vip_test = send_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, "🚀 *VIP Engine Initialized...*")
    free_test = send_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, "🚀 *Free Engine Initialized...*")
    
    time.sleep(2)
    coins = fetch_crypto_data()
    
    if not coins or not isinstance(coins, list):
        send_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, "⚠️ *Data Engine Alert*: Fetch Failed.")
        return

    for index, coin in enumerate(coins):
        symbol = coin["symbol"].upper() + "USDT"
        price = coin["current_price"]
        volume = float(coin["total_volume"]) / 1_000_000
        change = coin.get("price_change_percentage_24h", 0.0)

        spot = (
            f"🟢 *[SPOT SIGNAL] {symbol}*\n\n"
            f"📥 *Entry Range*: ${price}\n"
            f"📊 *24h Vol*: ${volume:.2f}M | *Change*: {change:+.2f}%\n\n"
            f"🎯 *Target 1*: ${round(price * 1.02, 4)} (+2.0%)\n"
            f"⛔ *Stop Loss*: ${round(price * 0.965, 4)} (-3.5%)"
        )
        
        futures = (
            f"⚡ *[FUTURES LONG] {symbol}*\n\n"
            f"⚙️ *Leverage*: Cross 10x\n"
            f"📥 *Entry*: ${price}\n\n"
            f"🎯 *Target 1*: ${round(price * 1.015, 4)} (+15% @ 10x)\n"
            f"⛔ *Stop Loss*: ${round(price * 0.985, 4)} (-15% @ 10x)"
        )

        send_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, spot)
        time.sleep(1)
        send_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, futures)
        time.sleep(1)

        if index < 2:
            promo = (
                f"🚀 *FREE PREVIEW SIGNAL*\n\n{spot}\n\n"
                f"🔥 *JOIN VIP FOR ALL 10 SIGNALS*\n"
                f"👉 @BinanceTop10_VIPBot"
            )
            send_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, promo)
            time.sleep(1)

def run_loop():
    time.sleep(3)
    execute_signal_cycle()
    while True:
        time.sleep(3600)
        execute_signal_cycle()

threading.Thread(target=run_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
